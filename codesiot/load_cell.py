"""
HX711 Load Cell Driver for Raspberry Pi using pigpio.

Uses pigpio daemon for microsecond-accurate GPIO timing, which is critical
for reliable HX711 communication.  No third-party HX711 package needed.

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
    python load_cell.py                   # continuous reading (must calibrate first)
    python load_cell.py --raw             # show raw ADC values (no calibration needed)
    python load_cell.py --once            # single reading then exit
    python load_cell.py --tare            # tare before reading
    python load_cell.py --samples 30      # override samples per reading

Requires: pigpio daemon running  ->  sudo pigpiod
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import pigpio

# ---------------------------------------------------------------------------
# Pin defaults (BCM numbering) — matches your wiring
# ---------------------------------------------------------------------------
DEFAULT_DT_PIN = 5       # GPIO5  = physical pin 29
DEFAULT_SCK_PIN = 6      # GPIO6  = physical pin 31

# Calibration file lives next to this script
CALIBRATION_FILE = Path(__file__).resolve().parent / "hx711_calibration.json"


class HX711:
    """
    Low-level HX711 24-bit ADC driver using pigpio for bit-bang SPI.

    The HX711 protocol:
    1. Wait for DOUT to go LOW  (data ready).
    2. Pulse SCK 24 times, reading DOUT each time  -> 24-bit raw value.
    3. Pulse SCK 1-3 more times to set gain for the *next* conversion:
         1 extra pulse  = Channel A, gain 128  (default, most sensitive)
         2 extra pulses = Channel B, gain 32
         3 extra pulses = Channel A, gain 64
    4. DOUT goes HIGH after all pulses  -> chip starts next conversion.
    """

    # Gain -> extra clock pulses after the 24 data bits
    _GAIN_PULSES = {128: 1, 64: 3, 32: 2}

    def __init__(
        self,
        pi: pigpio.pi,
        dout_pin: int = DEFAULT_DT_PIN,
        sck_pin: int = DEFAULT_SCK_PIN,
        gain: int = 128,
    ):
        self._pi = pi
        self._dout = dout_pin
        self._sck = sck_pin

        if gain not in self._GAIN_PULSES:
            raise ValueError(f"Gain must be 128, 64, or 32 — got {gain}")
        self._gain = gain
        self._extra_pulses = self._GAIN_PULSES[gain]

        # Configure pins
        self._pi.set_mode(self._dout, pigpio.INPUT)
        self._pi.set_pull_up_down(self._dout, pigpio.PUD_DOWN)
        self._pi.set_mode(self._sck, pigpio.OUTPUT)
        self._pi.write(self._sck, 0)

        # Flush one reading to lock in gain setting
        self._read_raw()

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------
    def is_ready(self) -> bool:
        """HX711 pulls DOUT low when a new conversion is ready."""
        return self._pi.read(self._dout) == 0

    def _wait_ready(self, timeout_s: float = 2.0) -> None:
        """Block until DOUT goes LOW or timeout."""
        deadline = time.time() + timeout_s
        while not self.is_ready():
            if time.time() > deadline:
                raise TimeoutError(
                    "HX711 not responding — check wiring (DT/SCK) and power."
                )
            time.sleep(0.001)

    def _read_raw(self) -> int:
        """
        Read one raw 24-bit signed value from the HX711.

        Returns an integer roughly in the range -8 388 608 … +8 388 607.
        """
        self._wait_ready()

        # Shift in 24 data bits (MSB first)
        raw = 0
        for _ in range(24):
            self._pi.write(self._sck, 1)
            # Small delay is inherent in the pigpio daemon round-trip;
            # the HX711 needs SCK HIGH for >= 0.1 µs — pigpio is fine.
            raw = (raw << 1) | self._pi.read(self._dout)
            self._pi.write(self._sck, 0)

        # Extra pulses to set gain/channel for NEXT conversion
        for _ in range(self._extra_pulses):
            self._pi.write(self._sck, 1)
            self._pi.write(self._sck, 0)

        # Convert unsigned 24-bit to signed (two's complement)
        if raw & 0x800000:
            raw -= 0x1000000

        return raw

    def read_raw_average(self, samples: int = 10) -> float:
        """Return the mean of *samples* raw readings (outliers removed)."""
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
        self._pi.write(self._sck, 0)
        self._pi.write(self._sck, 1)
        time.sleep(0.0001)  # 100 µs

    def power_up(self) -> None:
        """Wake from low-power mode."""
        self._pi.write(self._sck, 0)
        time.sleep(0.001)
        # Flush one reading to re-lock gain
        self._read_raw()


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

        # Connect to pigpio daemon
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError(
                "Cannot connect to pigpio daemon. Start it with:  sudo pigpiod"
            )

        self._hx = HX711(self._pi, dout_pin, sck_pin, gain)

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
        if abs(net) < 10:
            raise RuntimeError(
                "Raw reading is almost the same as tare offset — "
                "is the weight actually on the scale?"
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
        """Power down HX711 and disconnect pigpio."""
        try:
            self._hx.power_down()
        except Exception:
            pass
        try:
            self._pi.stop()
        except Exception:
            pass


# =======================================================================
# Standalone CLI — run directly on the Pi
# =======================================================================
def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Read weight (grams) from HX711 load cell via pigpio.",
    )
    parser.add_argument("--dt", type=int, default=DEFAULT_DT_PIN,
                        help="HX711 DT pin in BCM (default: 5 = physical pin 29)")
    parser.add_argument("--sck", type=int, default=DEFAULT_SCK_PIN,
                        help="HX711 SCK pin in BCM (default: 6 = physical pin 31)")
    parser.add_argument("--samples", type=int, default=15,
                        help="Samples per averaged reading (default: 15)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Seconds between readings (default: 0.5)")
    parser.add_argument("--raw", action="store_true",
                        help="Show raw ADC values instead of grams")
    parser.add_argument("--once", action="store_true",
                        help="Print one reading then exit")
    parser.add_argument("--tare", action="store_true",
                        help="Tare (zero) the scale before reading")
    args = parser.parse_args()

    lc = LoadCell(dout_pin=args.dt, sck_pin=args.sck)

    try:
        if args.tare:
            lc.tare(samples=args.samples)

        if args.raw:
            print("\n--- Raw ADC values (Ctrl+C to stop) ---\n")
        else:
            if lc._scale == 1.0 and lc._offset == 0.0:
                print("\n[!] No calibration found. Run calibrate_hx711.py first,")
                print("    or use --raw to see uncalibrated values.\n")
                return
            print(f"\n--- Weight in grams (Ctrl+C to stop) ---\n")

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
