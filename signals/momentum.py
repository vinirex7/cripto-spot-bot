"""
Momentum 2.0 signal with age-based decay and bootstrap validation.
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class MomentumSignal:
    """
    Momentum 2.0 signal generator with age-based decay.
    
    Formula: M = sum(log_returns) / sigma
    Age decay: 0-12m → 1.00, 12-15m → 0.75, 15-18m → 0.50, 18m+ → 0.25
    """
    
    def __init__(self, config: Dict):
        self.short_window = config.get('short_window', 60)
        self.mid_window = config.get('mid_window', 90)
        self.long_window = config.get('long_window', 120)
        self.sma_window = config.get('sma_window', 50)
        
        # Age decay thresholds (in months)
        age_decay = config.get('age_decay', {})
        self.age_excellent = age_decay.get('excellent', 12)
        self.age_good = age_decay.get('good', 15)
        self.age_fair = age_decay.get('fair', 18)
        
        # Entry/exit conditions
        entry = config.get('entry', {})
        self.min_age_factor = entry.get('min_age_factor', 0.5)
        self.min_delta_m = entry.get('min_delta_m', 0.0)
        
        exit_config = config.get('exit', {})
        self.max_age_factor = exit_config.get('max_age_factor', 0.0)
        self.max_delta_m_days = exit_config.get('max_delta_m_days', 3)
        self.use_sma_exit = exit_config.get('use_sma_exit', True)
    
    def calculate_momentum(self, df: pd.DataFrame, window: int) -> float:
        """
        Calculate momentum for a given window.
        
        M = sum(log_returns) / sigma
        
        Args:
            df: DataFrame with 'close' prices
            window: Lookback window in days
        
        Returns:
            Momentum value
        """
        if len(df) < window:
            return 0.0
        
        prices = df['close'].tail(window)
        log_returns = np.log(prices / prices.shift(1)).dropna()
        
        if len(log_returns) == 0:
            return 0.0
        
        sigma = log_returns.std()
        if sigma == 0 or np.isnan(sigma):
            return 0.0
        
        momentum = log_returns.sum() / sigma
        return momentum
    
    def get_age_factor(self, df: pd.DataFrame) -> float:
        """
        Calculate age-based decay factor.
        
        Age is measured as months since the oldest data point.
        0-12m → 1.00
        12-15m → 0.75
        15-18m → 0.50
        18m+ → 0.25
        
        Args:
            df: DataFrame with timestamp index
        
        Returns:
            Age factor (0.25 to 1.00)
        """
        if df.empty:
            return 0.25
        
        oldest_date = df.index.min()
        newest_date = df.index.max()
        
        age_months = (newest_date - oldest_date).days / 30.0
        
        if age_months >= self.age_fair:
            return 0.25
        elif age_months >= self.age_good:
            return 0.50
        elif age_months >= self.age_excellent:
            return 0.75
        else:
            return 1.00
    
    def calculate_signals(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate all momentum signals and metrics.
        
        Args:
            df: DataFrame with OHLCV data (daily)
        
        Returns:
            Dictionary with momentum metrics
        """
        if len(df) < self.long_window:
            logger.warning(f"Insufficient data for momentum calculation: {len(df)} < {self.long_window}")
            return {
                'M_short': 0.0,
                'M_mid': 0.0,
                'M_long': 0.0,
                'M_age_factor': 0.0,
                'delta_M': 0.0,
                'sma50': 0.0,
                'current_price': 0.0,
                'signal': 0
            }
        
        # Calculate momentum for different windows
        M_short = self.calculate_momentum(df, self.short_window)
        M_mid = self.calculate_momentum(df, self.mid_window)
        M_long = self.calculate_momentum(df, self.long_window)
        
        # Calculate age factor
        M_age_factor = self.get_age_factor(df)
        
        # Calculate delta M (acceleration: M_short - M_long)
        # This measures the difference between short and long momentum
        delta_M = M_short - M_long
        
        # Calculate SMA
        sma50 = df['close'].tail(self.sma_window).mean()
        current_price = df['close'].iloc[-1]
        
        
        
        # Bootstrap validation
bootstrap_metrics = self.block_bootstrap(df)

# Generate raw signal
signal = self._generate_signal(
    M_age_factor, delta_M, current_price, sma50
)

# Apply bootstrap gate (BLOCK ENTRY)
if signal == 1 and not self.check_bootstrap_gate(bootstrap_metrics):
    signal = 0

        
        return {
            'M_short': M_short,
            'M_mid': M_mid,
            'M_long': M_long,
            'M_age_factor': M_age_factor,
            'delta_M': delta_M,
            'sma50': sma50,
            'current_price': current_price,
            'bootstrap': bootstrap_metrics,
            'signal': signal
        }
    
    def _generate_signal(
        self,
        M_age_factor: float,
        delta_M: float,
        current_price: float,
        sma50: float
    ) -> int:
        """
        Generate buy/sell/hold signal based on momentum conditions.
        
        Buy: M_age >= 0.5 AND ΔM >= 0
        Exit: M_age < 0 OR (ΔM < 0 for X days) OR (P < SMA50)
        
        Returns:
            1 for buy, -1 for exit, 0 for hold
        """
        # Exit conditions
        if M_age_factor < self.max_age_factor:
            return -1
        
        if self.use_sma_exit and current_price < sma50:
            return -1
        
        # Entry conditions
        if M_age_factor >= self.min_age_factor and delta_M >= self.min_delta_m:
            return 1
        
        # Hold
        return 0
    
    def block_bootstrap(
        self,
        df: pd.DataFrame,
        block_size: int = 7,
        n_resamples: int = 400
    ) -> Dict[str, float]:
        """
        Perform block bootstrap on daily returns to assess momentum stability.
        
        Only applied to 1d series.
        
        Args:
            df: DataFrame with daily OHLCV data
            block_size: Block size in days (5-10)
            n_resamples: Number of bootstrap resamples
        
        Returns:
            Dictionary with bootstrap metrics
        """
        if len(df) < self.long_window:
            return {
                'p_win_mom': 0.0,
                'M_p05': 0.0,
                'M_mean': 0.0,
                'M_std': 0.0,
                'stability': 0.0
            }
        
        # Calculate log returns
        log_returns = np.log(df['close'] / df['close'].shift(1)).dropna()
        
        if len(log_returns) < block_size:
            return {
                'p_win_mom': 0.0,
                'M_p05': 0.0,
                'M_mean': 0.0,
                'M_std': 0.0,
                'stability': 0.0
            }
        
        # Perform block bootstrap
        momentums = []
        n_blocks = len(log_returns) // block_size
        
        for _ in range(n_resamples):
            # Sample blocks with replacement
            sampled_returns = []
            for _ in range(n_blocks):
                block_start = np.random.randint(0, len(log_returns) - block_size + 1)
                block = log_returns.iloc[block_start:block_start + block_size]
                sampled_returns.extend(block.values)
            
            # Calculate momentum for this bootstrap sample
            sampled_returns = np.array(sampled_returns)
            if len(sampled_returns) >= self.long_window:
                sampled_returns = sampled_returns[-self.long_window:]
                sigma = np.std(sampled_returns)
                if sigma > 0:
                    M = np.sum(sampled_returns) / sigma
                    momentums.append(M)
        
        if not momentums:
            return {
                'p_win_mom': 0.0,
                'M_p05': 0.0,
                'M_mean': 0.0,
                'M_std': 0.0,
                'stability': 0.0
            }
        
        # Calculate metrics
        momentums = np.array(momentums)
        p_win_mom = np.mean(momentums > 0)
        M_p05 = np.percentile(momentums, 5)
        M_mean = np.mean(momentums)
        M_std = np.std(momentums)
        
        # Stability = 1 - std(M_boot) / |mean(M_boot)|
        if abs(M_mean) > 0:
            stability = 1 - (M_std / abs(M_mean))
        else:
            stability = 0.0
        
        return {
            'p_win_mom': p_win_mom,
            'M_p05': M_p05,
            'M_mean': M_mean,
            'M_std': M_std,
            'stability': stability
        }
    
    def check_bootstrap_gate(
        self,
        bootstrap_metrics: Dict[str, float],
        min_pwin: float = 0.60
    ) -> bool:
        """
        Check if momentum passes bootstrap gate.
        
        Args:
            bootstrap_metrics: Bootstrap metrics from block_bootstrap()
            min_pwin: Minimum P(M > 0) threshold
        
        Returns:
            True if passes gate, False otherwise
        """
        p_win = bootstrap_metrics.get('p_win_mom', 0.0)
        return p_win >= min_pwin
