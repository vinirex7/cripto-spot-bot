"""
JSONL logging for bot decisions and metrics.
Never logs sensitive data (API keys, secrets).
"""
import json
import os
from datetime import datetime
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class LogWriter:
    """
    Write structured logs in JSONL format.
    
    CRITICAL: Never log sensitive data like API keys, secrets, etc.
    """
    
    def __init__(self, log_path: str, create_dirs: bool = True):
        self.log_path = log_path
        
        if create_dirs:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
        
        logger.info(f"LogWriter initialized: {log_path}")
    
    def _sanitize(self, data: Dict) -> Dict:
        """
        Remove sensitive fields from log data.
        
        Args:
            data: Dictionary that may contain sensitive data
        
        Returns:
            Sanitized dictionary
        """
        sensitive_keys = [
            'api_key', 'api_secret', 'secret', 'password', 'token',
            'authorization', 'auth', 'key', 'signature'
        ]
        
        sanitized = {}
        for key, value in data.items():
            # Check if key is sensitive
            if any(sens in key.lower() for sens in sensitive_keys):
                sanitized[key] = '***REDACTED***'
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        
        return sanitized
    
    def write_log(
        self,
        event_type: str,
        data: Dict[str, Any]
    ):
        """
        Write a log entry in JSONL format.
        
        Args:
            event_type: Type of event (e.g., 'signal', 'trade', 'error')
            data: Event data
        """
        # Sanitize data
        sanitized_data = self._sanitize(data)
        
        # Create log entry
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'event_type': event_type,
            **sanitized_data
        }
        
        # Write to file
        try:
            with open(self.log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"Failed to write log: {e}")
    
    def log_signal(
        self,
        symbol: str,
        signal_type: str,
        value: float,
        metadata: Dict[str, Any]
    ):
        """Log a signal generation event."""
        self.write_log('signal', {
            'symbol': symbol,
            'signal_type': signal_type,
            'value': value,
            'metadata': metadata
        })
    
    def log_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_type: str,
        reason: str,
        success: bool
    ):
        """Log a trade execution event."""
        self.write_log('trade', {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': price,
            'order_type': order_type,
            'reason': reason,
            'success': success
        })
    
    def log_decision(
        self,
        symbol: str,
        decision: str,
        reason: str,
        metrics: Dict[str, Any]
    ):
        """Log a bot decision."""
        self.write_log('decision', {
            'symbol': symbol,
            'decision': decision,
            'reason': reason,
            'metrics': metrics
        })
    
    def log_risk_event(
        self,
        event_type: str,
        symbol: str,
        details: Dict[str, Any]
    ):
        """Log a risk management event."""
        self.write_log('risk', {
            'event_type': event_type,
            'symbol': symbol,
            'details': details
        })
    
    def log_news_event(
        self,
        symbol: str,
        news_summary: Dict[str, Any]
    ):
        """Log a news event."""
        self.write_log('news', {
            'symbol': symbol,
            'news_summary': news_summary
        })
    
    def log_error(
        self,
        error_type: str,
        message: str,
        details: Dict[str, Any]
    ):
        """Log an error event."""
        self.write_log('error', {
            'error_type': error_type,
            'message': message,
            'details': details
        })
    
    def log_bot_start(self, config: Dict[str, Any]):
        """Log bot startup."""
        # Remove sensitive config
        safe_config = self._sanitize(config)
        self.write_log('bot_start', {
            'config': safe_config
        })
    
    def log_bot_stop(self, reason: str):
        """Log bot shutdown."""
        self.write_log('bot_stop', {
            'reason': reason
        })
    
    def log_heartbeat(self, metrics: Dict[str, Any]):
        """Log periodic heartbeat with bot status."""
        self.write_log('heartbeat', {
            'metrics': metrics
        })
