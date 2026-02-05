import pigpio
import time

servo_pin = 18  # GPIO18 (Pin 12) - VERIFIED WORKING

# Servo pulse width constants (in microseconds)
# Standard servo: 500µs = 0°, 1500µs = 90°, 2500µs = 180°
SERVO_MIN_PULSE = 500   # 0 degrees (was duty cycle 2 at 50Hz ≈ 400µs)
SERVO_MAX_PULSE = 2500  # 180 degrees (was duty cycle 12 at 50Hz = 2400µs)
SERVO_OFF = 0           # Turn off servo signal

# Initialize pigpio
pi = pigpio.pi()

if not pi.connected:
    raise RuntimeError("Failed to connect to pigpio daemon. Make sure pigpiod is running.")

def activate_servo(position=None):
    """
    Activate servo motor using pigpio hardware PWM.
    Feed is dispensed at BOTH positions (0° and 180°).
    position=0: move to 0° (dispense feed) - pulse width 500µs
    position=180: move to 180° (dispense feed) - pulse width 2500µs
    position=None: cycle between 0° and 180° (dispenses twice)
    """
    try:
        if position == 0:
            pi.set_servo_pulsewidth(servo_pin, SERVO_MIN_PULSE)  # 0 degrees
            print("Servo at 0° (feed dispensed)")
            time.sleep(0.3)  # Wait for feed to drop
        elif position == 180:
            pi.set_servo_pulsewidth(servo_pin, SERVO_MAX_PULSE)  # 180 degrees
            print("Servo at 180° (feed dispensed)")
            time.sleep(0.3)  # Wait for feed to drop
        else:
            # Default: cycle from 0° to 180° (dispenses at each position)
            pi.set_servo_pulsewidth(servo_pin, SERVO_MIN_PULSE)  # 0 degrees - dispense
            print("Servo at 0° (feed dispensed)")
            time.sleep(0.3)
            pi.set_servo_pulsewidth(servo_pin, SERVO_MAX_PULSE)  # 180 degrees - dispense
            print("Servo at 180° (feed dispensed)")
            time.sleep(0.3)
    except Exception as e:
        print(f"Servo error: {e}")

def set_servo_angle(angle):
    """
    Set servo to a specific angle (0-180 degrees).
    Uses linear interpolation between min and max pulse widths.
    """
    if angle < 0:
        angle = 0
    elif angle > 180:
        angle = 180
    
    # Linear interpolation: map angle (0-180) to pulse width (500-2500µs)
    pulse_width = SERVO_MIN_PULSE + (angle / 180.0) * (SERVO_MAX_PULSE - SERVO_MIN_PULSE)
    pi.set_servo_pulsewidth(servo_pin, int(pulse_width))
    print(f"Servo set to {angle}° (pulse width: {int(pulse_width)}µs)")

def stop_servo():
    """
    Stop sending PWM signal to servo (allows servo to be moved freely).
    """
    pi.set_servo_pulsewidth(servo_pin, SERVO_OFF)
    print("Servo signal stopped")

# Cleanup on exit
import atexit

def cleanup_servo():
    try:
        pi.set_servo_pulsewidth(servo_pin, SERVO_OFF)  # Stop servo signal
        pi.stop()  # Disconnect from pigpio daemon
    except:
        pass

atexit.register(cleanup_servo)
