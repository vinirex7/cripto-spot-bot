"""News engine for aggregating and analyzing market news."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from news.cryptopanic import fetch_news
from news.openai_news import analyze_news


def _parse_iso8601_dt(s: str) -> Optional[datetime]:
    """Parse ISO 8601. Returns aware UTC datetime if possible."""
    if not s:
        return None
    try:
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


def _as_utc(now: datetime) -> datetime:
    return now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _age_minutes(now_utc: datetime, published_at: Optional[datetime]) -> Optional[float]:
    if not published_at:
        return None
    age_s = (now_utc - published_at).total_seconds()
    # allow slight negative skew
    if age_s < 0:
        age_s = 0.0
    return age_s / 60.0


class NewsEngine:
    """
    Engine for processing and analyzing news.

    Key behaviors:
    - Designed to run on EVERY bot wake (loop), not only trade decision slots.
    - fetch_and_analyze() keeps backward compatibility.
    - update() is an alias for fetch_and_analyze() (clearer semantics for "wake").
    - OpenAI analysis is cached by news_id with TTL.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.news_cache: List[Dict[str, Any]] = []
        # analysis_cache[news_id] = analysis dict (includes analyzed_at)
        self.analysis_cache: Dict[str, Dict[str, Any]] = {}
        self._last_status: Dict[str, Any] = {
            "sent_llm": 0.0,
            "shock_level": "ok",
            "cooldown_active": False,
            "news_count": 0,
        }

    def _news_cfg(self) -> Dict[str, Any]:
        return self.config.get("news", {}) or {}

    def _get_thresholds(self) -> Dict[str, float]:
        """
        Thresholds are used as fallback when no explicit 'label' signals are available.

        Recommended keys:
          news.llm_hard_threshold (default -0.6)
          news.llm_soft_threshold (default -0.3)

        Backward-compat:
          news.sentz_hard, news.ns_soft
        """
        news_cfg = self._news_cfg()

        hard = news_cfg.get("llm_hard_threshold", None)
        soft = news_cfg.get("llm_soft_threshold", None)

        if hard is None:
            hard = news_cfg.get("sentz_hard", -0.6)
        if soft is None:
            soft = news_cfg.get("ns_soft", -0.3)

        hard = float(hard)
        soft = float(soft)
        if hard > soft:
            hard, soft = soft, hard
        return {"hard": hard, "soft": soft}

    def _get_time_settings(self) -> Dict[str, float]:
        """
        Controls:
          news.lookback_hours (default 12)
          news.analysis_cache_ttl_minutes (default 180)
          news.decay_half_life_minutes (default 180)
        """
        news_cfg = self._news_cfg()
        lookback_hours = float(news_cfg.get("lookback_hours", 12))
        ttl_min = float(news_cfg.get("analysis_cache_ttl_minutes", 180))
        half_life_min = float(news_cfg.get("decay_half_life_minutes", 180))

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

    def update(self, now: datetime) -> List[Dict[str, Any]]:
        """Alias for fetch_and_analyze(), intended to be called on EVERY bot wake."""
        return self.fetch_and_analyze(now)

    def fetch_and_analyze(self, now: datetime) -> List[Dict[str, Any]]:
        """
        Fetch news (CryptoPanic API OR Telegram feed depending on fetch_news implementation)
        and analyze with OpenAI.

        Returns:
            List of analyzed news items (only recent items are returned).
        """
        now_utc = _as_utc(now)
        tcfg = self._get_time_settings()

        news_items = fetch_news(now_utc, self.config)

        # Keep only items within lookback window (defensive)
        lookback_seconds = tcfg["lookback_hours"] * 3600.0
        filtered_items: List[Dict[str, Any]] = []
        for item in news_items:
            published_dt = _parse_iso8601_dt(str(item.get("published_at", "")))
            if not published_dt:
                filtered_items.append(item)
                continue
            age_s = (now_utc - published_dt).total_seconds()
            if age_s <= lookback_seconds and age_s >= -300:
                filtered_items.append(item)

        self.news_cache = filtered_items

        analyzed_news: List[Dict[str, Any]] = []
        for item in self.news_cache:
            # Support multiple sources: prefer stable id; fallback to url/title hash-like key
            raw_id = item.get("id", "")
            news_id = str(raw_id) if raw_id is not None else ""
            if not news_id:
                # Fallback: do not crash; just skip (keeps compatibility)
                continue

            cached = self.analysis_cache.get(news_id)
            if cached and self._analysis_is_fresh(cached, now_utc, tcfg["ttl_minutes"]):
                analysis = cached
            else:
                # Inputs for OpenAI
                title = item.get("title", "") or ""
                url = item.get("url", "") or ""
                content = item.get("content") or item.get("text")  # telegram messages often come here
                panic_score = item.get("panic_score", None)

                published_dt = _parse_iso8601_dt(str(item.get("published_at", "")))
                age_min = _age_minutes(now_utc, published_dt)

                analysis = analyze_news(
                    title=title,
                    url=url,
                    content=content if isinstance(content, str) else None,
                    config=self.config,
                    panic_score=panic_score,
                    age_minutes=age_min,
                    published_at=item.get("published_at", None),
                    source=str(item.get("source", "") or ""),
                )

                analysis = {**analysis, "analyzed_at": now_utc.isoformat()}
                self.analysis_cache[news_id] = analysis

            analyzed_item = {**item, **analysis}
            analyzed_news.append(analyzed_item)

        self._prune_cache(now_utc)

        # Update last status snapshot (so trading cycle can just read it)
        self._last_status = self.current_status(now_utc)

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

    def last_status(self) -> Dict[str, Any]:
        """Return the last computed status (fast)."""
        return dict(self._last_status)

    def _aggregate_labels(
        self, now_utc: datetime, half_life_minutes: float
    ) -> Tuple[str, bool, bool, List[Dict[str, Any]]]:
        """
        Decide shock_level primarily by explicit label (good/info/soft/hard),
        with time decay and confidence.

        Returns: (shock_level, cooldown_active, sell_risk_exit, top_events)
        """
        # We keep it conservative and deterministic:
        # - any recent HARD with enough confidence triggers "hard"
        # - else any recent SOFT triggers "soft"
        # - else "ok"
        hard_hit = False
        soft_hit = False

        # Sell exit is ONLY a hint here. Actual sell should still be guarded by price/risk modules.
        sell_risk_exit = False

        top_events: List[Dict[str, Any]] = []

        for item in self.news_cache:
            nid = str(item.get("id", "")) or ""
            if not nid:
                continue
            analysis = self.analysis_cache.get(nid) or {}
            if analysis.get("openai_error", False):
                continue

            label = str(analysis.get("label", "") or "").lower()
            conf = float(analysis.get("confidence", 0.0))
            conf = _clamp(conf, 0.0, 1.0)

            published_dt = _parse_iso8601_dt(str(item.get("published_at", "")))
            age_min = _age_minutes(now_utc, published_dt)
            if age_min is None:
                w_time = 0.6
            else:
                w_time = 0.5 ** (age_min / half_life_minutes)

            # ignore extremely weak/old signals
            if conf * w_time < 0.15:
                continue

            if label == "hard":
                # For hard we also require a moderate confidence threshold
                if conf >= 0.55:
                    hard_hit = True
                    # if OpenAI flagged recommend_sell, bubble it up (still guarded elsewhere)
                    if bool(analysis.get("recommend_sell", False)):
                        sell_risk_exit = True
            elif label == "soft":
                if conf >= 0.45:
                    soft_hit = True

            # Collect a few events for logs
            if label in ("hard", "soft") and len(top_events) < 5:
                top_events.append(
                    {
                        "id": nid,
                        "label": label,
                        "sentiment": float(analysis.get("sentiment", 0.0)),
                        "confidence": conf,
                        "category": str(analysis.get("category", "other")),
                        "why": str(analysis.get("why", ""))[:240],
                        "published_at": item.get("published_at", ""),
                        "source": item.get("source", ""),
                        "url": item.get("url", ""),
                    }
                )

        if hard_hit:
            return ("hard", True, sell_risk_exit, top_events)
        if soft_hit:
            return ("soft", False, False, top_events)
        return ("ok", False, False, top_events)

    def current_status(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Aggregates current batch (self.news_cache) into a simple status used by risk evaluation.

        Output keeps backward compatibility:
          - sent_llm
          - shock_level
          - cooldown_active
          - news_count
        Plus additions:
          - label_counts
          - risk_mult (suggested)
          - sell_risk_exit (hint; still must be guarded elsewhere)
          - top_events
        """
        now_utc = _as_utc(now) if now else datetime.now(timezone.utc)

        if not self.news_cache:
            return {
                "sent_llm": 0.0,
                "shock_level": "ok",
                "cooldown_active": False,
                "news_count": 0,
            }

        tcfg = self._get_time_settings()
        thresholds = self._get_thresholds()
        half_life = tcfg["half_life_minutes"]

        total = 0.0
        total_w = 0.0
        count = 0

        label_counts = {"good": 0, "info": 0, "soft": 0, "hard": 0}

        for item in self.news_cache:
            nid = str(item.get("id", "")) or ""
            if not nid:
                continue

            analysis = self.analysis_cache.get(nid) or {}
            if analysis.get("openai_error", False):
                continue

            sentiment = float(analysis.get("sentiment", 0.0))
            confidence = float(analysis.get("confidence", 0.0))
            confidence = _clamp(confidence, 0.0, 1.0)

            label = str(analysis.get("label", "") or "").lower()
            if label in label_counts:
                label_counts[label] += 1

            published_dt = _parse_iso8601_dt(str(item.get("published_at", "")))
            age_min = _age_minutes(now_utc, published_dt)
            if age_min is None:
                w_time = 0.6
            else:
                w_time = 0.5 ** (age_min / half_life)

            # Optional extra weight by panic score (if present)
            panic_score = item.get("panic_score", None)
            try:
                ps = float(panic_score) if panic_score is not None else None
            except Exception:
                ps = None

            w_panic = 1.0
            if ps is not None:
                # Keep it gentle to avoid overreacting
                # Cap at 150 just in case your feed shows >100 values.
                ps_c = _clamp(ps, 0.0, 150.0)
                w_panic = 1.0 + (ps_c / 150.0) * 0.6  # 1.0 .. 1.6

            w = confidence * w_time * w_panic
            if w <= 0.0:
                continue

            total += sentiment * w
            total_w += w
            count += 1

        sent_llm = total / total_w if total_w > 0 else 0.0

        # Prefer explicit label-driven shock, fallback to threshold on sent_llm.
        shock_level, cooldown_active, sell_risk_exit, top_events = self._aggregate_labels(now_utc, half_life)

        if shock_level == "ok":
            if sent_llm <= thresholds["hard"]:
                shock_level = "hard"
                cooldown_active = True
            elif sent_llm <= thresholds["soft"]:
                shock_level = "soft"

        # Suggested risk multiplier (tradebot may override)
        # hard -> 0.0 (no new entries), soft -> 0.5, ok -> 1.0
        risk_mult = 1.0
        if shock_level == "soft":
            risk_mult = 0.5
        elif shock_level == "hard":
            risk_mult = 0.0

        return {
            "sent_llm": sent_llm,
            "shock_level": shock_level,
            "cooldown_active": cooldown_active,
            "news_count": count,
            "thresholds": thresholds,
            "label_counts": label_counts,
            "risk_mult": risk_mult,
            "sell_risk_exit": sell_risk_exit,
            "top_events": top_events,
        }