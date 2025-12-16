"""
Position sizing with volatility targeting.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    Calculate position sizes based on volatility targeting.
    
    Includes:
    - Volatility targeting
    - Maximum position limits
    - Cash buffer management
    """
    
    def __init__(self, config: Dict):
        risk_config = config.get('risk', {})
        
        self.target_vol_1d = risk_config.get('target_vol_1d', 0.012)  # 1.2%
        self.max_positions = risk_config.get('max_positions', 2)
        self.weight_per_position_max = risk_config.get('weight_per_position_max', 0.30)  # 30%
        self.cash_buffer_min = risk_config.get('cash_buffer_min', 0.40)  # 40%
    
    def calculate_realized_vol(
        self,
        df: pd.DataFrame,
        window: int = 30
    ) -> float:
        """
        Calculate realized volatility from price data.
        
        Args:
            df: DataFrame with 'close' prices
            window: Lookback window in days
        
        Returns:
            Annualized volatility
        """
        if len(df) < window:
            window = len(df)
        
        if window < 2:
            return 0.0
        
        returns = df['close'].pct_change().dropna()
        vol = returns.tail(window).std() * np.sqrt(252)  # Annualized
        
        return vol if not np.isnan(vol) else 0.0
    
    def calculate_vol_target_weight(
        self,
        realized_vol: float,
        target_vol: Optional[float] = None
    ) -> float:
        """
        Calculate position weight based on volatility targeting.
        
        Weight = target_vol / realized_vol
        
        Args:
            realized_vol: Realized volatility
            target_vol: Target volatility (uses default if None)
        
        Returns:
            Position weight (0 to 1)
        """
        if target_vol is None:
            target_vol = self.target_vol_1d
        
        if realized_vol == 0 or np.isnan(realized_vol):
            return 0.0
        
        weight = target_vol / realized_vol
        
        # Cap at maximum
        weight = min(weight, self.weight_per_position_max)
        
        return weight
    
    def calculate_position_size(
        self,
        account_value: float,
        current_price: float,
        realized_vol: float,
        existing_positions: int = 0,
        target_vol: Optional[float] = None
    ) -> Dict[str, any]:
        """
        Calculate position size in units and dollars.
        
        Args:
            account_value: Total account value
            current_price: Current asset price
            realized_vol: Realized volatility
            existing_positions: Number of existing positions
            target_vol: Optional override for target volatility
        
        Returns:
            Dictionary with position sizing details
        """
        # Check if we can open new positions
        if existing_positions >= self.max_positions:
            return {
                'can_trade': False,
                'reason': 'Max positions reached',
                'size_usd': 0.0,
                'size_units': 0.0,
                'weight': 0.0
            }
        
        # Calculate available capital
        available_capital = account_value * (1 - self.cash_buffer_min)
        
        # Calculate weight based on volatility
        weight = self.calculate_vol_target_weight(realized_vol, target_vol)
        
        # Calculate position size in USD
        size_usd = account_value * weight
        
        # Check if we have enough capital
        if size_usd > available_capital:
            size_usd = available_capital
            weight = size_usd / account_value
        
        # Calculate size in units
        size_units = size_usd / current_price if current_price > 0 else 0.0
        
        # Validate
        can_trade = size_usd > 0 and size_units > 0
        
        return {
            'can_trade': can_trade,
            'reason': 'OK' if can_trade else 'Insufficient capital or invalid price',
            'size_usd': size_usd,
            'size_units': size_units,
            'weight': weight,
            'target_vol': target_vol if target_vol else self.target_vol_1d,
            'realized_vol': realized_vol
        }
    
    def adjust_for_regime(
        self,
        base_sizing: Dict[str, any],
        regime_metrics: Dict[str, any]
    ) -> Dict[str, any]:
        """
        Adjust position size based on regime.
        
        Reduces size if in high-risk regime.
        
        Args:
            base_sizing: Base position sizing from calculate_position_size()
            regime_metrics: Regime detection metrics
        
        Returns:
            Adjusted position sizing
        """
        adjusted = base_sizing.copy()
        
        if regime_metrics.get('block_trading', False):
            # Reduce position size by 50% in high correlation regime
            adjusted['size_usd'] *= 0.5
            adjusted['size_units'] *= 0.5
            adjusted['weight'] *= 0.5
            adjusted['reason'] = 'Reduced due to high correlation regime'
            logger.info("Position size reduced due to regime")
        
        return adjusted
    
    def get_max_positions_allowed(self) -> int:
        """Get maximum number of positions allowed."""
        return self.max_positions
    
    def get_cash_buffer_required(self, account_value: float) -> float:
        """Calculate required cash buffer in USD."""
        return account_value * self.cash_buffer_min
    
    def validate_portfolio(
        self,
        account_value: float,
        positions: Dict[str, Dict]
    ) -> Dict[str, any]:
        """
        Validate current portfolio against risk limits.
        
        Args:
            account_value: Total account value
            positions: Dictionary of current positions {symbol: position_data}
        
        Returns:
            Validation results
        """
        num_positions = len(positions)
        total_exposure = sum([p.get('value', 0) for p in positions.values()])
        
        cash_buffer = account_value - total_exposure
        cash_buffer_pct = cash_buffer / account_value if account_value > 0 else 0
        
        # Check violations
        violations = []
        
        if num_positions > self.max_positions:
            violations.append(f"Too many positions: {num_positions} > {self.max_positions}")
        
        if cash_buffer_pct < self.cash_buffer_min:
            violations.append(
                f"Insufficient cash buffer: {cash_buffer_pct*100:.1f}% < {self.cash_buffer_min*100:.1f}%"
            )
        
        for symbol, pos in positions.items():
            weight = pos.get('value', 0) / account_value if account_value > 0 else 0
            if weight > self.weight_per_position_max:
                violations.append(
                    f"{symbol} exceeds max weight: {weight*100:.1f}% > {self.weight_per_position_max*100:.1f}%"
                )
        
        is_valid = len(violations) == 0
        
        return {
            'is_valid': is_valid,
            'violations': violations,
            'num_positions': num_positions,
            'total_exposure': total_exposure,
            'cash_buffer_pct': cash_buffer_pct,
            'positions': positions
        }
