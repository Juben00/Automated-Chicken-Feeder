import RPi.GPIO as GPIO
import time
import statistics
from hx711 import HX711

GPIO.setmode(GPIO.BCM)

hx = HX711(5, 6)
hx.reset()

print("HX711 ready – raw readings")
print("Press Ctrl+C to stop.\n")

try:
    while True:
        data = hx.get_raw_data(num_measures=5)
        if data:
            avg = statistics.mean(data)
            print(f"Raw: {avg:.1f}")
        else:
            print("Error reading")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")
finally:
    GPIO.cleanup()
