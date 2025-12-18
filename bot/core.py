import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yaml

from bot.engine import BotEngine
from bot.scheduler import SlotScheduler
from bot.utils import ensure_dir, utcnow, write_jsonl
from data.backfill import run_backfill
from data.history_store import HistoryStore
from news.news_engine import NewsEngine
from risk.guards import RiskGuards


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class BotCore:
    def __init__(self, config_path: str = "config.yaml") -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        self._prepare_paths()
        self.scheduler = SlotScheduler(
            decision_every_minutes=self.config["execution"]["decision_every_minutes"]
        )
        self.history_store = HistoryStore(self.config)
        self.news_engine = NewsEngine(self.config)
        self.risk_guards = RiskGuards(self.config, self.news_engine)
        self.engine = BotEngine(
            self.config, self.history_store, self.news_engine, self.risk_guards
        )

    def _prepare_paths(self) -> None:
        paths = self.config.get("paths", {})
        ensure_dir(paths.get("data_dir", "data"))
        ensure_dir(paths.get("logs_dir", "logs"))

    def _log_system(self, event: str, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "ts": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": event,
        }
        if extra:
            payload.update(extra)
        logs_cfg = self.config.get("logging", {})
        write_jsonl(
            logs_cfg.get("files", {}).get("system", "logs/system.jsonl"),
            payload,
            flush=logs_cfg.get("flush_every_write", True),
        )

    def bootstrap(self) -> None:
        history_cfg = self.config.get("history", {})
        if history_cfg.get("enabled") and history_cfg.get("backfill_on_start"):
            self._log_system("backfill_start", {"path": self.config["paths"]["db_path"]})
            run_backfill(self.config, self.history_store)
            self._log_system("backfill_end", {"path": self.config["paths"]["db_path"]})

    def run_once(self) -> None:
        now = utcnow()
        self.news_engine.maybe_fetch(now)
        if self.scheduler.should_run(now):
            slot = self.scheduler.current_slot(now)
            self.engine.step(slot=slot, now=now)

    def run_forever(self) -> None:
        self.bootstrap()
        loop_seconds = self.config["execution"]["loop_seconds"]
        while True:
            self.run_once()
            time.sleep(loop_seconds)


if __name__ == "__main__":
    bot = BotCore("config.yaml")
    bot.run_forever()
