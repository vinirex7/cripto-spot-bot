"""Binance Spot API client."""
import hashlib
import hmac
import time
from typing import Any, Dict, List, Optional
import requests


class BinanceSpotClient:
    """Client for Binance Spot API."""
    
    def __init__(self, api_key: str, api_secret: str, config: Dict[str, Any]):
        """
        Initialize Binance Spot client.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            config: Exchange configuration dictionary
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = config.get("base_url", "https://api.binance.com")
        self.recv_window = config.get("recv_window", 5000)
        self.timeout = config.get("timeout_seconds", 30)
    
    def _sign(self, params: Dict[str, Any]) -> str:
        """
        Generate HMAC SHA256 signature for signed requests.
        
        Args:
            params: Request parameters
            
        Returns:
            Hex digest signature
        """
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _request(self, method: str, endpoint: str, signed: bool = False, **kwargs) -> Dict[str, Any]:
        """
        Make HTTP request to Binance API.
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint
            signed: Whether to sign the request
            **kwargs: Additional request arguments
            
        Returns:
            JSON response as dictionary
            
        Raises:
            requests.HTTPError: On HTTP errors
        """
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key}
        
        if signed:
            params = kwargs.get("params", {})
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self.recv_window
            params["signature"] = self._sign(params)
            kwargs["params"] = params
        
        response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response.json()
    
    def get_account(self) -> Dict[str, Any]:
        """
        Get account information.
        
        Returns:
            Account information including balances
        """
        return self._request("GET", "/api/v3/account", signed=True)
    
    def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        """
        Get current ticker price for a symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            
        Returns:
            Ticker price information
        """
        return self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol})
    
    def create_order(self, symbol: str, side: str, order_type: str, quantity: float, 
                     price: Optional[float] = None, time_in_force: str = "GTC") -> Dict[str, Any]:
        """
        Create a new order.
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            side: Order side (BUY or SELL)
            order_type: Order type (LIMIT or MARKET)
            quantity: Order quantity
            price: Order price (required for LIMIT orders)
            time_in_force: Time in force (GTC, IOC, FOK)
            
        Returns:
            Order information
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }
        
        if order_type == "LIMIT":
            params["price"] = price
            params["timeInForce"] = time_in_force
        
        return self._request("POST", "/api/v3/order", signed=True, params=params)
    
    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """
        Cancel an active order.
        
        Args:
            symbol: Trading pair symbol
            order_id: Order ID to cancel
            
        Returns:
            Cancellation confirmation
        """
        return self._request("DELETE", "/api/v3/order", signed=True, 
                            params={"symbol": symbol, "orderId": order_id})
    
    def get_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """
        Query order status.
        
        Args:
            symbol: Trading pair symbol
            order_id: Order ID to query
            
        Returns:
            Order status information
        """
        return self._request("GET", "/api/v3/order", signed=True,
                            params={"symbol": symbol, "orderId": order_id})
    
    def get_klines(self, symbol: str, interval: str, limit: int = 500,
                   start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[List[Any]]:
        """
        Get klines/candlestick data for a symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            interval: Kline interval (e.g., 1m, 5m, 1h, 1d)
            limit: Number of klines to return (max 1000)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            
        Returns:
            List of klines data
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000)
        }
        
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        
        return self._request("GET", "/api/v3/klines", params=params)
