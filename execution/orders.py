"""Order execution module with paper and live executors."""
import os
from typing import Any, Dict

from bot.utils import write_jsonl, utcnow
from execution.binance_client import BinanceSpotClient


class PaperExecutor:
    """Paper trading executor for simulation mode."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.logs_cfg = config.get("logging", {})
        self.balance_usdt = (
            config.get("execution", {}).get("paper", {}).get("initial_balance_usdt", 10000)
        )
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
        write_jsonl(
            self._trades_path(),
            payload,
            flush=self.logs_cfg.get("flush_every_write", True),
        )


class LiveExecutor:
    """Live trading executor for real trades."""

    def __init__(self, config: Dict[str, Any], binance_client: BinanceSpotClient) -> None:
        self.config = config
        self.client = binance_client
        self.logs_cfg = config.get("logging", {})
        self.dry_run = config.get("execution", {}).get("trade", {}).get("dry_run", False)
        self.orders_cfg = config.get("exchange", {}).get("orders", {})

    def _get_free_usdt(self, account: Dict[str, Any]) -> float:
        try:
            balances = account.get("balances", [])
            for b in balances:
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

        # --- NEW: Enforce cash buffer (max investable fraction of free USDT) ---
        cash_buffer = float(self.config.get("risk", {}).get("cash_buffer", 0.40))
        cash_buffer = max(0.0, min(0.95, cash_buffer))  # safety clamp
        max_investable = balance_usdt * (1.0 - cash_buffer)

        # Base target order value from weight
        order_value = balance_usdt * float(target_weight)

        # Do not exceed investable cash by design
        order_value = min(order_value, max_investable)

        # Existing hard cap per order
        max_order = float(self.config.get("execution", {}).get("trade", {}).get("max_order_value_usdt", 1000))
        order_value = min(order_value, max_order)

        # Min notional guard
        min_notional = float(self.orders_cfg.get("min_notional_usdt", 10))

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

        quantity = order_value / float(current_price)

        order_type = self.orders_cfg.get("default_type", "LIMIT")

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
            }
            self.record_trade(result)
            return result

        # Live order creation
        price_offset_bps = float(self.orders_cfg.get("price_offset_bps", 5))
        offset = 1 + (price_offset_bps / 10000.0) if action == "BUY" else 1 - (price_offset_bps / 10000.0)
        limit_price = float(current_price) * offset

        try:
            order = self.client.create_order(
                symbol=symbol,
                side=action,
                order_type=order_type,
                quantity=quantity,
                price=limit_price if order_type == "LIMIT" else None,
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
            }
        except Exception as e:
            result = {
                "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mode": "trade_live",
                "symbol": symbol,
                "action": action,
                "status": "error",
                "error": str(e),
                "order_value_usdt": order_value,
                "balance_usdt_free": balance_usdt,
                "cash_buffer": cash_buffer,
                "max_investable_usdt": max_investable,
            }

        self.record_trade(result)
        return result

    def _trades_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("trades", "logs/trades.jsonl")

    def record_trade(self, payload: Dict[str, Any]) -> None:
        write_jsonl(
            self._trades_path(),
            payload,
            flush=self.logs_cfg.get("flush_every_write", True),
        )


def create_executor(config: Dict[str, Any]) -> Any:
    mode = config.get("execution", {}).get("mode", "paper")

    if mode == "paper":
        return PaperExecutor(config)

    if mode == "trade":
        api_keys = config.get("api_keys", {}).get("binance", {})
        api_key = api_keys.get("api_key") or os.getenv("BINANCE_API_KEY")
        api_secret = api_keys.get("api_secret") or os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("Binance API credentials not found in config or environment")

        client = BinanceSpotClient(api_key, api_secret, config.get("exchange", {}))
        return LiveExecutor(config, client)

    raise ValueError(f"Invalid execution mode: {mode}")