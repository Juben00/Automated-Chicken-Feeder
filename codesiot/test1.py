import RPi.GPIO as GPIO
import time
from hx711 import HX711

GPIO.setmode(GPIO.BCM)

hx = HX711(dout_pin=5, pd_sck_pin=6, gain_channel_A=128, select_channel='A')
hx.reset()

print("HX711 ready – raw readings")
print("Press Ctrl+C to stop.\n")

try:
    while True:
        raw = hx.get_raw_data_mean(readings=5)
        if raw is not False:
            print(f"Raw: {raw}")
        else:
            print("Error reading")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")
finally:
    GPIO.cleanup()
