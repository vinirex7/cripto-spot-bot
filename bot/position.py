# bot/position.py
"""Persistent position + order state (restart-safe).

Why this exists:
- "Already in position" false positives happen when you have dust (tiny balances).
- The bot needs to remember entry/peak and also remember orders it created.
- On every loop "wake up", we snapshot balances + open orders and persist them with timestamps.

This file is intentionally dependency-light (pure stdlib).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class PositionStore:
    """JSON-backed store keyed by symbol.

    Schema per symbol (all optional, but we normalize on write):
      - in_position: bool
      - qty: float
      - entry_price: float
      - entry_ts: str (UTC ISO)
      - peak_price: float
      - peak_ts: str (UTC ISO)
      - last_update_ts: str (UTC ISO)
      - last_source: str ("engine" | "paper" | "exchange")
      - pending_order: {order_id, side, type, qty, price, status, ts}
      - last_order: {order_id, side, type, qty, price, status, ts}
    """

    def __init__(self, path: str = "logs/positions.json") -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data: Dict[str, Any] = self._load()

    # -----------------
    # IO
    # -----------------
    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    # -----------------
    # Helpers
    # -----------------
    def _default(self) -> Dict[str, Any]:
        return {
            "in_position": False,
            "qty": 0.0,
            "entry_price": 0.0,
            "entry_ts": "",
            "peak_price": 0.0,
            "peak_ts": "",
            "last_update_ts": "",
            "last_source": "",
            "pending_order": None,
            "last_order": None,
        }

    def get(self, symbol: str) -> Dict[str, Any]:
        raw = self._data.get(symbol)
        if not isinstance(raw, dict):
            return self._default()

        # normalize a bit so caller can rely on keys existing
        d = self._default()
        d.update(raw)
        d["in_position"] = bool(d.get("in_position", False))
        d["qty"] = _safe_float(d.get("qty", 0.0))
        d["entry_price"] = _safe_float(d.get("entry_price", 0.0))
        d["peak_price"] = _safe_float(d.get("peak_price", 0.0))
        return d

    def set(self, symbol: str, pos: Dict[str, Any]) -> None:
        base = self.get(symbol)
        base.update(pos)
        self._data[symbol] = base
        self._save()

    # -----------------
    # Core: snapshot sync (called every loop)
    # -----------------
    def sync_snapshot(
        self,
        symbol: str,
        *,
        qty: float,
        current_price: float,
        position_min_notional_usdt: float,
        ts: Optional[str] = None,
        source: str = "exchange",
        open_order_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist *current* holdings (and optionally open order info).

        This is how we ensure the bot "remembers" even after restart.
        """
        ts = ts or utcnow_iso()
        qty_f = max(0.0, _safe_float(qty))
        px = max(0.0, _safe_float(current_price))
        notional = qty_f * px

        in_pos = bool(notional >= max(0.0, float(position_min_notional_usdt)))

        pos = self.get(symbol)
        prev_in = bool(pos.get("in_position"))

        # If we just transitioned into a position (e.g., bot restarted mid-position)
        # keep existing entry if it exists; otherwise set a best-effort entry.
        if in_pos and not prev_in:
            if pos.get("entry_price", 0.0) <= 0:
                pos["entry_price"] = px
                pos["entry_ts"] = ts
            if pos.get("peak_price", 0.0) <= 0:
                pos["peak_price"] = px
                pos["peak_ts"] = ts

        # If we transitioned OUT of a position, clear peaks/entry (but keep order history)
        if (not in_pos) and prev_in:
            pos["entry_price"] = 0.0
            pos["entry_ts"] = ""
            pos["peak_price"] = 0.0
            pos["peak_ts"] = ""

        pos["in_position"] = in_pos
        pos["qty"] = qty_f
        pos["last_update_ts"] = ts
        pos["last_source"] = source

        if open_order_summary is not None:
            # store compact info (avoid huge payloads in positions.json)
            pos["open_orders"] = open_order_summary

        self.set(symbol, pos)
        return pos

    # -----------------
    # Peak tracking
    # -----------------
    def on_tick(self, symbol: str, current_price: float, ts: Optional[str] = None) -> None:
        pos = self.get(symbol)
        if not pos.get("in_position"):
            return
        px = _safe_float(current_price)
        if px <= 0:
            return
        peak = _safe_float(pos.get("peak_price", 0.0))
        if px > peak:
            pos["peak_price"] = px
            pos["peak_ts"] = ts or utcnow_iso()
            pos["last_update_ts"] = ts or utcnow_iso()
            pos["last_source"] = pos.get("last_source") or "engine"
            self.set(symbol, pos)

    # -----------------
    # Order persistence
    # -----------------
    def record_order(
        self,
        symbol: str,
        *,
        order_id: Any,
        side: str,
        order_type: str,
        qty: Any,
        price: Any,
        status: str,
        ts: Optional[str] = None,
        pending: bool = True,
    ) -> None:
        ts = ts or utcnow_iso()
        payload = {
            "order_id": order_id,
            "side": str(side).upper(),
            "type": str(order_type).upper(),
            "qty": _safe_float(qty),
            "price": _safe_float(price),
            "status": str(status).lower(),
            "ts": ts,
        }
        pos = self.get(symbol)
        pos["last_order"] = payload
        pos["pending_order"] = payload if pending else None
        pos["last_update_ts"] = ts
        pos["last_source"] = pos.get("last_source") or "engine"
        self.set(symbol, pos)

    def clear_pending(self, symbol: str, ts: Optional[str] = None) -> None:
        pos = self.get(symbol)
        if pos.get("pending_order") is None:
            return
        pos["pending_order"] = None
        pos["last_update_ts"] = ts or utcnow_iso()
        self.set(symbol, pos)

    # -----------------
    # Convenience for fills (engine calls)
    # -----------------
    def on_buy_filled(self, symbol: str, fill_price: float, qty: Optional[float] = None, ts: Optional[str] = None) -> None:
        ts = ts or utcnow_iso()
        pos = self.get(symbol)
        pos["in_position"] = True
        pos["entry_price"] = _safe_float(fill_price)
        pos["entry_ts"] = ts
        pos["peak_price"] = _safe_float(fill_price)
        pos["peak_ts"] = ts
        if qty is not None:
            pos["qty"] = max(0.0, _safe_float(qty))
        pos["last_update_ts"] = ts
        pos["last_source"] = pos.get("last_source") or "engine"
        pos["pending_order"] = None
        self.set(symbol, pos)

    def on_sell_filled(self, symbol: str, ts: Optional[str] = None) -> None:
        ts = ts or utcnow_iso()
        pos = self.get(symbol)
        pos["in_position"] = False
        pos["qty"] = 0.0
        pos["entry_price"] = 0.0
        pos["entry_ts"] = ""
        pos["peak_price"] = 0.0
        pos["peak_ts"] = ""
        pos["last_update_ts"] = ts
        pos["last_source"] = pos.get("last_source") or "engine"
        pos["pending_order"] = None
        self.set(symbol, pos)
