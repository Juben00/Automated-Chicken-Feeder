#!/usr/bin/env python3
"""
Simple valve servo test on Raspberry Pi using pigpio.
Run this to manually test the valve: opens for 5 seconds then closes.
Usage: python test_servo.py [duration_seconds]
"""

import sys
import time

# Import the valve function from the main servo module
from servo import activate_servo, VALVE_OPEN_ANGLE, VALVE_CLOSED_ANGLE

duration = 5  # default test duration
if len(sys.argv) > 1:
    try:
        duration = float(sys.argv[1])
    except ValueError:
        print(f"Invalid duration '{sys.argv[1]}', using default {duration}s")

print(f"=== Valve Servo Test ===")
print(f"  Closed angle : {VALVE_CLOSED_ANGLE}°")
print(f"  Open angle   : {VALVE_OPEN_ANGLE}°")
print(f"  Test duration: {duration}s")
print()

activate_servo(duration_seconds=duration)

print(f"\nValve test complete! Valve was open for {duration}s.")
