import pigpio
import time
import math

servo_pin = 18  # GPIO18 (Pin 12) - VERIFIED WORKING

# Servo pulse width constants (in microseconds)
# Standard servo: 500µs = 0°, 1500µs = 90°, 2500µs = 180°
SERVO_MIN_PULSE = 500   # 0 degrees (was duty cycle 2 at 50Hz ≈ 400µs)
SERVO_MAX_PULSE = 2500  # 180 degrees (was duty cycle 12 at 50Hz = 2400µs)
SERVO_OFF = 0           # Turn off servo signal

# Speed control settings
SERVO_STEP_SIZE = 5     # Degrees per step (36 steps per full rotation)
SERVO_STEP_DELAY = 0.012 # Base seconds between steps (~0.43s per full rotation)

# Initialize pigpio
pi = pigpio.pi()

if not pi.connected:
    raise RuntimeError("Failed to connect to pigpio daemon. Make sure pigpiod is running.")

def slow_move_servo(from_angle, to_angle, step_size=None, step_delay=None):
    """
    Move the servo with ease-in/ease-out motion.
    Starts gentle (protects the 3D printed rod), speeds up in the middle
    (prevents feed from getting stuck), and slows down at the end (gentle stop).
    from_angle: starting angle (0-180)
    to_angle: target angle (0-180)
    step_size: degrees per step (default: SERVO_STEP_SIZE)
    step_delay: base seconds between steps (default: SERVO_STEP_DELAY)
    """
    if step_size is None:
        step_size = SERVO_STEP_SIZE
    if step_delay is None:
        step_delay = SERVO_STEP_DELAY

    # Determine direction
    if from_angle < to_angle:
        angles = list(range(from_angle, to_angle + 1, step_size))
    else:
        angles = list(range(from_angle, to_angle - 1, -step_size))

    total_steps = len(angles)
    for i, angle in enumerate(angles):
        pulse_width = SERVO_MIN_PULSE + (angle / 180.0) * (SERVO_MAX_PULSE - SERVO_MIN_PULSE)
        pi.set_servo_pulsewidth(servo_pin, int(pulse_width))

        # Ease-in/ease-out: slower at start and end, faster in the middle
        # progress goes from 0.0 to 1.0 across the movement
        if total_steps > 1:
            progress = i / (total_steps - 1)
        else:
            progress = 1.0
        # Sine-based easing: delay is highest at edges, lowest at center
        ease_factor = 1.0 + 1.5 * (1.0 - math.sin(math.pi * progress))
        # ease_factor ranges from ~1.0 (middle) to ~2.5 (start/end)
        time.sleep(step_delay * ease_factor)

    # Ensure we land exactly on the target angle
    final_pulse = SERVO_MIN_PULSE + (to_angle / 180.0) * (SERVO_MAX_PULSE - SERVO_MIN_PULSE)
    pi.set_servo_pulsewidth(servo_pin, int(final_pulse))
    print(f"Servo moved from {from_angle}° to {to_angle}° (eased)")


def activate_servo(position=None):
    """
    Activate servo motor using pigpio hardware PWM with slow rotation.
    Feed is dispensed at BOTH positions (0° and 180°).
    position=0: move to 0° (dispense feed) - pulse width 500µs
    position=180: move to 180° (dispense feed) - pulse width 2500µs
    position=None: cycle between 0° and 180° (dispenses twice)
    """
    try:
        if position == 0:
            slow_move_servo(180, 0)
            print("Servo at 0° (feed dispensed)")
            time.sleep(2)  # Wait for feed to drop
        elif position == 180:
            slow_move_servo(0, 180)
            print("Servo at 180° (feed dispensed)")
            time.sleep(2)  # Wait for feed to drop
        else:
            # Default: cycle from 0° to 180° (dispenses at each position)
            slow_move_servo(180, 0)
            print("Servo at 0° (feed dispensed)")
            time.sleep(2)
            slow_move_servo(0, 180)
            print("Servo at 180° (feed dispensed)")
            time.sleep(2)
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
