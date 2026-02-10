import RPi.GPIO as GPIO
import time
from hx711 import HX711

GPIO.setmode(GPIO.BCM)

hx = HX711(5, 6)
hx.set_reading_format("MSB", "MSB")
hx.reset()

print("HX711 Calibration Test")
print("Press Ctrl+C to stop.\n")

try:
    # Step 1: Tare
    input("Remove all weight from the scale, then press Enter...")
    hx.tare(times=30)
    print(f"Tare complete. Offset: {hx.get_offset():.1f}\n")

    # Step 2: Calibrate
    input("Place known weight on scale, then press Enter...")
    time.sleep(1.5)

    known_weight_grams = input("Enter known weight in grams: ")
    value = float(known_weight_grams)

    # Read raw minus offset, then compute reference unit
    reading = hx.get_value(times=30)
    reference_unit = reading / value
    hx.set_reference_unit(reference_unit)
    print(f"Reference unit: {reference_unit:.4f}\n")

    # Step 3: Read weight continuously
    print("Reading weight...\n")
    while True:
        weight = hx.get_weight(times=5)
        print(f"{weight:.2f} g")
        hx.power_down()
        hx.power_up()
        time.sleep(0.3)

except KeyboardInterrupt:
    print("\nStopped")
finally:
    GPIO.cleanup()
