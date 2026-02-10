from hx711 import HX711
import time

hx = HX711(5, 6)  # DT, SCK

hx.reset()
hx.tare()

print("HX711 raw data test")

try:
    while True:
        raw = hx.get_raw_data()
        print("Raw value:", raw)
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Stopped")
