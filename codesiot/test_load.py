from hx711 import HX711
import time

hx = HX711(dout_pin=5, pd_sck_pin=6)

hx.reset()
hx.tare()

print("HX711 ready. Reading raw values...")

try:
    while True:
        raw_value = hx.get_raw_data_mean()
        print("Raw Value:", raw_value)
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Stopped")
