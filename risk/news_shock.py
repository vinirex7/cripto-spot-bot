"""
NewsShock v3: Combined sentiment and price shock analysis.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class NewsShockV3:
    """
    NewsShock v3 implementation.
    
    Formula:
    - SentLLM = sentiment * confidence
    - SentComb = 0.7*SentZ + 0.3*SentLLM
    - PriceShockZ_1h = ret_1h / vol_1h(EWMA)
    - NS_v3 = 0.6*SentComb - 0.4*PriceShockZ_1h
    
    Pause rules:
    - HARD PAUSE (6h): critical category + conf >= 0.65 + SentLLM <= -0.5
    - SOFT PAUSE (1-3h): NS_v3 <= -1.2
    """
    
    def __init__(self, config: Dict):
        ns_config = config.get('news_shock', {})
        
        # Weights
        self.weight_sent_comb = ns_config.get('weight_sent_comb', 0.6)
        self.weight_price_shock = ns_config.get('weight_price_shock', 0.4)
        self.weight_sent_z = ns_config.get('weight_sent_z', 0.7)
        self.weight_sent_llm = ns_config.get('weight_sent_llm', 0.3)
        
        # Hard pause
        hard_pause = ns_config.get('hard_pause', {})
        self.hard_pause_duration_hours = hard_pause.get('duration_hours', 6)
        self.hard_pause_min_confidence = hard_pause.get('min_confidence', 0.65)
        self.hard_pause_max_sent_llm = hard_pause.get('max_sent_llm', -0.5)
        self.critical_categories = hard_pause.get('critical_categories', [
            'regulation', 'hack', 'bankruptcy', 'delisting'
        ])
        
        # Soft pause
        soft_pause = ns_config.get('soft_pause', {})
        self.soft_pause_duration_hours = soft_pause.get('duration_hours', 3)
        self.soft_pause_threshold = soft_pause.get('ns_v3_threshold', -1.2)
        
        # Pause state
        self.pause_until: Dict[str, datetime] = {}
        self.pause_reasons: Dict[str, str] = {}
    
    def calculate_sent_llm(
        self,
        sentiment: float,
        confidence: float
    ) -> float:
        """Calculate SentLLM = sentiment * confidence."""
        return sentiment * confidence
    
    def calculate_sent_comb(
        self,
        sent_z: float,
        sent_llm: float
    ) -> float:
        """Calculate SentComb = 0.7*SentZ + 0.3*SentLLM."""
        return self.weight_sent_z * sent_z + self.weight_sent_llm * sent_llm
    
    def calculate_price_shock_z(
        self,
        df_1h: pd.DataFrame,
        ewma_span: int = 24
    ) -> float:
        """
        Calculate PriceShockZ_1h = ret_1h / vol_1h(EWMA).
        
        Args:
            df_1h: Hourly OHLCV data
            ewma_span: EWMA span for volatility calculation
        
        Returns:
            Price shock z-score
        """
        if len(df_1h) < 2:
            return 0.0
        
        # Calculate 1h return
        ret_1h = df_1h['close'].pct_change().iloc[-1]
        
        if pd.isna(ret_1h):
            return 0.0
        
        # Calculate EWMA volatility
        returns = df_1h['close'].pct_change().dropna()
        if len(returns) < ewma_span:
            vol_1h = returns.std()
        else:
            vol_1h = returns.ewm(span=ewma_span).std().iloc[-1]
        
        if vol_1h == 0 or pd.isna(vol_1h):
            return 0.0
        
        price_shock_z = ret_1h / vol_1h
        return price_shock_z
    
    def calculate_ns_v3(
        self,
        sent_comb: float,
        price_shock_z: float
    ) -> float:
        """
        Calculate NS_v3 = 0.6*SentComb - 0.4*PriceShockZ_1h.
        
        Args:
            sent_comb: Combined sentiment
            price_shock_z: Price shock z-score
        
        Returns:
            NewsShock v3 score
        """
        ns_v3 = (
            self.weight_sent_comb * sent_comb -
            self.weight_price_shock * price_shock_z
        )
        return ns_v3
    
    def check_hard_pause(
        self,
        symbol: str,
        category: str,
        confidence: float,
        sent_llm: float,
        current_time: datetime
    ) -> bool:
        """
        Check if hard pause should be triggered.
        
        HARD PAUSE (6h): critical category + conf >= 0.65 + SentLLM <= -0.5
        
        Args:
            symbol: Trading pair
            category: News category
            confidence: Confidence score
            sent_llm: SentLLM score
            current_time: Current timestamp
        
        Returns:
            True if hard pause triggered
        """
        if (
            category in self.critical_categories and
            confidence >= self.hard_pause_min_confidence and
            sent_llm <= self.hard_pause_max_sent_llm
        ):
            # Trigger hard pause
            pause_until = current_time + timedelta(hours=self.hard_pause_duration_hours)
            self.pause_until[symbol] = pause_until
            self.pause_reasons[symbol] = f"HARD_PAUSE: {category} news (conf={confidence:.2f}, sent_llm={sent_llm:.2f})"
            
            logger.warning(f"Hard pause triggered for {symbol} until {pause_until}: {category}")
            return True
        
        return False
    
    def check_soft_pause(
        self,
        symbol: str,
        ns_v3: float,
        current_time: datetime
    ) -> bool:
        """
        Check if soft pause should be triggered.
        
        SOFT PAUSE (1-3h): NS_v3 <= -1.2
        
        Args:
            symbol: Trading pair
            ns_v3: NewsShock v3 score
            current_time: Current timestamp
        
        Returns:
            True if soft pause triggered
        """
        if ns_v3 <= self.soft_pause_threshold:
            # Trigger soft pause
            pause_until = current_time + timedelta(hours=self.soft_pause_duration_hours)
            self.pause_until[symbol] = pause_until
            self.pause_reasons[symbol] = f"SOFT_PAUSE: NS_v3={ns_v3:.2f}"
            
            logger.warning(f"Soft pause triggered for {symbol} until {pause_until}")
            return True
        
        return False
    
    def is_paused(self, symbol: str, current_time: datetime) -> bool:
        """
        Check if symbol is currently paused.
        
        Args:
            symbol: Trading pair
            current_time: Current timestamp
        
        Returns:
            True if paused, False otherwise
        """
        if symbol not in self.pause_until:
            return False
        
        pause_until = self.pause_until[symbol]
        
        if current_time >= pause_until:
            # Pause expired
            del self.pause_until[symbol]
            if symbol in self.pause_reasons:
                del self.pause_reasons[symbol]
            logger.info(f"Pause expired for {symbol}")
            return False
        
        return True
    
    def get_pause_info(self, symbol: str) -> Optional[Dict]:
        """Get pause information for a symbol."""
        if symbol not in self.pause_until:
            return None
        
        return {
            'paused': True,
            'pause_until': self.pause_until[symbol].isoformat(),
            'reason': self.pause_reasons.get(symbol, 'Unknown')
        }
    
    def analyze_news_shock(
        self,
        symbol: str,
        sent_z: float,
        llm_sentiment: float,
        llm_confidence: float,
        llm_category: str,
        df_1h: pd.DataFrame,
        current_time: datetime
    ) -> Dict[str, any]:
        """
        Complete NewsShock v3 analysis.
        
        Args:
            symbol: Trading pair
            sent_z: Quantitative sentiment z-score
            llm_sentiment: LLM sentiment score
            llm_confidence: LLM confidence score
            llm_category: LLM news category
            df_1h: Hourly OHLCV data
            current_time: Current timestamp
        
        Returns:
            Dictionary with NewsShock analysis
        """
        # Calculate components
        sent_llm = self.calculate_sent_llm(llm_sentiment, llm_confidence)
        sent_comb = self.calculate_sent_comb(sent_z, sent_llm)
        price_shock_z = self.calculate_price_shock_z(df_1h)
        ns_v3 = self.calculate_ns_v3(sent_comb, price_shock_z)
        
        # Check pauses
        hard_pause_triggered = self.check_hard_pause(
            symbol, llm_category, llm_confidence, sent_llm, current_time
        )
        
        soft_pause_triggered = False
        if not hard_pause_triggered:
            soft_pause_triggered = self.check_soft_pause(symbol, ns_v3, current_time)
        
        # Check if currently paused
        is_paused = self.is_paused(symbol, current_time)
        pause_info = self.get_pause_info(symbol)
        
        return {
            'sent_llm': sent_llm,
            'sent_comb': sent_comb,
            'price_shock_z': price_shock_z,
            'ns_v3': ns_v3,
            'hard_pause_triggered': hard_pause_triggered,
            'soft_pause_triggered': soft_pause_triggered,
            'is_paused': is_paused,
            'pause_info': pause_info
        }
