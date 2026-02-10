#!/usr/bin/env python3
"""
calibrate_hx711.py - Interactive HX711 Load Cell Calibration
=============================================================
Step-by-step interactive script to calibrate your HX711 load cell
for accurate gram measurements.

What you need:
    - A known weight object (e.g., a bag of rice, coins, or a calibration weight)
    - The exact weight of that object in grams

How it works:
    1. Takes a zero reading with nothing on the scale (tare)
    2. Takes a reading with your known weight on the scale
    3. Calculates the scale ratio (raw units per gram)
    4. Verifies accuracy by reading the known weight back
    5. Saves calibration to calibration.json for future use

Run:
    python3 calibrate_hx711.py

Wiring (HX711 -> Raspberry Pi 3):
    VCC  -> Pin 1  (3.3V)
    GND  -> Pin 9  (Ground)
    DT   -> Pin 29 (GPIO 5)
    SCK  -> Pin 31 (GPIO 6)
"""

import time
import sys
import os
import RPi.GPIO as GPIO

# Add the script directory to path so we can import load_cell
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load_cell import LoadCell, CALIBRATION_FILE


def print_header(text):
    """Print a formatted section header."""
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)
    print()


def print_step(step_num, text):
    """Print a formatted step indicator."""
    print(f"\n>>> STEP {step_num}: {text}")
    print("-" * 40)


def get_float_input(prompt, min_val=0.1, max_val=50000):
    """Get a validated float input from the user."""
    while True:
        try:
            value = float(input(prompt))
            if min_val <= value <= max_val:
                return value
            print(f"  Please enter a value between {min_val} and {max_val}")
        except ValueError:
            print("  Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\n\nCalibration cancelled.")
            sys.exit(0)


def main():
    print_header("HX711 LOAD CELL CALIBRATION")
    print("This script will calibrate your load cell for accurate")
    print("gram measurements. Follow each step carefully.")
    print()
    print("Pin Configuration:")
    print("  DT (Data)  -> GPIO 5  (Physical Pin 29)")
    print("  SCK (Clock) -> GPIO 6  (Physical Pin 31)")
    print("  VCC        -> 3.3V    (Physical Pin 1)")
    print("  GND        -> Ground  (Physical Pin 9)")

    # ─── Initialize ────────────────────────────────────────────
    print_step(1, "INITIALIZATION")
    print("Connecting to HX711...")

    try:
        lc = LoadCell()
    except Exception as e:
        print(f"\nERROR: {e}")
        print("\nTroubleshooting:")
        print("  1. Check all wiring connections")
        print("  2. Ensure HX711 has power (VCC and GND)")
        print("  3. Verify DT is on GPIO 5 (Pin 29) and SCK is on GPIO 6 (Pin 31)")
        print("  4. Try swapping the green (A+) and white (A-) load cell wires")
        sys.exit(1)

    print("HX711 connected successfully!\n")

    # ─── Warm-up readings ─────────────────────────────────────
    print_step(2, "WARM-UP")
    print("Taking a few warm-up readings to stabilize the ADC...")
    print("(This helps the HX711 settle after power-on)")
    print()

    for i in range(5):
        raw = lc.get_raw_value(readings=10)
        if raw is not None:
            print(f"  Warm-up {i+1}/5: {raw:.0f}")
        else:
            print(f"  Warm-up {i+1}/5: no data (retrying...)")
        time.sleep(0.3)

    print("\nWarm-up complete.")

    # ─── Tare (Zero) ──────────────────────────────────────────
    print_step(3, "TARE (ZERO THE SCALE)")
    print("Remove EVERYTHING from the load cell.")
    print("The load cell should be completely empty/unloaded.")
    print()
    input("Press Enter when the load cell is empty...")

    print("\nZeroing the scale (this takes a few seconds)...")
    success = lc.tare(readings=50)

    if not success:
        print("\nWARNING: Tare may not be accurate. Possible issues:")
        print("  - Load cell is not stable (vibrations, wind)")
        print("  - Wiring issue (check connections)")
        print("  - Try running this script again")
        resp = input("\nContinue anyway? (y/n): ").strip().lower()
        if resp != 'y':
            lc.cleanup()
            sys.exit(0)

    # Verify tare by reading a few values
    print("\nVerifying zero point...")
    tare_readings = []
    for i in range(5):
        raw = lc.get_raw_value(readings=20)
        if raw is not None:
            tare_readings.append(raw)
            print(f"  Zero check {i+1}: {raw:.0f}")
        time.sleep(0.3)

    if tare_readings:
        spread = max(tare_readings) - min(tare_readings)
        avg = sum(tare_readings) / len(tare_readings)
        print(f"\n  Average: {avg:.0f}")
        print(f"  Spread:  {spread:.0f} (lower is better)")
        if spread > abs(avg * 0.1) and avg != 0:
            print("  NOTE: Readings have some variation. This is normal for")
            print("        sensitive load cells. Averaging compensates for this.")

    print("\nTare complete!")

    # ─── Calibration Weight ───────────────────────────────────
    print_step(4, "PLACE CALIBRATION WEIGHT")
    print("You need an object with a KNOWN weight in grams.")
    print()
    print("Good calibration weights:")
    print("  - Kitchen scale verified weight")
    print("  - Coins (specific denominations have known weights)")
    print("  - Calibration weights (lab weights)")
    print("  - Any item with weight printed on packaging")
    print()

    known_weight = get_float_input("Enter the weight of your calibration object (grams): ")
    print(f"\nCalibration weight: {known_weight}g")
    print(f"Place the {known_weight}g object on the load cell now.")
    print("Center it on the load cell for best accuracy.")
    print()
    input("Press Enter when the weight is placed and stable...")

    # Wait a moment for the load cell to settle
    print("\nWaiting for load cell to settle...")
    time.sleep(2)

    # ─── Calculate Scale Ratio ────────────────────────────────
    print_step(5, "CALCULATING CALIBRATION FACTOR")
    print(f"Taking readings with {known_weight}g on the scale...")

    ratio = lc.calibrate(known_weight, readings=80)

    if ratio is None:
        print("\nERROR: Calibration failed.")
        print("Possible causes:")
        print("  1. Weight not properly on the load cell")
        print("  2. Wiring issue (especially A+/A- connections)")
        print("  3. Load cell may be damaged")
        print("  4. Try swapping the green and white wires on the HX711")
        lc.cleanup()
        sys.exit(1)

    # ─── Verify Calibration ───────────────────────────────────
    print_step(6, "VERIFICATION")
    print(f"Reading back the {known_weight}g weight to verify accuracy...\n")

    errors = []
    for i in range(10):
        weight = lc.get_weight(readings=30)
        if weight is not None:
            error = abs(weight - known_weight)
            error_pct = (error / known_weight) * 100
            errors.append(error)
            status = "OK" if error_pct < 2 else "WARN" if error_pct < 5 else "BAD"
            print(f"  Reading {i+1:2d}: {weight:8.1f}g  "
                  f"(error: {error:.1f}g / {error_pct:.1f}%)  [{status}]")
        else:
            print(f"  Reading {i+1:2d}: failed to read")
        time.sleep(0.3)

    if errors:
        avg_error = sum(errors) / len(errors)
        max_error = max(errors)
        avg_error_pct = (avg_error / known_weight) * 100
        max_error_pct = (max_error / known_weight) * 100

        print(f"\n  --- Verification Summary ---")
        print(f"  Average error: {avg_error:.2f}g ({avg_error_pct:.1f}%)")
        print(f"  Max error:     {max_error:.2f}g ({max_error_pct:.1f}%)")

        if avg_error_pct < 1:
            print(f"  Rating:        EXCELLENT - Very accurate!")
        elif avg_error_pct < 2:
            print(f"  Rating:        GOOD - Suitable for feed dispensing")
        elif avg_error_pct < 5:
            print(f"  Rating:        FAIR - Acceptable for most uses")
        else:
            print(f"  Rating:        POOR - Consider recalibrating")
            print(f"  Tips: Use a heavier calibration weight, check wiring,")
            print(f"        or try a different gain setting.")

    # ─── Save Calibration ─────────────────────────────────────
    print_step(7, "SAVE CALIBRATION")

    save = input(f"Save calibration to {CALIBRATION_FILE}? (y/n): ").strip().lower()
    if save == 'y':
        lc.save_calibration()
        print("\nCalibration saved! The load_cell module will auto-load it.")
    else:
        print(f"\nCalibration NOT saved.")
        print(f"  Scale ratio: {ratio:.2f}")
        print(f"  You can manually set this later with:")
        print(f"    lc.set_scale_ratio({ratio:.2f})")

    # ─── Additional Test ──────────────────────────────────────
    print_step(8, "ADDITIONAL TESTING (Optional)")
    print("You can now test with different objects.")
    print("Press Ctrl+C to exit.\n")

    input("Remove the calibration weight, then press Enter to tare...")
    lc.tare(readings=30)
    print()

    try:
        while True:
            input("Place an object on the scale and press Enter...")
            time.sleep(1)  # Let it settle

            print("Reading weight (stabilizing)...")
            stable_weight = lc.get_stable_weight(
                target_readings=5,
                stability_threshold=1.0,
                timeout=8
            )
            if stable_weight is not None:
                print(f"\n  >>> Weight: {stable_weight:.1f} grams <<<\n")
            else:
                # Fall back to regular reading
                weight = lc.get_weight(readings=40)
                if weight is not None:
                    print(f"\n  >>> Weight: {weight:.1f} grams <<<\n")
                else:
                    print("\n  Could not read weight.\n")
    except KeyboardInterrupt:
        print("\n\nCalibration session complete!")

    lc.cleanup()
    print("Done. GPIO cleaned up.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCalibration cancelled by user.")
        GPIO.cleanup()
    except Exception as e:
        print(f"\nFatal error: {e}")
        GPIO.cleanup()
        sys.exit(1)
