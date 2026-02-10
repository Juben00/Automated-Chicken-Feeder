"""List all available methods on the installed HX711 class."""
import RPi.GPIO as GPIO
from hx711 import HX711

GPIO.setmode(GPIO.BCM)
hx = HX711(5, 6)

print("Installed HX711 methods:")
for name in sorted(dir(hx)):
    if not name.startswith('_'):
        print(f"  {name}")

GPIO.cleanup()
