import time
import sys

try:
    from hx711 import HX711
except ImportError:
    print("ERROR: hx711 module not found.")
    print("Install it with: sudo python3 -m pip install hx711")
    sys.exit(1)

hx = HX711(dout_pin=5, pd_sck_pin=6, channel='A', gain=64)

hx.reset()

print("Ready to measure weight...")

try:
    while True:
        reading = hx.get_raw_data(times=5)
        print(f"Reading: {reading}")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("Exiting...")
    sys.exit(0)