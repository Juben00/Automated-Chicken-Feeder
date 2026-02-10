from hx711 import HX711
import time

hx = HX711(dout_pin=5, pd_sck_pin=6)

hx.reset()
hx.tare()

print("Testing HX711... Press Ctrl+C to stop")

try:
    while True:
        print("Raw:", hx.get_raw_data_mean())
        time.sleep(0.5)
except KeyboardInterrupt:
    print("Stopped")
