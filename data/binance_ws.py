"""
Binance WebSocket client for real-time market data.
"""
import json
import logging
import threading
import time
from typing import Dict, Callable, Optional, Any
import websocket

logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    """WebSocket client for real-time Binance market data."""
    
    def __init__(self, base_url: str = "wss://stream.binance.com:9443/ws"):
        self.base_url = base_url
        self.ws: Optional[websocket.WebSocketApp] = None
        self.thread: Optional[threading.Thread] = None
        self.callbacks: Dict[str, Callable] = {}
        self.running = False
    
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
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
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
        if self.ws and self.running:
            self.ws.close()
            self.running = False
            if self.thread:
                self.thread.join(timeout=5)
            logger.info("WebSocket stopped")
    
    def is_running(self) -> bool:
        """Check if WebSocket is running."""
        return self.running
