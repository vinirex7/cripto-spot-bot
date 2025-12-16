"""
Test suite for Momentum 2.0 signal generation.
Tests momentum calculation, age-based decay, and signal generation.
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from signals.momentum import MomentumSignal


@pytest.fixture
def momentum_config():
    """Standard momentum configuration."""
    return {
        'short_window': 60,
        'mid_window': 90,
        'long_window': 120,
        'sma_window': 50,
        'age_decay': {
            'excellent': 12,
            'good': 15,
            'fair': 18,
            'poor': 999
        },
        'entry': {
            'min_age_factor': 0.5,
            'min_delta_m': 0.0
        },
        'exit': {
            'max_age_factor': 0.0,
            'max_delta_m_days': 3,
            'use_sma_exit': True
        }
    }


@pytest.fixture
def uptrend_data():
    """Generate uptrending price data."""
    dates = pd.date_range(start='2023-01-01', periods=150, freq='D')
    # Exponential uptrend with some noise
    prices = 100 * np.exp(np.linspace(0, 0.5, 150)) + np.random.randn(150) * 2
    
    df = pd.DataFrame({
        'close': prices,
        'volume': np.random.rand(150) * 1000 + 500
    }, index=dates)
    
    return df


@pytest.fixture
def downtrend_data():
    """Generate downtrending price data."""
    dates = pd.date_range(start='2023-01-01', periods=150, freq='D')
    # Exponential downtrend with some noise
    prices = 100 * np.exp(np.linspace(0, -0.3, 150)) + np.random.randn(150) * 2
    
    df = pd.DataFrame({
        'close': prices,
        'volume': np.random.rand(150) * 1000 + 500
    }, index=dates)
    
    return df


def test_momentum_calculation_uptrend(momentum_config, uptrend_data):
    """Test that momentum is positive for uptrending data."""
    signal = MomentumSignal(momentum_config)
    
    momentum = signal.calculate_momentum(uptrend_data, window=60)
    
    assert momentum > 0, "Momentum should be positive for uptrend"
    assert not np.isnan(momentum), "Momentum should not be NaN"


def test_momentum_calculation_downtrend(momentum_config, downtrend_data):
    """Test that momentum is negative for downtrending data."""
    signal = MomentumSignal(momentum_config)
    
    momentum = signal.calculate_momentum(downtrend_data, window=60)
    
    assert momentum < 0, "Momentum should be negative for downtrend"
    assert not np.isnan(momentum), "Momentum should not be NaN"


def test_age_factor_calculation(momentum_config, uptrend_data):
    """Test age-based decay factor calculation."""
    signal = MomentumSignal(momentum_config)
    
    # Recent data (< 12 months)
    recent_data = uptrend_data.tail(120)
    age_factor = signal.get_age_factor(recent_data)
    assert age_factor == 1.00, "Recent data should have age factor of 1.00"
    
    # Older data (12-15 months) - simulate by creating older timestamps
    old_dates = pd.date_range(start='2022-01-01', periods=450, freq='D')
    old_data = pd.DataFrame({
        'close': np.random.rand(450) * 100,
        'volume': np.random.rand(450) * 1000
    }, index=old_dates)
    
    age_factor_old = signal.get_age_factor(old_data)
    assert age_factor_old <= 1.00, "Old data should have age factor <= 1.00"


def test_signal_generation(momentum_config, uptrend_data):
    """Test complete signal generation."""
    signal = MomentumSignal(momentum_config)
    
    signals = signal.calculate_signals(uptrend_data)
    
    # Check all expected keys exist
    assert 'M_short' in signals
    assert 'M_mid' in signals
    assert 'M_long' in signals
    assert 'M_age_factor' in signals
    assert 'delta_M' in signals
    assert 'sma50' in signals
    assert 'current_price' in signals
    assert 'signal' in signals
    
    # Check signal is valid (-1, 0, or 1)
    assert signals['signal'] in [-1, 0, 1]


def test_momentum_with_insufficient_data(momentum_config):
    """Test momentum calculation with insufficient data."""
    signal = MomentumSignal(momentum_config)
    
    # Create very short dataset
    dates = pd.date_range(start='2023-01-01', periods=10, freq='D')
    short_data = pd.DataFrame({
        'close': np.random.rand(10) * 100,
        'volume': np.random.rand(10) * 1000
    }, index=dates)
    
    signals = signal.calculate_signals(short_data)
    
    # Should return safe defaults
    assert signals['signal'] == 0
    assert signals['M_age_factor'] >= 0


def test_momentum_deterministic(momentum_config, uptrend_data):
    """Test that momentum calculation is deterministic."""
    signal = MomentumSignal(momentum_config)
    
    # Calculate twice with same data
    result1 = signal.calculate_momentum(uptrend_data, window=60)
    result2 = signal.calculate_momentum(uptrend_data, window=60)
    
    assert result1 == result2, "Momentum calculation should be deterministic"


def test_entry_conditions(momentum_config, uptrend_data):
    """Test entry signal conditions."""
    signal = MomentumSignal(momentum_config)
    
    signals = signal.calculate_signals(uptrend_data)
    
    # If signal is 1 (buy), conditions should be met
    if signals['signal'] == 1:
        assert signals['M_age_factor'] >= momentum_config['entry']['min_age_factor']
        assert signals['delta_M'] >= momentum_config['entry']['min_delta_m']


def test_exit_conditions(momentum_config, downtrend_data):
    """Test exit signal conditions."""
    signal = MomentumSignal(momentum_config)
    
    signals = signal.calculate_signals(downtrend_data)
    
    # If signal is -1 (exit), some exit condition should be met
    if signals['signal'] == -1:
        # At least one exit condition should be true
        age_exit = signals['M_age_factor'] < momentum_config['exit']['max_age_factor']
        sma_exit = signals['current_price'] < signals['sma50']
        
        assert age_exit or sma_exit, "Exit signal should meet at least one condition"
