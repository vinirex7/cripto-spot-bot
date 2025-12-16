"""
Binance REST API client for fetching historical OHLCV data.
"""
import os
import time
import hmac
import hashlib
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class BinanceRESTClient:
    """Binance REST API client for market data and trading."""
    
    def __init__(self, base_url: str = "https://api.binance.com"):
        self.base_url = base_url
        self.api_key = os.getenv("BINANCE_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_API_SECRET", "")
        self.session = requests.Session()
        
        if self.api_key:
            self.session.headers.update({"X-MBX-APIKEY": self.api_key})
    
    def _sign_request(self, params: Dict[str, Any]) -> str:
        """Generate signature for authenticated requests."""
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000
    ) -> List[List]:
        """
        Fetch OHLCV klines/candlestick data.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            interval: Kline interval (1m, 5m, 15m, 1h, 1d, etc.)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            limit: Number of klines to fetch (max 1000)
        
        Returns:
            List of klines: [open_time, open, high, low, close, volume, close_time, ...]
        """
        url = f"{self.base_url}/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching klines for {symbol}: {e}")
            return []
    
    def get_all_klines(
        self,
        symbol: str,
        interval: str,
        days_back: int
    ) -> List[List]:
        """
        Fetch all klines for a symbol over a specified period.
        Handles pagination automatically.
        
        Args:
            symbol: Trading pair
            interval: Kline interval
            days_back: Number of days to fetch
        
        Returns:
            List of all klines
        """
        all_klines = []
        end_time = int(time.time() * 1000)
        start_time = end_time - (days_back * 24 * 60 * 60 * 1000)
        
        logger.info(f"Fetching {interval} klines for {symbol} ({days_back} days)")
        
        current_start = start_time
        while current_start < end_time:
            klines = self.get_klines(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_time,
                limit=1000
            )
            
            if not klines:
                break
            
            all_klines.extend(klines)
            
            # Move to next batch
            current_start = klines[-1][0] + 1
            
            # Rate limiting
            time.sleep(0.2)
        
        logger.info(f"Fetched {len(all_klines)} klines for {symbol} {interval}")
        return all_klines
    
    def get_ticker_24h(self, symbol: str) -> Dict[str, Any]:
        """Get 24h ticker price change statistics."""
        url = f"{self.base_url}/api/v3/ticker/24hr"
        params = {"symbol": symbol}
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching 24h ticker for {symbol}: {e}")
            return {}
    
    def get_order_book(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        """Get order book depth."""
        url = f"{self.base_url}/api/v3/depth"
        params = {"symbol": symbol, "limit": limit}
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching order book for {symbol}: {e}")
            return {}
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account information (requires authentication)."""
        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not set")
            return {}
        
        url = f"{self.base_url}/api/v3/account"
        params = {"timestamp": int(time.time() * 1000)}
        params["signature"] = self._sign_request(params)
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching account info: {e}")
            return {}
    
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """
        Place an order (requires authentication).
        
        Args:
            symbol: Trading pair
            side: BUY or SELL
            order_type: LIMIT, MARKET, etc.
            quantity: Order quantity
            price: Order price (required for LIMIT orders)
            time_in_force: GTC, IOC, FOK
        
        Returns:
            Order response
        """
        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not set")
            return {}
        
        url = f"{self.base_url}/api/v3/order"
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "timestamp": int(time.time() * 1000)
        }
        
        if order_type == "LIMIT":
            if price is None:
                raise ValueError("Price required for LIMIT orders")
            params["price"] = price
            params["timeInForce"] = time_in_force
        
        params["signature"] = self._sign_request(params)
        
        try:
            response = self.session.post(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error placing order: {e}")
            return {}
    
    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel an existing order."""
        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not set")
            return {}
        
        url = f"{self.base_url}/api/v3/order"
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = self._sign_request(params)
        
        try:
            response = self.session.delete(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error canceling order: {e}")
            return {}
