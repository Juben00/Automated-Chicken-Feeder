import RPi.GPIO as GPIO
import time
from hx711 import HX711

GPIO.setmode(GPIO.BCM)

hx = HX711(5, 6)
hx.reset()

print("HX711 Calibration Test")
print("Press Ctrl+C to stop.\n")

try:
    input("Remove all weight from the scale, then press Enter...")
    hx.zero()
    print("Tare complete.\n")

    input("Place known weight on scale, then press Enter...")
    time.sleep(1.5)

    reading = hx.get_data_mean(readings=30)
    if reading is False:
        print("Error: could not read data from HX711.")
    else:
        known_weight_grams = input("Enter known weight in grams: ")
        value = float(known_weight_grams)

        ratio = reading / value
        hx.set_scale_ratio(ratio)
        print(f"Scale ratio set to: {ratio:.4f}\n")

        print("Reading weight...\n")
        while True:
            weight = hx.get_weight_mean(readings=15)
            if weight is not False:
                print(f"{weight:.2f} g")
            else:
                print("Error reading")
            time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")
finally:
    GPIO.cleanup()
