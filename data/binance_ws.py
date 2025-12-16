"""
Binance WebSocket client for real-time market data with auto-reconnection.
"""
import json
import logging
import threading
import time
from typing import Dict, Callable, Optional, Any
import websocket

logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    """WebSocket client for real-time Binance market data with auto-reconnection."""
    
    def __init__(self, base_url: str = "wss://stream.binance.com:9443/ws", auto_reconnect: bool = True):
        self.base_url = base_url
        self.ws: Optional[websocket.WebSocketApp] = None
        self.thread: Optional[threading.Thread] = None
        self.callbacks: Dict[str, Callable] = {}
        self.running = False
        self.auto_reconnect = auto_reconnect
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # seconds
        self.ws_healthy = True
        self.last_message_time = time.time()
    
    def subscribe_ticker(self, symbol: str, callback: Callable[[Dict], None]):
        """Subscribe to ticker updates for a symbol."""
        stream = f"{symbol.lower()}@ticker"
        self.callbacks[stream] = callback
    
    def subscribe_trade(self, symbol: str, callback: Callable[[Dict], None]):
        """Subscribe to trade updates for a symbol."""
        stream = f"{symbol.lower()}@trade"
        self.callbacks[stream] = callback
    
    def subscribe_depth(self, symbol: str, callback: Callable[[Dict], None], level: int = 10):
        """Subscribe to order book depth updates."""
        stream = f"{symbol.lower()}@depth{level}"
        self.callbacks[stream] = callback
    
    def _on_message(self, ws, message: str):
        """Handle incoming WebSocket messages."""
        try:
            self.last_message_time = time.time()
            self.ws_healthy = True
            self.reconnect_attempts = 0  # Reset on successful message
            
            data = json.loads(message)
            stream = data.get("stream", "")
            
            if stream in self.callbacks:
                self.callbacks[stream](data.get("data", data))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    def _on_error(self, ws, error):
        """Handle WebSocket errors."""
        logger.error(f"WebSocket error: {error}")
        self.ws_healthy = False
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close with auto-reconnect."""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.ws_healthy = False
        
        # Auto-reconnect if enabled and still running
        if self.auto_reconnect and self.running:
            self._attempt_reconnect()
        else:
            self.running = False
    
    def _on_open(self, ws):
        """Handle WebSocket open."""
        logger.info("WebSocket connection opened")
        
        # Subscribe to all streams
        if self.callbacks:
            streams = list(self.callbacks.keys())
            subscribe_msg = {
                "method": "SUBSCRIBE",
                "params": streams,
                "id": 1
            }
            ws.send(json.dumps(subscribe_msg))
    
    def start(self):
        """Start the WebSocket connection in a separate thread."""
        if self.running:
            logger.warning("WebSocket already running")
            return
        
        streams = "/".join(self.callbacks.keys())
        url = f"{self.base_url}/{streams}"
        
        self.ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )
        
        self.running = True
        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()
        
        logger.info(f"WebSocket started for streams: {streams}")
    
    def stop(self):
        """Stop the WebSocket connection."""
        self.auto_reconnect = False  # Disable reconnection on manual stop
        if self.ws and self.running:
            self.ws.close()
            self.running = False
            if self.thread:
                self.thread.join(timeout=5)
            logger.info("WebSocket stopped")
    
    def is_running(self) -> bool:
        """Check if WebSocket is running."""
        return self.running
    
    def _attempt_reconnect(self):
        """Attempt to reconnect WebSocket with exponential backoff."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnect attempts ({self.max_reconnect_attempts}) reached. Giving up.")
            self.running = False
            return
        
        self.reconnect_attempts += 1
        delay = self.reconnect_delay * (2 ** (self.reconnect_attempts - 1))
        delay = min(delay, 300)  # Cap at 5 minutes
        
        logger.warning(f"Attempting reconnect #{self.reconnect_attempts} in {delay}s...")
        time.sleep(delay)
        
        # Restart connection
        self.start()
    
    def is_healthy(self) -> bool:
        """
        Check if WebSocket connection is healthy.
        
        Returns:
            True if connection is healthy and receiving messages
        """
        if not self.running or not self.ws_healthy:
            return False
        
        # Check if we've received messages recently (within last 60 seconds)
        time_since_last_message = time.time() - self.last_message_time
        if time_since_last_message > 60:
            logger.warning(f"No messages received for {time_since_last_message:.0f}s - connection may be stale")
            return False
        
        return True
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status."""
        return {
            'running': self.running,
            'healthy': self.is_healthy(),
            'reconnect_attempts': self.reconnect_attempts,
            'seconds_since_last_message': time.time() - self.last_message_time
        }
