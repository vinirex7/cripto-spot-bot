from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bot.utils import write_jsonl
from data.history_store import HistoryStore
from news.news_engine import NewsEngine
from risk.guards import RiskGuards
from signals.momentum import compute_momentum_features


class BotEngine:
    def __init__(
        self,
        config: Dict[str, Any],
        history_store: HistoryStore,
        news_engine: NewsEngine,
        risk_guards: RiskGuards,
    ) -> None:
        self.config = config
        self.history_store = history_store
        self.news_engine = news_engine
        self.risk_guards = risk_guards
        self.logs_cfg = config.get("logging", {})

    def _decisions_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("decisions", "logs/decisions.jsonl")

    def step(self, slot: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        symbols = self.config.get("universe", [])
        results: List[Dict[str, Any]] = []
        for symbol in symbols:
            features = compute_momentum_features(
                self.history_store,
                symbol,
                self.config.get("momentum", {}),
            )
            news_status = self.news_engine.current_status()
            risk_ctx = self.risk_guards.evaluate(symbol, features, news_status)
            target_weight = 0.0
            action = "HOLD"
            reason = "Momentum insufficient or risk constraints"
            if features and risk_ctx.get("risk_multiplier", 0) > 0:
                if features.get("m_age", 0) >= self.config["momentum"].get(
                    "min_momentum_idade", 0
                ):
                    if not self.config["momentum"].get(
                        "require_delta_positive", True
                    ) or features.get("delta_m", 0) > 0:
                        target_weight = min(
                            self.config["risk"].get("weight_per_position", 0.0),
                            self.config["risk"].get("target_vol_1d", 1.0),
                        )
                        action = "BUY" if target_weight > 0 else "HOLD"
                        reason = "Momentum ok; risk ok"
            decision = {
                "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "slot": slot,
                "symbol": symbol,
                "action": action,
                "target_weight": target_weight,
                "features": features or {},
                "risk": risk_ctx,
                "reason": reason,
            }
            write_jsonl(
                self._decisions_path(),
                decision,
                flush=self.logs_cfg.get("flush_every_write", True),
            )
            results.append(decision)
        return results
