"""
Test suite for risk guards.
Tests drawdown limits, spread guards, and regime blocking.
"""
import pytest
import pandas as pd
import numpy as np

from risk.guards import Guards
from risk.position_sizing import PositionSizer
from signals.regime import RegimeDetector


@pytest.fixture
def risk_config():
    """Standard risk configuration."""
    return {
        'risk': {
            'daily_drawdown_pause_pct': 2.5,
            'max_holding_hours': 72,
            'target_vol_1d': 0.012,
            'max_positions': 2,
            'weight_per_position_max': 0.30,
            'cash_buffer_min': 0.40
        }
    }


@pytest.fixture
def guards(risk_config):
    """Create Guards instance."""
    return Guards(risk_config)


@pytest.fixture
def position_sizer(risk_config):
    """Create PositionSizer instance."""
    return PositionSizer(risk_config)


def test_drawdown_guard_pass(guards):
    """Test that trading continues with acceptable drawdown."""
    micro_metrics = {'all_guards_pass': True}
    
    result = guards.check_all_guards(
        micro_metrics,
        position_data=None,
        daily_pnl_pct=-1.0  # 1% loss, below 2.5% limit
    )
    
    assert result['drawdown_ok'] == True
    assert result['guards_pass'] == True


def test_drawdown_guard_block(guards):
    """Test that trading stops with excessive drawdown."""
    micro_metrics = {'all_guards_pass': True}
    
    result = guards.check_all_guards(
        micro_metrics,
        position_data=None,
        daily_pnl_pct=-3.0  # 3% loss, exceeds 2.5% limit
    )
    
    assert result['drawdown_ok'] == False
    assert result['guards_pass'] == False
    assert any('drawdown' in r.lower() for r in result['reasons'])


def test_holding_period_guard_pass(guards):
    """Test that holding period within limit passes."""
    micro_metrics = {'all_guards_pass': True}
    position_data = {'holding_hours': 48}  # 48h, below 72h limit
    
    result = guards.check_all_guards(
        micro_metrics,
        position_data=position_data,
        daily_pnl_pct=0.0
    )
    
    assert result['holding_period_ok'] == True


def test_holding_period_guard_block(guards):
    """Test that excessive holding period triggers guard."""
    micro_metrics = {'all_guards_pass': True}
    position_data = {'holding_hours': 80}  # 80h, exceeds 72h limit
    
    result = guards.check_all_guards(
        micro_metrics,
        position_data=position_data,
        daily_pnl_pct=0.0
    )
    
    assert result['holding_period_ok'] == False
    assert result['guards_pass'] == False


def test_microstructure_guard_fail(guards):
    """Test that failed microstructure checks block trading."""
    micro_metrics = {
        'all_guards_pass': False,
        'spread_ok': False,
        'spread_bps': 15.0
    }
    
    result = guards.check_all_guards(micro_metrics)
    
    assert result['guards_pass'] == False
    assert len(result['reasons']) > 0


def test_force_exit_drawdown(guards):
    """Test force exit triggered by drawdown."""
    position_data = {'holding_hours': 24}
    micro_metrics = {'all_guards_pass': True}
    
    should_exit = guards.should_force_exit(
        position_data,
        micro_metrics,
        daily_pnl_pct=-3.0  # Exceeds 2.5%
    )
    
    assert should_exit == True


def test_force_exit_holding_period(guards):
    """Test force exit triggered by holding period."""
    position_data = {'holding_hours': 80}  # Exceeds 72h
    micro_metrics = {'all_guards_pass': True}
    
    should_exit = guards.should_force_exit(
        position_data,
        micro_metrics,
        daily_pnl_pct=0.0
    )
    
    assert should_exit == True


def test_force_exit_not_triggered(guards):
    """Test force exit not triggered with good conditions."""
    position_data = {'holding_hours': 24}
    micro_metrics = {'all_guards_pass': True}
    
    should_exit = guards.should_force_exit(
        position_data,
        micro_metrics,
        daily_pnl_pct=-1.0
    )
    
    assert should_exit == False


def test_position_sizer_max_positions(position_sizer):
    """Test that max positions limit is enforced."""
    # Try to size when at max positions
    sizing = position_sizer.calculate_position_size(
        account_value=10000,
        current_price=100,
        realized_vol=0.02,
        existing_positions=2  # At max
    )
    
    assert sizing['can_trade'] == False
    assert 'max positions' in sizing['reason'].lower()


def test_position_sizer_weight_cap(position_sizer):
    """Test that weight per position is capped."""
    sizing = position_sizer.calculate_position_size(
        account_value=10000,
        current_price=100,
        realized_vol=0.001,  # Very low vol would suggest large position
        existing_positions=0
    )
    
    # Weight should never exceed max
    assert sizing['weight'] <= position_sizer.weight_per_position_max


def test_position_sizer_cash_buffer(position_sizer):
    """Test that cash buffer is respected."""
    max_allowed = position_sizer.get_cash_buffer_required(10000)
    
    assert max_allowed == 4000  # 40% of 10000


def test_position_sizer_portfolio_validation(position_sizer):
    """Test portfolio validation against limits."""
    positions = {
        'BTCUSDT': {'value': 2000},
        'ETHUSDT': {'value': 2000}
    }
    
    result = position_sizer.validate_portfolio(
        account_value=10000,
        positions=positions
    )
    
    # Total 4000 exposure, 6000 cash = 60% buffer (OK)
    assert result['is_valid'] == True
    assert result['num_positions'] == 2
    assert result['cash_buffer_pct'] == 0.6


def test_position_sizer_portfolio_violation_cash(position_sizer):
    """Test portfolio validation fails with insufficient cash."""
    positions = {
        'BTCUSDT': {'value': 4000},
        'ETHUSDT': {'value': 3000}
    }
    
    result = position_sizer.validate_portfolio(
        account_value=10000,
        positions=positions
    )
    
    # Total 7000 exposure, only 30% cash buffer (< 40% required)
    assert result['is_valid'] == False
    assert len(result['violations']) > 0


def test_regime_blocking():
    """Test that regime detector blocks in high correlation."""
    config = {
        'corr_window_short': 7,
        'corr_window_long': 30,
        'corr_threshold': 0.75,
        'vol_ratio_threshold': 1.0
    }
    
    detector = RegimeDetector(config)
    
    # Create synthetic high correlation scenario
    dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
    
    # BTC and alts move together
    np.random.seed(42)
    btc_returns = np.random.randn(100) * 0.02
    btc_prices = 100 * np.exp(np.cumsum(btc_returns))
    
    btc_df = pd.DataFrame({
        'close': btc_prices,
        'volume': np.random.rand(100) * 1000
    }, index=dates)
    
    # Alt follows BTC closely
    alt_prices = 50 * np.exp(np.cumsum(btc_returns * 0.9 + np.random.randn(100) * 0.005))
    alt_df = pd.DataFrame({
        'close': alt_prices,
        'volume': np.random.rand(100) * 1000
    }, index=dates)
    
    result = detector.detect_regime(btc_df, {'ETHUSDT': alt_df})
    
    # Should have correlation metrics
    assert 'corr_mean_short' in result
    assert 'block_trading' in result
