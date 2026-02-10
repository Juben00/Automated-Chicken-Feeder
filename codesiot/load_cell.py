"""
load_cell.py - HX711 Load Cell Module for Chicken Feeder
=========================================================
Reusable module with aggressive noise filtering for accurate
weight readings from an HX711 load cell amplifier.
Compatible with tatobari's hx711py library.

Filtering pipeline:
    1. Collect N raw samples (default 50)
    2. Sort and trim top/bottom 20% (outlier rejection)
    3. From remaining samples, reject anything > 1.5 IQR from median
    4. Return median of surviving samples

This makes readings resilient to electrical noise, vibration,
and random ADC spikes common with cheap HX711 boards on 3.3V.

Wiring (HX711 -> Raspberry Pi 3):
    VCC  -> Pin 1  (3.3V)
    GND  -> Pin 9  (Ground)
    DT   -> Pin 29 (GPIO 5)
    SCK  -> Pin 31 (GPIO 6)

Load Cell -> HX711:
    Red   -> E+  (Excitation+)
    Black -> E-  (Excitation-)
    White -> A-  (Signal-)
    Green -> A+  (Signal+)

Usage:
    from load_cell import LoadCell

    lc = LoadCell()
    lc.tare()
    weight = lc.get_weight()
    print(f"Weight: {weight:.1f} g")
    lc.cleanup()
"""

import time
import json
import os
import statistics
import RPi.GPIO as GPIO
from hx711 import HX711

# ==============================================================
# Pin Configuration (BCM numbering)
# ==============================================================
HX711_DT_PIN = 5      # Data pin  (Physical Pin 29)
HX711_SCK_PIN = 6     # Clock pin (Physical Pin 31)

# ==============================================================
# Filtering Settings - tune these if readings are still noisy
# ==============================================================
DEFAULT_SAMPLES = 50           # Raw samples per reading (more = slower but cleaner)
TRIM_PERCENT = 0.20            # Trim this % from top & bottom (outlier removal)
IQR_FACTOR = 1.5               # Reject values beyond this * IQR from median
SETTLE_TIME = 0.01             # Seconds between individual raw samples

CALIBRATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")


# ==============================================================
# Filtering Functions
# ==============================================================

def filtered_median(raw_samples, trim_pct=TRIM_PERCENT, iqr_factor=IQR_FACTOR):
    """
    Aggressively filter a list of raw ADC samples and return
    a clean median value.

    Pipeline:
        1. Sort values
        2. Trim top/bottom trim_pct (removes extreme outliers)
        3. Of remaining, compute IQR and reject values beyond iqr_factor * IQR
        4. Return median of survivors

    Args:
        raw_samples: List of raw int/float values from the ADC.
        trim_pct:    Fraction to trim from each end (0.20 = 20%).
        iqr_factor:  IQR multiplier for outlier rejection.

    Returns:
        Filtered median value (float), or None if too few samples survive.
    """
    if not raw_samples or len(raw_samples) < 3:
        return None

    # Step 1: Sort
    sorted_vals = sorted(raw_samples)

    # Step 2: Trim top/bottom
    trim_count = int(len(sorted_vals) * trim_pct)
    if trim_count > 0:
        trimmed = sorted_vals[trim_count:-trim_count]
    else:
        trimmed = sorted_vals[:]

    if len(trimmed) < 3:
        trimmed = sorted_vals[:]  # Fall back to untrimmed if too few left

    # Step 3: IQR-based outlier rejection
    n = len(trimmed)
    q1 = trimmed[n // 4]
    q3 = trimmed[(3 * n) // 4]
    iqr = q3 - q1

    if iqr > 0:
        lower_bound = q1 - iqr_factor * iqr
        upper_bound = q3 + iqr_factor * iqr
        clean = [v for v in trimmed if lower_bound <= v <= upper_bound]
    else:
        clean = trimmed  # All values very close, no rejection needed

    if len(clean) < 2:
        clean = trimmed  # Fall back if IQR rejected too many

    # Step 4: Return median
    return statistics.median(clean)


def collect_raw_samples(hx, num_samples=DEFAULT_SAMPLES, settle_time=SETTLE_TIME):
    """
    Collect multiple raw readings from the HX711.

    Args:
        hx:          HX711 instance.
        num_samples: Number of raw samples to collect.
        settle_time: Delay between each sample (seconds).

    Returns:
        List of raw integer values.
    """
    samples = []
    for _ in range(num_samples):
        try:
            val = hx.read_long()
            samples.append(val)
        except Exception:
            pass
        if settle_time > 0:
            time.sleep(settle_time)
    return samples


class LoadCell:
    """
    High-level interface for reading weight from an HX711 load cell.

    Uses aggressive multi-stage filtering for accurate readings even
    with noisy ADCs and 3.3V power supply.
    """

    def __init__(self, dout_pin=HX711_DT_PIN, pd_sck_pin=HX711_SCK_PIN, gain=128):
        """
        Initialize the HX711 load cell amplifier.

        Args:
            dout_pin:   BCM GPIO pin connected to HX711 DT (data).
            pd_sck_pin: BCM GPIO pin connected to HX711 SCK (clock).
            gain:       Amplifier gain (128 or 64 for channel A, 32 for channel B).
        """
        self.dout_pin = dout_pin
        self.pd_sck_pin = pd_sck_pin
        self._reference_unit = 1
        self._offset = 0
        self._calibrated = False

        try:
            # tatobari's hx711py uses positional args: HX711(dout, pd_sck, gain)
            self.hx = HX711(dout_pin, pd_sck_pin, gain)
            self.hx.set_reading_format("MSB", "MSB")

            # Fix Python 3 bug in tatobari's hx711py
            self._patch_hx711_read_median()

            self.hx.reset()
            time.sleep(0.5)

            # Discard first few readings (HX711 needs to settle after reset)
            for _ in range(5):
                try:
                    self.hx.read_long()
                except Exception:
                    pass
                time.sleep(0.05)

            print(f"[LoadCell] Initialized on DT=GPIO{dout_pin}, SCK=GPIO{pd_sck_pin}")
        except Exception as e:
            raise RuntimeError(
                f"[LoadCell] Failed to initialize HX711: {e}\n"
                f"  - Check wiring: DT->GPIO{dout_pin} (Pin 29), SCK->GPIO{pd_sck_pin} (Pin 31)\n"
                f"  - Ensure HX711 has power: VCC->3.3V (Pin 1), GND->GND (Pin 9)\n"
                f"  - Make sure no other process is using these GPIO pins"
            )

        # Try to load saved calibration
        if os.path.exists(CALIBRATION_FILE):
            self.load_calibration()

    def _patch_hx711_read_median(self):
        """
        Monkey-patch the read_median method in tatobari's hx711py to fix
        a Python 3 incompatibility: len(valueList) / 2 returns a float,
        but it's used as a slice index which requires an int.
        """
        hx = self.hx

        def fixed_read_median(times=3):
            if times <= 0:
                raise ValueError("HX711::read_median(): times must be greater than zero!")
            if times == 1:
                return hx.read_long()
            valueList = []
            for x in range(times):
                valueList.append(hx.read_long())
            valueList.sort()
            if (times & 0x1) == 0x1:
                return valueList[len(valueList) // 2]
            else:
                midpoint = len(valueList) // 2
                return sum(valueList[midpoint:midpoint + 2]) / 2.0

        hx.read_median = fixed_read_median

    # ==============================================================
    # Core filtered reading methods
    # ==============================================================

    def _read_filtered(self, num_samples=DEFAULT_SAMPLES):
        """
        Take a filtered reading using our full noise-rejection pipeline.
        Returns raw ADC value (no offset/reference applied).

        Args:
            num_samples: Number of raw samples to collect.

        Returns:
            Filtered median raw value, or None on error.
        """
        samples = collect_raw_samples(self.hx, num_samples)
        if len(samples) < 5:
            print("[LoadCell] WARNING: Very few samples collected. Check connection.")
            return None
        return filtered_median(samples)

    def _read_filtered_value(self, num_samples=DEFAULT_SAMPLES):
        """
        Take a filtered reading with tare offset subtracted.

        Returns:
            Filtered value minus offset, or None on error.
        """
        raw = self._read_filtered(num_samples)
        if raw is None:
            return None
        return raw - self._offset

    # ==============================================================
    # Public API
    # ==============================================================

    def tare(self, num_samples=80):
        """
        Zero/tare the scale. Call with nothing on the load cell.
        Uses extra-heavy filtering for a clean zero point.

        Args:
            num_samples: Number of samples for tare (more = better zero).

        Returns:
            The tare offset value, or None on error.
        """
        print(f"[LoadCell] Taring... (collecting {num_samples} samples)")
        try:
            raw = self._read_filtered(num_samples)
            if raw is None:
                print("[LoadCell] WARNING: Could not get stable tare reading.")
                return None

            self._offset = raw
            # Also set the offset in the hx711 library for its internal methods
            self.hx.set_offset(raw)
            print(f"[LoadCell] Tare complete. Offset: {raw:.0f}")
            return raw
        except Exception as e:
            print(f"[LoadCell] Tare error: {e}")
            return None

    def get_raw_value(self, num_samples=DEFAULT_SAMPLES):
        """
        Get the filtered raw ADC value (after tare offset subtracted).

        Args:
            num_samples: Number of samples to collect.

        Returns:
            Filtered raw value (float), or None on error.
        """
        return self._read_filtered_value(num_samples)

    def read_raw_no_offset(self, num_samples=DEFAULT_SAMPLES):
        """
        Get the filtered absolute raw ADC value (ignoring tare offset).

        Args:
            num_samples: Number of samples to collect.

        Returns:
            Filtered raw value (float), or None on error.
        """
        return self._read_filtered(num_samples)

    def get_weight(self, num_samples=DEFAULT_SAMPLES):
        """
        Get weight in grams. Requires prior calibration.

        Args:
            num_samples: Number of samples for this reading.

        Returns:
            Weight in grams (float), or None if not calibrated / error.
        """
        if not self._calibrated:
            print("[LoadCell] ERROR: Not calibrated. Run calibrate_hx711.py first.")
            return None

        value = self._read_filtered_value(num_samples)
        if value is None:
            return None

        weight = value / self._reference_unit
        return round(weight, 1)

    def get_stable_weight(self, num_passes=5, stability_threshold=2.0,
                          timeout=15):
        """
        Get a stable weight reading by taking multiple filtered passes
        and checking they agree within the threshold.

        Args:
            num_passes: Number of filtered weight readings to compare.
            stability_threshold: Max allowed spread (grams) between passes.
            timeout: Max seconds to wait for stability.

        Returns:
            Stable weight in grams (float), or best estimate on timeout.
        """
        if not self._calibrated:
            print("[LoadCell] ERROR: Not calibrated.")
            return None

        readings = []
        start = time.time()

        while time.time() - start < timeout:
            w = self.get_weight(num_samples=40)
            if w is None:
                continue

            readings.append(w)

            if len(readings) >= num_passes:
                recent = readings[-num_passes:]
                spread = max(recent) - min(recent)
                if spread <= stability_threshold:
                    return round(statistics.median(recent), 1)

            time.sleep(0.2)

        # Timeout - return best estimate
        if readings:
            return round(statistics.median(readings[-num_passes:] if len(readings) >= num_passes else readings), 1)
        return None

    def calibrate(self, known_weight_grams, num_passes=3, samples_per_pass=80):
        """
        Calibrate the scale using a known weight with multi-pass averaging.

        Takes multiple calibration passes and averages the reference unit
        for better accuracy.

        Args:
            known_weight_grams: Exact weight of calibration object (grams).
            num_passes: Number of calibration passes to average.
            samples_per_pass: Raw samples per pass.

        Returns:
            The reference unit (float) if successful, None otherwise.
        """
        print(f"[LoadCell] Calibrating with {known_weight_grams}g reference weight...")
        print(f"[LoadCell] Running {num_passes} passes x {samples_per_pass} samples each...")

        ref_units = []

        for p in range(num_passes):
            value = self._read_filtered_value(samples_per_pass)

            if value is None or value == 0:
                print(f"  Pass {p+1}: FAILED (no valid reading)")
                continue

            ref = value / known_weight_grams
            ref_units.append(ref)
            print(f"  Pass {p+1}: raw={value:.0f}, ref_unit={ref:.2f}")
            time.sleep(0.5)

        if not ref_units:
            print("[LoadCell] ERROR: All calibration passes failed.")
            return None

        # Use median of passes (resistant to one bad pass)
        self._reference_unit = statistics.median(ref_units)
        self.hx.set_reference_unit(self._reference_unit)
        self._calibrated = True

        if len(ref_units) > 1:
            spread = max(ref_units) - min(ref_units)
            spread_pct = (spread / abs(self._reference_unit)) * 100 if self._reference_unit != 0 else 0
            print(f"\n[LoadCell] Calibration complete!")
            print(f"  Reference unit: {self._reference_unit:.2f} (median of {len(ref_units)} passes)")
            print(f"  Pass spread: {spread:.2f} ({spread_pct:.1f}%)")
        else:
            print(f"\n[LoadCell] Calibration complete!")
            print(f"  Reference unit: {self._reference_unit:.2f}")

        return self._reference_unit

    def set_reference_unit(self, ref_unit):
        """
        Manually set the reference unit (raw units per gram).

        Args:
            ref_unit: The reference unit from a previous calibration.
        """
        self._reference_unit = ref_unit
        self.hx.set_reference_unit(ref_unit)
        self._calibrated = True
        print(f"[LoadCell] Reference unit set to {ref_unit:.2f}")

    def save_calibration(self, filepath=None):
        """
        Save calibration data to a JSON file.
        """
        if filepath is None:
            filepath = CALIBRATION_FILE

        if not self._calibrated:
            print("[LoadCell] WARNING: No calibration data to save.")
            return False

        data = {
            "reference_unit": self._reference_unit,
            "dout_pin": self.dout_pin,
            "pd_sck_pin": self.pd_sck_pin,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "notes": "Generated by calibrate_hx711.py"
        }

        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"[LoadCell] Calibration saved to {filepath}")
            return True
        except Exception as e:
            print(f"[LoadCell] Error saving calibration: {e}")
            return False

    def load_calibration(self, filepath=None):
        """
        Load calibration data from a JSON file.
        """
        if filepath is None:
            filepath = CALIBRATION_FILE

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            self._reference_unit = data["reference_unit"]
            self.hx.set_reference_unit(self._reference_unit)
            self._calibrated = True
            print(f"[LoadCell] Calibration loaded from {filepath}")
            print(f"  Reference unit: {self._reference_unit:.2f}")
            print(f"  Calibrated on: {data.get('timestamp', 'unknown')}")
            return True
        except FileNotFoundError:
            print(f"[LoadCell] No calibration file found at {filepath}")
            return False
        except Exception as e:
            print(f"[LoadCell] Error loading calibration: {e}")
            return False

    def is_calibrated(self):
        """Check if the scale has been calibrated."""
        return self._calibrated

    def power_down(self):
        """Power down the HX711 to save energy."""
        self.hx.power_down()

    def power_up(self):
        """Power up the HX711."""
        self.hx.power_up()

    def cleanup(self):
        """Clean up GPIO resources."""
        try:
            GPIO.cleanup()
            print("[LoadCell] GPIO cleanup done.")
        except Exception:
            pass


# ==============================================================
# Quick test when run directly
# ==============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("  HX711 Load Cell - Quick Test")
    print("=" * 50)
    print()

    lc = LoadCell()

    input("Remove everything from the load cell, then press Enter...")
    lc.tare()
    print()

    if lc.is_calibrated():
        print("Calibration found! Reading weight...")
        for i in range(10):
            weight = lc.get_weight()
            if weight is not None:
                print(f"  Reading {i+1}: {weight:.1f} g")
            time.sleep(0.5)
    else:
        print("No calibration found. Showing raw values...")
        print("Run calibrate_hx711.py to calibrate for gram readings.")
        for i in range(10):
            raw = lc.get_raw_value()
            if raw is not None:
                print(f"  Reading {i+1}: {raw}")
            time.sleep(0.5)

    lc.cleanup()
