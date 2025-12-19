# execution/orders.py
"""Order execution module with paper and live executors."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

from bot.utils import write_jsonl, utcnow
from execution.binance_client import BinanceSpotClient


def _dec_places(step_str: str) -> int:
    # "0.00100000" -> 3, "1.00000000" -> 0
    s = step_str.strip()
    if "E" in s or "e" in s:
        # fallback; should not happen for Binance filters
        return 8
    if "." not in s:
        return 0
    return len(s.split(".")[1].rstrip("0"))


def _floor_to_step(value: float, step_str: str) -> float:
    step = Decimal(step_str)
    v = Decimal(str(value))
    if step == 0:
        return float(value)
    # floor to step: floor(v/step)*step
    floored = (v / step).to_integral_value(rounding=ROUND_DOWN) * step
    return float(floored)


def _fmt(value: float, decimals: int) -> str:
    if decimals <= 0:
        return str(int(value))
    return f"{value:.{decimals}f}"


class PaperExecutor:
    """Paper trading executor for simulation mode."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.logs_cfg = config.get("logging", {})
        self.balance_usdt = config.get("execution", {}).get("paper", {}).get("initial_balance_usdt", 10000)
        self.positions: Dict[str, float] = {}

    def execute(self, symbol: str, action: str, target_weight: float, current_price: float) -> Dict[str, Any]:
        result = {
            "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "paper",
            "symbol": symbol,
            "action": action,
            "target_weight": target_weight,
            "price": current_price,
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
                quantity = order_value / float(current_price)
                self.positions[symbol] = self.positions.get(symbol, 0.0) + quantity
                result["quantity"] = quantity
                result["value_usdt"] = order_value

        elif action == "SELL":
            quantity = float(self.positions.get(symbol, 0.0))
            if quantity > 0:
                self.positions[symbol] = 0.0
                result["quantity"] = quantity
                result["value_usdt"] = quantity * float(current_price)
            else:
                result["status"] = "skipped"
                result["reason"] = "No position to sell"

        else:
            result["status"] = "skipped"
            result["reason"] = "Invalid action"

        self.record_trade(result)
        return result

    def _trades_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("trades", "logs/trades.jsonl")

    def record_trade(self, payload: Dict[str, Any]) -> None:
        write_jsonl(self._trades_path(), payload, flush=self.logs_cfg.get("flush_every_write", True))


class LiveExecutor:
    """Live trading executor for real trades."""

    def __init__(self, config: Dict[str, Any], binance_client: BinanceSpotClient) -> None:
        self.config = config
        self.client = binance_client
        self.logs_cfg = config.get("logging", {})
        self.dry_run = config.get("execution", {}).get("trade", {}).get("dry_run", False)
        self.orders_cfg = config.get("exchange", {}).get("orders", {})

    def _trades_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("trades", "logs/trades.jsonl")

    def record_trade(self, payload: Dict[str, Any]) -> None:
        write_jsonl(self._trades_path(), payload, flush=self.logs_cfg.get("flush_every_write", True))

    def _get_free_usdt(self, account: Dict[str, Any]) -> float:
        try:
            for b in account.get("balances", []) or []:
                if b.get("asset") == "USDT":
                    return float(b.get("free", 0.0))
        except Exception:
            pass
        return 0.0

    def execute(self, symbol: str, action: str, target_weight: float, current_price: float) -> Dict[str, Any]:
        if action not in ["BUY", "SELL"]:
            return {"status": "skipped", "reason": "Invalid action"}

        if current_price <= 0:
            return {"status": "skipped", "reason": "Invalid price"}

        # Pull account balances
        try:
            account = self.client.get_account()
        except Exception as e:
            return {"status": "error", "reason": "Failed to fetch account", "error": str(e)}

        balance_usdt = self._get_free_usdt(account)
        if balance_usdt <= 0:
            return {"status": "skipped", "reason": "No free USDT balance"}

        # Cash buffer
        cash_buffer = float(self.config.get("risk", {}).get("cash_buffer", 0.40))
        cash_buffer = max(0.0, min(0.95, cash_buffer))
        max_investable = balance_usdt * (1.0 - cash_buffer)

        # Base target value
        order_value = balance_usdt * float(target_weight)
        order_value = min(order_value, max_investable)

        # Hard cap
        max_order = float(self.config.get("execution", {}).get("trade", {}).get("max_order_value_usdt", 1000))
        order_value = min(order_value, max_order)

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

        lot = filters.get("LOT_SIZE", {})
        pf = filters.get("PRICE_FILTER", {})
        mn = filters.get("MIN_NOTIONAL", {})  # older
        notional = filters.get("NOTIONAL", {})  # newer on some symbols

        step_str = lot.get("stepSize", "0.00000100")
        tick_str = pf.get("tickSize", "0.01")

        qty_dec = _dec_places(step_str)
        px_dec = _dec_places(tick_str)

        # minNotional from exchange if present, else config fallback
        cfg_min_notional = float(self.orders_cfg.get("min_notional_usdt", 10))
        exch_min_notional = None
        if "minNotional" in mn:
            try:
                exch_min_notional = float(mn["minNotional"])
            except Exception:
                pass
        elif "minNotional" in notional:
            try:
                exch_min_notional = float(notional["minNotional"])
            except Exception:
                pass

        min_notional = max(cfg_min_notional, exch_min_notional or 0.0)

        if order_value < min_notional:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run" if self.dry_run else "trade_live",
                "symbol": symbol,
                "action": action,
                "target_weight": target_weight,
                "price": current_price,
                "status": "skipped",
                "reason": "Order value below min_notional or blocked by cash_buffer/max caps",
                "order_value_usdt": order_value,
                "balance_usdt_free": balance_usdt,
                "cash_buffer": cash_buffer,
                "max_investable_usdt": max_investable,
                "max_order_value_usdt": max_order,
                "min_notional_usdt": min_notional,
            }
            self.record_trade(result)
            return result

        # Compute qty and normalize to stepSize
        raw_qty = order_value / float(current_price)
        quantity = _floor_to_step(raw_qty, step_str)

        if quantity <= 0:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run" if self.dry_run else "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "skipped",
                "reason": "Quantity rounded to zero by stepSize",
                "raw_quantity": raw_qty,
                "stepSize": step_str,
            }
            self.record_trade(result)
            return result

        order_type = self.orders_cfg.get("default_type", "LIMIT").upper()

        # Dry-run
        if self.dry_run:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_dry_run",
                "symbol": symbol,
                "action": action,
                "side": action,
                "type": order_type,
                "quantity": quantity,
                "price": current_price,
                "status": "dry_run_success",
                "order_value_usdt": order_value,
                "balance_usdt_free": balance_usdt,
                "cash_buffer": cash_buffer,
                "max_investable_usdt": max_investable,
                "stepSize": step_str,
                "tickSize": tick_str,
            }
            self.record_trade(result)
            return result

        # Live order creation
        price_offset_bps = float(self.orders_cfg.get("price_offset_bps", 5))
        offset = 1 + (price_offset_bps / 10000.0) if action == "BUY" else 1 - (price_offset_bps / 10000.0)
        raw_limit_price = float(current_price) * offset
        limit_price = _floor_to_step(raw_limit_price, tick_str)

        # Re-check notional after rounding (important!)
        est_notional = float(quantity) * float(limit_price if order_type == "LIMIT" else current_price)
        if est_notional < min_notional:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "skipped",
                "reason": "Notional fell below min_notional after precision rounding",
                "est_notional": est_notional,
                "min_notional_usdt": min_notional,
                "quantity": quantity,
                "limit_price": limit_price,
                "stepSize": step_str,
                "tickSize": tick_str,
            }
            self.record_trade(result)
            return result

        # Send as strings (avoids scientific notation / float quirks)
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
                "order_value_usdt": order_value,
                "balance_usdt_free": balance_usdt,
                "cash_buffer": cash_buffer,
                "max_investable_usdt": max_investable,
                "stepSize": step_str,
                "tickSize": tick_str,
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
                "order_value_usdt": order_value,
                "balance_usdt_free": balance_usdt,
                "stepSize": step_str,
                "tickSize": tick_str,
            }
            self.record_trade(result)
            return result

def create_executor(config: Dict[str, Any]):
    """
    Factory: decide se usa PaperExecutor ou LiveExecutor.
    """
    mode = (config.get("execution", {}) or {}).get("mode", "paper").lower()

    if mode == "paper":
        return PaperExecutor(config)

    # trade mode
    # API keys: prefer env vars, fallback to config.yaml api_keys.binance.*
    api_cfg = (config.get("api_keys", {}) or {}).get("binance", {}) or {}
    api_key = os.getenv("BINANCE_API_KEY") or api_cfg.get("api_key") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or api_cfg.get("api_secret") or ""

    if not api_key or not api_secret:
        raise RuntimeError("Missing Binance API keys (set BINANCE_API_KEY/BINANCE_API_SECRET or config.yaml api_keys.binance).")

    client = BinanceSpotClient(
        api_key=api_key,
        api_secret=api_secret,
        config=config,
    )
    return LiveExecutor(config, client)