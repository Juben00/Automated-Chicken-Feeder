from hx711 import HX711
import time

REFERENCE_UNIT = 213.4  # replace with yours

hx = HX711(5, 6)
hx.set_reading_format("MSB", "MSB")
hx.set_reference_unit(REFERENCE_UNIT)
hx.reset()
hx.tare()

print("Real-time weight")

try:
    while True:
        weight = hx.get_weight(5)
        print(f"Weight: {weight:.2f} g")
        hx.power_down()
        hx.power_up()
        time.sleep(0.3)

except KeyboardInterrupt:
    print("Done")
