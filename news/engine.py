"""News engine for aggregating and analyzing market news."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from news.cryptopanic import fetch_news
from news.openai_news import analyze_news


def _parse_iso8601_dt(s: str) -> Optional[datetime]:
    """Parse CryptoPanic published_at (usually ISO 8601). Returns aware UTC datetime if possible."""
    if not s:
        return None
    try:
        # Handles: "2025-12-20T10:12:34Z" and offsets like "+00:00"
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


class NewsEngine:
    """Engine for processing and analyzing news."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.news_cache: List[Dict[str, Any]] = []
        # analysis_cache[news_id] = { sentiment, confidence, ..., analyzed_at_iso }
        self.analysis_cache: Dict[str, Dict[str, Any]] = {}

    def _news_cfg(self) -> Dict[str, Any]:
        return self.config.get("news", {}) or {}

    def _get_thresholds(self) -> Dict[str, float]:
        """
        New config keys (recommended):
          news.llm_hard_threshold (default -0.6)
          news.llm_soft_threshold (default -0.3)

        Backward-compat:
          news.sentz_hard, news.ns_soft (old names)
        """
        news_cfg = self._news_cfg()

        hard = news_cfg.get("llm_hard_threshold", None)
        soft = news_cfg.get("llm_soft_threshold", None)

        # Backward compatibility (old keys)
        if hard is None:
            hard = news_cfg.get("sentz_hard", -0.6)
        if soft is None:
            soft = news_cfg.get("ns_soft", -0.3)

        # Ensure sensible ordering: hard <= soft (both negative)
        hard = float(hard)
        soft = float(soft)
        if hard > soft:
            # swap defensively
            hard, soft = soft, hard
        return {"hard": hard, "soft": soft}

    def _get_time_settings(self) -> Dict[str, float]:
        """
        Controls:
          news.lookback_hours (default 12)  -> only consider recent items
          news.analysis_cache_ttl_minutes (default 180) -> expire cached OpenAI analyses
          news.decay_half_life_minutes (default 180) -> exponential decay of older news weight
        """
        news_cfg = self._news_cfg()
        lookback_hours = float(news_cfg.get("lookback_hours", 12))
        ttl_min = float(news_cfg.get("analysis_cache_ttl_minutes", 180))
        half_life_min = float(news_cfg.get("decay_half_life_minutes", 180))

        # Defensive clamps
        lookback_hours = _clamp(lookback_hours, 1.0, 72.0)
        ttl_min = _clamp(ttl_min, 10.0, 7 * 24 * 60.0)
        half_life_min = _clamp(half_life_min, 10.0, 7 * 24 * 60.0)

        return {
            "lookback_hours": lookback_hours,
            "ttl_minutes": ttl_min,
            "half_life_minutes": half_life_min,
        }

    def _analysis_is_fresh(self, analysis: Dict[str, Any], now_utc: datetime, ttl_minutes: float) -> bool:
        ts = analysis.get("analyzed_at")
        if not ts:
            return False
        dt = _parse_iso8601_dt(str(ts))
        if not dt:
            return False
        age_min = (now_utc - dt).total_seconds() / 60.0
        return age_min <= ttl_minutes

    def fetch_and_analyze(self, now: datetime) -> List[Dict[str, Any]]:
        """
        Fetch news and analyze with OpenAI.

        Returns:
            List of analyzed news items (only recent items are returned).
        """
        now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
        tcfg = self._get_time_settings()

        # Fetch news from CryptoPanic (cryptopanic.py will handle limit/filter/lookback too),
        # but we apply a defensive lookback filter here as well.
        news_items = fetch_news(now_utc, self.config)

        # Keep only items within lookback window
        lookback_seconds = tcfg["lookback_hours"] * 3600.0
        filtered_items: List[Dict[str, Any]] = []
        for item in news_items:
            published_at = _parse_iso8601_dt(str(item.get("published_at", "")))
            if not published_at:
                # If missing timestamp, keep it but it'll be down-weighted later
                filtered_items.append(item)
                continue
            age_s = (now_utc - published_at).total_seconds()
            if age_s <= lookback_seconds and age_s >= -300:  # allow small clock skew
                filtered_items.append(item)

        self.news_cache = filtered_items

        # Analyze each news item with OpenAI (cache + TTL)
        analyzed_news: List[Dict[str, Any]] = []
        for item in self.news_cache:
            news_id = str(item.get("id", "")) or ""
            if not news_id:
                continue

            cached = self.analysis_cache.get(news_id)
            if cached and self._analysis_is_fresh(cached, now_utc, tcfg["ttl_minutes"]):
                analysis = cached
            else:
                analysis = analyze_news(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=None,
                    config=self.config,
                )
                # Add analyzed_at for TTL tracking
                analysis = {**analysis, "analyzed_at": now_utc.isoformat()}
                self.analysis_cache[news_id] = analysis

            analyzed_item = {**item, **analysis}
            analyzed_news.append(analyzed_item)

        # Optional: prune cache keys not seen recently to prevent unbounded growth
        self._prune_cache(now_utc)

        return analyzed_news

    def _prune_cache(self, now_utc: datetime) -> None:
        """Remove stale cache entries (older than TTL * 3) to prevent growth."""
        tcfg = self._get_time_settings()
        ttl = tcfg["ttl_minutes"]
        hard_cap = ttl * 3.0
        to_del: List[str] = []
        for nid, a in self.analysis_cache.items():
            ts = a.get("analyzed_at")
            dt = _parse_iso8601_dt(str(ts)) if ts else None
            if not dt:
                continue
            age_min = (now_utc - dt).total_seconds() / 60.0
            if age_min > hard_cap:
                to_del.append(nid)
        for nid in to_del:
            self.analysis_cache.pop(nid, None)

    def current_status(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get current news status for risk evaluation.

        IMPORTANT:
        - Aggregates ONLY the current batch (self.news_cache).
        - Applies exponential decay based on news age.
        - Uses corrected thresholds on [-1, 1] scale.

        Args:
            now: Optional datetime override (useful for tests). Defaults to utcnow().

        Returns:
            Dictionary with aggregated news metrics.
        """
        now_utc = (
            (now.astimezone(timezone.utc) if now and now.tzinfo else now.replace(tzinfo=timezone.utc))
            if now
            else datetime.now(timezone.utc)
        )

        if not self.news_cache:
            return {
                "sent_llm": 0.0,
                "shock_level": "ok",
                "cooldown_active": False,
                "news_count": 0,
            }

        tcfg = self._get_time_settings()
        thresholds = self._get_thresholds()

        # Only aggregate analyses for current batch IDs
        active_ids = {str(i.get("id", "")) for i in self.news_cache if i.get("id") is not None}
        active_ids = {i for i in active_ids if i}

        total = 0.0
        total_w = 0.0
        count = 0

        # Exponential decay factor: w_time = 0.5^(age / half_life)
        half_life = tcfg["half_life_minutes"]

        for item in self.news_cache:
            nid = str(item.get("id", "")) or ""
            if not nid or nid not in active_ids:
                continue

            analysis = self.analysis_cache.get(nid) or {}
            if analysis.get("openai_error", False):
                continue

            sentiment = float(analysis.get("sentiment", 0.0))
            confidence = float(analysis.get("confidence", 0.0))
            confidence = _clamp(confidence, 0.0, 1.0)

            published_at = _parse_iso8601_dt(str(item.get("published_at", "")))
            if published_at:
                age_min = (now_utc - published_at).total_seconds() / 60.0
                if age_min < 0:
                    age_min = 0.0
                w_time = 0.5 ** (age_min / half_life)
            else:
                # Unknown age: down-weight
                w_time = 0.6

            w = confidence * w_time
            if w <= 0.0:
                continue

            total += sentiment * w
            total_w += w
            count += 1

        sent_llm = total / total_w if total_w > 0 else 0.0

        shock_level = "ok"
        if sent_llm <= thresholds["hard"]:
            shock_level = "hard"
        elif sent_llm <= thresholds["soft"]:
            shock_level = "soft"

        return {
            "sent_llm": sent_llm,
            "shock_level": shock_level,
            # cooldown policy can be enriched later; for now, hard => active
            "cooldown_active": shock_level == "hard",
            "news_count": count,
            "thresholds": thresholds,  # helps debugging/logs
        }
