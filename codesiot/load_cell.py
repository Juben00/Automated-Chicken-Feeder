"""
HX711 Load Cell Driver for Raspberry Pi using RPi.GPIO.

Uses RPi.GPIO for direct memory-mapped GPIO access (~1-5 µs per call).
This is critical because the HX711 enters power-down mode if SCK stays
HIGH for > 60 µs.  The pigpio daemon adds ~100-200 µs socket latency
per call, which exceeds that threshold and breaks communication.

RPi.GPIO is pre-installed on every Raspberry Pi OS image.

Wiring (your setup):
    HX711 DT   -> GPIO5  (physical pin 29)
    HX711 SCK  -> GPIO6  (physical pin 31)
    HX711 VCC  -> 3.3V   (physical pin 1)
    HX711 GND  -> GND    (physical pin 9)

Usage as module:
    from load_cell import LoadCell
    lc = LoadCell()
    lc.tare()
    print(lc.get_grams())

Usage standalone:
    python load_cell.py                   # continuous grams (calibrate first)
    python load_cell.py --raw             # raw ADC values (no calibration needed)
    python load_cell.py --once            # single reading then exit
    python load_cell.py --tare            # tare before reading
    python load_cell.py --samples 30      # override samples per reading
    python load_cell.py --debug           # diagnose wiring / signal issues
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Pin defaults (BCM numbering) — matches your wiring
# ---------------------------------------------------------------------------
DEFAULT_DT_PIN = 5       # GPIO5  = physical pin 29
DEFAULT_SCK_PIN = 6      # GPIO6  = physical pin 31

# Calibration file lives next to this script
CALIBRATION_FILE = Path(__file__).resolve().parent / "hx711_calibration.json"


class HX711:
    """
    Low-level HX711 24-bit ADC driver using RPi.GPIO (direct, fast).

    The HX711 protocol:
    1. Wait for DOUT to go LOW  (data ready).
    2. Pulse SCK 24 times, reading DOUT each time -> 24-bit raw value.
    3. Pulse SCK 1-3 more times to set gain for the *next* conversion:
         1 extra pulse  = Channel A, gain 128  (default, most sensitive)
         2 extra pulses = Channel B, gain 32
         3 extra pulses = Channel A, gain 64
    4. DOUT goes HIGH after all pulses -> chip starts next conversion.

    IMPORTANT: Each SCK HIGH pulse must be < 60 µs or the HX711 enters
    power-down mode.  RPi.GPIO calls take ~1-5 µs (in-process, memory-
    mapped), so this is safely within spec.
    """

    # Gain -> extra clock pulses after the 24 data bits
    _GAIN_PULSES = {128: 1, 64: 3, 32: 2}

    def __init__(
        self,
        dout_pin: int = DEFAULT_DT_PIN,
        sck_pin: int = DEFAULT_SCK_PIN,
        gain: int = 128,
    ):
        self._dout = dout_pin
        self._sck = sck_pin

        if gain not in self._GAIN_PULSES:
            raise ValueError(f"Gain must be 128, 64, or 32 — got {gain}")
        self._gain = gain
        self._extra_pulses = self._GAIN_PULSES[gain]

        # Configure GPIO (BCM numbering, no warnings for shared use with pigpio/servo)
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._sck, GPIO.OUT)
        GPIO.setup(self._dout, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.output(self._sck, False)

        # Power-cycle the HX711 to reset it to a known state
        self._power_cycle()

        # Flush two readings to lock in gain setting
        self._read_raw()
        self._read_raw()

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------
    def is_ready(self) -> bool:
        """HX711 pulls DOUT low when a new conversion is ready."""
        return GPIO.input(self._dout) == 0

    def _wait_ready(self, timeout_s: float = 5.0) -> None:
        """Block until DOUT goes LOW or timeout."""
        deadline = time.time() + timeout_s
        while not self.is_ready():
            if time.time() > deadline:
                raise TimeoutError(
                    "HX711 not responding — check wiring:\n"
                    f"  DT  = GPIO{self._dout}  (physical pin {self._bcm_to_board(self._dout)})\n"
                    f"  SCK = GPIO{self._sck}  (physical pin {self._bcm_to_board(self._sck)})\n"
                    "  VCC = 3.3V, GND = GND\n"
                    "Also make sure no other process is using these GPIO pins."
                )
            time.sleep(0.001)

    @staticmethod
    def _bcm_to_board(bcm: int) -> str:
        """Quick lookup for common BCM -> physical pin (for error messages)."""
        mapping = {5: "29", 6: "31", 12: "32", 13: "33", 16: "36", 17: "11",
                   18: "12", 19: "35", 20: "38", 21: "40", 22: "15", 23: "16",
                   24: "18", 25: "22", 26: "37", 27: "13"}
        return mapping.get(bcm, "?")

    def _read_raw(self) -> int:
        """
        Read one raw 24-bit signed value from the HX711.

        Returns an integer roughly in the range -8 388 608 … +8 388 607.
        """
        self._wait_ready()

        # Shift in 24 data bits (MSB first)
        # Each GPIO.output / GPIO.input call takes ~1-5 µs (well under 60 µs limit)
        raw = 0
        for _ in range(24):
            GPIO.output(self._sck, True)
            raw = (raw << 1) | GPIO.input(self._dout)
            GPIO.output(self._sck, False)

        # Extra pulses to set gain/channel for NEXT conversion
        for _ in range(self._extra_pulses):
            GPIO.output(self._sck, True)
            GPIO.output(self._sck, False)

        # Convert unsigned 24-bit to signed (two's complement)
        if raw & 0x800000:
            raw -= 0x1000000

        return raw

    def read_raw_average(self, samples: int = 10) -> float:
        """Return the mean of *samples* raw readings (outliers trimmed)."""
        if samples < 1:
            raise ValueError("samples must be >= 1")

        readings: list[int] = []
        for _ in range(samples):
            readings.append(self._read_raw())

        if samples >= 5:
            # Drop lowest and highest to remove spikes
            readings.sort()
            trimmed = readings[1:-1]
        else:
            trimmed = readings

        return sum(trimmed) / len(trimmed)

    # ------------------------------------------------------------------
    # Power management
    # ------------------------------------------------------------------
    def power_down(self) -> None:
        """Enter low-power mode (hold SCK HIGH > 60 µs)."""
        GPIO.output(self._sck, False)
        GPIO.output(self._sck, True)
        time.sleep(0.0001)  # 100 µs — triggers power-down

    def power_up(self) -> None:
        """Wake from low-power mode."""
        GPIO.output(self._sck, False)
        time.sleep(0.001)

    def _power_cycle(self) -> None:
        """Reset HX711 by power-cycling (down then up)."""
        self.power_down()
        time.sleep(0.01)
        self.power_up()

    def cleanup(self) -> None:
        """Release only the HX711 GPIO pins (does NOT touch servo pins)."""
        try:
            GPIO.output(self._sck, False)
            GPIO.cleanup([self._dout, self._sck])
        except Exception:
            pass


class LoadCell:
    """
    High-level interface: tare, calibrate, read grams.

    Wraps HX711 and adds offset/scale calibration with JSON persistence.
    """

    def __init__(
        self,
        dout_pin: int = DEFAULT_DT_PIN,
        sck_pin: int = DEFAULT_SCK_PIN,
        gain: int = 128,
        calibration_file: Path | str = CALIBRATION_FILE,
    ):
        self._cal_path = Path(calibration_file)
        self._offset: float = 0.0          # raw value at zero load
        self._scale: float = 1.0           # raw-units-per-gram

        self._hx = HX711(dout_pin, sck_pin, gain)

        # Load saved calibration if it exists
        self._load_calibration()

    # ------------------------------------------------------------------
    # Calibration persistence
    # ------------------------------------------------------------------
    def _load_calibration(self) -> bool:
        """Load offset + scale from JSON.  Returns True if loaded."""
        if self._cal_path.exists():
            try:
                data = json.loads(self._cal_path.read_text(encoding="utf-8"))
                self._offset = float(data["offset"])
                self._scale = float(data["scale"])
                print(f"[LoadCell] Calibration loaded  (offset={self._offset:.1f}, scale={self._scale:.4f})")
                return True
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                print(f"[LoadCell] Bad calibration file, ignoring: {exc}")
        return False

    def save_calibration(self) -> None:
        """Persist current offset + scale to JSON."""
        payload = {
            "offset": self._offset,
            "scale": self._scale,
            "dout_pin_bcm": self._hx._dout,
            "sck_pin_bcm": self._hx._sck,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._cal_path.parent.mkdir(parents=True, exist_ok=True)
        self._cal_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[LoadCell] Calibration saved to {self._cal_path}")

    # ------------------------------------------------------------------
    # Tare (zero the scale)
    # ------------------------------------------------------------------
    def tare(self, samples: int = 20) -> None:
        """
        Set the zero-point offset with nothing on the scale.

        Takes *samples* readings (default 20) and averages them.
        """
        print("[LoadCell] Taring — remove all weight from the scale ...")
        time.sleep(0.5)
        self._offset = self._hx.read_raw_average(samples)
        print(f"[LoadCell] Tare complete  (offset = {self._offset:.1f})")

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def calibrate(self, known_grams: float, samples: int = 25) -> None:
        """
        Calibrate scale factor using a known reference weight.

        Call tare() first with an empty scale, then place the weight and
        call calibrate(known_grams).
        """
        if known_grams <= 0:
            raise ValueError("known_grams must be > 0")

        raw = self._hx.read_raw_average(samples)
        net = raw - self._offset
        if abs(net) < 100:
            raise RuntimeError(
                f"Raw reading ({raw:.1f}) is too close to tare offset ({self._offset:.1f}).\n"
                "   Possible causes:\n"
                "   1. Weight is not on the load cell\n"
                "   2. Load cell wires may be swapped — try swapping A+ (green) and A- (white)\n"
                "   3. Load cell is not properly mounted to a base plate\n"
                "   4. Run:  python load_cell.py --debug   to diagnose further"
            )
        self._scale = net / known_grams
        print(f"[LoadCell] Scale ratio set  ({self._scale:.4f} raw/gram)")

    # ------------------------------------------------------------------
    # Read weight
    # ------------------------------------------------------------------
    def get_raw(self, samples: int = 10) -> float:
        """Return the raw (uncalibrated) averaged ADC value."""
        return self._hx.read_raw_average(samples)

    def get_grams(self, samples: int = 10) -> float:
        """
        Return calibrated weight in grams.

        Uses median-of-3-batches for extra stability:
            - Take 3 independent averaged readings.
            - Return the median (rejects a single noisy batch).
        """
        batch_values: list[float] = []
        for _ in range(3):
            raw = self._hx.read_raw_average(samples)
            grams = (raw - self._offset) / self._scale
            batch_values.append(grams)
        return float(statistics.median(batch_values))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Power down HX711 and release its GPIO pins only."""
        self._hx.cleanup()


# =======================================================================
# Debug / diagnostic mode
# =======================================================================
def _run_debug(dt: int, sck: int) -> None:
    """
    Interactive diagnostic: shows raw ADC values so you can check
    whether the HX711 responds and whether values change with load.
    """
    print("=" * 55)
    print("   HX711 DIAGNOSTIC MODE")
    print("=" * 55)
    print(f"   DT  = GPIO{dt}  (physical pin {HX711._bcm_to_board(dt)})")
    print(f"   SCK = GPIO{sck}  (physical pin {HX711._bcm_to_board(sck)})")
    print("=" * 55)

    hx = HX711(dout_pin=dt, sck_pin=sck)

    print("\nReading raw ADC values — the number should CHANGE when you")
    print("press on the load cell or place/remove weight.")
    print("If the value stays constant, you have a wiring problem.\n")
    print("Press Ctrl+C to stop.\n")

    prev: float | None = None
    try:
        while True:
            raw = hx.read_raw_average(samples=7)
            delta = f"  (delta: {raw - prev:>+10.1f})" if prev is not None else ""
            print(f"  raw: {raw:>12.1f}{delta}")
            prev = raw
            time.sleep(0.6)
    except KeyboardInterrupt:
        print("\nDiagnostic stopped.")
    finally:
        hx.cleanup()


# =======================================================================
# Standalone CLI
# =======================================================================
def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Read weight (grams) from HX711 load cell on Raspberry Pi.",
    )
    parser.add_argument("--dt", type=int, default=DEFAULT_DT_PIN,
                        help="HX711 DT pin in BCM (default: 5 = physical pin 29)")
    parser.add_argument("--sck", type=int, default=DEFAULT_SCK_PIN,
                        help="HX711 SCK pin in BCM (default: 6 = physical pin 31)")
    parser.add_argument("--samples", type=int, default=5,
                        help="Samples per averaged reading (default: 5)")
    parser.add_argument("--interval", type=float, default=0.03,
                        help="Seconds between readings (default: 0.03)")
    parser.add_argument("--raw", action="store_true",
                        help="Show raw ADC values instead of grams")
    parser.add_argument("--once", action="store_true",
                        help="Print one reading then exit")
    parser.add_argument("--tare", action="store_true",
                        help="Tare (zero) the scale before reading")
    parser.add_argument("--debug", action="store_true",
                        help="Run wiring diagnostic (no calibration needed)")
    args = parser.parse_args()

    # Debug mode is standalone — doesn't need calibration
    if args.debug:
        _run_debug(args.dt, args.sck)
        return

    lc = LoadCell(dout_pin=args.dt, sck_pin=args.sck)

    try:
        if args.tare:
            lc.tare(samples=args.samples)

        if args.raw:
            print("\n--- Raw ADC values (Ctrl+C to stop) ---\n")
        else:
            if lc._scale == 1.0 and lc._offset == 0.0:
                print("\n[!] No calibration found. Run calibrate_hx711.py first,")
                print("    or use --raw to see raw ADC values.\n")
                print("    Quick start:")
                print("      python load_cell.py --debug              # verify wiring")
                print("      python calibrate_hx711.py --known-grams 100  # calibrate")
                print("      python load_cell.py                      # read grams\n")
                return
            print("\n--- Weight in grams (Ctrl+C to stop) ---\n")

        while True:
            if args.raw:
                val = lc.get_raw(args.samples)
                print(f"  raw: {val:>12.1f}")
            else:
                grams = lc.get_grams(args.samples)
                print(f"  {grams:>8.2f} g")

            if args.once:
                break
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        lc.close()


if __name__ == "__main__":
    _cli()
