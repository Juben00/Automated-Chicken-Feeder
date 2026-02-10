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

        # ── Step 3: Verify + Fine-tune ────────────────────────────────
        print("\n── Step 3/4: VERIFY & FINE-TUNE ──")
        print("Leave the reference weight on the scale.")
        time.sleep(1.5)
        measured = lc.get_grams(samples=args.samples)
        error_g = measured - known
        error_pct = (error_g / known) * 100
        print(f"   Measured   : {measured:>8.2f} g")
        print(f"   Expected   : {known:>8.2f} g")
        print(f"   Error      : {error_g:>+8.2f} g  ({error_pct:>+.2f}%)")

        # Apply correction mathematically (do NOT re-read — raw values drift)
        if abs(measured) > 0.01 and abs(error_pct) > 0.5:
            # Adjust scale so that the SAME raw reading would produce exactly known_grams
            lc._scale *= (measured / known)
            print(f"   Corrected scale ratio: {lc._scale:.4f}")
            print(f"   (mathematically adjusted — same reading now maps to {known:.2f} g)")
        else:
            print("   Already accurate — no correction needed.")

        # ── Step 4: Fresh verification ────────────────────────────────
        print("\n── Step 4/4: FRESH VERIFICATION ──")
        print("Remove the weight, wait 3 seconds, then place it back.")
        wait_enter("Weight back on the scale?")
        time.sleep(2.0)

        # Quick re-tare check: see if zero has drifted
        verify = lc.get_grams(samples=args.samples)
        v_err = verify - known
        v_pct = (v_err / known) * 100
        print(f"   Measured   : {verify:>8.2f} g")
        print(f"   Expected   : {known:>8.2f} g")
        print(f"   Error      : {v_err:>+8.2f} g  ({v_pct:>+.2f}%)")
        if abs(v_pct) > 10:
            print("\n   [!] Error is still large (>10%).")
            print("   This usually means the load cell is not mounted properly.")
            print("   Make sure one end is fixed (screwed down) and weight")
            print("   is on the free end.  Then re-run calibration.")

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
