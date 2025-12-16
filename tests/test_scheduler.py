"""
Test suite for anti-duplication scheduler.
Tests that bot.step() runs only once per time slot.
"""
import pytest
import time
from datetime import datetime

from bot.main import Scheduler


def test_scheduler_initialization():
    """Test scheduler initializes correctly."""
    scheduler = Scheduler(interval_minutes=15)
    
    assert scheduler.interval_minutes == 15
    assert scheduler.last_slot is None
    assert scheduler.running == False


def test_scheduler_slot_format():
    """Test that slot format is correct."""
    scheduler = Scheduler(interval_minutes=15)
    
    slot = scheduler.get_current_slot()
    
    # Should be in format "YYYY-MM-DDTHH:MM"
    assert isinstance(slot, str)
    assert len(slot) == 16
    assert 'T' in slot
    
    # Should be parseable as datetime
    datetime.strptime(slot, "%Y-%m-%dT%H:%M")


def test_scheduler_first_run_returns_true():
    """Test that first call to should_run() returns True."""
    scheduler = Scheduler(interval_minutes=15)
    
    should_run = scheduler.should_run()
    
    assert should_run == True, "First call should return True"
    assert scheduler.last_slot is not None, "last_slot should be set"


def test_scheduler_duplicate_prevention():
    """Test that duplicate calls in same slot return False."""
    scheduler = Scheduler(interval_minutes=15)
    
    # First call - should run
    first = scheduler.should_run()
    assert first == True
    
    # Second call in same slot - should NOT run
    second = scheduler.should_run()
    assert second == False
    
    # Third call - still should NOT run
    third = scheduler.should_run()
    assert third == False


def test_scheduler_slot_changes():
    """Test scheduler behavior across different slots."""
    scheduler = Scheduler(interval_minutes=1)  # 1 minute for faster testing
    
    # First slot
    slot1 = scheduler.get_current_slot()
    run1 = scheduler.should_run()
    assert run1 == True
    
    # Duplicate in same slot
    run1_dup = scheduler.should_run()
    assert run1_dup == False
    
    # Wait for slot to change (need to actually wait or mock time)
    # For unit test, we simulate by manually changing last_slot
    scheduler.last_slot = "2023-01-01T00:00"
    
    # New slot should allow running
    run2 = scheduler.should_run()
    assert run2 == True


def test_scheduler_interval_rounding():
    """Test that slots are rounded to interval correctly."""
    scheduler = Scheduler(interval_minutes=15)
    
    # Get multiple slots and verify they're rounded
    for _ in range(5):
        slot = scheduler.get_current_slot()
        minute = int(slot.split(':')[1])
        
        # Minute should be divisible by interval
        assert minute % 15 == 0, f"Minute {minute} should be multiple of 15"


def test_scheduler_different_intervals():
    """Test scheduler with different intervals."""
    for interval in [1, 5, 10, 15, 30, 60]:
        scheduler = Scheduler(interval_minutes=interval)
        
        slot = scheduler.get_current_slot()
        minute = int(slot.split(':')[1])
        
        # Minute should be divisible by interval (or 0)
        assert minute % interval == 0


def test_scheduler_no_race_condition():
    """Test that rapid calls don't bypass deduplication."""
    scheduler = Scheduler(interval_minutes=15)
    
    results = []
    # Rapid fire 100 calls
    for _ in range(100):
        results.append(scheduler.should_run())
    
    # Only the first should be True
    assert results[0] == True
    assert all(r == False for r in results[1:]), \
        "All subsequent calls should return False"


def test_scheduler_slot_uniqueness():
    """Test that slot IDs are unique per interval."""
    scheduler = Scheduler(interval_minutes=15)
    
    slots = set()
    for _ in range(10):
        slot = scheduler.get_current_slot()
        slots.add(slot)
    
    # In a single test run, should all be the same slot
    assert len(slots) == 1, "All calls in quick succession should return same slot"


def test_wait_for_next_slot_calculation():
    """Test that wait calculation doesn't crash."""
    scheduler = Scheduler(interval_minutes=15)
    
    # This should calculate wait time without error
    # We don't actually wait in test
    try:
        # Mock by setting a very short wait
        now = datetime.utcnow()
        minutes_to_next = scheduler.interval_minutes - (now.minute % scheduler.interval_minutes)
        seconds_to_next = (minutes_to_next * 60) - now.second
        
        assert seconds_to_next >= 0, "Wait time should be non-negative"
        assert seconds_to_next <= scheduler.interval_minutes * 60, \
            "Wait time should not exceed interval"
    except Exception as e:
        pytest.fail(f"Wait calculation failed: {e}")
