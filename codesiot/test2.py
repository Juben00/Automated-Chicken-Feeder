import RPi.GPIO as GPIO
import time
import statistics
from hx711 import HX711

GPIO.setmode(GPIO.BCM)

hx = HX711(5, 6)
hx.reset()

print("HX711 Calibration Test")
print("Press Ctrl+C to stop.\n")


def read_mean(num=30):
    """Read num samples and return the mean."""
    data = hx.get_raw_data(num_measures=num)
    if data:
        return statistics.mean(data)
    return None


try:
    # Step 1: Tare
    input("Remove all weight from the scale, then press Enter...")
    offset = read_mean(30)
    if offset is None:
        print("Error reading HX711. Check wiring.")
        raise SystemExit
    print(f"Tare complete. Offset: {offset:.1f}\n")

    # Step 2: Calibrate
    input("Place known weight on scale, then press Enter...")
    time.sleep(1.5)

    known_weight_grams = input("Enter known weight in grams: ")
    value = float(known_weight_grams)

    raw_with_weight = read_mean(30)
    if raw_with_weight is None:
        print("Error reading HX711.")
        raise SystemExit

    ratio = (raw_with_weight - offset) / value
    print(f"Scale ratio: {ratio:.4f}\n")

    # Step 3: Read weight continuously
    print("Reading weight...\n")
    while True:
        raw = read_mean(15)
        if raw is not None:
            grams = (raw - offset) / ratio
            print(f"{grams:.2f} g")
        else:
            print("Error reading")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")
finally:
    GPIO.cleanup()
