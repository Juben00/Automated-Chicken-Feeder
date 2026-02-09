#!/usr/bin/env python3
"""
HX711 Load Cell Real-Time Weight Tracker
=========================================
Continuously reads weight from an HX711 load cell amplifier
and prints the value in real-time to the terminal.

Wiring (HX711 -> Raspberry Pi):
    VCC  -> 3.3V or 5V
    GND  -> GND
    DT   -> GPIO 5  (Pin 29)  [Data]
    SCK  -> GPIO 6  (Pin 31)  [Clock]

Usage:
    sudo python3 test_hx711.py

    Options:
        --dt   INT   GPIO pin for HX711 data   (default: 5)
        --sck  INT   GPIO pin for HX711 clock  (default: 6)
        --ref  FLOAT Reference unit calibration (default: 1.0)
        --samples INT Number of samples to average per reading (default: 5)
        --interval FLOAT  Seconds between readings (default: 0.5)
"""

import pigpio
import time
import sys
import argparse
import signal

# ─── GPIO Pin Defaults ───────────────────────────────────────────────
DEFAULT_DT_PIN  = 5    # HX711 Data pin  (GPIO 5 / Pin 29)
DEFAULT_SCK_PIN = 6    # HX711 Clock pin (GPIO 6 / Pin 31)


class HX711:
    """
    Driver for the HX711 24-bit ADC for load cells using pigpio.
    """

    def __init__(self, pi, dout_pin, sck_pin, gain=128):
        self.pi = pi
        self.dout = dout_pin
        self.sck = sck_pin
        self.gain = gain
        self.offset = 0
        self.reference_unit = 1.0

        # Configure pins
        self.pi.set_mode(self.dout, pigpio.INPUT)
        self.pi.set_mode(self.sck, pigpio.OUTPUT)
        self.pi.write(self.sck, 0)

        # Set gain
        self._set_gain(gain)

    def _set_gain(self, gain):
        """Set the gain for the next reading. gain: 128, 64, or 32."""
        if gain == 128:
            self._gain_pulses = 1
        elif gain == 64:
            self._gain_pulses = 3
        elif gain == 32:
            self._gain_pulses = 2
        else:
            self._gain_pulses = 1  # default to 128

        # Perform a dummy read to set the gain
        self._read_raw()

    def _is_ready(self):
        """Check if the HX711 has data ready (DOUT goes LOW)."""
        return self.pi.read(self.dout) == 0

    def _wait_ready(self, timeout=2.0):
        """Wait until HX711 is ready or timeout."""
        start = time.time()
        while not self._is_ready():
            if time.time() - start > timeout:
                raise TimeoutError("HX711 not ready - check wiring and connections!")
            time.sleep(0.001)

    def _read_raw(self):
        """Read a single raw 24-bit value from the HX711."""
        self._wait_ready()

        # Read 24 bits of data
        raw = 0
        for _ in range(24):
            self.pi.write(self.sck, 1)
            time.sleep(0.000001)  # 1 microsecond pulse
            raw = (raw << 1) | self.pi.read(self.dout)
            self.pi.write(self.sck, 0)
            time.sleep(0.000001)

        # Set gain for NEXT reading (1-3 extra clock pulses)
        for _ in range(self._gain_pulses):
            self.pi.write(self.sck, 1)
            time.sleep(0.000001)
            self.pi.write(self.sck, 0)
            time.sleep(0.000001)

        # Convert from 24-bit two's complement
        if raw & 0x800000:
            raw -= 0x1000000

        return raw

    def read_average(self, num_samples=5):
        """Read multiple samples and return the average raw value."""
        values = []
        for _ in range(num_samples):
            try:
                val = self._read_raw()
                values.append(val)
            except TimeoutError:
                continue

        if not values:
            raise TimeoutError("Could not get any readings from HX711")

        return sum(values) / len(values)

    def get_weight(self, num_samples=5):
        """Get weight in grams (after tare and calibration)."""
        raw_avg = self.read_average(num_samples)
        return (raw_avg - self.offset) / self.reference_unit

    def tare(self, num_samples=15):
        """Tare the scale (set current weight as zero)."""
        print("Taring... Remove all weight from the scale.")
        time.sleep(2)
        self.offset = self.read_average(num_samples)
        print(f"Tare complete. Offset = {self.offset:.0f}")

    def set_reference_unit(self, reference_unit):
        """Set the calibration reference unit (raw counts per gram)."""
        if reference_unit == 0:
            raise ValueError("Reference unit cannot be zero.")
        self.reference_unit = reference_unit

    def power_down(self):
        """Put the HX711 into low-power mode."""
        self.pi.write(self.sck, 0)
        self.pi.write(self.sck, 1)
        time.sleep(0.0001)

    def power_up(self):
        """Wake the HX711 from low-power mode."""
        self.pi.write(self.sck, 0)
        time.sleep(0.0005)


def calibrate(hx):
    """
    Interactive calibration routine.
    Place a known weight on the scale and enter the weight in grams.
    Returns the reference unit.
    """
    print("\n" + "=" * 50)
    print("  CALIBRATION MODE")
    print("=" * 50)
    print("\nStep 1: Make sure the scale is EMPTY, then press Enter...")
    input()
    hx.tare()

    print("\nStep 2: Place a KNOWN weight on the scale, then press Enter...")
    input()

    raw_value = hx.read_average(num_samples=20)
    adjusted = raw_value - hx.offset

    known_weight = float(input("Step 3: Enter the known weight in grams: "))
    if known_weight <= 0:
        print("Invalid weight. Calibration aborted.")
        return 1.0

    reference_unit = adjusted / known_weight
    hx.set_reference_unit(reference_unit)

    print(f"\nCalibration complete!")
    print(f"  Raw value:      {raw_value:.0f}")
    print(f"  Offset:         {hx.offset:.0f}")
    print(f"  Adjusted:       {adjusted:.0f}")
    print(f"  Reference unit: {reference_unit:.2f}")
    print(f"\nUse --ref {reference_unit:.2f} next time to skip calibration.")
    print("=" * 50 + "\n")

    return reference_unit


def main():
    parser = argparse.ArgumentParser(
        description="HX711 Load Cell Real-Time Weight Tracker"
    )
    parser.add_argument("--dt", type=int, default=DEFAULT_DT_PIN,
                        help=f"GPIO pin for HX711 data (default: {DEFAULT_DT_PIN})")
    parser.add_argument("--sck", type=int, default=DEFAULT_SCK_PIN,
                        help=f"GPIO pin for HX711 clock (default: {DEFAULT_SCK_PIN})")
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

    # Connect to pigpio daemon
    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: Cannot connect to pigpio daemon.")
        print("Start it with: sudo pigpiod")
        sys.exit(1)

    print("=" * 55)
    print("  HX711 Load Cell - Real-Time Weight Tracker")
    print("=" * 55)
    print(f"  Data pin (DT):   GPIO {args.dt}")
    print(f"  Clock pin (SCK): GPIO {args.sck}")
    print(f"  Samples/reading: {args.samples}")
    print(f"  Read interval:   {args.interval}s")
    print(f"  Reference unit:  {args.ref}")
    print("=" * 55)

    # Initialize HX711
    try:
        hx = HX711(pi, dout_pin=args.dt, sck_pin=args.sck)
    except Exception as e:
        print(f"\nERROR initializing HX711: {e}")
        pi.stop()
        sys.exit(1)

    # Calibration mode
    if args.calibrate:
        calibrate(hx)
    else:
        hx.set_reference_unit(args.ref)

    # Tare on startup
    if args.tare or args.calibrate:
        hx.tare(num_samples=15)
    else:
        print("\nSkipping tare (use --tare to zero the scale on startup)")

    # Graceful shutdown
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n\nShutting down...")

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
                raw = hx.read_average(args.samples)
                weight = (raw - hx.offset) / hx.reference_unit
                reading_count += 1

                # Track min/max
                min_weight = min(min_weight, weight)
                max_weight = max(max_weight, weight)

                # Determine status indicator
                if abs(weight) < 1.0:
                    status = "[ EMPTY ]"
                elif weight < 0:
                    status = "[ !! NEGATIVE !! ]"
                else:
                    status = f"[  OK  ]"

                timestamp = time.strftime("%H:%M:%S")

                # Print with carriage return for clean real-time display
                print(f"  {timestamp:<12} {weight:>10.1f} g  {raw:>12.0f}  {status}")

                time.sleep(args.interval)

            except TimeoutError:
                print(f"  {time.strftime('%H:%M:%S'):<12} {'---':>12}  {'---':>12}  [ TIMEOUT - check wiring ]")
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

    # Cleanup
    hx.power_down()
    pi.stop()
    print("  GPIO cleaned up. Goodbye!\n")


if __name__ == "__main__":
    main()
