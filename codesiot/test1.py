import RPi.GPIO as GPIO
import time
from hx711 import HX711

GPIO.setmode(GPIO.BCM)

hx = HX711(5, 6)
hx.set_reading_format("MSB", "MSB")
hx.reset()

print("HX711 ready – raw readings")
print("Press Ctrl+C to stop.\n")

try:
    while True:
        raw = hx.read_average(times=5)
        print(f"Raw: {raw:.1f}")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")
finally:
    GPIO.cleanup()
