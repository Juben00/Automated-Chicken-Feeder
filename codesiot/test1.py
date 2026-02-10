from hx711 import HX711
import time

hx = HX711(5, 6)

hx.set_reading_format("MSB", "MSB")
hx.set_reference_unit(1)
hx.reset()
hx.tare()

print("HX711 ready")

try:
    while True:
        value = hx.get_weight(5)
        print("Raw-ish value:", value)
        hx.power_down()
        hx.power_up()
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Stopped")
