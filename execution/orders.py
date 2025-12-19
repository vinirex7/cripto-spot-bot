# execution/orders.py
"""Order execution module with paper and live executors (Spot Binance).

Key upgrades (LiveExecutor):
- Prevent duplicate entries: won't BUY if you already hold the base asset.
- Prevent order spam: won't place a new order if there is any open order on the symbol.
- Proper SELL: sells your actual free balance (base asset), not a computed qty from USDT.
- Optional: cancel open BUY orders before SELL (to avoid conflicts and free funds).
- Uses Binance filters: stepSize / tickSize / minNotional, with post-rounding notional checks.
"""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, List, Optional, Tuple

from bot.utils import write_jsonl, utcnow
from execution.binance_client import BinanceSpotClient


# -----------------------------
# Precision helpers
# -----------------------------
def _dec_places(step_str: str) -> int:
    s = (step_str or "").strip()
    if not s:
        return 8
    if "E" in s or "e" in s:
        return 8
    if "." not in s:
        return 0
    return len(s.split(".")[1].rstrip("0"))


def _floor_to_step(value: float, step_str: str) -> float:
    step_s = (step_str or "0.00000100").strip()
    step = Decimal(step_s)
    v = Decimal(str(value))
    if step == 0:
        return float(value)
    floored = (v / step).to_integral_value(rounding=ROUND_DOWN) * step
    return float(floored)


def _ceil_to_step(value: float, step_str: str) -> float:
    step_s = (step_str or "0.00000100").strip()
    step = Decimal(step_s)
    v = Decimal(str(value))
    if step == 0:
        return float(value)
    ceiled = (v / step).to_integral_value(rounding=ROUND_UP) * step
    return float(ceiled)


def _round_price_to_tick(value: float, tick_str: str, side: str) -> float:
    """
    Tick rounding:
      - BUY  -> round DOWN (avoid paying above planned)
      - SELL -> round UP   (avoid posting below planned due to tick)
    """
    tick = (tick_str or "0.01").strip()
    if side.upper() == "SELL":
        return _ceil_to_step(value, tick)
    return _floor_to_step(value, tick)


def _fmt(value: float, decimals: int) -> str:
    if decimals <= 0:
        return str(int(value))
    return f"{value:.{decimals}f}"


# -----------------------------
# Paper executor
# -----------------------------
class PaperExecutor:
    """Paper trading executor for simulation mode."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.logs_cfg = config.get("logging", {}) or {}
        self.balance_usdt = float(
            ((config.get("execution", {}) or {}).get("paper", {}) or {}).get("initial_balance_usdt", 10000)
        )
        self.positions: Dict[str, float] = {}

    def _trades_path(self) -> str:
        return (self.logs_cfg.get("files", {}) or {}).get("trades", "logs/trades.jsonl")

    def record_trade(self, payload: Dict[str, Any]) -> None:
        write_jsonl(self._trades_path(), payload, flush=self.logs_cfg.get("flush_every_write", True))

    def execute(self, symbol: str, action: str, target_weight: float, current_price: float) -> Dict[str, Any]:
        action = str(action).upper()

        result: Dict[str, Any] = {
            "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "paper",
            "symbol": symbol,
            "action": action,
            "target_weight": float(target_weight),
            "price": float(current_price),
            "status": "simulated",
        }

        if current_price <= 0:
            result["status"] = "skipped"
            result["reason"] = "Invalid price"
            self.record_trade(result)
            return result

        if action == "BUY":
            order_value = float(self.balance_usdt) * float(target_weight)
            if order_value <= 0:
                result["status"] = "skipped"
                result["reason"] = "Non-positive order_value"
            else:
                qty = order_value / float(current_price)
                self.positions[symbol] = self.positions.get(symbol, 0.0) + qty
                result["quantity"] = qty
                result["value_usdt"] = order_value

        elif action == "SELL":
            qty = float(self.positions.get(symbol, 0.0))
            if qty > 0:
                self.positions[symbol] = 0.0
                result["quantity"] = qty
                result["value_usdt"] = qty * float(current_price)
            else:
                result["status"] = "skipped"
                result["reason"] = "No position to sell"
        else:
            result["status"] = "skipped"
            result["reason"] = "Invalid action"

        self.record_trade(result)
        return result


# -----------------------------
# Live executor
# -----------------------------
class LiveExecutor:
    """Live trading executor for real trades (Spot)."""

    def __init__(self, config: Dict[str, Any], binance_client: BinanceSpotClient) -> None:
        self.config = config
        self.client = binance_client
        self.logs_cfg = config.get("logging", {}) or {}
        self.dry_run = bool(((config.get("execution", {}) or {}).get("trade", {}) or {}).get("dry_run", False))
        self.orders_cfg = (config.get("exchange", {}) or {}).get("orders", {}) or {}

        # Safety toggles (defaults are safe)
        self.prevent_duplicate_entries = bool(self.orders_cfg.get("prevent_duplicate_entries", True))
        self.prevent_if_open_orders = bool(self.orders_cfg.get("prevent_if_open_orders", True))
        self.cancel_open_buys_before_sell = bool(self.orders_cfg.get("cancel_open_buys_before_sell", True))
        self.position_epsilon = float(self.orders_cfg.get("position_epsilon", 1e-12))  # tiny threshold

    def _trades_path(self) -> str:
        return (self.logs_cfg.get("files", {}) or {}).get("trades", "logs/trades.jsonl")

    def record_trade(self, payload: Dict[str, Any]) -> None:
        write_jsonl(self._trades_path(), payload, flush=self.logs_cfg.get("flush_every_write", True))

    # ---- Binance state helpers ----
    def _get_free_balance(self, account: Dict[str, Any], asset: str) -> float:
        try:
            for b in account.get("balances", []) or []:
                if b.get("asset") == asset:
                    return float(b.get("free", 0.0))
        except Exception:
            pass
        return 0.0

    def _get_total_balance(self, account: Dict[str, Any], asset: str) -> float:
        try:
            for b in account.get("balances", []) or []:
                if b.get("asset") == asset:
                    free = float(b.get("free", 0.0))
                    locked = float(b.get("locked", 0.0))
                    return free + locked
        except Exception:
            pass
        return 0.0

    def _symbol_assets(self, symbol: str) -> Tuple[str, str]:
        """
        Return (baseAsset, quoteAsset) for symbol using cached exchangeInfo.
        """
        info = self.client.get_exchange_info()
        for s in info.get("symbols", []) or []:
            if s.get("symbol") == symbol:
                base = str(s.get("baseAsset") or "")
                quote = str(s.get("quoteAsset") or "")
                if base and quote:
                    return base, quote
        raise ValueError(f"Symbol not found in exchangeInfo: {symbol}")

    def _get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        # Uses private client._request for signed endpoint
        return self.client._request("GET", "/api/v3/openOrders", signed=True, params={"symbol": symbol})  # type: ignore[attr-defined]

    def _cancel_order(self, symbol: str, order_id: Any) -> Dict[str, Any]:
        return self.client._request(  # type: ignore[attr-defined]
            "DELETE",
            "/api/v3/order",
            signed=True,
            params={"symbol": symbol, "orderId": order_id},
        )

    def execute(self, symbol: str, action: str, target_weight: float, current_price: float) -> Dict[str, Any]:
        action = str(action).upper()

        if action not in ("BUY", "SELL"):
            return {"status": "skipped", "reason": "Invalid action"}

        if current_price <= 0:
            return {"status": "skipped", "reason": "Invalid price"}

        # Pull account balances
        try:
            account = self.client.get_account()
        except Exception as e:
            result = {"status": "error", "reason": "Failed to fetch account", "error": str(e)}
            self.record_trade(
                {
                    **result,
                    "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": "trade_live",
                    "symbol": symbol,
                    "action": action,
                }
            )
            return result

        # Determine base/quote assets (e.g., BNBUSDT -> base=BNB, quote=USDT)
        try:
            base_asset, quote_asset = self._symbol_assets(symbol)
        except Exception as e:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run" if self.dry_run else "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "error",
                "reason": "Failed to read symbol assets",
                "error": str(e),
            }
            self.record_trade(result)
            return result

        # Open orders guard (prevents duplicates / conflicts)
        open_orders: List[Dict[str, Any]] = []
        if self.prevent_if_open_orders:
            try:
                open_orders = self._get_open_orders(symbol)
            except Exception as e:
                # If we can't read open orders, fail-safe: do NOT trade
                result = {
                    "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": "trade_dry_run" if self.dry_run else "trade_live",
                    "symbol": symbol,
                    "action": action,
                    "status": "skipped",
                    "reason": "Cannot verify open orders (fail-safe)",
                    "error": str(e),
                }
                self.record_trade(result)
                return result

            if open_orders:
                # Optionally: if SELL and there are open BUYs, cancel them first
                if action == "SELL" and self.cancel_open_buys_before_sell:
                    cancelled: List[Any] = []
                    for o in open_orders:
                        if str(o.get("side", "")).upper() == "BUY":
                            try:
                                self._cancel_order(symbol, o.get("orderId"))
                                cancelled.append(o.get("orderId"))
                            except Exception:
                                # ignore individual cancel failures; we will re-check open orders
                                pass
                    # Re-check after cancels
                    try:
                        open_orders = self._get_open_orders(symbol)
                    except Exception:
                        open_orders = open_orders  # keep previous

                    # If still any open orders, skip to avoid conflicts
                    if open_orders:
                        result = {
                            "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "mode": "trade_dry_run" if self.dry_run else "trade_live",
                            "symbol": symbol,
                            "action": action,
                            "status": "skipped",
                            "reason": "Open orders exist (blocked)",
                            "open_orders_count": len(open_orders),
                            "cancelled_order_ids": cancelled,
                        }
                        self.record_trade(result)
                        return result
                else:
                    # BUY (or SELL without cancel policy): do not place more
                    result = {
                        "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "mode": "trade_dry_run" if self.dry_run else "trade_live",
                        "symbol": symbol,
                        "action": action,
                        "status": "skipped",
                        "reason": "Open orders exist (blocked)",
                        "open_orders_count": len(open_orders),
                    }
                    self.record_trade(result)
                    return result

        # Position guard: don't BUY if you already hold base asset (prevents pyramiding by default)
        base_total = self._get_total_balance(account, base_asset)
        base_free = self._get_free_balance(account, base_asset)

        if action == "BUY" and self.prevent_duplicate_entries and base_total > self.position_epsilon:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run" if self.dry_run else "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "skipped",
                "reason": "Already in position (base asset balance > 0)",
                "base_asset": base_asset,
                "base_total": float(base_total),
            }
            self.record_trade(result)
            return result

        # For SELL: sell what you actually have (free balance), optionally fraction
        sell_fraction = float(self.orders_cfg.get("sell_fraction", 1.0))
        sell_fraction = max(0.0, min(1.0, sell_fraction))

        # Pull symbol filters (precision + minNotional)
        try:
            filters = self.client.get_symbol_filters(symbol)
        except Exception as e:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run" if self.dry_run else "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "error",
                "reason": "Failed to fetch symbol filters",
                "error": str(e),
            }
            self.record_trade(result)
            return result

        lot = (filters.get("LOT_SIZE", {}) or {})
        pf = (filters.get("PRICE_FILTER", {}) or {})
        mn = (filters.get("MIN_NOTIONAL", {}) or {})     # older
        notional = (filters.get("NOTIONAL", {}) or {})   # newer

        step_str = lot.get("stepSize", "0.00000100")
        tick_str = pf.get("tickSize", "0.01")

        qty_dec = _dec_places(step_str)
        px_dec = _dec_places(tick_str)

        # Min notional: prefer exchange requirement, else config fallback
        cfg_min_notional = float(self.orders_cfg.get("min_notional_usdt", 0))
        exch_min_notional = 0.0
        if "minNotional" in mn:
            try:
                exch_min_notional = float(mn["minNotional"])
            except Exception:
                exch_min_notional = 0.0
        elif "minNotional" in notional:
            try:
                exch_min_notional = float(notional["minNotional"])
            except Exception:
                exch_min_notional = 0.0

        min_notional = exch_min_notional if exch_min_notional > 0 else cfg_min_notional

        # Order type
        order_type = str(self.orders_cfg.get("default_type", "LIMIT")).upper()
        if order_type not in ("LIMIT", "MARKET"):
            order_type = "LIMIT"

        # Price for LIMIT (current_price with small offset bps to improve fill odds)
        price_offset_bps = float(self.orders_cfg.get("price_offset_bps", 5.0))
        if action == "BUY":
            offset = 1.0 + (price_offset_bps / 10000.0)
        else:
            offset = 1.0 - (price_offset_bps / 10000.0)
        raw_limit_price = float(current_price) * offset
        limit_price = _round_price_to_tick(raw_limit_price, tick_str, action)

        # If MARKET, use current_price for notional checks (best effort)
        effective_price = float(limit_price) if order_type == "LIMIT" else float(current_price)

        # ---- Sizing ----
        if action == "BUY":
            # Use quote balance (USDT) for buy sizing
            quote_free = self._get_free_balance(account, quote_asset)
            if quote_free <= 0:
                result = {
                    "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": "trade_dry_run" if self.dry_run else "trade_live",
                    "symbol": symbol,
                    "action": action,
                    "status": "skipped",
                    "reason": f"No free {quote_asset} balance",
                    "quote_asset": quote_asset,
                    "quote_free": float(quote_free),
                }
                self.record_trade(result)
                return result

            # Cash buffer (risk)
            cash_buffer = float((self.config.get("risk", {}) or {}).get("cash_buffer", 0.40))
            cash_buffer = max(0.0, min(0.95, cash_buffer))
            max_investable = quote_free * (1.0 - cash_buffer)

            # Base target value in quote currency
            order_value = quote_free * float(target_weight)
            order_value = min(order_value, max_investable)

            # Hard cap per order
            max_order = float(((self.config.get("execution", {}) or {}).get("trade", {}) or {}).get("max_order_value_usdt", 1e18))
            order_value = min(order_value, max_order)

            if order_value < min_notional:
                result = {
                    "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": "trade_dry_run" if self.dry_run else "trade_live",
                    "symbol": symbol,
                    "action": action,
                    "target_weight": float(target_weight),
                    "price": float(current_price),
                    "status": "skipped",
                    "reason": "Order value below min_notional or blocked by cash_buffer/max caps",
                    "order_value_usdt": float(order_value),
                    "quote_free": float(quote_free),
                    "cash_buffer": float(cash_buffer),
                    "max_investable_usdt": float(max_investable),
                    "max_order_value_usdt": float(max_order),
                    "min_notional_usdt": float(min_notional),
                    "stepSize": step_str,
                    "tickSize": tick_str,
                }
                self.record_trade(result)
                return result

            raw_qty = float(order_value) / float(effective_price)
            quantity = _floor_to_step(raw_qty, step_str)

        else:
            # SELL: sell what you have (base asset)
            if base_free <= self.position_epsilon:
                result = {
                    "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": "trade_dry_run" if self.dry_run else "trade_live",
                    "symbol": symbol,
                    "action": action,
                    "status": "skipped",
                    "reason": "No position to sell (base free balance <= 0)",
                    "base_asset": base_asset,
                    "base_free": float(base_free),
                }
                self.record_trade(result)
                return result

            raw_qty = float(base_free) * sell_fraction
            quantity = _floor_to_step(raw_qty, step_str)

        if quantity <= 0:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run" if self.dry_run else "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "skipped",
                "reason": "Quantity rounded to zero by stepSize",
                "raw_quantity": float(raw_qty),
                "stepSize": step_str,
            }
            self.record_trade(result)
            return result

        # Post-rounding notional check
        est_notional = float(quantity) * float(effective_price)
        if est_notional < min_notional:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run" if self.dry_run else "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "skipped",
                "reason": "Notional below min_notional after rounding",
                "est_notional": float(est_notional),
                "min_notional_usdt": float(min_notional),
                "quantity": float(quantity),
                "effective_price": float(effective_price),
                "stepSize": step_str,
                "tickSize": tick_str,
            }
            self.record_trade(result)
            return result

        # Dry-run returns what it WOULD do
        if self.dry_run:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run",
                "symbol": symbol,
                "action": action,
                "side": action,
                "type": order_type,
                "quantity": float(quantity),
                "price": float(limit_price if order_type == "LIMIT" else current_price),
                "status": "dry_run_success",
                "est_notional": float(est_notional),
                "stepSize": step_str,
                "tickSize": tick_str,
                "min_notional_usdt": float(min_notional),
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "base_free": float(base_free),
                "base_total": float(base_total),
            }
            self.record_trade(result)
            return result

        # Send as strings (avoid float quirks)
        qty_str = _fmt(quantity, qty_dec)
        price_str = _fmt(limit_price, px_dec) if order_type == "LIMIT" else None

        try:
            order = self.client.create_order(
                symbol=symbol,
                side=action,
                order_type=order_type,
                quantity=qty_str,
                price=price_str,
            )

            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_live",
                "symbol": symbol,
                "action": action,
                "order_id": order.get("orderId"),
                "client_order_id": order.get("clientOrderId"),
                "side": order.get("side"),
                "type": order.get("type"),
                "quantity": order.get("origQty"),
                "price": order.get("price"),
                "status": order.get("status"),
                "est_notional": float(est_notional),
                "stepSize": step_str,
                "tickSize": tick_str,
                "min_notional_usdt": float(min_notional),
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "base_free": float(base_free),
                "base_total": float(base_total),
            }
            self.record_trade(result)
            return result

        except Exception as e:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "error",
                "reason": "Failed to create order",
                "error": str(e),
                "quantity": qty_str,
                "price": price_str,
                "est_notional": float(est_notional),
                "stepSize": step_str,
                "tickSize": tick_str,
                "min_notional_usdt": float(min_notional),
            }
            self.record_trade(result)
            return result


# -----------------------------
# Factory
# -----------------------------
def create_executor(config: Dict[str, Any]):
    """Factory: decide se usa PaperExecutor ou LiveExecutor."""
    mode = str(((config.get("execution", {}) or {}).get("mode", "paper"))).lower()

    if mode == "paper":
        return PaperExecutor(config)

    # treat "trade" and "live" as live execution
    if mode not in ("trade", "live"):
        mode = "trade"

    # API keys: prefer env vars, fallback to config.yaml api_keys.binance.*
    api_cfg = ((config.get("api_keys", {}) or {}).get("binance", {}) or {})
    api_key = os.getenv("BINANCE_API_KEY") or api_cfg.get("api_key") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or api_cfg.get("api_secret") or ""

    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing Binance API keys (set BINANCE_API_KEY/BINANCE_API_SECRET or config.yaml api_keys.binance)."
        )

    client = BinanceSpotClient(
        api_key=api_key,
        api_secret=api_secret,
        config=config,
    )
    return LiveExecutor(config, client)