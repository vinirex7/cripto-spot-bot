"""News engine for aggregating and analyzing market news."""
from datetime import datetime
from typing import Any, Dict, List

from news.cryptopanic import fetch_news
from news.openai_news import analyze_news


class NewsEngine:
    """Engine for processing and analyzing news."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize news engine.
        
        Args:
            config: Bot configuration dictionary
        """
        self.config = config
        self.news_cache: List[Dict[str, Any]] = []
        self.analysis_cache: Dict[str, Dict[str, Any]] = {}
    
    def fetch_and_analyze(self, now: datetime) -> List[Dict[str, Any]]:
        """
        Fetch news and analyze with OpenAI.
        
        Args:
            now: Current datetime
            
        Returns:
            List of analyzed news items
        """
        # Fetch news from CryptoPanic
        news_items = fetch_news(now, self.config)
        self.news_cache = news_items
        
        # Analyze each news item with OpenAI
        analyzed_news = []
        for item in news_items:
            news_id = str(item.get("id", ""))
            
            # Check cache
            if news_id in self.analysis_cache:
                analysis = self.analysis_cache[news_id]
            else:
                # Analyze with OpenAI
                analysis = analyze_news(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=None,
                    config=self.config
                )
                self.analysis_cache[news_id] = analysis
            
            analyzed_item = {**item, **analysis}
            analyzed_news.append(analyzed_item)
        
        return analyzed_news
    
    def current_status(self) -> Dict[str, Any]:
        """
        Get current news status for risk evaluation.
        
        Returns:
            Dictionary with aggregated news metrics
        """
        if not self.news_cache:
            return {
                "sent_llm": 0.0,
                "shock_level": "ok",
                "cooldown_active": False,
            }
        
        # Aggregate sentiment
        total_sentiment = 0.0
        total_confidence = 0.0
        count = 0
        
        for news_id, analysis in self.analysis_cache.items():
            if not analysis.get("openai_error", False):
                sentiment = analysis.get("sentiment", 0.0)
                confidence = analysis.get("confidence", 0.0)
                total_sentiment += sentiment * confidence
                total_confidence += confidence
                count += 1
        
        sent_llm = total_sentiment / total_confidence if total_confidence > 0 else 0.0
        
        # Determine shock level based on sentiment
        news_cfg = self.config.get("news", {})
        sentz_hard = news_cfg.get("sentz_hard", -3.0)
        sentz_soft = news_cfg.get("ns_soft", -1.5)
        
        shock_level = "ok"
        if sent_llm <= sentz_hard:
            shock_level = "hard"
        elif sent_llm <= sentz_soft:
            shock_level = "soft"
        
        return {
            "sent_llm": sent_llm,
            "shock_level": shock_level,
            "cooldown_active": shock_level == "hard",
            "news_count": count,
        }
