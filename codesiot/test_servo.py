#!/usr/bin/env python3
"""
Simple servo test on Raspberry Pi using RPi.GPIO PWM.
Run this to manually test the servo motor.
"""

import RPi.GPIO as GPIO
import time

servo_pin = 18  # GPIO18 (Pin 12) - VERIFIED WORKING

print("Testing servo on GPIO18...")
GPIO.setmode(GPIO.BCM)
GPIO.setup(servo_pin, GPIO.OUT)
pwm = GPIO.PWM(servo_pin, 50)  # 50Hz
pwm.start(0)

try:
    print("\nMoving to 0° (min)...")
    pwm.ChangeDutyCycle(2)
    time.sleep(1)

    print("Moving to 180° (max)...")
    pwm.ChangeDutyCycle(12)
    time.sleep(1)

    print("Back to 0° (min)...")
    pwm.ChangeDutyCycle(2)
    time.sleep(1)

    print("Servo test complete!")
finally:
    pwm.stop()
    GPIO.cleanup()
