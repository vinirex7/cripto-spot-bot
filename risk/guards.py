from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


@dataclass
class RiskAssessment:
    allow_entry: bool
    weight: float
    reason: str
    exit_all: bool = False
    pause_until: Optional[datetime] = None


class RiskGuards:
    def __init__(self, config: Dict):
        self.config = config
        self.daily_pnl = 0.0
        self.daily_start = datetime.now(timezone.utc).date()

    def _reset_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.daily_start:
            self.daily_start = today
            self.daily_pnl = 0.0

    def _next_utc_day_start(self) -> datetime:
        base = datetime.now(timezone.utc)
        return base.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    def register_pnl(self, pnl: float):
        self._reset_if_new_day()
        self.daily_pnl += pnl

    def assess(
        self,
        portfolio_value: float,
        open_positions: int,
        vol_1d: float,
        illiq: float,
        soft_risk_off: bool = False,
        current_allocation: float = 0.0,
    ) -> RiskAssessment:
        cfg = self.config.get("risk", {})
        positioning = self.config.get("positioning", {})
        max_positions = cfg.get("max_positions", positioning.get("max_positions", 2))
        max_weight = cfg.get("weight_per_position", positioning.get("weight_per_position", 0.30))
        cash_buffer = cfg.get("cash_buffer", positioning.get("cash_buffer", 0.40))
        target_vol = cfg.get("target_vol_1d", 0.012)
        daily_drawdown_pause = cfg.get("daily_drawdown_pause", 0.025)

        self._reset_if_new_day()
        if self.daily_pnl <= -abs(daily_drawdown_pause) * portfolio_value:
            return RiskAssessment(
                allow_entry=False,
                weight=0.0,
                reason="daily_drawdown_pause",
                exit_all=True,
                pause_until=self._next_utc_day_start(),
            )

        if open_positions >= max_positions:
            return RiskAssessment(allow_entry=False, weight=0.0, reason="max_positions")

        vol_1d = max(vol_1d, 1e-6)
        base_weight = min(max_weight, target_vol / vol_1d)

        # Liquidity adjustment
        if illiq > 0:
            base_weight *= 0.5

        if soft_risk_off:
            base_weight *= 0.5

        # Cash buffer check
        if current_allocation + base_weight > 1 - cash_buffer:
            return RiskAssessment(allow_entry=False, weight=0.0, reason="cash_buffer")

        return RiskAssessment(allow_entry=True, weight=base_weight, reason="ok")
