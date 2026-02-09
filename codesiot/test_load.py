import time
import sys

try:
    from hx711 import HX711
except ImportError:
    print("ERROR: hx711 module not found.")
    print("Install it with: sudo python3 -m pip install hx711")
    sys.exit(1)

# ─── Configuration ────────────────────────────────────────────────
# REFERENCE_UNIT converts raw values to grams.
# To find yours: place a known weight, note the raw average,
# then: REFERENCE_UNIT = raw_average / known_weight_in_grams
# Example: if 500g reads as 420000 raw, then REFERENCE_UNIT = 840.0
REFERENCE_UNIT = 1.0  # <-- UPDATE THIS after calibration

hx = HX711(dout_pin=5, pd_sck_pin=6, channel='A', gain=64)
hx.reset()

# ─── Tare (zero the scale) ───────────────────────────────────────
print("Taring... keep the scale EMPTY.")
time.sleep(2)

tare_readings = hx.get_raw_data(times=15)
if not tare_readings:
    print("ERROR: Could not read from HX711. Check wiring!")
    sys.exit(1)

OFFSET = sum(tare_readings) / len(tare_readings)
print(f"Tare complete. Offset = {OFFSET:.0f}")

# ─── Continuous weight reading ────────────────────────────────────
print("\nReady to measure weight... Press Ctrl+C to stop.\n")

try:
    while True:
        raw_data = hx.get_raw_data(times=5)
        if raw_data:
            raw_avg = sum(raw_data) / len(raw_data)
            weight_g = (raw_avg - OFFSET) / REFERENCE_UNIT
            print(f"Weight: {weight_g:>8.1f} g  |  {weight_g / 1000:>6.3f} kg  |  raw: {raw_avg:.0f}")
        else:
            print("No data - check wiring!")
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)