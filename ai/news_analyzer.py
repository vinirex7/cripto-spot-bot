"""
News analyzer using OpenAI for sentiment classification.
STRICTLY LIMITED: Can only classify news, cannot make trade decisions.
"""
from typing import Dict, List, Optional
import logging

from ai.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class NewsAnalyzer:
    """
    Analyze news using OpenAI for sentiment and category classification.
    
    CRITICAL LIMITATIONS:
    - Can ONLY classify news sentiment and category
    - CANNOT suggest buy/sell decisions
    - CANNOT set prices or position sizes
    - Can ONLY return numerical sentiment and confidence scores
    """
    
    def __init__(self, openai_client: OpenAIClient):
        self.client = openai_client
        
        # Define critical news categories
        self.critical_categories = [
            'regulation',
            'hack',
            'bankruptcy',
            'delisting',
            'fraud',
            'legal'
        ]
    
    def analyze_news_item(
        self,
        title: str,
        source: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Analyze a single news item for sentiment and category.
        
        Returns ONLY:
        - sentiment: float (-1.0 to 1.0)
        - confidence: float (0.0 to 1.0)
        - category: str (one of predefined categories)
        
        NEVER returns trade recommendations.
        
        Args:
            title: News title
            source: News source (optional)
            symbol: Related symbol (optional)
        
        Returns:
            Dictionary with sentiment, confidence, and category
        """
        if not self.client.is_enabled():
            return {
                'sentiment': 0.0,
                'confidence': 0.0,
                'category': 'unknown',
                'source': 'fallback'
            }
        
        # Construct prompt
        system_prompt = """You are a financial news classifier. 
Your ONLY job is to classify news sentiment and category.

You MUST return ONLY a JSON object with exactly these fields:
- sentiment: number from -1.0 (very negative) to 1.0 (very positive)
- confidence: number from 0.0 (uncertain) to 1.0 (certain)
- category: one of [regulation, hack, bankruptcy, delisting, fraud, legal, partnership, upgrade, adoption, general]

You MUST NOT:
- Suggest buying or selling
- Recommend prices
- Suggest position sizes
- Give trading advice

Only classify the news sentiment and category."""

        user_prompt = f"""Classify this crypto news:

Title: {title}
"""
        
        if source:
            user_prompt += f"Source: {source}\n"
        
        if symbol:
            user_prompt += f"Symbol: {symbol}\n"
        
        user_prompt += "\nReturn JSON with sentiment, confidence, and category."
        
        # Call API
        response = self.client.call_api(
            prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"}
        )
        
        if not response or 'error' in response:
            logger.warning("Failed to get valid response from OpenAI")
            return {
                'sentiment': 0.0,
                'confidence': 0.0,
                'category': 'unknown',
                'source': 'error'
            }
        
        # Extract and validate response
        sentiment = float(response.get('sentiment', 0.0))
        confidence = float(response.get('confidence', 0.0))
        category = response.get('category', 'general')
        
        # Clamp values
        sentiment = max(-1.0, min(1.0, sentiment))
        confidence = max(0.0, min(1.0, confidence))
        
        # Validate category
        valid_categories = [
            'regulation', 'hack', 'bankruptcy', 'delisting', 'fraud', 'legal',
            'partnership', 'upgrade', 'adoption', 'general', 'unknown'
        ]
        if category not in valid_categories:
            category = 'general'
        
        return {
            'sentiment': sentiment,
            'confidence': confidence,
            'category': category,
            'source': 'openai'
        }
    
    def analyze_multiple_news(
        self,
        news_items: List[Dict],
        symbol: Optional[str] = None
    ) -> List[Dict]:
        """
        Analyze multiple news items.
        
        Args:
            news_items: List of news items with 'title' field
            symbol: Related symbol (optional)
        
        Returns:
            List of news items with added analysis fields
        """
        analyzed_items = []
        
        for item in news_items:
            title = item.get('title', '')
            source = item.get('source', '')
            
            if not title:
                continue
            
            # Analyze
            analysis = self.analyze_news_item(title, source, symbol)
            
            # Add analysis to item
            analyzed_item = item.copy()
            analyzed_item['llm_sentiment'] = analysis['sentiment']
            analyzed_item['llm_confidence'] = analysis['confidence']
            analyzed_item['llm_category'] = analysis['category']
            
            analyzed_items.append(analyzed_item)
        
        return analyzed_items
    
    def is_critical_news(
        self,
        category: str,
        confidence: float,
        min_confidence: float = 0.65
    ) -> bool:
        """
        Determine if news is critical (e.g., for hard pause).
        
        Args:
            category: News category
            confidence: Confidence score
            min_confidence: Minimum confidence threshold
        
        Returns:
            True if critical, False otherwise
        """
        return (
            category in self.critical_categories and
            confidence >= min_confidence
        )
    
    def calculate_sent_llm(
        self,
        sentiment: float,
        confidence: float
    ) -> float:
        """
        Calculate SentLLM = sentiment * confidence.
        
        Args:
            sentiment: Sentiment score (-1 to 1)
            confidence: Confidence score (0 to 1)
        
        Returns:
            SentLLM score
        """
        return sentiment * confidence
