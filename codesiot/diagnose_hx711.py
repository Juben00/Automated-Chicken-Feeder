#!/usr/bin/env python3
"""
HX711 Diagnostic Script
========================
Run this to figure out why your load cell is reading 0.
It tests raw communication, checks for signal changes,
and helps you identify wiring or library issues.

Usage:
    sudo python3 diagnose_hx711.py

Wiring (HX711 -> Raspberry Pi):
    VCC  -> 3.3V or 5V
    GND  -> GND
    DT   -> GPIO 5  (Pin 29)  [Data]
    SCK  -> GPIO 6  (Pin 31)  [Clock]
"""

import sys
import time

# ─── Configuration ────────────────────────────────────────────────
DT_PIN  = 5   # Data pin  (DOUT on HX711)
SCK_PIN = 6   # Clock pin (PD_SCK on HX711)

print("=" * 60)
print("  HX711 DIAGNOSTIC TOOL")
print("=" * 60)
print(f"  DT  (Data)  pin: GPIO {DT_PIN}")
print(f"  SCK (Clock) pin: GPIO {SCK_PIN}")
print("=" * 60)


# ─── Test 1: Check which hx711 library is installed ──────────────
print("\n[TEST 1] Checking which HX711 library is imported...")

try:
    import hx711 as hx711_module
    module_file = getattr(hx711_module, '__file__', 'unknown')
    print(f"  Module location: {module_file}")

    # Check if it's the tatobari version (has RPi.GPIO dependency, specific methods)
    hx711_class = getattr(hx711_module, 'HX711', None)
    if hx711_class is None:
        # Try submodule import
        try:
            from hx711 import HX711
            hx711_class = HX711
        except ImportError:
            print("  ERROR: Cannot import HX711 class!")
            sys.exit(1)

    # Inspect constructor signature to identify which library
    import inspect
    sig = inspect.signature(hx711_class.__init__)
    params = list(sig.parameters.keys())
    print(f"  HX711.__init__ parameters: {params}")

    if 'dout' in params and 'pd_sck' in params:
        LIB_TYPE = "tatobari"
        print("  >> Detected: tatobari/hx711py library (RPi.GPIO based)")
    elif 'dout_pin' in params and ('pd_sck_pin' in params or 'sck_pin' in params):
        LIB_TYPE = "pip"
        print("  >> Detected: pip 'hx711' package")
    else:
        LIB_TYPE = "unknown"
        print(f"  >> Unknown library variant. Parameters: {params}")

except ImportError:
    print("  ERROR: No hx711 module found!")
    print("  Install with: sudo pip3 install hx711")
    print("  OR clone: git clone https://github.com/tatobari/hx711py.git")
    sys.exit(1)


# ─── Test 2: Check RPi.GPIO access ──────────────────────────────
print("\n[TEST 2] Checking GPIO access...")
try:
    import RPi.GPIO as GPIO
    print(f"  RPi.GPIO version: {GPIO.VERSION}")
    print("  GPIO access: OK")
except ImportError:
    print("  WARNING: RPi.GPIO not available.")
    print("  The tatobari library requires RPi.GPIO.")
    print("  Install with: sudo pip3 install RPi.GPIO")
except RuntimeError as e:
    print(f"  ERROR: {e}")
    print("  Make sure you run this script with sudo!")
    sys.exit(1)


# ─── Test 3: Initialize HX711 and read raw values ───────────────
print("\n[TEST 3] Initializing HX711 and reading RAW values...")
print("  (This tests basic communication with the chip)")

try:
    from hx711 import HX711

    if LIB_TYPE == "tatobari":
        hx = HX711(DT_PIN, SCK_PIN)
        hx.set_reading_format("MSB", "MSB")
        hx.set_reference_unit(1)  # Raw values, no scaling
        hx.reset()
        time.sleep(0.5)

        print("\n  Reading 10 raw samples (reference_unit=1, no tare)...")
        raw_values = []
        for i in range(10):
            val = hx.read_long()
            raw_values.append(val)
            print(f"    Sample {i+1:2d}: {val}")
            time.sleep(0.1)

    elif LIB_TYPE == "pip":
        # Try different constructor signatures
        try:
            hx = HX711(dout_pin=DT_PIN, pd_sck_pin=SCK_PIN)
        except TypeError:
            try:
                hx = HX711(dout_pin=DT_PIN, sck_pin=SCK_PIN)
            except TypeError:
                hx = HX711(DT_PIN, SCK_PIN)

        hx.reset()
        time.sleep(0.5)

        print("\n  Reading 10 raw samples...")
        raw_values = []
        for i in range(10):
            # Try different method names
            val = None
            for method_name in ['get_raw_data_mean', 'get_raw_data', 'read_long']:
                method = getattr(hx, method_name, None)
                if method:
                    try:
                        result = method(readings=3) if 'readings' in str(inspect.signature(method)) else method(3)
                        if isinstance(result, list):
                            result = result[0] if result else None
                        val = result
                        break
                    except Exception:
                        continue

            if val is None:
                val = 0
                print(f"    Sample {i+1:2d}: FAILED TO READ")
            else:
                raw_values.append(val)
                print(f"    Sample {i+1:2d}: {val}")
            time.sleep(0.1)

    else:
        print("  Cannot test - unknown library type.")
        raw_values = []

except Exception as e:
    print(f"\n  ERROR during initialization/reading: {e}")
    import traceback
    traceback.print_exc()
    print("\n  POSSIBLE CAUSES:")
    print("  - Not running as sudo (required for GPIO)")
    print("  - Wrong GPIO pin numbers")
    print("  - HX711 not powered or not connected")
    sys.exit(1)


# ─── Test 4: Analyze raw values ─────────────────────────────────
print("\n[TEST 4] Analyzing raw values...")

if not raw_values:
    print("  No values to analyze!")
    sys.exit(1)

all_zero = all(v == 0 for v in raw_values)
all_same = len(set(raw_values)) == 1
min_val = min(raw_values)
max_val = max(raw_values)
spread = max_val - min_val
avg_val = sum(raw_values) / len(raw_values)

print(f"  Count:   {len(raw_values)}")
print(f"  Min:     {min_val}")
print(f"  Max:     {max_val}")
print(f"  Average: {avg_val:.0f}")
print(f"  Spread:  {spread}")
print(f"  All zero: {all_zero}")
print(f"  All same: {all_same}")

if all_zero:
    print("\n  >> DIAGNOSIS: All values are ZERO")
    print("     This typically means:")
    print("     1. DT (Data) and SCK (Clock) wires are SWAPPED")
    print("        - Try swapping GPIO 5 and GPIO 6 connections")
    print("     2. The HX711 board is not getting power")
    print("        - Check VCC and GND connections")
    print("     3. Load cell is not connected to the HX711 board")
    print("        - Check E+, E-, A+, A- connections on HX711")
    print("     4. Wrong GPIO pin numbers in the script")
    print("        - Verify which GPIO pins you actually wired to")

elif all_same:
    print("\n  >> DIAGNOSIS: All values are THE SAME (but not zero)")
    print(f"     Constant value: {raw_values[0]}")
    print("     This typically means:")
    print("     1. The load cell is not connected (HX711 reads internal noise)")
    print("     2. Load cell wires are on wrong terminals (try A+/A- vs B+/B-)")

elif spread < 100:
    print("\n  >> Values look stable (low noise). Basic communication is working.")
    print("     The HX711 is responding. Now let's test weight detection...")
else:
    print("\n  >> Values have some spread, which is normal for HX711.")
    print("     Basic communication appears to be working.")


# ─── Test 5: Weight change detection ────────────────────────────
print("\n[TEST 5] Weight change detection...")
print("  This test checks if the sensor reacts when you apply pressure.")
print()

input("  Step A: Make sure NOTHING is on the load cell. Press Enter...")
print("  Reading empty scale...")
time.sleep(1)

empty_values = []
for i in range(10):
    if LIB_TYPE == "tatobari":
        val = hx.read_long()
    else:
        val = None
        for method_name in ['get_raw_data_mean', 'get_raw_data', 'read_long']:
            method = getattr(hx, method_name, None)
            if method:
                try:
                    result = method(readings=3) if 'readings' in str(inspect.signature(method)) else method(3)
                    if isinstance(result, list):
                        result = result[0] if result else None
                    val = result
                    break
                except Exception:
                    continue
        if val is None:
            val = 0
    empty_values.append(val)
    time.sleep(0.1)

empty_avg = sum(empty_values) / len(empty_values)
print(f"  Empty average: {empty_avg:.0f}")

print()
input("  Step B: Now PRESS DOWN or place weight on the load cell. Press Enter...")
print("  Reading with weight...")
time.sleep(1)

weight_values = []
for i in range(10):
    if LIB_TYPE == "tatobari":
        val = hx.read_long()
    else:
        val = None
        for method_name in ['get_raw_data_mean', 'get_raw_data', 'read_long']:
            method = getattr(hx, method_name, None)
            if method:
                try:
                    result = method(readings=3) if 'readings' in str(inspect.signature(method)) else method(3)
                    if isinstance(result, list):
                        result = result[0] if result else None
                    val = result
                    break
                except Exception:
                    continue
        if val is None:
            val = 0
    weight_values.append(val)
    time.sleep(0.1)

weight_avg = sum(weight_values) / len(weight_values)
print(f"  Weighted average: {weight_avg:.0f}")

difference = weight_avg - empty_avg
print(f"\n  Difference (weighted - empty): {difference:.0f}")

if abs(difference) < 50:
    print("\n  >> DIAGNOSIS: NO CHANGE detected when weight was applied!")
    print("     This means:")
    print("     1. Load cell is NOT connected, or wired wrong")
    print("        - Check the 4 wires from load cell to HX711:")
    print("          Red   -> E+ (Excitation+)")
    print("          Black -> E- (Excitation-)")
    print("          White -> A- (Signal-)")
    print("          Green -> A+ (Signal+)")
    print("        - NOTE: Wire colors vary by manufacturer!")
    print("     2. Load cell is not MOUNTED properly")
    print("        - One end must be fixed, the other must flex")
    print("        - Weight must cause the load cell to BEND")
    print("     3. Load cell might be damaged")
    print()
    print("     QUICK TEST: Try pressing directly on the load cell")
    print("     metal bar with your finger while the script reads.")
elif abs(difference) > 50:
    print("\n  >> SUCCESS! The sensor IS detecting weight changes!")
    print(f"     Raw change: {difference:.0f}")
    print()
    print("     The reason you see '0' in example.py is likely because:")
    print("     1. The reference_unit (114) doesn't match YOUR load cell.")
    print("        Every load cell has a different reference unit.")
    print("     2. You need to CALIBRATE for your specific load cell.")
    print()
    if difference > 0:
        print(f"     To calculate YOUR reference unit:")
        print(f"       1. Place a known weight (e.g., 1000g) on the cell")
        print(f"       2. Your reference_unit = raw_difference / weight_in_grams")
        print(f"       3. Example: {difference:.0f} / 1000 = {difference/1000:.2f}")
        print(f"     Then use: hx.set_reference_unit({difference/1000:.1f})")


# ─── Test 6: Try both byte orders ───────────────────────────────
if LIB_TYPE == "tatobari":
    print("\n[TEST 6] Testing byte order formats...")

    for byte_fmt in ["MSB", "LSB"]:
        for bit_fmt in ["MSB", "LSB"]:
            hx.set_reading_format(byte_fmt, bit_fmt)
            vals = []
            for _ in range(5):
                vals.append(hx.read_long())
                time.sleep(0.05)
            avg = sum(vals) / len(vals)
            spread = max(vals) - min(vals)
            print(f"  byte={byte_fmt} bit={bit_fmt}: avg={avg:>12.0f}  spread={spread:>8}")

    print("\n  >> Pick the format with the most STABLE values (smallest spread)")
    print("     and values that are NOT zero or near 8388607 (0x7FFFFF).")

    # Reset to default
    hx.set_reading_format("MSB", "MSB")


# ─── Summary ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  DIAGNOSTIC SUMMARY")
print("=" * 60)
print(f"  Library: {LIB_TYPE}")
print(f"  Raw values all zero: {all_zero}")
print(f"  Weight change detected: {abs(difference) > 50 if 'difference' in dir() else 'N/A'}")
print()
print("  COMMON FIXES:")
print("  1. Swap DT and SCK wires (most common mistake)")
print("  2. Check load cell wiring to HX711 board")
print("  3. Make sure load cell can physically flex/bend")
print("  4. Run with: sudo python3 diagnose_hx711.py")
print("  5. Use YOUR calibrated reference_unit, not 114")
print("=" * 60)

# Cleanup
try:
    import RPi.GPIO as GPIO
    GPIO.cleanup()
except Exception:
    pass
