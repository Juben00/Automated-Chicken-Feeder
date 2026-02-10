from hx711 import HX711
import time

hx = HX711(5, 6)

hx.set_reading_format("MSB", "MSB")
hx.set_reference_unit(1)
hx.reset()
hx.tare()

print("Place known weight (e.g. 500g)")
time.sleep(5)

value = hx.get_weight(10)
known_weight = 500  # grams

reference_unit = value / known_weight

print("Reference unit:", reference_unit)
