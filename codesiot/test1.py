from load_cell import HX711
import time

hx = HX711(dout_pin=5, sck_pin=6)

print("HX711 ready – raw readings")
print("Press Ctrl+C to stop.\n")

try:
    while True:
        raw = hx.read_raw_average(samples=5)
        print(f"Raw: {raw:.1f}")
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\nStopped")
finally:
    hx.cleanup()
