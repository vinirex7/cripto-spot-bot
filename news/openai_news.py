"""OpenAI news analysis with config-based API key loading."""
import os
from typing import Any, Dict, Optional


def analyze_news(
    title: str,
    url: str,
    content: Optional[str],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Analyze news using OpenAI ChatGPT API.
    
    The OpenAI model analyzes news sentiment and returns numerical values
    (sentiment, confidence, impact_horizon_minutes, category, action_bias)
    that are used by the NewsEngine to calculate sent_llm and evaluate
    market shock (hard/soft/ok), which multiplies risk in bot decisions.
    
    Args:
        title: News title
        url: News URL
        content: Optional news content
        config: Bot configuration dictionary
        
    Returns:
        Dictionary with sentiment analysis results:
        - sentiment: float (-1 to 1)
        - confidence: float (0 to 1)
        - impact_horizon_minutes: int
        - category: str
        - action_bias: str (bullish/bearish/neutral)
    """
    # Try config first, then env var
    api_keys = config.get("api_keys", {}).get("openai", {})
    api_key = api_keys.get("api_key") or os.getenv("OPENAI_API_KEY")
    model = api_keys.get("model") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    openai_cfg = config.get("news", {}).get("openai", {})
    timeout = openai_cfg.get("request_timeout_s", 25)
    
    if not api_key or not openai_cfg.get("enabled", True):
        return {
            "sentiment": 0.0,
            "confidence": 0.0,
            "impact_horizon_minutes": 0,
            "category": "unknown",
            "action_bias": "neutral",
            "openai_error": True,
        }
    
    try:
        import requests
        
        prompt = f"""Analyze this crypto news and return a JSON response with:
- sentiment: float from -1 (very negative) to 1 (very positive)
- confidence: float from 0 to 1
- impact_horizon_minutes: estimated impact duration in minutes
- category: one of [regulation, adoption, technical, market, security, other]
- action_bias: one of [bullish, bearish, neutral]

Title: {title}
URL: {url}
Content: {content or "N/A"}

Return only valid JSON, no additional text."""

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a crypto market analyst. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        response.raise_for_status()
        
        result = response.json()
        content_text = result["choices"][0]["message"]["content"]
        
        # Parse JSON response
        import json
        analysis = json.loads(content_text)
        
        return {
            "sentiment": float(analysis.get("sentiment", 0.0)),
            "confidence": float(analysis.get("confidence", 0.0)),
            "impact_horizon_minutes": int(analysis.get("impact_horizon_minutes", 0)),
            "category": analysis.get("category", "other"),
            "action_bias": analysis.get("action_bias", "neutral"),
            "openai_error": False,
        }
        
    except Exception as e:
        print(f"Error analyzing news with OpenAI: {e}")
        return {
            "sentiment": 0.0,
            "confidence": 0.0,
            "impact_horizon_minutes": 0,
            "category": "unknown",
            "action_bias": "neutral",
            "openai_error": True,
        }
