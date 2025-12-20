"""OpenAI news analysis with config-based API key loading (Responses API + JSON mode)."""
from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional, List

import requests


def _extract_response_text(resp_json: Dict[str, Any]) -> str:
    """
    Robustly extract text from a Responses API payload.

    Docs note: It's not safe to assume text is at output[0].content[0].text,
    because output may contain tool calls and other items. We aggregate all
    text-like chunks found.  :contentReference[oaicite:4]{index=4}
    """
    out_chunks: List[str] = []

    output = resp_json.get("output", []) or []
    for item in output:
        # Most commonly: item has "content": [{type: "output_text", "text": "..."}]
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                # Common cases
                if "text" in part and isinstance(part["text"], str):
                    out_chunks.append(part["text"])
                # Some variants may store as {"text": {"value": "..."}}
                elif isinstance(part.get("text"), dict) and isinstance(part["text"].get("value"), str):
                    out_chunks.append(part["text"]["value"])
                # Sometimes the type may be "output_text" with "text" field already handled above
        # Fallback: some items may have direct "text"
        if isinstance(item.get("text"), str):
            out_chunks.append(item["text"])

    return "\n".join(c for c in out_chunks if c).strip()


def analyze_news(
    title: str,
    url: str,
    content: Optional[str],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Analyze news using OpenAI Responses API in JSON mode.

    Returns:
        Dictionary with:
        - sentiment: float (-1 to 1)
        - confidence: float (0 to 1)
        - impact_horizon_minutes: int
        - category: str
        - action_bias: str (bullish/bearish/neutral)
        - openai_error: bool
    """
    # Try config first, then env var (keep original behavior)
    api_keys = (config.get("api_keys", {}) or {}).get("openai", {}) or {}
    api_key = api_keys.get("api_key") or os.getenv("OPENAI_API_KEY")
    model = api_keys.get("model") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    openai_cfg = (config.get("news", {}) or {}).get("openai", {}) or {}
    timeout = openai_cfg.get("request_timeout_s", 25)
    enabled = openai_cfg.get("enabled", True)

    if not api_key or not enabled:
        return {
            "sentiment": 0.0,
            "confidence": 0.0,
            "impact_horizon_minutes": 0,
            "category": "unknown",
            "action_bias": "neutral",
            "openai_error": True,
        }

    # Keep temperature configurable (default slightly lower for consistency)
    temperature = float(openai_cfg.get("temperature", 0.2))
    max_output_tokens = openai_cfg.get("max_output_tokens", 250)  # small JSON payload

    try:
        # IMPORTANT: JSON mode requires "JSON" mentioned in context; docs warn otherwise. :contentReference[oaicite:5]{index=5}
        system_msg = (
            "You are a crypto market analyst designed to output JSON. "
            "Return ONLY a single valid JSON object."
        )

        prompt = f"""Analyze this crypto news and return a JSON object with keys:
- sentiment: float from -1 (very negative) to 1 (very positive)
- confidence: float from 0 to 1
- impact_horizon_minutes: int (estimated impact duration in minutes)
- category: one of [regulation, adoption, technical, market, security, other]
- action_bias: one of [bullish, bearish, neutral]

Title: {title}
URL: {url}
Content: {content or "N/A"}

Return ONLY JSON (no markdown, no extra text)."""

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            # Responses API JSON mode:
            # Use text.format = {type:"json_object"} :contentReference[oaicite:6]{index=6}
            "text": {"format": {"type": "json_object"}},
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }

        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()

        resp_json = response.json()
        content_text = _extract_response_text(resp_json)

        # Parse JSON response
        analysis = json.loads(content_text)

        return {
            "sentiment": float(analysis.get("sentiment", 0.0)),
            "confidence": float(analysis.get("confidence", 0.0)),
            "impact_horizon_minutes": int(analysis.get("impact_horizon_minutes", 0)),
            "category": str(analysis.get("category", "other")),
            "action_bias": str(analysis.get("action_bias", "neutral")),
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
