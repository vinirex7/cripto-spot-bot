import json
import os
from typing import Any, Dict, Optional

import requests


OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"


def _clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, value))


def analyze_news(
    title: str,
    url: str,
    content: Optional[str],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
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
    prompt = f"""Analyze the following crypto news and respond ONLY with valid JSON matching the schema:
{{
  "sentiment": -1.0,
  "confidence": 0.80,
  "impact_horizon_minutes": 360,
  "category": "hack",
  "action_bias": "risk_off",
  "why": "Exchange exploit / security incident"
}}
Rules:
- sentiment in [-1, 1]
- confidence in [0, 1]
- impact_horizon_minutes in [15, 4320]
- action_bias in {{"risk_on","risk_off","neutral"}}
Title: {title}
URL: {url}
Body: {content or "N/A"}
"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict JSON generator for risk analysis."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(
            OPENAI_ENDPOINT, headers=headers, json=payload, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        content_resp = data["choices"][0]["message"]["content"]
        parsed = json.loads(content_resp)
        sentiment = _clamp(float(parsed.get("sentiment", 0)), -1, 1)
        confidence = _clamp(float(parsed.get("confidence", 0)), 0, 1)
        horizon = int(
            _clamp(float(parsed.get("impact_horizon_minutes", 0)), 15, 4320)
        )
        category = str(parsed.get("category", "unknown"))[:64]
        action_bias = parsed.get("action_bias", "neutral")
        if action_bias not in {"risk_on", "risk_off", "neutral"}:
            action_bias = "neutral"
        return {
            "sentiment": sentiment,
            "confidence": confidence,
            "impact_horizon_minutes": horizon,
            "category": category,
            "action_bias": action_bias,
            "why": parsed.get("why", ""),
            "openai_error": False,
        }
    except Exception:
        return {
            "sentiment": 0.0,
            "confidence": 0.0,
            "impact_horizon_minutes": 0,
            "category": "unknown",
            "action_bias": "neutral",
            "openai_error": True,
        }
