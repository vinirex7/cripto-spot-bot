"""Order execution module with paper and live executors."""
import os
from typing import Any, Dict

from bot.utils import write_jsonl, utcnow
from execution.binance_client import BinanceSpotClient


class PaperExecutor:
    """Paper trading executor for simulation mode."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize paper executor.
        
        Args:
            config: Bot configuration dictionary
        """
        self.config = config
        self.logs_cfg = config.get("logging", {})
        self.balance_usdt = config.get("execution", {}).get("paper", {}).get("initial_balance_usdt", 10000)
        self.positions: Dict[str, float] = {}
    
    def execute(self, symbol: str, action: str, target_weight: float, current_price: float) -> Dict[str, Any]:
        """
        Execute a paper trade.
        
        Args:
            symbol: Trading pair symbol
            action: Trade action (BUY, SELL, HOLD)
            target_weight: Target portfolio weight
            current_price: Current price
            
        Returns:
            Trade execution result
        """
        result = {
            "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "paper",
            "symbol": symbol,
            "action": action,
            "target_weight": target_weight,
            "price": current_price,
            "status": "simulated"
        }
        
        if action == "BUY":
            order_value = self.balance_usdt * target_weight
            quantity = order_value / current_price
            self.positions[symbol] = self.positions.get(symbol, 0) + quantity
            result["quantity"] = quantity
            result["value_usdt"] = order_value
        elif action == "SELL":
            quantity = self.positions.get(symbol, 0)
            if quantity > 0:
                self.positions[symbol] = 0
                result["quantity"] = quantity
                result["value_usdt"] = quantity * current_price
        
        self.record_trade(result)
        return result
    
    def _trades_path(self) -> str:
        """Get path for trades log file."""
        return self.logs_cfg.get("files", {}).get("trades", "logs/trades.jsonl")
    
    def record_trade(self, payload: Dict[str, Any]) -> None:
        """
        Record trade to log file.
        
        Args:
            payload: Trade information to log
        """
        write_jsonl(
            self._trades_path(),
            payload,
            flush=self.logs_cfg.get("flush_every_write", True),
        )


class LiveExecutor:
    """Live trading executor for real trades."""
    
    def __init__(self, config: Dict[str, Any], binance_client: BinanceSpotClient) -> None:
        """
        Initialize live executor.
        
        Args:
            config: Bot configuration dictionary
            binance_client: Binance API client
        """
        self.config = config
        self.client = binance_client
        self.logs_cfg = config.get("logging", {})
        self.dry_run = config.get("execution", {}).get("trade", {}).get("dry_run", False)
        self.orders_cfg = config.get("exchange", {}).get("orders", {})
    
    def execute(self, symbol: str, action: str, target_weight: float, current_price: float) -> Dict[str, Any]:
        """
        Execute a live trade.
        
        Args:
            symbol: Trading pair symbol
            action: Trade action (BUY, SELL, HOLD)
            target_weight: Target portfolio weight
            current_price: Current price
            
        Returns:
            Trade execution result
        """
        if action not in ["BUY", "SELL"]:
            return {"status": "skipped", "reason": "Invalid action"}
        
        # Calculate quantity
        account = self.client.get_account()
        balance_usdt = float([b["free"] for b in account["balances"] if b["asset"] == "USDT"][0])
        
        order_value = balance_usdt * target_weight
        max_order = self.config.get("execution", {}).get("trade", {}).get("max_order_value_usdt", 1000)
        order_value = min(order_value, max_order)
        
        quantity = order_value / current_price
        
        # Create order
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
                "status": "dry_run_success"
            }
        else:
            price_offset_bps = self.orders_cfg.get("price_offset_bps", 5)
            offset = 1 + (price_offset_bps / 10000.0) if action == "BUY" else 1 - (price_offset_bps / 10000.0)
            limit_price = current_price * offset
            
            try:
                order = self.client.create_order(
                    symbol=symbol,
                    side=action,
                    order_type=order_type,
                    quantity=quantity,
                    price=limit_price if order_type == "LIMIT" else None
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
                    "status": order.get("status")
                }
            except Exception as e:
                result = {
                    "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": "trade_live",
                    "symbol": symbol,
                    "action": action,
                    "status": "error",
                    "error": str(e)
                }
        
        self.record_trade(result)
        return result
    
    def _trades_path(self) -> str:
        """Get path for trades log file."""
        return self.logs_cfg.get("files", {}).get("trades", "logs/trades.jsonl")
    
    def record_trade(self, payload: Dict[str, Any]) -> None:
        """
        Record trade to log file.
        
        Args:
            payload: Trade information to log
        """
        write_jsonl(
            self._trades_path(),
            payload,
            flush=self.logs_cfg.get("flush_every_write", True),
        )


def create_executor(config: Dict[str, Any]) -> Any:
    """
    Factory to create executor based on execution mode.
    
    Args:
        config: Bot configuration dictionary
        
    Returns:
        PaperExecutor or LiveExecutor instance
        
    Raises:
        ValueError: If mode is invalid or credentials are missing
    """
    mode = config.get("execution", {}).get("mode", "paper")
    
    if mode == "paper":
        return PaperExecutor(config)
    elif mode == "trade":
        api_keys = config.get("api_keys", {}).get("binance", {})
        api_key = api_keys.get("api_key") or os.getenv("BINANCE_API_KEY")
        api_secret = api_keys.get("api_secret") or os.getenv("BINANCE_API_SECRET")
        
        if not api_key or not api_secret:
            raise ValueError("Binance API credentials not found in config or environment")
        
        client = BinanceSpotClient(api_key, api_secret, config.get("exchange", {}))
        return LiveExecutor(config, client)
    else:
        raise ValueError(f"Invalid execution mode: {mode}")
