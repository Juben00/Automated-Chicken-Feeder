import pigpio
import time
import atexit

servo_pin = 18  # GPIO18 (Pin 12) - VERIFIED WORKING

# Servo pulse width constants (in microseconds)
# Standard servo: 500µs = 0°, 1500µs = 90°, 2500µs = 180°
SERVO_MIN_PULSE = 500   # 0 degrees
SERVO_MAX_PULSE = 2500  # 180 degrees
SERVO_OFF = 0           # Turn off servo signal

# Valve positions (adjust these angles to match your physical valve setup)
VALVE_CLOSED_ANGLE = 0    # Angle when valve is fully closed
VALVE_OPEN_ANGLE = 90     # Angle when valve is fully open

# Pre-compute pulse widths for valve positions
VALVE_CLOSED_PULSE = int(SERVO_MIN_PULSE + (VALVE_CLOSED_ANGLE / 180.0) * (SERVO_MAX_PULSE - SERVO_MIN_PULSE))
VALVE_OPEN_PULSE = int(SERVO_MIN_PULSE + (VALVE_OPEN_ANGLE / 180.0) * (SERVO_MAX_PULSE - SERVO_MIN_PULSE))

# Initialize pigpio
pi = pigpio.pi()

if not pi.connected:
    raise RuntimeError("Failed to connect to pigpio daemon. Make sure pigpiod is running.")

# Ensure valve starts in the closed position
pi.set_servo_pulsewidth(servo_pin, VALVE_CLOSED_PULSE)
time.sleep(0.5)
pi.set_servo_pulsewidth(servo_pin, SERVO_OFF)


def activate_servo(duration_seconds=5):
    """
    Valve-style dispensing: open the valve, hold for the given duration,
    then close it again.

    duration_seconds: how long to keep the valve open (controls how much
                      feed flows through).  Must be > 0.
    """
    if duration_seconds <= 0:
        print("Duration must be > 0. Skipping.")
        return

    try:
        # --- OPEN the valve ---
        pi.set_servo_pulsewidth(servo_pin, VALVE_OPEN_PULSE)
        print(f"Valve OPEN  ({VALVE_OPEN_ANGLE}°) — dispensing for {duration_seconds}s …")

        # Hold open for the requested duration
        time.sleep(duration_seconds)

        # --- CLOSE the valve ---
        pi.set_servo_pulsewidth(servo_pin, VALVE_CLOSED_PULSE)
        print(f"Valve CLOSED ({VALVE_CLOSED_ANGLE}°)")

        # Brief pause to let the servo reach the closed position, then
        # cut the signal so the servo isn't buzzing.
        time.sleep(0.5)
        pi.set_servo_pulsewidth(servo_pin, SERVO_OFF)

    except Exception as e:
        # On any error, try to close the valve for safety
        try:
            pi.set_servo_pulsewidth(servo_pin, VALVE_CLOSED_PULSE)
            time.sleep(0.3)
            pi.set_servo_pulsewidth(servo_pin, SERVO_OFF)
        except:
            pass
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

    pulse_width = SERVO_MIN_PULSE + (angle / 180.0) * (SERVO_MAX_PULSE - SERVO_MIN_PULSE)
    pi.set_servo_pulsewidth(servo_pin, int(pulse_width))
    print(f"Servo set to {angle}° (pulse width: {int(pulse_width)}µs)")


def stop_servo():
    """
    Stop sending PWM signal to servo (allows servo to be moved freely).
    """
    pi.set_servo_pulsewidth(servo_pin, SERVO_OFF)
    print("Servo signal stopped")


def cleanup_servo():
    """Ensure valve is closed and pigpio is disconnected on exit."""
    try:
        pi.set_servo_pulsewidth(servo_pin, VALVE_CLOSED_PULSE)
        time.sleep(0.3)
        pi.set_servo_pulsewidth(servo_pin, SERVO_OFF)
        pi.stop()
    except:
        pass

atexit.register(cleanup_servo)
