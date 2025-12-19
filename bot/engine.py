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
        """
        Initialize bot engine.
        
        Args:
            config: Bot configuration dictionary
            history_store: Historical data storage
            news_engine: News analysis engine
            risk_guards: Risk management guards
        """
        self.config = config
        self.history_store = history_store
        self.news_engine = news_engine
        self.risk_guards = risk_guards
        self.logs_cfg = config.get("logging", {})
        self.executor = create_executor(config)

    def step(self, slot: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Execute one decision cycle for all symbols.
        
        Args:
            slot: Time slot identifier
            now: Current datetime (defaults to UTC now)
            
        Returns:
            List of decision records
        """
        now = now or datetime.now(timezone.utc)
        symbols = self.config.get("universe", [])
        results: List[Dict[str, Any]] = []
        
        for symbol in symbols:
            # Compute momentum features
            features = compute_momentum_features(
                self.history_store,
                symbol,
                self.config.get("momentum", {}),
            )
            
            # Get news status
            news_status = self.news_engine.current_status()
            
            # Evaluate risk
            risk_ctx = self.risk_guards.evaluate(symbol, features, news_status)
            
            # Make trading decision
            target_weight = 0.0
            action = "HOLD"
            reason = "Momentum insufficient or risk constraints"

            if features and risk_ctx.get("risk_multiplier", 0) > 0:
            momentum_cfg = self.config.get("momentum", {})

                m6 = features.get("m_6", 0.0)
                m12 = features.get("m_12", 0.0)
                delta_m = features.get("delta_m", 0.0)
                m_age = features.get("m_age", 0.0)

            min_age = momentum_cfg.get("min_momentum_idade", 0)
            require_delta = momentum_cfg.get("require_delta_positive", True)

            direction_ok = (m6 > 0) and (m12 > 0)
            acceleration_ok = (delta_m > 0) if require_delta else True
            age_ok = (m_age >= min_age)

            momentum_ok = direction_ok and acceleration_ok and age_ok

            if momentum_ok:
                base_weight = self.config.get("risk", {}).get("weight_per_position", 0.0)
                target_weight = base_weight * risk_ctx.get("risk_multiplier", 1.0)

                if target_weight > 0:
                    action = "BUY"
                    reason = "Momentum ok; risk ok"
            else:
                reason = (
                    f"Momentum blocked | "
                    f"m6={m6:.2f}, m12={m12:.2f}, Δm={delta_m:.2f}, age={m_age:.0f}"
                )


            











            
            # Execute trade if action != HOLD
            execution_result = None
            if action != "HOLD":
                # Fetch current price (use latest close from history or Binance ticker)
                recent = self.history_store.fetch_ohlcv("1h", symbol, limit=1)
                current_price = recent[-1][4] if recent and len(recent) > 0 else 0
                
                if current_price > 0:
                    execution_result = self.executor.execute(symbol, action, target_weight, current_price)
            
            # Record decision
            decision = {
                "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "slot": slot,
                "symbol": symbol,
                "action": action,
                "target_weight": target_weight,
                "features": features or {},
                "risk": risk_ctx,
                "reason": reason,
                "execution": execution_result
            }
            
            write_jsonl(
                self._decisions_path(),
                decision,
                flush=self.logs_cfg.get("flush_every_write", True),
            )
            results.append(decision)
        
        return results
    
    def _decisions_path(self) -> str:
        """Get path for decisions log file."""
        return self.logs_cfg.get("files", {}).get("decisions", "logs/decisions.jsonl")
