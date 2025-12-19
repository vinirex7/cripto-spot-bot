"""Bot engine integrating all components."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bot.utils import write_jsonl
from bot.storage import HistoryStore
from news.engine import NewsEngine
from risk.guards import RiskGuards
from signals.momentum import compute_momentum_features
from execution.orders import create_executor


class BotEngine:
    """Main bot engine coordinating all components."""
    
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
        self.executor = create_executor(config)

    def step(self, slot: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        symbols = self.config.get("universe", [])
        results: List[Dict[str, Any]] = []
        
        for symbol in symbols:
            # ---- Features ----
            features = compute_momentum_features(
                self.history_store,
                symbol,
                self.config.get("momentum", {}),
            )
            
            news_status = self.news_engine.current_status()
            risk_ctx = self.risk_guards.evaluate(symbol, features, news_status)

            # Defaults
            target_weight = 0.0
            action = "HOLD"
            regime = "blocked"
            reason = "Momentum insufficient or risk constraints"

            if features and risk_ctx.get("risk_multiplier", 0.0) > 0.0:
                m6 = float(features.get("m_6", 0.0))
                m12 = float(features.get("m_12", 0.0))
                delta_m = float(features.get("delta_m", 0.0))
                m_age = float(features.get("m_age", 0.0))

                # ---- Config / thresholds ----
                weight_per_position = self.config.get("risk", {}).get("weight_per_position", 0.0)

                REV_M6_MIN = 1.0
                REV_AGE_MIN = 270.0        # ~9 meses
                REV_WEIGHT_FACTOR = 0.35  # peso reduzido em reversão
                EPS = 1e-9

                # ---- Regimes ----
                trend_ok = (m12 > 0.0) and (m6 > 0.0) and (delta_m > 0.0)

                delta_norm = delta_m / (abs(m12) + EPS)

                strong_reversal_ok = (
                    (m12 <= 0.0) and
                    (m6 >= REV_M6_MIN) and
                    (delta_norm >= 1.0) and
                    (m_age >= REV_AGE_MIN)
                )

                if trend_ok:
                    regime = "trend"
                    base_weight = weight_per_position
                    reason = (
                        f"Momentum ok (trend) | "
                        f"m6={m6:.2f}, m12={m12:.2f}, Δm={delta_m:.2f}, age={m_age:.0f}"
                    )

                elif strong_reversal_ok:
                    regime = "early_reversal"
                    base_weight = weight_per_position * REV_WEIGHT_FACTOR
                    reason = (
                        f"Momentum ok (early reversal) | "
                        f"m6={m6:.2f}, m12={m12:.2f}, Δm={delta_m:.2f}, "
                        f"Δm_norm={delta_norm:.2f}, age={m_age:.0f}"
                    )

                else:
                    base_weight = 0.0
                    reason = (
                        f"Momentum blocked | "
                        f"m6={m6:.2f}, m12={m12:.2f}, Δm={delta_m:.2f}, "
                        f"Δm_norm={delta_norm:.2f}, age={m_age:.0f}"
                    )

                target_weight = base_weight * float(risk_ctx.get("risk_multiplier", 1.0))

                if target_weight > 0.0:
                    action = "BUY"

            # ---- Execution ----
            execution_result = None
            if action != "HOLD":
                recent = self.history_store.fetch_ohlcv("1h", symbol, limit=1)
                current_price = recent[-1][4] if recent else 0.0

                if current_price > 0:
                    execution_result = self.executor.execute(
                        symbol, action, target_weight, current_price
                    )

            # ---- Log ----
            decision = {
                "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "slot": slot,
                "symbol": symbol,
                "action": action,
                "regime": regime,
                "target_weight": target_weight,
                "features": features or {},
                "risk": risk_ctx,
                "reason": reason,
                "execution": execution_result,
            }

            write_jsonl(
                self._decisions_path(),
                decision,
                flush=self.logs_cfg.get("flush_every_write", True),
            )
            results.append(decision)

        return results
    
    def _decisions_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("decisions", "logs/decisions.jsonl")