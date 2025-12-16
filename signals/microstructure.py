"""
Microstructure signals: spread, OFI, VWAP, Amihud illiquidity.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class MicrostructureSignals:
    """
    Microstructure analysis for trade execution quality.
    
    Includes:
    - Spread guard (basis points)
    - Order Flow Imbalance (OFI) z-score
    - VWAP deviation
    - Amihud illiquidity measure
    """
    
    def __init__(self, config: Dict):
        self.spread_max_bps = config.get('spread_max_bps', 12)
        
        ofi_config = config.get('ofi', {})
        self.ofi_z_max = ofi_config.get('z_score_max', 3.0)
        
        vwap_config = config.get('vwap', {})
        self.vwap_max_dev_pct = vwap_config.get('max_deviation_pct', 1.5)
        
        amihud_config = config.get('amihud', {})
        self.use_p95_threshold = amihud_config.get('use_p95_threshold', True)
    
    def calculate_spread_bps(
        self,
        bid_price: float,
        ask_price: float,
        mid_price: Optional[float] = None
    ) -> float:
        """
        Calculate bid-ask spread in basis points.
        
        Spread (bps) = (ask - bid) / mid * 10000
        
        Args:
            bid_price: Best bid price
            ask_price: Best ask price
            mid_price: Mid price (optional, calculated if not provided)
        
        Returns:
            Spread in basis points
        """
        if mid_price is None:
            mid_price = (bid_price + ask_price) / 2
        
        if mid_price == 0:
            return float('inf')
        
        spread_bps = ((ask_price - bid_price) / mid_price) * 10000
        return spread_bps
    
    def check_spread_guard(
        self,
        bid_price: float,
        ask_price: float
    ) -> bool:
        """
        Check if spread is within acceptable limits.
        
        Returns:
            True if spread is acceptable, False otherwise
        """
        spread_bps = self.calculate_spread_bps(bid_price, ask_price)
        return spread_bps <= self.spread_max_bps
    
    def calculate_ofi(
        self,
        order_book: Dict,
        prev_order_book: Optional[Dict] = None
    ) -> float:
        """
        Calculate Order Flow Imbalance (OFI).
        
        OFI measures the net buying/selling pressure from order book changes.
        
        Args:
            order_book: Current order book with 'bids' and 'asks'
            prev_order_book: Previous order book snapshot
        
        Returns:
            OFI value
        """
        if not prev_order_book:
            return 0.0
        
        try:
            # Get bid and ask volumes
            bids = order_book.get('bids', [])
            asks = order_book.get('asks', [])
            prev_bids = prev_order_book.get('bids', [])
            prev_asks = prev_order_book.get('asks', [])
            
            if not bids or not asks or not prev_bids or not prev_asks:
                return 0.0
            
            # Calculate volume changes
            bid_volume = sum([float(b[1]) for b in bids[:10]])
            ask_volume = sum([float(a[1]) for a in asks[:10]])
            prev_bid_volume = sum([float(b[1]) for b in prev_bids[:10]])
            prev_ask_volume = sum([float(a[1]) for a in prev_asks[:10]])
            
            delta_bid = bid_volume - prev_bid_volume
            delta_ask = ask_volume - prev_ask_volume
            
            # OFI = delta_bid - delta_ask
            ofi = delta_bid - delta_ask
            return ofi
        
        except Exception as e:
            logger.error(f"Error calculating OFI: {e}")
            return 0.0
    
    def calculate_ofi_zscore(
        self,
        ofi_history: pd.Series,
        window: int = 100
    ) -> float:
        """
        Calculate z-score of OFI.
        
        Args:
            ofi_history: Historical OFI values
            window: Rolling window for mean/std calculation
        
        Returns:
            OFI z-score
        """
        if len(ofi_history) < window:
            return 0.0
        
        recent_ofi = ofi_history.tail(window)
        mean = recent_ofi.mean()
        std = recent_ofi.std()
        
        if std == 0 or np.isnan(std):
            return 0.0
        
        current_ofi = ofi_history.iloc[-1]
        z_score = (current_ofi - mean) / std
        return z_score
    
    def check_ofi_guard(self, ofi_zscore: float) -> bool:
        """
        Check if OFI z-score is within acceptable limits.
        
        Returns:
            True if OFI is acceptable, False if extreme
        """
        return abs(ofi_zscore) <= self.ofi_z_max
    
    def calculate_vwap(self, df: pd.DataFrame) -> float:
        """
        Calculate Volume-Weighted Average Price (VWAP).
        
        VWAP = sum(price * volume) / sum(volume)
        
        Args:
            df: DataFrame with 'close' and 'volume' columns
        
        Returns:
            VWAP value
        """
        if df.empty or 'close' not in df.columns or 'volume' not in df.columns:
            return 0.0
        
        total_volume = df['volume'].sum()
        if total_volume == 0:
            return 0.0
        
        vwap = (df['close'] * df['volume']).sum() / total_volume
        return vwap
    
    def check_vwap_guard(
        self,
        current_price: float,
        vwap: float
    ) -> bool:
        """
        Check if current price is within acceptable deviation from VWAP.
        
        Block if |P - VWAP| / VWAP > max_deviation_pct
        
        Returns:
            True if acceptable, False if too far from VWAP
        """
        if vwap == 0:
            return False
        
        deviation_pct = abs(current_price - vwap) / vwap * 100
        return deviation_pct <= self.vwap_max_dev_pct
    
    def calculate_amihud_illiq(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate Amihud illiquidity measure.
        
        ILLIQ = |return| / volume
        
        Higher values indicate lower liquidity.
        
        Args:
            df: DataFrame with 'close' and 'volume' columns
        
        Returns:
            Series of Amihud illiquidity values
        """
        if df.empty or len(df) < 2:
            return pd.Series()
        
        returns = df['close'].pct_change().abs()
        volume = df['volume']
        
        # Avoid division by zero
        illiq = returns / volume.replace(0, np.nan)
        return illiq.fillna(0)
    
    def check_amihud_guard(
        self,
        current_illiq: float,
        illiq_history: pd.Series
    ) -> bool:
        """
        Check if current illiquidity is acceptable.
        
        Block if current ILLIQ > p95 of historical ILLIQ.
        
        Returns:
            True if acceptable, False if too illiquid
        """
        if not self.use_p95_threshold or illiq_history.empty:
            return True
        
        p95 = illiq_history.quantile(0.95)
        return current_illiq <= p95
    
    def get_microstructure_metrics(
        self,
        current_price: float,
        bid_price: float,
        ask_price: float,
        df_1h: pd.DataFrame,
        order_book: Optional[Dict] = None,
        prev_order_book: Optional[Dict] = None,
        ofi_history: Optional[pd.Series] = None
    ) -> Dict[str, any]:
        """
        Calculate all microstructure metrics and guards.
        
        Args:
            current_price: Current market price
            bid_price: Best bid
            ask_price: Best ask
            df_1h: Hourly OHLCV data
            order_book: Current order book
            prev_order_book: Previous order book
            ofi_history: Historical OFI values
        
        Returns:
            Dictionary with metrics and guard results
        """
        # Spread
        spread_bps = self.calculate_spread_bps(bid_price, ask_price)
        spread_ok = spread_bps <= self.spread_max_bps
        
        # OFI
        ofi = 0.0
        ofi_zscore = 0.0
        ofi_ok = True
        if order_book and prev_order_book and ofi_history is not None:
            ofi = self.calculate_ofi(order_book, prev_order_book)
            ofi_zscore = self.calculate_ofi_zscore(ofi_history)
            ofi_ok = self.check_ofi_guard(ofi_zscore)
        
        # VWAP (1h only as per spec)
        vwap = self.calculate_vwap(df_1h.tail(1))  # Last 1 hour
        vwap_ok = self.check_vwap_guard(current_price, vwap)
        
        # Amihud
        illiq_series = self.calculate_amihud_illiq(df_1h)
        current_illiq = illiq_series.iloc[-1] if not illiq_series.empty else 0.0
        amihud_ok = self.check_amihud_guard(current_illiq, illiq_series)
        
        # Overall pass/fail
        all_guards_pass = spread_ok and ofi_ok and vwap_ok and amihud_ok
        
        return {
            'spread_bps': spread_bps,
            'spread_ok': spread_ok,
            'ofi': ofi,
            'ofi_zscore': ofi_zscore,
            'ofi_ok': ofi_ok,
            'vwap': vwap,
            'vwap_ok': vwap_ok,
            'current_illiq': current_illiq,
            'amihud_ok': amihud_ok,
            'all_guards_pass': all_guards_pass
        }
