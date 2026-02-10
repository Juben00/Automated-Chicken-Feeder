from load_cell import HX711
import time

hx = HX711(dout_pin=5, sck_pin=6)

print("HX711 ready – raw readings")
print("Press Ctrl+C to stop.\n")

hx.zero()

input('place known weight on scale:')
reading = hx.get_data_mean(readings=100)

known_weight_grams = input('enter known weight')
value = float(known_weight_grams)

 ration = reading/value
 hx.set_scale_ratio(ratio)

 while True:
    weight = hx.get_weight_mean()
    print(weight)