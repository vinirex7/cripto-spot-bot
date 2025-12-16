"""
Metrics collection and monitoring for bot performance.
"""
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Collect and track bot performance metrics.
    
    Tracks:
    - Equity curve
    - Drawdown
    - Trade count
    - Pause events
    - Error rates
    """
    
    def __init__(self):
        self.metrics_history: List[Dict] = []
        self.trade_count = 0
        self.error_count = 0
        self.pause_count = 0
        self.start_time = time.time()
        self.last_equity = None
        self.peak_equity = None
        self.current_drawdown_pct = 0.0
    
    def record_equity(self, equity: float, timestamp: Optional[datetime] = None):
        """Record current equity for tracking."""
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        self.last_equity = equity
        
        # Update peak
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        
        # Calculate drawdown
        if self.peak_equity > 0:
            self.current_drawdown_pct = ((self.peak_equity - equity) / self.peak_equity) * 100
        
        self.metrics_history.append({
            'timestamp': timestamp,
            'equity': equity,
            'drawdown_pct': self.current_drawdown_pct
        })
    
    def record_trade(self):
        """Increment trade counter."""
        self.trade_count += 1
    
    def record_error(self):
        """Increment error counter."""
        self.error_count += 1
    
    def record_pause(self):
        """Increment pause counter."""
        self.pause_count += 1
    
    def get_current_metrics(self) -> Dict:
        """Get current metrics snapshot."""
        uptime_hours = (time.time() - self.start_time) / 3600
        
        return {
            'equity': self.last_equity,
            'peak_equity': self.peak_equity,
            'current_drawdown_pct': self.current_drawdown_pct,
            'total_trades': self.trade_count,
            'trades_per_day': (self.trade_count / uptime_hours * 24) if uptime_hours > 0 else 0,
            'error_count': self.error_count,
            'pause_count': self.pause_count,
            'uptime_hours': uptime_hours
        }
    
    def get_equity_curve(self) -> pd.DataFrame:
        """Get equity curve as DataFrame."""
        if not self.metrics_history:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.metrics_history)
        df.set_index('timestamp', inplace=True)
        return df
    
    def check_alert_conditions(self, config: Dict) -> List[str]:
        """
        Check if any alert conditions are met.
        
        Args:
            config: Alert configuration
        
        Returns:
            List of alert messages
        """
        alerts = []
        
        # Drawdown alert
        max_dd_alert = config.get('max_drawdown_alert_pct', 5.0)
        if self.current_drawdown_pct > max_dd_alert:
            alerts.append(
                f"⚠️  DRAWDOWN ALERT: Current drawdown {self.current_drawdown_pct:.2f}% "
                f"exceeds threshold {max_dd_alert}%"
            )
        
        # Error rate alert
        error_threshold = config.get('max_errors_per_hour', 10)
        uptime_hours = (time.time() - self.start_time) / 3600
        if uptime_hours > 0:
            error_rate = self.error_count / uptime_hours
            if error_rate > error_threshold:
                alerts.append(
                    f"⚠️  ERROR RATE ALERT: {error_rate:.1f} errors/hour "
                    f"exceeds threshold {error_threshold}"
                )
        
        return alerts
    
    def print_summary(self):
        """Print metrics summary to console."""
        metrics = self.get_current_metrics()
        
        print("\n" + "="*50)
        print(" BOT METRICS SUMMARY")
        print("="*50)
        print(f"Equity:             ${metrics['equity']:>12,.2f}")
        print(f"Peak Equity:        ${metrics['peak_equity']:>12,.2f}")
        print(f"Current Drawdown:   {metrics['current_drawdown_pct']:>12.2f}%")
        print(f"Total Trades:       {metrics['total_trades']:>12}")
        print(f"Trades/Day:         {metrics['trades_per_day']:>12.1f}")
        print(f"Errors:             {metrics['error_count']:>12}")
        print(f"Pauses:             {metrics['pause_count']:>12}")
        print(f"Uptime:             {metrics['uptime_hours']:>12.1f}h")
        print("="*50 + "\n")


class AlertManager:
    """
    Alert manager for critical events.
    
    Can send alerts via:
    - Console (always)
    - Webhook (optional)
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.webhook_url = self.config.get('webhook_url')
        self.alert_history: List[Dict] = []
    
    def send_alert(self, level: str, message: str):
        """
        Send alert.
        
        Args:
            level: Alert level (INFO, WARNING, ERROR, CRITICAL)
            message: Alert message
        """
        timestamp = datetime.utcnow()
        
        # Log to console
        if level == 'CRITICAL':
            logger.critical(f"🚨 {message}")
        elif level == 'ERROR':
            logger.error(f"❌ {message}")
        elif level == 'WARNING':
            logger.warning(f"⚠️  {message}")
        else:
            logger.info(f"ℹ️  {message}")
        
        # Record in history
        self.alert_history.append({
            'timestamp': timestamp,
            'level': level,
            'message': message
        })
        
        # Send via webhook if configured
        if self.webhook_url:
            self._send_webhook(level, message, timestamp)
    
    def _send_webhook(self, level: str, message: str, timestamp: datetime):
        """Send alert via webhook (placeholder implementation)."""
        try:
            import requests
            
            payload = {
                'level': level,
                'message': message,
                'timestamp': timestamp.isoformat(),
                'bot': 'Vini QuantBot v3.0.1'
            }
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=5
            )
            
            if response.status_code != 200:
                logger.warning(f"Webhook failed: {response.status_code}")
        
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
    
    def get_recent_alerts(self, hours: int = 24) -> List[Dict]:
        """Get alerts from the last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return [
            alert for alert in self.alert_history
            if alert['timestamp'] > cutoff
        ]
