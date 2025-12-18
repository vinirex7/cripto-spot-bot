from typing import Any, Dict

from risk.news_shock import shock_multiplier


class RiskGuards:
    def __init__(self, config: Dict[str, Any], news_engine: Any) -> None:
        self.config = config
        self.news_engine = news_engine

    def evaluate(
        self, symbol: str, features: Dict[str, Any], news_status: Dict[str, Any]
    ) -> Dict[str, Any]:
        multiplier = shock_multiplier(news_status)
        drawdown_pause = False  # placeholder for daily drawdown logic
        return {
            "econ_risk_on": True,
            "news_status": news_status.get("status", "ok"),
            "risk_multiplier": multiplier,
            "drawdown_pause": drawdown_pause,
        }
