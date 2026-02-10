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
    offset = hx.read_average(times=30)
    hx.set_offset(offset)
    print(f"Tare complete. Offset: {offset:.1f}\n")

    # Step 2: Calibrate
    input("Place known weight on scale, then press Enter...")
    time.sleep(1.5)

    known_weight_grams = input("Enter known weight in grams: ")
    value = float(known_weight_grams)

    raw_with_weight = hx.read_average(times=30)
    reading = raw_with_weight - offset
    reference_unit = reading / value
    hx.set_reference_unit(reference_unit)
    print(f"Reference unit: {reference_unit:.4f}\n")

    # Step 3: Read weight continuously
    print("Reading weight...\n")
    while True:
        raw = hx.read_average(times=5)
        grams = (raw - offset) / reference_unit
        print(f"{grams:.2f} g")
        hx.power_down()
        hx.power_up()
        time.sleep(0.3)

except KeyboardInterrupt:
    print("\nStopped")
finally:
    GPIO.cleanup()
