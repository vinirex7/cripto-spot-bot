from typing import Any, Dict

from bot.utils import write_jsonl


class PaperExecutor:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.logs_cfg = config.get("logging", {})

    def _trades_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("trades", "logs/trades.jsonl")

    def record_trade(self, payload: Dict[str, Any]) -> None:
        write_jsonl(
            self._trades_path(),
            payload,
            flush=self.logs_cfg.get("flush_every_write", True),
        )
