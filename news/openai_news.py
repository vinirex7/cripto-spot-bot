"""OpenAI news analysis with config-based API key loading (Responses API + JSON mode)."""
from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional, List

import requests


def _extract_response_text(resp_json: Dict[str, Any]) -> str:
    """Robustly extract text from a Responses API payload."""
    out_chunks: List[str] = []

    output = resp_json.get("output", []) or []
    for item in output:
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if "text" in part and isinstance(part["text"], str):
                    out_chunks.append(part["text"])
                elif isinstance(part.get("text"), dict) and isinstance(part["text"].get("value"), str):
                    out_chunks.append(part["text"]["value"])
        if isinstance(item.get("text"), str):
            out_chunks.append(item["text"])

    return "\n".join(c for c in out_chunks if c).strip()


def analyze_news(
    title: str,
    url: str,
    content: Optional[str],
    config: Dict[str, Any],
    # --- New optional context (backward compatible) ---
    panic_score: Optional[float] = None,
    age_minutes: Optional[float] = None,
    published_at: Optional[str] = None,
    source: str = "",
) -> Dict[str, Any]:
    """
    Analyze news using OpenAI Responses API in JSON mode.

    Backward-compatible return keys (kept):
      - sentiment: float (-1..1)
      - confidence: float (0..1)
      - impact_horizon_minutes: int
      - category: str
      - action_bias: str
      - openai_error: bool

    New keys added for your strategy:
      - label: one of [good, info, soft, hard]
      - cooldown_minutes: int (suggested)
      - risk_mult: float (0..1 suggested; hard~0, soft~0.5)
      - recommend_sell: bool (HINT ONLY; tradebot must still guard)
      - why: short explanation string
    """
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
            "label": "info",
            "cooldown_minutes": 0,
            "risk_mult": 1.0,
            "recommend_sell": False,
            "why": "",
            "openai_error": True,
        }

    temperature = float(openai_cfg.get("temperature", 0.2))
    max_output_tokens = openai_cfg.get("max_output_tokens", 350)

    # Small deterministic mapping for your bot:
    # hard -> 0 (no entries), soft -> 0.5, info/good -> 1.0
    # You can override this in engine/risk later if you prefer.
    try:
        system_msg = (
            "You are a crypto risk analyst. You must output ONLY valid JSON. "
            "No markdown, no extra text. "
            "Classify the news into: good, info, soft, hard."
        )

        # Format optional context nicely
        ctx_bits = []
        if source:
            ctx_bits.append(f"Source: {source}")
        if published_at:
            ctx_bits.append(f"PublishedAt: {published_at}")
        if age_minutes is not None:
            ctx_bits.append(f"AgeMinutes: {age_minutes:.1f}")
        if panic_score is not None:
            ctx_bits.append(f"PanicScore: {panic_score}")

        ctx = "\n".join(ctx_bits) if ctx_bits else "N/A"

        # IMPORTANT: we explicitly ask for JSON object only
        prompt = f"""Analyze this crypto news. Return a SINGLE JSON object with keys:

Required keys:
- label: one of ["good","info","soft","hard"]
- sentiment: float from -1 to 1
- confidence: float from 0 to 1
- impact_horizon_minutes: int (estimated duration of impact)
- category: one of ["security","exchange","regulation","macro","tech","market","other"]
- action_bias: one of ["bullish","bearish","neutral"]
- cooldown_minutes: int (suggested cooldown for trading entries; 0 if none)
- risk_mult: float 0..1 (suggested risk multiplier for NEW entries; hard≈0, soft≈0.5, info/good≈1)
- recommend_sell: boolean (ONLY true for severe HARD risk like hack/exploit/insolvency; this is a hint, not an order)
- why: short string (max 180 chars) explaining the label

Context:
{ctx}

Title: {title}
URL: {url}
Content: {content or "N/A"}

Rules:
- Use "hard" for severe risks (hack/exploit, insolvency, withdrawals halted, critical outage, severe enforcement).
- Use "soft" for moderate risk / uncertainty / potentially negative developments.
- Use "info" for neutral informational updates.
- Use "good" for clearly positive fundamental news, but do NOT recommend selling for good/news.
- Consider AgeMinutes: very old news should reduce confidence and usually lower severity unless it's still active.
- PanicScore is intensity/attention; it can be high for good or bad news. Use it as a weak modifier, not a direction.

Return ONLY JSON.
"""

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
        analysis = json.loads(content_text)

        # Normalize / defensive defaults
        label = str(analysis.get("label", "info")).lower().strip()
        if label not in ("good", "info", "soft", "hard"):
            label = "info"

        sentiment = float(analysis.get("sentiment", 0.0))
        confidence = float(analysis.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        impact_h = int(analysis.get("impact_horizon_minutes", 0) or 0)
        category = str(analysis.get("category", "other"))
        action_bias = str(analysis.get("action_bias", "neutral"))
        why = str(analysis.get("why", ""))[:180]

        cooldown = int(analysis.get("cooldown_minutes", 0) or 0)
        recommend_sell = bool(analysis.get("recommend_sell", False))

        # Risk multiplier: accept model suggestion, clamp, fallback by label
        try:
            risk_mult = float(analysis.get("risk_mult", 1.0))
        except Exception:
            risk_mult = 1.0
        risk_mult = max(0.0, min(1.0, risk_mult))
        if label == "hard" and risk_mult > 0.1:
            risk_mult = 0.0
        elif label == "soft" and (risk_mult > 0.9 or risk_mult < 0.1):
            risk_mult = 0.5
        elif label in ("info", "good") and risk_mult < 0.5:
            risk_mult = 1.0

        # For safety: only allow recommend_sell on hard labels with decent confidence
        if label != "hard" or confidence < 0.65:
            recommend_sell = False

        return {
            "sentiment": sentiment,
            "confidence": confidence,
            "impact_horizon_minutes": impact_h,
            "category": category,
            "action_bias": action_bias,
            "label": label,
            "cooldown_minutes": max(0, cooldown),
            "risk_mult": risk_mult,
            "recommend_sell": recommend_sell,
            "why": why,
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
            "label": "info",
            "cooldown_minutes": 0,
            "risk_mult": 1.0,
            "recommend_sell": False,
            "why": "",
            "openai_error": True,
        }