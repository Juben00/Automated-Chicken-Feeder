"""
load_cell.py - HX711 Load Cell Module for Chicken Feeder
=========================================================
Reusable module for reading weight from an HX711 load cell amplifier.
Compatible with tatobari's hx711py library.

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
import RPi.GPIO as GPIO
from hx711 import HX711

# ==============================================================
# Pin Configuration (BCM numbering)
# ==============================================================
HX711_DT_PIN = 5      # Data pin  (Physical Pin 29)
HX711_SCK_PIN = 6     # Clock pin (Physical Pin 31)

# ==============================================================
# Default Settings
# ==============================================================
DEFAULT_READINGS = 15          # Number of readings to average
CALIBRATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")


class LoadCell:
    """
    High-level interface for reading weight from an HX711 load cell.

    Handles initialization, taring, calibration, and weight reading
    with built-in noise filtering and stability checks.
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
        self._calibrated = False

        try:
            # tatobari's hx711py uses positional args: HX711(dout, pd_sck, gain)
            self.hx = HX711(dout_pin, pd_sck_pin, gain)
            self.hx.set_reading_format("MSB", "MSB")

            # Fix Python 3 bug in tatobari's hx711py: read_median() uses
            # float division (/) instead of integer division (//) for slice
            # indices, causing "slice indices must be integers" errors.
            self._patch_hx711_read_median()

            self.hx.reset()
            time.sleep(0.2)
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
            # Odd number of samples: take the centre value
            if (times & 0x1) == 0x1:
                return valueList[len(valueList) // 2]
            else:
                # Even number: average the two middle values
                # FIX: use // (integer division) instead of / (float division)
                midpoint = len(valueList) // 2
                return sum(valueList[midpoint:midpoint + 2]) / 2.0

        hx.read_median = fixed_read_median

    def tare(self, times=15):
        """
        Zero/tare the scale. Call with nothing on the load cell.

        Args:
            times: Number of readings to average for the zero point.

        Returns:
            The tare offset value.
        """
        print(f"[LoadCell] Taring... (averaging {times} readings)")
        try:
            # set_reference_unit to 1 so tare reads raw values
            self.hx.set_reference_unit(1)
            val = self.hx.tare(times)
            # restore reference unit after tare
            if self._calibrated:
                self.hx.set_reference_unit(self._reference_unit)
            print(f"[LoadCell] Tare complete. Offset: {val}")
            return val
        except Exception as e:
            print(f"[LoadCell] Tare error: {e}")
            return None

    def get_raw_value(self, times=DEFAULT_READINGS):
        """
        Get the raw ADC value from the HX711 (after tare offset).

        Args:
            times: Number of readings to average.

        Returns:
            Mean raw value (float), or None on error.
        """
        try:
            value = self.hx.get_value(times)
            return value
        except Exception as e:
            print(f"[LoadCell] Raw read error: {e}")
            return None

    def read_raw_no_offset(self, times=DEFAULT_READINGS):
        """
        Get the absolute raw ADC value (ignoring tare offset).

        Args:
            times: Number of readings to average.

        Returns:
            Mean raw value (float), or None on error.
        """
        try:
            value = self.hx.read_average(times)
            return value
        except Exception as e:
            print(f"[LoadCell] Raw read error: {e}")
            return None

    def get_weight(self, times=DEFAULT_READINGS):
        """
        Get weight in grams. Requires prior calibration.

        Args:
            times: Number of readings to average for better accuracy.

        Returns:
            Weight in grams (float), or None if not calibrated / error.
        """
        if not self._calibrated:
            print("[LoadCell] ERROR: Not calibrated. Run calibrate_hx711.py first.")
            return None

        try:
            weight = self.hx.get_weight(times)
            return round(weight, 1)
        except Exception as e:
            print(f"[LoadCell] Weight read error: {e}")
            return None

    def get_stable_weight(self, target_readings=10, stability_threshold=0.5,
                          timeout=10):
        """
        Get a stable weight reading. Waits until consecutive readings
        agree within the threshold, or until timeout.

        Args:
            target_readings: Number of consecutive stable readings required.
            stability_threshold: Max allowed deviation (grams) between readings.
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
            w = self.get_weight(times=10)
            if w is None:
                continue

            readings.append(w)

            # Check last N readings for stability
            if len(readings) >= target_readings:
                recent = readings[-target_readings:]
                spread = max(recent) - min(recent)
                if spread <= stability_threshold:
                    avg = sum(recent) / len(recent)
                    return round(avg, 1)

            time.sleep(0.1)

        # Timeout - return best estimate from last readings
        if readings:
            last_few = readings[-5:] if len(readings) >= 5 else readings
            avg = sum(last_few) / len(last_few)
            spread = max(last_few) - min(last_few)
            print(f"[LoadCell] Stability timeout. Best estimate: {avg:.1f}g "
                  f"(spread: {spread:.2f}g)")
            return round(avg, 1)
        return None

    def calibrate(self, known_weight_grams, times=50):
        """
        Calibrate the scale using a known weight.

        Steps:
            1. Tare the scale first (nothing on it).
            2. Place the known weight.
            3. Call this method.

        Args:
            known_weight_grams: The exact weight of your calibration object (grams).
            times: Number of readings to average for calibration.

        Returns:
            The reference unit (float) if successful, None otherwise.
        """
        print(f"[LoadCell] Calibrating with {known_weight_grams}g reference weight...")
        print(f"[LoadCell] Taking {times} readings...")

        # Read raw value (offset already subtracted by get_value)
        # With reference_unit=1, get_value returns raw - offset
        self.hx.set_reference_unit(1)
        raw_value = self.hx.get_value(times)

        if raw_value == 0:
            print("[LoadCell] ERROR: Raw value is 0. Check wiring and load cell.")
            return None

        # reference_unit = raw_value_per_gram
        self._reference_unit = raw_value / known_weight_grams
        self.hx.set_reference_unit(self._reference_unit)
        self._calibrated = True

        print(f"[LoadCell] Calibration complete!")
        print(f"  Raw value with {known_weight_grams}g: {raw_value:.0f}")
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

        Args:
            filepath: Path to save file. Defaults to calibration.json in script dir.
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

        Args:
            filepath: Path to calibration file. Defaults to calibration.json in script dir.

        Returns:
            True if loaded successfully, False otherwise.
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

    # Tare
    input("Remove everything from the load cell, then press Enter...")
    lc.tare()
    print()

    # Check if calibrated
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
