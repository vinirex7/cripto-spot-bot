"""
Regime detection based on correlation and volatility.
"""
import pandas as pd
import numpy as np
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class RegimeDetector:
    """
    Detect market regime based on BTC vs alts correlation and volatility.
    
    Block condition: corr_mean > threshold AND vol_7d > vol_30d
    """
    
    def __init__(self, config: Dict):
        self.corr_window_short = config.get('corr_window_short', 7)
        self.corr_window_long = config.get('corr_window_long', 30)
        self.corr_threshold = config.get('corr_threshold', 0.75)
        self.vol_ratio_threshold = config.get('vol_ratio_threshold', 1.0)
    
    def calculate_correlation(
        self,
        btc_returns: pd.Series,
        alt_returns: pd.Series,
        window: int
    ) -> float:
        """
        Calculate rolling correlation between BTC and alt returns.
        
        Args:
            btc_returns: BTC returns series
            alt_returns: Alt coin returns series
            window: Rolling window in days
        
        Returns:
            Correlation coefficient
        """
        if len(btc_returns) < window or len(alt_returns) < window:
            return 0.0
        
        # Align series
        aligned = pd.DataFrame({
            'btc': btc_returns,
            'alt': alt_returns
        }).dropna()
        
        if len(aligned) < window:
            return 0.0
        
        corr = aligned['btc'].tail(window).corr(aligned['alt'].tail(window))
        return corr if not np.isnan(corr) else 0.0
    
    def calculate_volatility(
        self,
        returns: pd.Series,
        window: int
    ) -> float:
        """
        Calculate rolling volatility (standard deviation of returns).
        
        Args:
            returns: Returns series
            window: Rolling window in days
        
        Returns:
            Volatility (annualized)
        """
        if len(returns) < window:
            return 0.0
        
        vol = returns.tail(window).std() * np.sqrt(252)  # Annualized
        return vol if not np.isnan(vol) else 0.0
    
    def detect_regime(
        self,
        btc_df: pd.DataFrame,
        alt_dfs: Dict[str, pd.DataFrame]
    ) -> Dict[str, any]:
        """
        Detect current market regime.
        
        Args:
            btc_df: BTC OHLCV DataFrame
            alt_dfs: Dictionary of alt coin DataFrames {symbol: df}
        
        Returns:
            Dictionary with regime metrics and block signal
        """
        if btc_df.empty or not alt_dfs:
            return {
                'regime': 'unknown',
                'block_trading': False,
                'corr_mean_short': 0.0,
                'corr_mean_long': 0.0,
                'vol_7d': 0.0,
                'vol_30d': 0.0,
                'vol_ratio': 0.0
            }
        
        # Calculate BTC returns
        btc_returns = btc_df['close'].pct_change().dropna()
        
        # Calculate correlations for each alt
        corrs_short = []
        corrs_long = []
        
        for symbol, alt_df in alt_dfs.items():
            if alt_df.empty:
                continue
            
            alt_returns = alt_df['close'].pct_change().dropna()
            
            # Short-term correlation
            corr_short = self.calculate_correlation(
                btc_returns, alt_returns, self.corr_window_short
            )
            corrs_short.append(corr_short)
            
            # Long-term correlation
            corr_long = self.calculate_correlation(
                btc_returns, alt_returns, self.corr_window_long
            )
            corrs_long.append(corr_long)
        
        # Average correlations
        corr_mean_short = np.mean(corrs_short) if corrs_short else 0.0
        corr_mean_long = np.mean(corrs_long) if corrs_long else 0.0
        
        # Calculate BTC volatility
        vol_7d = self.calculate_volatility(btc_returns, self.corr_window_short)
        vol_30d = self.calculate_volatility(btc_returns, self.corr_window_long)
        vol_ratio = vol_7d / vol_30d if vol_30d > 0 else 0.0
        
        # Determine regime
        block_trading = (
            corr_mean_short > self.corr_threshold and
            vol_ratio > self.vol_ratio_threshold
        )
        
        regime = 'high_correlation_high_vol' if block_trading else 'normal'
        
        return {
            'regime': regime,
            'block_trading': block_trading,
            'corr_mean_short': corr_mean_short,
            'corr_mean_long': corr_mean_long,
            'vol_7d': vol_7d,
            'vol_30d': vol_30d,
            'vol_ratio': vol_ratio
        }
    
    def should_reduce_risk(self, regime_metrics: Dict[str, any]) -> bool:
        """
        Determine if risk should be reduced based on regime.
        
        Args:
            regime_metrics: Output from detect_regime()
        
        Returns:
            True if should reduce risk, False otherwise
        """
        return regime_metrics.get('block_trading', False)
