from hx711 import HX711
import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)

hx = HX711(dout_pin=5, pd_sck_pin=6)

while True:
    print(hx.get_raw_data_mean())
    
