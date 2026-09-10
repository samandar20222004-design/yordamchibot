#!/usr/bin/env python3
"""Test callback query throttling middleware - in-memory dict test."""

import os
import sys
import time
from pathlib import Path

passed = 0
failures = 0

# In-memory throttle state (same as in handlers/new_post.py)
_callback_last_call = {}


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def check_callback_throttle(user_id, min_interval=1.5):
    """Same logic as in handlers/new_post.py"""
    now = time.time()
    last_time = _callback_last_call.get(user_id, 0)
    elapsed = now - last_time
    
    if elapsed < min_interval:
        return True  # throttled
    _callback_last_call[user_id] = now
    return False  # not throttled


def test_throttle_basic():
    """Test basic throttle functionality."""
    print("== Basic throttle test ==")
    
    uid = 12345
    
    # First call should not be throttled
    result1 = check_callback_throttle(uid)
    check("First call not throttled", result1 == False)
    
    # Second call within 1.5s should be throttled
    result2 = check_callback_throttle(uid)
    check("Second call within interval throttled", result2 == True)
    
    # Third call after interval should not be throttled
    time.sleep(2)  # Wait more than 1.5s
    result3 = check_callback_throttle(uid)
    check("Call after interval not throttled", result3 == False)


def test_throttle_different_users():
    """Test that throttle is per-user."""
    print("\n== Per-user throttle test ==")
    
    # User 1
    r1 = check_callback_throttle(11111)
    check("User 1 first call not throttled", r1 == False)
    
    # User 2 should be independent
    r2 = check_callback_throttle(22222)
    check("User 2 first call not throttled", r2 == False)
    
    # User 1 again - should still be throttled if within interval
    r1b = check_callback_throttle(11111)
    check("User 1 second call throttled", r1b == True)


def test_throttle_reset():
    """Test that throttle timer resets properly."""
    print("\n== Throttle reset test ==")
    
    uid = 55555
    
    # Make a call
    check_callback_throttle(uid)
    
    # Immediately another call - should be throttled
    immediate = check_callback_throttle(uid)
    check("Immediate second call throttled", immediate == True)
    
    # Wait for reset (1.5s + a bit)
    time.sleep(2)
    
    # Now it should not be throttled
    after_wait = check_callback_throttle(uid)
    check("After wait, not throttled", after_wait == False)


# Run tests
test_throttle_basic()
test_throttle_different_users()
test_throttle_reset()

print(f"\n\n=== Results: {passed} passed, {failures} failed ===")
