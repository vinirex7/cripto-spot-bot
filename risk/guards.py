"""
Microstructure guards for trade execution quality.
"""
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class Guards:
    """
    Comprehensive risk guards for trade execution.
    
    Includes:
    - Spread checks
    - OFI checks
    - VWAP deviation checks
    - Liquidity checks
    - Drawdown checks
    """
    
    def __init__(self, config: Dict):
        risk_config = config.get('risk', {})
        self.daily_drawdown_pause_pct = risk_config.get('daily_drawdown_pause_pct', 2.5)
        self.max_holding_hours = risk_config.get('max_holding_hours', 72)
    
    def check_all_guards(
        self,
        microstructure_metrics: Dict,
        position_data: Optional[Dict] = None,
        daily_pnl_pct: Optional[float] = None
    ) -> Dict[str, any]:
        """
        Check all risk guards.
        
        Args:
            microstructure_metrics: Metrics from MicrostructureSignals
            position_data: Current position data (if any)
            daily_pnl_pct: Daily P&L percentage
        
        Returns:
            Dictionary with guard results and reasons
        """
        guards_pass = True
        reasons = []
        
        # Microstructure guards
        if not microstructure_metrics.get('all_guards_pass', False):
            guards_pass = False
            
            if not microstructure_metrics.get('spread_ok', True):
                reasons.append(f"Spread too wide: {microstructure_metrics.get('spread_bps', 0):.1f} bps")
            
            if not microstructure_metrics.get('ofi_ok', True):
                reasons.append(f"OFI extreme: z={microstructure_metrics.get('ofi_zscore', 0):.2f}")
            
            if not microstructure_metrics.get('vwap_ok', True):
                reasons.append(f"Price far from VWAP")
            
            if not microstructure_metrics.get('amihud_ok', True):
                reasons.append(f"Illiquidity too high")
        
        # Drawdown guard
        if daily_pnl_pct is not None and daily_pnl_pct < -self.daily_drawdown_pause_pct:
            guards_pass = False
            reasons.append(f"Daily drawdown exceeded: {daily_pnl_pct:.2f}%")
        
        # Holding period guard
        if position_data:
            holding_hours = position_data.get('holding_hours', 0)
            if holding_hours > self.max_holding_hours:
                guards_pass = False
                reasons.append(f"Max holding period exceeded: {holding_hours:.1f}h")
        
        return {
            'guards_pass': guards_pass,
            'reasons': reasons,
            'drawdown_ok': daily_pnl_pct is None or daily_pnl_pct >= -self.daily_drawdown_pause_pct,
            'holding_period_ok': position_data is None or position_data.get('holding_hours', 0) <= self.max_holding_hours
        }
    
    def should_force_exit(
        self,
        position_data: Dict,
        microstructure_metrics: Dict,
        daily_pnl_pct: float
    ) -> bool:
        """
        Determine if position should be force-exited due to risk.
        
        Args:
            position_data: Current position data
            microstructure_metrics: Microstructure metrics
            daily_pnl_pct: Daily P&L percentage
        
        Returns:
            True if should force exit
        """
        # Force exit if daily drawdown exceeded
        if daily_pnl_pct < -self.daily_drawdown_pause_pct:
            logger.warning(f"Force exit due to drawdown: {daily_pnl_pct:.2f}%")
            return True
        
        # Force exit if holding period exceeded
        holding_hours = position_data.get('holding_hours', 0)
        if holding_hours > self.max_holding_hours:
            logger.warning(f"Force exit due to holding period: {holding_hours:.1f}h")
            return True
        
        return False
