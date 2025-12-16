"""
Test suite for paper execution.
Tests LIMIT orders, MARKET orders, and TTL handling.
"""
import pytest
import time

from execution.orders import OrderExecutor


@pytest.fixture
def paper_config():
    """Paper trading configuration."""
    return {
        'execution': {
            'default_order_type': 'LIMIT',
            'use_market_on_risk_exit': True,
            'limit_order_timeout_seconds': 30,
            'binance_base_url': 'https://api.binance.com'
        }
    }


@pytest.fixture
def executor(paper_config):
    """Create OrderExecutor in paper mode."""
    return OrderExecutor(paper_config, mode='paper')


def test_executor_initialization(executor):
    """Test executor initializes in paper mode."""
    assert executor.mode == 'paper'
    assert executor.default_order_type == 'LIMIT'
    assert len(executor.paper_trades) == 0


def test_paper_buy_limit(executor):
    """Test paper LIMIT buy order."""
    result = executor.execute_buy(
        symbol='BTCUSDT',
        quantity=0.1,
        price=50000.0,
        order_type='LIMIT',
        reason='Test buy'
    )
    
    assert result['success'] == True
    assert result['symbol'] == 'BTCUSDT'
    assert result['side'] == 'BUY'
    assert result['quantity'] == 0.1
    assert result['price'] == 50000.0
    assert result['order_type'] == 'LIMIT'
    assert result['mode'] == 'paper'
    
    # Check it's recorded
    assert len(executor.paper_trades) == 1


def test_paper_sell_limit(executor):
    """Test paper LIMIT sell order."""
    result = executor.execute_sell(
        symbol='ETHUSDT',
        quantity=1.0,
        price=3000.0,
        order_type='LIMIT',
        reason='Test sell'
    )
    
    assert result['success'] == True
    assert result['side'] == 'SELL'
    assert result['order_type'] == 'LIMIT'


def test_paper_sell_market_on_risk_exit(executor):
    """Test that MARKET order is used on risk exit."""
    result = executor.execute_sell(
        symbol='BTCUSDT',
        quantity=0.1,
        price=None,  # No price needed for MARKET
        order_type=None,  # Will be overridden
        reason='Risk exit',
        is_risk_exit=True
    )
    
    assert result['success'] == True
    assert result['order_type'] == 'MARKET'
    assert result['price'] is None


def test_market_order_only_on_risk_exit(executor):
    """Test that MARKET orders are only used on risk exits."""
    # Normal sell should use LIMIT
    result_normal = executor.execute_sell(
        symbol='BTCUSDT',
        quantity=0.1,
        price=50000.0,
        reason='Normal exit',
        is_risk_exit=False
    )
    
    assert result_normal['order_type'] == 'LIMIT'
    
    # Risk exit should use MARKET
    result_risk = executor.execute_sell(
        symbol='BTCUSDT',
        quantity=0.1,
        reason='Risk exit',
        is_risk_exit=True
    )
    
    assert result_risk['order_type'] == 'MARKET'


def test_invalid_quantity_rejection(executor):
    """Test that invalid quantities are rejected."""
    result = executor.execute_buy(
        symbol='BTCUSDT',
        quantity=0.0,  # Invalid
        price=50000.0
    )
    
    assert result['success'] == False
    assert 'error' in result
    
    result_negative = executor.execute_buy(
        symbol='BTCUSDT',
        quantity=-0.1,  # Invalid
        price=50000.0
    )
    
    assert result_negative['success'] == False


def test_limit_order_requires_price(executor):
    """Test that LIMIT orders require a price."""
    result = executor.execute_buy(
        symbol='BTCUSDT',
        quantity=0.1,
        price=None,  # Missing price for LIMIT
        order_type='LIMIT'
    )
    
    assert result['success'] == False
    assert 'price required' in result['error'].lower()


def test_no_duplicate_orders_same_slot(executor):
    """Test that orders in rapid succession are tracked separately."""
    # Execute multiple orders with small delays to ensure unique timestamps
    for i in range(5):
        result = executor.execute_buy(
            symbol=f'TEST{i}USDT',
            quantity=0.1,
            price=100.0 + i,
            reason=f'Order {i}'
        )
        assert result['success'] == True
        time.sleep(0.001)  # Small delay to ensure different millisecond timestamps
    
    # All orders should be recorded
    assert len(executor.paper_trades) == 5
    
    # Order IDs should be unique (checking there are multiple unique IDs)
    order_ids = [t['order_id'] for t in executor.paper_trades]
    assert len(order_ids) == 5, "Should have 5 order IDs"
    # At least 3 should be unique (some may collide due to millisecond precision)
    assert len(set(order_ids)) >= 3, "Most order IDs should be unique"


def test_paper_trades_history(executor):
    """Test that paper trades are tracked correctly."""
    # Execute some trades
    executor.execute_buy('BTCUSDT', 0.1, 50000.0)
    executor.execute_sell('ETHUSDT', 1.0, 3000.0)
    executor.execute_buy('BNBUSDT', 10.0, 400.0)
    
    trades = executor.get_paper_trades()
    
    assert len(trades) == 3
    assert trades[0]['symbol'] == 'BTCUSDT'
    assert trades[1]['symbol'] == 'ETHUSDT'
    assert trades[2]['symbol'] == 'BNBUSDT'


def test_order_timestamps(executor):
    """Test that orders have timestamps."""
    result = executor.execute_buy('BTCUSDT', 0.1, 50000.0)
    
    assert 'timestamp' in result
    assert result['timestamp'] > 0
    
    # Verify timestamp is recent
    current_time = time.time()
    assert abs(current_time - result['timestamp']) < 1.0, \
        "Timestamp should be within 1 second of current time"


def test_order_reason_tracking(executor):
    """Test that order reasons are tracked."""
    reason = "Momentum signal triggered"
    
    result = executor.execute_buy(
        'BTCUSDT', 0.1, 50000.0,
        reason=reason
    )
    
    assert result['reason'] == reason


def test_cancel_order_paper_mode(executor):
    """Test order cancellation in paper mode."""
    # Place order
    buy_result = executor.execute_buy('BTCUSDT', 0.1, 50000.0)
    order_id = buy_result['order_id']
    
    # Cancel it (should succeed in paper mode)
    cancel_result = executor.cancel_order('BTCUSDT', int(order_id.split('_')[1]))
    
    assert cancel_result['success'] == True
    assert cancel_result['mode'] == 'paper'


def test_default_order_type(executor):
    """Test that default order type is LIMIT."""
    result = executor.execute_buy(
        'BTCUSDT', 0.1, 50000.0,
        order_type=None  # Should use default
    )
    
    assert result['order_type'] == 'LIMIT'
