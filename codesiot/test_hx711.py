#!/usr/bin/env python3
"""
HX711 Load Cell Real-Time Weight Tracker
=========================================
Continuously reads weight from an HX711 load cell amplifier
and prints the value in real-time to the terminal.

Uses the 'hx711' pip package (same as test_load.py).

Wiring (HX711 -> Raspberry Pi):
    VCC  -> 3.3V (Pin 1)
    GND  -> GND  (Pin 30)
    DT   -> GPIO 5  (Pin 29)  [Data]
    SCK  -> GPIO 6  (Pin 31)  [Clock]

Install:
    sudo python3 -m pip install hx711

Usage:
    sudo python3 test_hx711.py
    sudo python3 test_hx711.py --tare
    sudo python3 test_hx711.py --calibrate
    sudo python3 test_hx711.py --ref 420.5 --tare
"""

import time
import sys
import signal

try:
    from hx711 import HX711
except ImportError:
    print("ERROR: hx711 module not found.")
    print("Install it with: sudo python3 -m pip install hx711")
    sys.exit(1)

# ─── GPIO Pin Defaults ───────────────────────────────────────────────
DT_PIN  = 5    # HX711 Data pin  (GPIO 5 / Pin 29)
SCK_PIN = 6    # HX711 Clock pin (GPIO 6 / Pin 31)


def tare(hx, samples=15):
    """Tare the scale - sets current reading as zero."""
    print("\n  Taring... keep the scale EMPTY.")
    time.sleep(2)
    readings = []
    for _ in range(samples):
        val = hx.get_raw_data_mean(readings=3)
        if val is not None and val is not False:
            readings.append(val)
        time.sleep(0.05)

    if not readings:
        print("  ERROR: Could not get tare readings. Check wiring!")
        return 0

    offset = sum(readings) / len(readings)
    print(f"  Tare complete. Offset = {offset:.0f}")
    return offset


def calibrate(hx):
    """
    Interactive calibration routine.
    Returns (offset, reference_unit).
    """
    print("\n" + "=" * 50)
    print("  CALIBRATION MODE")
    print("=" * 50)

    # Step 1: Tare
    print("\n  Step 1: Make sure the scale is EMPTY.")
    input("  Press Enter when ready...")
    offset = tare(hx)

    # Step 2: Place known weight
    print("\n  Step 2: Place a KNOWN weight on the scale.")
    input("  Press Enter when ready...")

    readings = []
    for _ in range(20):
        val = hx.get_raw_data_mean(readings=3)
        if val is not None and val is not False:
            readings.append(val)
        time.sleep(0.05)

    if not readings:
        print("  ERROR: Could not get readings. Check wiring!")
        return offset, 1.0

    raw_avg = sum(readings) / len(readings)
    adjusted = raw_avg - offset

    # Step 3: Enter known weight
    try:
        known_weight = float(input("\n  Step 3: Enter the known weight in grams: "))
    except ValueError:
        print("  Invalid input. Calibration aborted.")
        return offset, 1.0

    if known_weight <= 0:
        print("  Invalid weight. Calibration aborted.")
        return offset, 1.0

    reference_unit = adjusted / known_weight

    print(f"\n  Calibration complete!")
    print(f"    Raw average:    {raw_avg:.0f}")
    print(f"    Offset:         {offset:.0f}")
    print(f"    Adjusted:       {adjusted:.0f}")
    print(f"    Reference unit: {reference_unit:.2f}")
    print(f"\n  Next time, run with: --ref {reference_unit:.2f} --tare")
    print("=" * 50)

    return offset, reference_unit


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="HX711 Load Cell Real-Time Weight Tracker"
    )
    parser.add_argument("--ref", type=float, default=1.0,
                        help="Reference unit for calibration (default: 1.0 = raw values)")
    parser.add_argument("--samples", type=int, default=5,
                        help="Number of samples to average per reading (default: 5)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Seconds between readings (default: 0.5)")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run interactive calibration before tracking")
    parser.add_argument("--tare", action="store_true",
                        help="Tare (zero) the scale on startup")
    args = parser.parse_args()

    # ─── Initialize HX711 ────────────────────────────────────────────
    print("=" * 55)
    print("  HX711 Load Cell - Real-Time Weight Tracker")
    print("=" * 55)
    print(f"  Data pin (DT):   GPIO {DT_PIN}")
    print(f"  Clock pin (SCK): GPIO {SCK_PIN}")
    print(f"  Samples/reading: {args.samples}")
    print(f"  Read interval:   {args.interval}s")
    print(f"  Reference unit:  {args.ref}")
    print("=" * 55)

    try:
        hx = HX711(dout_pin=DT_PIN, sck_pin=SCK_PIN)
        hx.reset()
        print("\n  HX711 initialized successfully!")
    except Exception as e:
        print(f"\n  ERROR initializing HX711: {e}")
        print("  Check your wiring and make sure you're running with sudo.")
        sys.exit(1)

    # ─── Calibration / Tare ──────────────────────────────────────────
    offset = 0
    reference_unit = args.ref

    if args.calibrate:
        offset, reference_unit = calibrate(hx)
    elif args.tare:
        offset = tare(hx)

    # ─── Graceful shutdown ───────────────────────────────────────────
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n\n  Shutting down...")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # ─── Real-Time Weight Tracking Loop ──────────────────────────────
    print("\n  Reading weight continuously... Press Ctrl+C to stop.\n")
    print(f"  {'Time':<12} {'Weight (g)':>12}  {'Raw Value':>12}  {'Status'}")
    print("  " + "-" * 55)

    reading_count = 0
    min_weight = float('inf')
    max_weight = float('-inf')

    try:
        while running:
            try:
                raw = hx.get_raw_data_mean(readings=args.samples)

                if raw is None or raw is False:
                    timestamp = time.strftime("%H:%M:%S")
                    print(f"  {timestamp:<12} {'---':>12}  {'---':>12}  [ NO DATA - check wiring ]")
                    time.sleep(1)
                    continue

                weight = (raw - offset) / reference_unit
                reading_count += 1

                # Track min/max
                min_weight = min(min_weight, weight)
                max_weight = max(max_weight, weight)

                # Status indicator
                if abs(weight) < 1.0:
                    status = "[ EMPTY ]"
                elif weight < 0:
                    status = "[ !! NEGATIVE !! ]"
                else:
                    status = "[  OK  ]"

                timestamp = time.strftime("%H:%M:%S")
                print(f"  {timestamp:<12} {weight:>10.1f} g  {raw:>12.0f}  {status}")

                time.sleep(args.interval)

            except Exception as e:
                timestamp = time.strftime("%H:%M:%S")
                print(f"  {timestamp:<12} {'ERROR':>12}  {'---':>12}  [ {e} ]")
                time.sleep(1)

    except KeyboardInterrupt:
        pass

    # ─── Summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  Session Summary")
    print("=" * 55)
    print(f"  Total readings: {reading_count}")
    if reading_count > 0:
        print(f"  Min weight:     {min_weight:.1f} g")
        print(f"  Max weight:     {max_weight:.1f} g")
    print("=" * 55)
    print("  Done. Goodbye!\n")


if __name__ == "__main__":
    main()
