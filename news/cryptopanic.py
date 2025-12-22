"""CryptoPanic news fetcher with config-based API key loading."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


def _parse_iso8601_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # CryptoPanic often uses Z suffix
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def fetch_news(now: datetime, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fetch news from CryptoPanic API.

    Defaults (unless overridden in config):
      - filter: hot
      - kind: news
      - limit: 50
      - lookback_hours: 12

    Args:
        now: Current datetime (recommended UTC-aware)
        config: Bot configuration dictionary

    Returns:
        List of normalized news items.
    """
    news_cfg = config.get("news", {}) or {}
    cp_cfg = (news_cfg.get("cryptopanic", {}) or {})

    if not cp_cfg.get("enabled", True):
        return []

    # Try config first, then env var
    api_keys = (config.get("api_keys", {}) or {}).get("cryptopanic", {}) or {}
    token = api_keys.get("token") or os.getenv("CRYPTOPANIC_TOKEN")
    if not token:
        return []

    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)

    # Configurable knobs
    timeout = int(cp_cfg.get("request_timeout_s", 10))
    limit = int(cp_cfg.get("limit", 50))
    limit = max(1, min(100, limit))  # defensive: keep reasonable

    # You asked: filter=hot
    filter_mode = str(cp_cfg.get("filter", "hot")).strip().lower() or "hot"

    # You asked: last 12 hours (use shared news.lookback_hours from engine config)
    lookback_hours = float(news_cfg.get("lookback_hours", 12))
    lookback_hours = _clamp(lookback_hours, 1.0, 72.0)
    lookback_seconds = lookback_hours * 3600.0


    url="https://cryptopanic.com/api/developer/v2/posts/"
    params = {
        "auth_token": token,
        "public": "true",
        "kind": "news",
        "filter": filter_mode,
        "limit": limit,
    }

    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()

        data = response.json() or {}
        results = data.get("results", []) or []

        out: List[Dict[str, Any]] = []
        seen_ids = set()

        for item in results:
            nid = item.get("id")
            if nid is None:
                continue
            if nid in seen_ids:
                continue
            seen_ids.add(nid)

            published_raw = item.get("published_at", "") or ""
            published_dt = _parse_iso8601_dt(str(published_raw))

            # Local time filter: keep only within lookback window
            if published_dt:
                age_s = (now_utc - published_dt).total_seconds()
                # allow small negative age for clock skew
                if age_s > lookback_seconds or age_s < -300:
                    continue

            source_title = (item.get("source", {}) or {}).get("title", "") or ""
            currencies = item.get("currencies", []) or []
            currency_codes = []
            for c in currencies:
                code = (c or {}).get("code")
                if code:
                    currency_codes.append(str(code))

            out.append(
                {
                    "id": nid,
                    "title": item.get("title", "") or "",
                    "url": item.get("url", "") or "",
                    "published_at": published_raw,
                    "source": source_title,
                    "currencies": currency_codes,
                }
            )

        return out

    except Exception as e:
        print(f"Error fetching CryptoPanic news: {e}")
        return []
