import RPi.GPIO as GPIO
import time

servo_pin = 18  # GPIO18 (Pin 12) - VERIFIED WORKING

GPIO.setmode(GPIO.BCM)
GPIO.setup(servo_pin, GPIO.OUT)
pwm = GPIO.PWM(servo_pin, 50)  # 50Hz
pwm.start(0)

def activate_servo(position=None):
    """
    Activate servo motor using RPi.GPIO PWM.
    Feed is dispensed at BOTH positions (0° and 180°).
    position=0: move to 0° (dispense feed) - duty cycle 2
    position=180: move to 180° (dispense feed) - duty cycle 12
    position=None: cycle between 0° and 180° (dispenses twice)
    """
    try:
        if position == 0:
            pwm.ChangeDutyCycle(2)  # 0 degrees
            print("Servo at 0° (feed dispensed)")
            time.sleep(0.3)  # Wait for feed to drop
        elif position == 180:
            pwm.ChangeDutyCycle(12)  # 180 degrees
            print("Servo at 180° (feed dispensed)")
            time.sleep(0.3)  # Wait for feed to drop
        else:
            # Default: cycle from 0° to 180° (dispenses at each position)
            pwm.ChangeDutyCycle(2)  # 0 degrees - dispense
            print("Servo at 0° (feed dispensed)")
            time.sleep(0.3)
            pwm.ChangeDutyCycle(12)  # 180 degrees - dispense
            print("Servo at 180° (feed dispensed)")
            time.sleep(0.3)
    except Exception as e:
        print(f"Servo error: {e}")

# Cleanup on exit
import atexit
def cleanup_servo():
    try:
        pwm.stop()
        GPIO.cleanup()
    except:
        pass

atexit.register(cleanup_servo)

