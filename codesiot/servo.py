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
    position=0: move to 0° (fill cup) - duty cycle 2
    position=180: move to 180° (drop cup) - duty cycle 12
    position=None: cycle between 0° and 180°
    """
    try:
        if position == 0:
            pwm.ChangeDutyCycle(2)  # 0 degrees
            print("Servo at 0° (fill cup)")
            time.sleep(0.3)  # Reduced from 0.5 for faster response
        elif position == 180:
            pwm.ChangeDutyCycle(12)  # 180 degrees
            print("Servo at 180° (drop cup)")
            time.sleep(0.3)  # Reduced from 0.5 for faster response
        else:
            # Default: cycle from 0° to 180° and back to 0°
            pwm.ChangeDutyCycle(2)  # 0 degrees
            time.sleep(0.3)
            pwm.ChangeDutyCycle(12)  # 180 degrees
            time.sleep(0.3)
            pwm.ChangeDutyCycle(2)  # back to 0
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

