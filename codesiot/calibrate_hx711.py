#!/usr/bin/env python3
"""
calibrate_hx711.py - Interactive HX711 Load Cell Calibration
=============================================================
Step-by-step calibration with multi-pass averaging and heavy
noise filtering for accurate gram measurements.

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
import statistics
import RPi.GPIO as GPIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load_cell import LoadCell, CALIBRATION_FILE


def print_header(text):
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)
    print()


def print_step(step_num, text):
    print(f"\n>>> STEP {step_num}: {text}")
    print("-" * 40)


def get_float_input(prompt, min_val=0.1, max_val=50000):
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
    print_header("HX711 LOAD CELL CALIBRATION (Enhanced)")
    print("This script uses aggressive noise filtering and multi-pass")
    print("calibration for the best possible accuracy.")
    print()
    print("Pin Configuration:")
    print("  DT (Data)   -> GPIO 5  (Physical Pin 29)")
    print("  SCK (Clock) -> GPIO 6  (Physical Pin 31)")
    print("  VCC         -> 3.3V    (Physical Pin 1)")
    print("  GND         -> Ground  (Physical Pin 9)")

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

    # ─── Warm-up ──────────────────────────────────────────────
    print_step(2, "WARM-UP")
    print("Taking warm-up readings to stabilize the ADC...")
    print("(The HX711 needs 10-20 readings to settle after power-on)\n")

    for i in range(5):
        raw = lc.read_raw_no_offset(num_samples=20)
        if raw is not None:
            print(f"  Warm-up {i+1}/5: {raw:.0f}")
        else:
            print(f"  Warm-up {i+1}/5: no data")
        time.sleep(0.3)

    print("\nWarm-up complete.")

    # ─── Tare ─────────────────────────────────────────────────
    print_step(3, "TARE (ZERO THE SCALE)")
    print("Remove EVERYTHING from the load cell.")
    print("The load cell should be completely empty/unloaded.")
    print()
    input("Press Enter when the load cell is empty...")

    print("\nZeroing the scale (heavy filtering, takes a few seconds)...")
    tare_val = lc.tare(num_samples=100)

    if tare_val is None:
        print("\nWARNING: Tare failed. Check wiring.")
        resp = input("Continue anyway? (y/n): ").strip().lower()
        if resp != 'y':
            lc.cleanup()
            sys.exit(0)

    # Verify zero
    print("\nVerifying zero point (5 filtered readings)...")
    zero_readings = []
    for i in range(5):
        val = lc.get_raw_value(num_samples=50)
        if val is not None:
            zero_readings.append(val)
            print(f"  Zero check {i+1}: {val:.0f}")
        time.sleep(0.3)

    if zero_readings:
        spread = max(zero_readings) - min(zero_readings)
        avg = statistics.mean(zero_readings)
        print(f"\n  Average: {avg:.0f} (should be near 0)")
        print(f"  Spread:  {spread:.0f}")

    print("\nTare complete!")

    # ─── Calibration Weight ───────────────────────────────────
    print_step(4, "PLACE CALIBRATION WEIGHT")
    print("You need an object with a KNOWN weight in grams.")
    print()
    print("TIPS FOR BEST RESULTS:")
    print("  - Use the HEAVIEST object you can (heavier = more accurate)")
    print("  - Verify its weight on a kitchen scale first")
    print("  - A full water bottle (500g) or bag of rice works great")
    print("  - Center it on the load cell")
    print("  - Place it gently and wait for it to settle")
    print()

    known_weight = get_float_input("Enter the weight of your calibration object (grams): ")
    print(f"\nCalibration weight: {known_weight}g")
    print(f"Place the {known_weight}g object on the load cell now.")
    print()
    input("Press Enter when the weight is placed and stable...")

    print("\nWaiting 3 seconds for load cell to settle...")
    time.sleep(3)

    # ─── Multi-pass Calibration ───────────────────────────────
    print_step(5, "CALCULATING CALIBRATION FACTOR (Multi-pass)")
    print(f"Running 5 calibration passes with 80 samples each...\n")

    ref_unit = lc.calibrate(known_weight, num_passes=5, samples_per_pass=80)

    if ref_unit is None:
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
    print(f"Reading back the {known_weight}g weight to verify accuracy...")
    print("(Each reading uses full filtering pipeline)\n")

    errors = []
    weights = []
    for i in range(10):
        weight = lc.get_weight(num_samples=50)
        if weight is not None:
            weights.append(weight)
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
        avg_error = statistics.mean(errors)
        max_error = max(errors)
        avg_error_pct = (avg_error / known_weight) * 100

        if weights:
            reading_std = statistics.stdev(weights) if len(weights) > 1 else 0
        else:
            reading_std = 0

        print(f"\n  --- Verification Summary ---")
        print(f"  Average error:    {avg_error:.2f}g ({avg_error_pct:.1f}%)")
        print(f"  Max error:        {max_error:.2f}g")
        print(f"  Reading std dev:  {reading_std:.2f}g")

        if avg_error_pct < 1:
            print(f"  Rating:           EXCELLENT")
        elif avg_error_pct < 2:
            print(f"  Rating:           GOOD - Suitable for feed dispensing")
        elif avg_error_pct < 5:
            print(f"  Rating:           FAIR - Acceptable for most uses")
        else:
            print(f"  Rating:           POOR - See tips below")
            print()
            print("  TIPS TO IMPROVE ACCURACY:")
            print("  Hardware:")
            print("    - Mount load cell firmly on both ends (screws, not tape)")
            print("    - Keep HX711 away from the servo motor")
            print("    - Use short wires between load cell and HX711")
            print("    - Make sure all connections are tight (no loose jumpers)")
            print("    - Check if RATE pin on HX711 is LOW (10 SPS = less noise)")
            print("  Software:")
            print("    - Calibrate with a heavier object (more signal vs noise)")
            print("    - Re-run this script to try again")

    # ─── Save ─────────────────────────────────────────────────
    print_step(7, "SAVE CALIBRATION")

    save = input(f"Save calibration to {CALIBRATION_FILE}? (y/n): ").strip().lower()
    if save == 'y':
        lc.save_calibration()
        print("\nCalibration saved! The load_cell module will auto-load it.")
    else:
        print(f"\nCalibration NOT saved.")
        print(f"  Reference unit: {ref_unit:.2f}")
        print(f"  Set manually later: lc.set_reference_unit({ref_unit:.2f})")

    # ─── Free Testing ─────────────────────────────────────────
    print_step(8, "FREE TESTING (Optional)")
    print("Test with different objects. Press Ctrl+C to exit.\n")

    input("Remove the calibration weight, press Enter to tare...")
    lc.tare(num_samples=80)
    print()

    try:
        while True:
            input("Place an object and press Enter...")
            time.sleep(2)  # Let it settle

            print("Reading weight (stabilizing)...")
            stable = lc.get_stable_weight(
                num_passes=5,
                stability_threshold=2.0,
                timeout=12
            )
            if stable is not None:
                print(f"\n  >>> Weight: {stable:.1f} grams <<<\n")
            else:
                w = lc.get_weight(num_samples=60)
                if w is not None:
                    print(f"\n  >>> Weight: {w:.1f} grams <<<\n")
                else:
                    print("\n  Could not read weight.\n")
    except KeyboardInterrupt:
        print("\n\nCalibration session complete!")

    lc.cleanup()
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCalibration cancelled by user.")
        GPIO.cleanup()
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        GPIO.cleanup()
        sys.exit(1)
