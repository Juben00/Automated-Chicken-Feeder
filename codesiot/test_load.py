import time
import sys
from hx711 import HX711

hx = HX711(dout_pin=5, sck_pin=6)

hx.reset()

print("Ready to measure weight...")

try:
    while True:
        reading = hx.get_raw_data_mean(readings=5)
        print(f"Reading: {reading}")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("Exiting...")
    sys.exit(0)