"""
Quantitative sentiment scoring without LLM.
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class QuantitativeSentiment:
    """
    Quantitative sentiment scoring based on news metadata.
    
    Does NOT use LLM - only uses CryptoPanic votes and metadata.
    """
    
    def __init__(self, config: Dict):
        self.half_life_hours = config.get('half_life_hours', 12)
        self.baseline_window_days = config.get('baseline_window_days', 30)
    
    def calculate_news_score(self, news_item: Dict) -> float:
        """
        Calculate sentiment score from news metadata.
        
        Uses CryptoPanic votes: positive, negative, important, liked, etc.
        
        Args:
            news_item: Parsed news item with 'votes' field
        
        Returns:
            Sentiment score (-1 to 1)
        """
        votes = news_item.get('votes', {})
        
        # Extract vote counts
        positive = votes.get('positive', 0)
        negative = votes.get('negative', 0)
        important = votes.get('important', 0)
        liked = votes.get('liked', 0)
        disliked = votes.get('disliked', 0)
        lol = votes.get('lol', 0)
        toxic = votes.get('toxic', 0)
        saved = votes.get('saved', 0)
        
        # Calculate sentiment
        # Positive indicators: positive, liked, important, saved
        # Negative indicators: negative, disliked, toxic
        
        pos_score = positive + liked + important * 0.5 + saved * 0.3
        neg_score = negative + disliked + toxic * 1.5
        
        total = pos_score + neg_score
        if total == 0:
            return 0.0
        
        # Normalize to [-1, 1]
        sentiment = (pos_score - neg_score) / total
        
        # Apply kind weighting
        kind = news_item.get('kind', '')
        if kind == 'news':
            # News is more reliable
            sentiment *= 1.0
        elif kind == 'media':
            # Media less reliable
            sentiment *= 0.7
        
        return np.clip(sentiment, -1, 1)
    
    def apply_time_decay(
        self,
        news_items: List[Dict],
        current_time: datetime
    ) -> List[Dict]:
        """
        Apply exponential time decay to news scores.
        
        Half-life determines how quickly news impact decays.
        
        Args:
            news_items: List of news items with scores
            current_time: Current timestamp
        
        Returns:
            News items with decayed scores
        """
        decayed_items = []
        
        for item in news_items:
            published_at_str = item.get('published_at', '')
            if not published_at_str:
                continue
            
            try:
                # Parse timestamp
                published_at = datetime.fromisoformat(
                    published_at_str.replace('Z', '+00:00')
                )
                
                # Calculate hours since publication
                hours_ago = (current_time - published_at).total_seconds() / 3600
                
                # Apply exponential decay
                decay_factor = 0.5 ** (hours_ago / self.half_life_hours)
                
                # Create decayed item
                decayed_item = item.copy()
                original_score = item.get('sentiment_score', 0.0)
                decayed_item['sentiment_score_decayed'] = original_score * decay_factor
                decayed_item['decay_factor'] = decay_factor
                decayed_item['hours_ago'] = hours_ago
                
                decayed_items.append(decayed_item)
            
            except Exception as e:
                logger.error(f"Error applying decay to news item: {e}")
                continue
        
        return decayed_items
    
    def aggregate_sentiment(
        self,
        news_items: List[Dict]
    ) -> Dict[str, float]:
        """
        Aggregate sentiment scores across multiple news items.
        
        Args:
            news_items: List of news items with sentiment scores
        
        Returns:
            Aggregated sentiment metrics
        """
        if not news_items:
            return {
                'sentiment_mean': 0.0,
                'sentiment_sum': 0.0,
                'sentiment_count': 0,
                'sentiment_positive_ratio': 0.0
            }
        
        scores = [item.get('sentiment_score_decayed', 0.0) for item in news_items]
        
        sentiment_mean = np.mean(scores)
        sentiment_sum = np.sum(scores)
        sentiment_count = len(scores)
        
        positive_count = sum(1 for s in scores if s > 0)
        sentiment_positive_ratio = positive_count / sentiment_count if sentiment_count > 0 else 0.0
        
        return {
            'sentiment_mean': sentiment_mean,
            'sentiment_sum': sentiment_sum,
            'sentiment_count': sentiment_count,
            'sentiment_positive_ratio': sentiment_positive_ratio
        }
    
    def calculate_sentiment_zscore(
        self,
        current_sentiment: float,
        sentiment_history: pd.Series
    ) -> float:
        """
        Calculate z-score of current sentiment relative to baseline.
        
        Args:
            current_sentiment: Current aggregated sentiment
            sentiment_history: Historical sentiment values
        
        Returns:
            Sentiment z-score
        """
        if sentiment_history.empty or len(sentiment_history) < 2:
            return 0.0
        
        # Use recent window for baseline
        baseline = sentiment_history.tail(self.baseline_window_days)
        
        mean = baseline.mean()
        std = baseline.std()
        
        if std == 0 or np.isnan(std):
            return 0.0
        
        z_score = (current_sentiment - mean) / std
        return z_score
    
    def process_news_for_symbol(
        self,
        symbol: str,
        news_items: List[Dict],
        current_time: datetime,
        sentiment_history: Optional[pd.Series] = None
    ) -> Dict[str, any]:
        """
        Process all news for a symbol and return sentiment metrics.
        
        Args:
            symbol: Trading pair symbol
            news_items: List of raw news items
            current_time: Current timestamp
            sentiment_history: Historical sentiment for z-score calculation
        
        Returns:
            Dictionary with sentiment metrics
        """
        # Calculate scores for each news item
        scored_items = []
        for item in news_items:
            score = self.calculate_news_score(item)
            item_with_score = item.copy()
            item_with_score['sentiment_score'] = score
            scored_items.append(item_with_score)
        
        # Apply time decay
        decayed_items = self.apply_time_decay(scored_items, current_time)
        
        # Aggregate
        aggregated = self.aggregate_sentiment(decayed_items)
        
        # Calculate z-score
        sentiment_z = 0.0
        if sentiment_history is not None:
            sentiment_z = self.calculate_sentiment_zscore(
                aggregated['sentiment_mean'],
                sentiment_history
            )
        
        return {
            'symbol': symbol,
            'news_count': len(news_items),
            'sentiment_mean': aggregated['sentiment_mean'],
            'sentiment_sum': aggregated['sentiment_sum'],
            'sentiment_z': sentiment_z,
            'positive_ratio': aggregated['sentiment_positive_ratio'],
            'items': decayed_items[:10]  # Keep top 10 for logging
        }
