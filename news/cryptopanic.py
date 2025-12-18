"""CryptoPanic news fetcher with config-based API key loading."""
import os
from datetime import datetime
from typing import Any, Dict, List
import requests


def fetch_news(now: datetime, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fetch news from CryptoPanic API.
    
    Args:
        now: Current datetime
        config: Bot configuration dictionary
        
    Returns:
        List of news items
    """
    news_cfg = config.get("news", {})
    cp_cfg = news_cfg.get("cryptopanic", {})
    
    if not cp_cfg.get("enabled", True):
        return []
    
    # Try config first, then env var
    api_keys = config.get("api_keys", {}).get("cryptopanic", {})
    token = api_keys.get("token") or os.getenv("CRYPTOPANIC_TOKEN")
    
    if not token:
        return []
    
    try:
        timeout = cp_cfg.get("request_timeout_s", 10)
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": token,
            "public": "true",
            "kind": "news",
            "filter": "rising"
        }
        
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        results = data.get("results", [])
        
        news_items = []
        for item in results:
            news_items.append({
                "id": item.get("id"),
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "published_at": item.get("published_at", ""),
                "source": item.get("source", {}).get("title", ""),
                "currencies": [c.get("code") for c in item.get("currencies", [])]
            })
        
        return news_items
        
    except Exception as e:
        print(f"Error fetching CryptoPanic news: {e}")
        return []
