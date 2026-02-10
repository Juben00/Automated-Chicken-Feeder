from load_cell import LoadCell
import time

lc = LoadCell(dout_pin=5, sck_pin=6)

print("HX711 Calibration Test")
print("Press Ctrl+C to stop.\n")

input("Remove all weight from the scale, then press Enter...")
lc.tare()

input("Place known weight on scale, then press Enter...")
time.sleep(1.5)

known_weight_grams = input("Enter known weight in grams: ")
value = float(known_weight_grams)

lc.calibrate(value)
lc.save_calibration()

print(f"\nCalibrated for {value}g. Reading weight...\n")

try:
    while True:
        weight = lc.get_grams()
        print(f"{weight:.2f} g")
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\nStopped")
finally:
    lc.close()
