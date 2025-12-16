"""
Dynamic parameter adjustments with strict guardrails.
LLM can ONLY suggest risk-reducing adjustments with TTL.
"""
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class DynamicParams:
    """
    Dynamic parameter adjustment system with strict guardrails.
    
    CRITICAL RULES:
    - Can ONLY reduce risk, never increase it
    - All adjustments have TTL (Time To Live)
    - LLM can suggest, but system validates and enforces limits
    
    Allowed (risk-reducing only):
    - Increase cooldown (up to 3x)
    - Reduce weight_per_position (up to 50% reduction)
    - Reduce target_vol (up to 50% reduction)
    - Reduce max_positions
    - Increase spread guard
    
    Never allowed:
    - Increase position size
    - Reduce spread guard
    - Increase target_vol
    - Increase max_positions
    """
    
    def __init__(self, config: Dict):
        dp_config = config.get('dynamic_params', {})
        
        self.enabled = dp_config.get('enabled', True)
        self.ttl_minutes = dp_config.get('ttl_minutes', 180)
        
        # Allowed adjustment limits
        allowed = dp_config.get('allowed', {})
        self.cooldown_max_multiplier = allowed.get('cooldown_max_multiplier', 3.0)
        self.weight_reduction_max_pct = allowed.get('weight_reduction_max_pct', 50)
        self.target_vol_reduction_max_pct = allowed.get('target_vol_reduction_max_pct', 50)
        self.max_positions_can_reduce = allowed.get('max_positions_can_reduce', True)
        self.spread_guard_can_increase = allowed.get('spread_guard_can_increase', True)
        
        # Active adjustments
        self.adjustments: Dict[str, Dict] = {}
    
    def suggest_adjustment(
        self,
        param_name: str,
        adjustment_type: str,
        value: float,
        reason: str,
        current_time: datetime
    ) -> Dict[str, any]:
        """
        Suggest a parameter adjustment.
        
        System validates and applies guardrails before accepting.
        
        Args:
            param_name: Parameter to adjust
            adjustment_type: 'multiply' or 'add' or 'set'
            value: Adjustment value
            reason: Reason for adjustment
            current_time: Current timestamp
        
        Returns:
            Result dictionary
        """
        if not self.enabled:
            return {
                'accepted': False,
                'reason': 'Dynamic params disabled'
            }
        
        # Validate against guardrails
        validation = self._validate_adjustment(param_name, adjustment_type, value)
        
        if not validation['valid']:
            logger.warning(f"Adjustment rejected: {validation['reason']}")
            return {
                'accepted': False,
                'reason': validation['reason']
            }
        
        # Apply adjustment with TTL
        expires_at = current_time + timedelta(minutes=self.ttl_minutes)
        
        self.adjustments[param_name] = {
            'adjustment_type': adjustment_type,
            'value': value,
            'reason': reason,
            'applied_at': current_time,
            'expires_at': expires_at
        }
        
        logger.info(f"Adjustment accepted: {param_name} {adjustment_type} {value} (expires {expires_at})")
        
        return {
            'accepted': True,
            'reason': 'OK',
            'expires_at': expires_at.isoformat()
        }
    
    def _validate_adjustment(
        self,
        param_name: str,
        adjustment_type: str,
        value: float
    ) -> Dict[str, any]:
        """
        Validate adjustment against guardrails.
        
        Returns:
            Validation result
        """
        # Check param name
        allowed_params = [
            'cooldown_multiplier',
            'weight_per_position',
            'target_vol_1d',
            'max_positions',
            'spread_max_bps'
        ]
        
        if param_name not in allowed_params:
            return {
                'valid': False,
                'reason': f'Parameter {param_name} not allowed for dynamic adjustment'
            }
        
        # Validate specific parameters
        if param_name == 'cooldown_multiplier':
            if adjustment_type == 'multiply' and value > self.cooldown_max_multiplier:
                return {
                    'valid': False,
                    'reason': f'Cooldown multiplier {value} exceeds max {self.cooldown_max_multiplier}'
                }
            if adjustment_type == 'multiply' and value < 1.0:
                return {
                    'valid': False,
                    'reason': 'Cannot reduce cooldown (only increase allowed)'
                }
        
        elif param_name == 'weight_per_position':
            if adjustment_type == 'multiply' and value > 1.0:
                return {
                    'valid': False,
                    'reason': 'Cannot increase position weight (only reduce allowed)'
                }
            max_reduction = 1 - (self.weight_reduction_max_pct / 100)
            if adjustment_type == 'multiply' and value < max_reduction:
                return {
                    'valid': False,
                    'reason': f'Weight reduction {value} exceeds max {max_reduction}'
                }
        
        elif param_name == 'target_vol_1d':
            if adjustment_type == 'multiply' and value > 1.0:
                return {
                    'valid': False,
                    'reason': 'Cannot increase target vol (only reduce allowed)'
                }
            max_reduction = 1 - (self.target_vol_reduction_max_pct / 100)
            if adjustment_type == 'multiply' and value < max_reduction:
                return {
                    'valid': False,
                    'reason': f'Target vol reduction {value} exceeds max {max_reduction}'
                }
        
        elif param_name == 'max_positions':
            if not self.max_positions_can_reduce:
                return {
                    'valid': False,
                    'reason': 'max_positions adjustment not allowed'
                }
            if adjustment_type == 'add' and value > 0:
                return {
                    'valid': False,
                    'reason': 'Cannot increase max_positions (only reduce allowed)'
                }
        
        elif param_name == 'spread_max_bps':
            if not self.spread_guard_can_increase:
                return {
                    'valid': False,
                    'reason': 'spread_max_bps adjustment not allowed'
                }
            if adjustment_type == 'multiply' and value < 1.0:
                return {
                    'valid': False,
                    'reason': 'Cannot reduce spread guard (only increase allowed)'
                }
        
        return {'valid': True, 'reason': 'OK'}
    
    def get_active_adjustments(self, current_time: datetime) -> Dict[str, Dict]:
        """
        Get currently active adjustments (not expired).
        
        Args:
            current_time: Current timestamp
        
        Returns:
            Dictionary of active adjustments
        """
        active = {}
        
        for param_name, adj in list(self.adjustments.items()):
            expires_at = adj['expires_at']
            
            if current_time >= expires_at:
                # Expired
                logger.info(f"Adjustment expired: {param_name}")
                del self.adjustments[param_name]
            else:
                active[param_name] = adj
        
        return active
    
    def apply_adjustments(
        self,
        base_params: Dict[str, float],
        current_time: datetime
    ) -> Dict[str, float]:
        """
        Apply active adjustments to base parameters.
        
        Args:
            base_params: Base parameter values
            current_time: Current timestamp
        
        Returns:
            Adjusted parameter values
        """
        adjusted_params = base_params.copy()
        active_adjustments = self.get_active_adjustments(current_time)
        
        for param_name, adj in active_adjustments.items():
            if param_name not in adjusted_params:
                continue
            
            base_value = adjusted_params[param_name]
            adjustment_type = adj['adjustment_type']
            adj_value = adj['value']
            
            if adjustment_type == 'multiply':
                adjusted_params[param_name] = base_value * adj_value
            elif adjustment_type == 'add':
                adjusted_params[param_name] = base_value + adj_value
            elif adjustment_type == 'set':
                adjusted_params[param_name] = adj_value
            
            logger.info(
                f"Applied adjustment: {param_name} {base_value} -> {adjusted_params[param_name]} "
                f"(reason: {adj['reason']})"
            )
        
        return adjusted_params
    
    def clear_all(self):
        """Clear all adjustments (use with caution)."""
        self.adjustments.clear()
        logger.info("All dynamic adjustments cleared")
    
    def get_summary(self, current_time: datetime) -> Dict[str, any]:
        """Get summary of dynamic parameter state."""
        active_adjustments = self.get_active_adjustments(current_time)
        
        return {
            'enabled': self.enabled,
            'ttl_minutes': self.ttl_minutes,
            'active_count': len(active_adjustments),
            'active_adjustments': active_adjustments
        }
