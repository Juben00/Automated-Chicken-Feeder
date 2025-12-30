import cv2
import os
import datetime

def capture_image():
    folder = "captures"
    os.makedirs(folder, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{folder}/feed_{timestamp}.jpg"
    print("Capturing image from webcam...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return None
    ret, frame = cap.read()
    cap.release()
    if ret:
        cv2.imwrite(path, frame)
        print(f"Image saved at {path}")
        return path
    else:
        print("Error: Could not capture image.")
        return None
