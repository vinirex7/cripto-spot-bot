from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bot.utils import write_jsonl
from news.cryptopanic import fetch_news
from news.openai_news import analyze_news


class NewsEngine:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.last_news_check: Optional[datetime] = None
        self._status: Dict[str, Any] = {"status": "ok", "sent_llm": 0.0}
        self.logs_cfg = config.get("logging", {})

    def _news_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("news", "logs/news.jsonl")

    def _system_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("system", "logs/system.jsonl")

    def current_status(self) -> Dict[str, Any]:
        return self._status

    def maybe_fetch(self, now: Optional[datetime] = None) -> None:
        news_cfg = self.config.get("news", {})
        if not news_cfg.get("enabled", True):
            return
        now = now or datetime.now(timezone.utc)
        if self.last_news_check:
            elapsed = now - self.last_news_check
            if elapsed < timedelta(hours=news_cfg["schedule"]["check_every_hours"]):
                return
        self._log_system({"event": "news_window_start", "ts": now.isoformat()})
        items = fetch_news(now, self.config)
        openai_cfg = news_cfg.get("openai", {})
        count = 0
        for itm in items:
            analysis = analyze_news(itm["title"], itm["url"], None, self.config)
            sent_llm = analysis.get("sentiment", 0) * analysis.get("confidence", 0)
            entry = {
                "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": itm.get("source", "cryptopanic"),
                "id": itm.get("id"),
                "title": itm.get("title"),
                "url": itm.get("url"),
                "openai": {
                    "sentiment": analysis.get("sentiment"),
                    "confidence": analysis.get("confidence"),
                    "impact_horizon_minutes": analysis.get("impact_horizon_minutes"),
                    "category": analysis.get("category"),
                    "action_bias": analysis.get("action_bias"),
                },
                "sent_llm": sent_llm,
            }
            write_jsonl(
                self._news_path(),
                entry,
                flush=self.logs_cfg.get("flush_every_write", True),
            )
            self._status = self._assess_news_shock(analysis, sent_llm)
            count += 1
            if count >= openai_cfg.get("max_calls_per_fetch", 50):
                break
        self.last_news_check = now
        self._log_system({"event": "news_window_end", "items": count})

    def _assess_news_shock(
        self, analysis: Dict[str, Any], sent_llm: float
    ) -> Dict[str, Any]:
        shock_cfg = self.config["news"]["shock"]
        category = analysis.get("category", "")
        confidence = analysis.get("confidence", 0.0)
        sentiment = analysis.get("sentiment", 0.0)
        status = "ok"
        if (
            category in shock_cfg.get("critical_categories", [])
            and confidence >= shock_cfg["hard_confidence_min"]
            and sentiment <= shock_cfg["hard_sentiment_max"]
        ):
            status = "hard"
        else:
            combined = sent_llm * self.config["news"]["scoring"].get(
                "w_sent_llm", 0.3
            )
            if combined <= shock_cfg["soft_threshold_ns"]:
                status = "soft"
        return {
            "status": status,
            "sent_llm": sent_llm,
            "category": category,
            "confidence": confidence,
            "sentiment": sentiment,
        }

    def _log_system(self, payload: Dict[str, Any]) -> None:
        write_jsonl(
            self._system_path(),
            payload,
            flush=self.logs_cfg.get("flush_every_write", True),
        )
