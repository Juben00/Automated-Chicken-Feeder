"""
Interactive HX711 calibration wizard for Raspberry Pi.

Walks you through:
  Step 1 — Tare (zero the empty scale)
  Step 2 — Place a known weight and compute the scale ratio
  Step 3 — Verify accuracy with the reference weight still on
  Step 4 — Fine-tune with a second correction pass
  Step 5 — Multi-point verification (optional)

Saves calibration to hx711_calibration.json so load_cell.py can use it.

Usage:
    python calibrate_hx711.py --known-grams 100
    python calibrate_hx711.py --known-grams 200 --samples 30

Tip: Run  python load_cell.py --debug  first to verify HX711 wiring.
"""

from __future__ import annotations

import argparse
import sys
import time

from load_cell import LoadCell, DEFAULT_DT_PIN, DEFAULT_SCK_PIN


def wait_enter(prompt: str = "") -> None:
    """Print prompt and block until the user presses Enter."""
    input(f"\n>>> {prompt}  [press Enter]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate HX711 load cell.")
    parser.add_argument(
        "--known-grams", type=float, required=True,
        help="Mass of your reference weight in grams (e.g. 100)",
    )
    parser.add_argument("--dt", type=int, default=DEFAULT_DT_PIN,
                        help="HX711 DT pin BCM (default: 5)")
    parser.add_argument("--sck", type=int, default=DEFAULT_SCK_PIN,
                        help="HX711 SCK pin BCM (default: 6)")
    parser.add_argument("--samples", type=int, default=25,
                        help="Samples per averaged reading (default: 25)")
    args = parser.parse_args()

    if args.known_grams <= 0:
        print("Error: --known-grams must be positive.")
        sys.exit(1)

    known = args.known_grams

    print("=" * 55)
    print("   HX711 Calibration Wizard")
    print("=" * 55)
    print(f"   Reference weight : {known:.2f} g")
    print(f"   DT pin (BCM)     : GPIO{args.dt}")
    print(f"   SCK pin (BCM)    : GPIO{args.sck}")
    print(f"   Samples/reading  : {args.samples}")
    print("=" * 55)

    lc = LoadCell(dout_pin=args.dt, sck_pin=args.sck)

    try:
        # ── Step 1: Tare ──────────────────────────────────────────────
        print("\n── Step 1/5: TARE ──")
        print("Remove ALL weight from the load cell.")
        wait_enter("Ready to tare?")
        lc.tare(samples=args.samples)
        print(f"   Zero offset = {lc._offset:.1f}")

        # ── Step 2: Calibrate ─────────────────────────────────────────
        print("\n── Step 2/5: CALIBRATE ──")
        print(f"Place your {known:.2f} g reference weight on the load cell.")
        wait_enter("Weight placed?")
        time.sleep(1.5)   # let the load settle
        lc.calibrate(known, samples=args.samples)
        print(f"   Scale ratio = {lc._scale:.4f}  (raw units per gram)")

        # ── Step 3: Verify ────────────────────────────────────────────
        print("\n── Step 3/5: VERIFY ──")
        print("Leave the reference weight on the scale.")
        time.sleep(1.0)
        measured = lc.get_grams(samples=args.samples)
        error_g = measured - known
        error_pct = (error_g / known) * 100
        print(f"   Measured   : {measured:>8.2f} g")
        print(f"   Expected   : {known:>8.2f} g")
        print(f"   Error      : {error_g:>+8.2f} g  ({error_pct:>+.2f}%)")

        # ── Step 4: Fine-tune ─────────────────────────────────────────
        print("\n── Step 4/5: FINE-TUNE ──")
        print("Applying one-pass correction to reduce residual error ...")
        if abs(measured) > 0.01:
            correction = known / measured
            lc._scale *= (1.0 / correction)
            # Re-measure
            time.sleep(0.5)
            tuned = lc.get_grams(samples=args.samples)
            tuned_err = tuned - known
            tuned_pct = (tuned_err / known) * 100
            print(f"   Tuned      : {tuned:>8.2f} g")
            print(f"   Error now  : {tuned_err:>+8.2f} g  ({tuned_pct:>+.2f}%)")
        else:
            print("   Already very accurate — no correction needed.")

        # ── Step 5: Multi-point check (optional) ──────────────────────
        print("\n── Step 5/5: MULTI-POINT CHECK (optional) ──")
        print("You can test with different weights to check linearity.")
        print("Type a weight in grams to test, or 'done' to finish.\n")
        while True:
            ans = input("   Test weight (grams) or 'done': ").strip().lower()
            if ans in ("done", "d", "q", "quit", "exit", ""):
                break
            try:
                test_g = float(ans)
            except ValueError:
                print("   Enter a number or 'done'.")
                continue
            wait_enter(f"Place {test_g:.2f} g on the scale, then press Enter")
            time.sleep(1.0)
            m = lc.get_grams(samples=args.samples)
            e = m - test_g
            ep = (e / test_g) * 100 if test_g != 0 else 0
            print(f"   Measured: {m:>8.2f} g | Expected: {test_g:>8.2f} g | Error: {e:>+.2f} g ({ep:>+.2f}%)")

        # ── Save ──────────────────────────────────────────────────────
        lc.save_calibration()
        print("\nCalibration complete!  You can now run:")
        print("   python load_cell.py          # continuous grams")
        print("   python load_cell.py --once   # single reading")

    except KeyboardInterrupt:
        print("\n\nCalibration cancelled.")
    finally:
        lc.close()


if __name__ == "__main__":
    main()
