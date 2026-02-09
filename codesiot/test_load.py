import time
import sys
import json
import os
import statistics

try:
    from hx711 import HX711
except ImportError:
    print("ERROR: hx711 module not found.")
    print("Install it with: sudo python3 -m pip install hx711")
    sys.exit(1)

# ─── Settings ─────────────────────────────────────────────────────
MAX_CAPACITY_G = 5000          # 5 kg load cell
CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), "calibration.json")
ROLLING_WINDOW = 10            # number of past readings to smooth over


def read_median(hx, times=15):
    """
    Read multiple samples from HX711, discard outliers, return median.
    Median is far more resistant to noise spikes than a simple average.
    """
    raw = hx.get_raw_data(times=times)
    valid = [v for v in raw if v is not None and v is not False]
    if len(valid) < 3:
        return None

    # Sort and trim the top/bottom 20% to remove spikes
    valid.sort()
    trim = max(1, len(valid) // 5)
    trimmed = valid[trim:-trim]

    if not trimmed:
        return None
    return statistics.median(trimmed)


def save_calibration(offset, ref_unit):
    """Save calibration values to file so you only calibrate once."""
    with open(CALIBRATION_FILE, "w") as f:
        json.dump({"offset": offset, "reference_unit": ref_unit}, f)
    print(f"  Calibration saved to {CALIBRATION_FILE}")


def load_calibration():
    """Load previously saved calibration values."""
    if os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE, "r") as f:
            data = json.load(f)
        return data.get("offset", 0), data.get("reference_unit", 1.0)
    return None, None


def calibrate(hx):
    """Interactive calibration for the 5 kg load cell."""
    print("\n" + "=" * 50)
    print("  LOAD CELL CALIBRATION (5 kg capacity)")
    print("=" * 50)

    # Step 1 - Tare
    print("\n  Step 1: Remove everything from the scale.")
    input("  Press Enter when the scale is EMPTY...")
    print("  Reading empty scale (this takes a few seconds)...")
    time.sleep(2)

    # Take many samples for a stable tare
    samples = []
    for _ in range(5):
        val = read_median(hx, times=20)
        if val is not None:
            samples.append(val)
        time.sleep(0.2)

    if not samples:
        print("  ERROR: No readings. Check wiring!")
        sys.exit(1)

    offset = statistics.median(samples)
    print(f"  Zero offset = {offset:.0f}")

    # Step 2 - Place known weight
    print("\n  Step 2: Place a KNOWN weight on the scale.")
    print("  (Use something you know the exact weight of, e.g. 500g, 1kg)")
    input("  Press Enter when the weight is on the scale...")
    print("  Reading (this takes a few seconds)...")
    time.sleep(2)

    samples = []
    for _ in range(5):
        val = read_median(hx, times=20)
        if val is not None:
            samples.append(val)
        time.sleep(0.2)

    if not samples:
        print("  ERROR: No readings. Check wiring!")
        sys.exit(1)

    raw_with_weight = statistics.median(samples)

    # Step 3 - Enter the known weight
    try:
        known_g = float(input("\n  Step 3: Enter the weight in grams (e.g. 500): "))
    except ValueError:
        print("  Invalid number. Calibration aborted.")
        sys.exit(1)

    if known_g <= 0 or known_g > MAX_CAPACITY_G:
        print(f"  Weight must be between 1 and {MAX_CAPACITY_G} g. Aborted.")
        sys.exit(1)

    ref_unit = (raw_with_weight - offset) / known_g

    if ref_unit == 0:
        print("  ERROR: Reference unit is zero -- readings didn't change.")
        print("  Check that the load cell is wired correctly.")
        sys.exit(1)

    print(f"\n  Calibration complete!")
    print(f"    Zero offset:    {offset:.0f}")
    print(f"    Raw with weight:{raw_with_weight:.0f}")
    print(f"    Reference unit: {ref_unit:.4f}")
    print("=" * 50)

    save_calibration(offset, ref_unit)
    return offset, ref_unit


# ─── Initialize HX711 ────────────────────────────────────────────
# gain=128 gives the best signal-to-noise ratio on channel A
hx = HX711(dout_pin=5, pd_sck_pin=6, channel='A', gain=128)
hx.reset()
time.sleep(1)  # let the HX711 settle after reset
print("HX711 initialized (5 kg load cell)\n")

# ─── Load or run calibration ─────────────────────────────────────
offset, ref_unit = load_calibration()

if offset is not None and ref_unit is not None:
    print(f"Loaded saved calibration (offset={offset:.0f}, ref={ref_unit:.4f})")
    recal = input("Recalibrate? (y/N): ").strip().lower()
    if recal == "y":
        offset, ref_unit = calibrate(hx)
else:
    print("No calibration found -- starting calibration.")
    offset, ref_unit = calibrate(hx)

# ─── Continuous weight reading with rolling average ───────────────
print("\nReading weight... Press Ctrl+C to stop.\n")
print(f"  {'Time':<10}  {'Weight':>10}  {'Status'}")
print("  " + "-" * 40)

history = []  # rolling window of recent weight readings

try:
    while True:
        raw_val = read_median(hx, times=15)
        timestamp = time.strftime("%H:%M:%S")

        if raw_val is None:
            print(f"  {timestamp:<10}  {'---':>10}  NO DATA")
            time.sleep(1)
            continue

        weight_g = (raw_val - offset) / ref_unit

        # Add to rolling history
        history.append(weight_g)
        if len(history) > ROLLING_WINDOW:
            history.pop(0)

        # Smoothed weight = median of recent readings
        smooth_g = statistics.median(history)

        # Clamp small noise around zero
        if abs(smooth_g) < 5:
            smooth_g = 0.0

        # Status
        if smooth_g < -5:
            status = "CHECK TARE"
        elif smooth_g > MAX_CAPACITY_G:
            status = "OVERLOAD!"
        elif smooth_g < 1:
            status = "EMPTY"
        else:
            status = "OK"

        if smooth_g >= 1000:
            print(f"  {timestamp:<10}  {smooth_g / 1000:>7.2f} kg  {status}")
        else:
            print(f"  {timestamp:<10}  {smooth_g:>7.1f}  g  {status}")

        time.sleep(0.5)

except KeyboardInterrupt:
    print("\n\nExiting...")
    sys.exit(0)