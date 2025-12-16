"""
CryptoPanic API client for fetching crypto news.
"""
import os
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class CryptoPanicClient:
    """Client for CryptoPanic news API."""
    
    def __init__(self, base_url: str = "https://cryptopanic.com/api/v1/posts/"):
        self.base_url = base_url
        self.token = os.getenv("CRYPTOPANIC_TOKEN", "")
        
        if not self.token:
            logger.warning("CRYPTOPANIC_TOKEN not set in environment")
    
    def fetch_news(
        self,
        currencies: Optional[List[str]] = None,
        filter_type: str = "hot",
        public: bool = True
    ) -> List[Dict]:
        """
        Fetch news from CryptoPanic.
        
        Args:
            currencies: List of currency codes (e.g., ['BTC', 'ETH'])
            filter_type: 'hot', 'trending', 'latest', 'rising'
            public: Whether to use public endpoint
        
        Returns:
            List of news items
        """
        if not self.token:
            logger.error("Cannot fetch news: CRYPTOPANIC_TOKEN not set")
            return []
        
        params = {
            "auth_token": self.token,
            "filter": filter_type,
            "public": "true" if public else "false"
        }
        
        if currencies:
            params["currencies"] = ",".join(currencies)
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            logger.info(f"Fetched {len(results)} news items from CryptoPanic")
            return results
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching news from CryptoPanic: {e}")
            return []
    
    def filter_by_symbol(
        self,
        news_items: List[Dict],
        symbol: str
    ) -> List[Dict]:
        """
        Filter news items by symbol.
        
        Args:
            news_items: List of news items from CryptoPanic
            symbol: Symbol to filter (e.g., 'BTCUSDT' or 'BTC')
        
        Returns:
            Filtered news items
        """
        # Extract base currency from symbol (e.g., BTC from BTCUSDT)
        base_currency = symbol.replace("USDT", "").upper()
        
        filtered = []
        for item in news_items:
            currencies = item.get("currencies", [])
            currency_codes = [c.get("code", "").upper() for c in currencies]
            
            if base_currency in currency_codes:
                filtered.append(item)
        
        return filtered
    
    def parse_news_item(self, item: Dict) -> Dict:
        """
        Parse a news item into a standardized format.
        
        Args:
            item: Raw news item from CryptoPanic
        
        Returns:
            Parsed news item
        """
        return {
            'id': item.get('id'),
            'title': item.get('title', ''),
            'url': item.get('url', ''),
            'published_at': item.get('published_at', ''),
            'source': item.get('source', {}).get('title', ''),
            'currencies': [c.get('code') for c in item.get('currencies', [])],
            'kind': item.get('kind', ''),
            'votes': item.get('votes', {})
        }
    
    def get_news_for_symbols(
        self,
        symbols: List[str],
        filter_type: str = "hot"
    ) -> Dict[str, List[Dict]]:
        """
        Fetch and organize news for multiple symbols.
        
        Args:
            symbols: List of trading pair symbols
            filter_type: Filter type for CryptoPanic
        
        Returns:
            Dictionary mapping symbol to list of news items
        """
        # Extract unique currency codes
        currencies = list(set([s.replace("USDT", "") for s in symbols]))
        
        # Fetch all news
        all_news = self.fetch_news(currencies=currencies, filter_type=filter_type)
        
        # Organize by symbol
        news_by_symbol = {}
        for symbol in symbols:
            news_by_symbol[symbol] = self.filter_by_symbol(all_news, symbol)
        
        return news_by_symbol
