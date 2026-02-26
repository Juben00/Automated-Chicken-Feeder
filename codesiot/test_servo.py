#!/usr/bin/env python3
"""
Continuous sweep test for the valve servo using pigpio.

This will move the servo smoothly from 0° to 180° and back to 0°
in an infinite loop so you can visually check the full travel range.

Usage:
    python test_servo.py [step_degrees] [delay_seconds]

    step_degrees  - how many degrees to move per step (default: 5)
    delay_seconds - delay between steps in seconds (default: 0.05)
"""

import sys
import time

from servo import set_servo_angle, stop_servo


def parse_args():
    step_deg = 5
    delay = 0.05

    if len(sys.argv) > 1:
        try:
            step_deg = max(1, int(sys.argv[1]))
        except ValueError:
            print(f"Invalid step_degrees '{sys.argv[1]}', using default {step_deg}°")

    if len(sys.argv) > 2:
        try:
            delay = max(0.01, float(sys.argv[2]))
        except ValueError:
            print(f"Invalid delay_seconds '{sys.argv[2]}', using default {delay}s")

    return step_deg, delay


def continuous_sweep(step_deg: int, delay: float) -> None:
    print("=== Continuous Servo Sweep Test ===")
    print(f"  Sweep range : 0° ↔ 180°")
    print(f"  Step size   : {step_deg}°")
    print(f"  Step delay  : {delay}s")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            # 0° -> 180°
            for angle in range(0, 181, step_deg):
                set_servo_angle(angle)
                time.sleep(delay)

            # 180° -> 0°
            for angle in range(180, -1, -step_deg):
                set_servo_angle(angle)
                time.sleep(delay)
    except KeyboardInterrupt:
        print("\nStopping sweep…")
    finally:
        # Stop PWM so the servo isn't held under tension
        stop_servo()
        print("Servo stopped. Goodbye.")


if __name__ == "__main__":
    step, delay = parse_args()
    continuous_sweep(step, delay)
