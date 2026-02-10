from hx711 import HX711
import time

hx = HX711(5, 6)  # DT, SCK

hx.tare()
print("HX711 ready – raw readings")

try:
    while True:
        raw = hx.read()
        print("Raw:", raw)
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Stopped")
