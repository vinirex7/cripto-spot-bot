"""Risk guards for position management."""
from typing import Any, Dict


class RiskGuards:
    """Risk management guards."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize risk guards.
        
        Args:
            config: Bot configuration dictionary
        """
        self.config = config
        self.risk_cfg = config.get("risk", {})
    
    def evaluate(self, symbol: str, features: Dict[str, Any], news_status: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate risk for a symbol.
        
        Args:
            symbol: Trading pair symbol
            features: Momentum features
            news_status: Current news status
            
        Returns:
            Risk evaluation context with risk_multiplier
        """
        risk_multiplier = 1.0
        reasons = []
        
        # Check news shock level
        shock_level = news_status.get("shock_level", "ok")
        if shock_level == "hard":
            risk_multiplier = 0.0
            reasons.append("hard_shock")
        elif shock_level == "soft":
            risk_multiplier *= 0.5
            reasons.append("soft_shock")
        
        # Check cooldown
        if news_status.get("cooldown_active", False):
            risk_multiplier = 0.0
            reasons.append("cooldown_active")
        
        # Check volatility if available
        if features and "vol_1d" in features:
            target_vol = self.risk_cfg.get("target_vol_1d", 0.012)
            vol_1d = features.get("vol_1d", 0.0)
            
            if vol_1d > 0:
                vol_multiplier = min(1.0, target_vol / vol_1d)
                risk_multiplier *= vol_multiplier
                reasons.append(f"vol_adjusted:{vol_multiplier:.2f}")
        
        return {
            "risk_multiplier": risk_multiplier,
            "shock_level": shock_level,
            "reasons": reasons,
            "weight_per_position": self.risk_cfg.get("weight_per_position", 0.30),
            "max_positions": self.risk_cfg.get("max_positions", 2),
        }
