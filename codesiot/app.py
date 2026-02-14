from flask import Flask, jsonify, request
import requests, json, os
from servo import activate_servo
from camera import capture_image
import time
import math
import threading

app = Flask(__name__)

# Thread lock to prevent overlapping servo activations
servo_activation_lock = threading.Lock()

# Safety limit: maximum valve-open duration per single dispense (seconds)
MAX_DISPENSE_SECONDS = 60

# Load configuration
with open("config.json") as f:
    config = json.load(f)

UPLOAD_ENDPOINT = config["upload_endpoint"]
DEVICE_ID = config["device_id"]
USER_TOKEN = config["user_token"]

# Default flow rate: grams dispensed per second of valve-open time
# (fallback only — server always sends the live value via grams_per_second)
DEFAULT_GRAMS_PER_SECOND = 2.0

@app.route('/')
def home():
    return jsonify({"message": f"IoT device {DEVICE_ID} online."})

@app.route('/activate_servo', methods=['POST'])
def servo_route():
    data = request.get_json(silent=True) or {}
    duration = data.get('duration_seconds', 5)
    try:
        duration = float(duration)
        if duration <= 0:
            duration = 5
    except (ValueError, TypeError):
        duration = 5
    activate_servo(duration_seconds=duration)
    return jsonify({"status": "success", "message": f"Valve opened for {duration}s."})

@app.route('/capture_image', methods=['POST'])
def capture_route():
    image_path = capture_image()
    if image_path is None:
        return jsonify({"status": "error", "message": "Failed to capture image"}), 500
    return jsonify({"status": "success", "image_path": image_path})


# New route: full feed cycle (capture, upload, dispense)
@app.route('/feed_cycle', methods=['POST'])
def feed_cycle():
    """Capture image, upload to website, receive amount to dispense, then open valve for the calculated duration."""
    # Accept optional schedule_id forwarded from the main server
    req = request.get_json(silent=True) or {}
    schedule_id = req.get('schedule_id')

    image_path = capture_image()
    
    # Handle camera capture failure
    if image_path is None:
        return jsonify({
            "status": "error", 
            "message": "Failed to capture image from camera. Check camera connection."
        }), 500
    
    with open(image_path, 'rb') as img:
        files = {'image': img}
        # forward device_id and optionally schedule_id so server can resolve the correct schedule
        data = {'device_id': DEVICE_ID}
        if schedule_id is not None:
            data['schedule_id'] = schedule_id
        headers = {'Authorization': f'Bearer {USER_TOKEN}'}
        try:
            res = requests.post(UPLOAD_ENDPOINT, files=files, data=data, headers=headers)
            if res.status_code == 200:
                result = res.json()
                grams_to_dispense = result.get('grams_to_dispense', 0)
                # Server may send grams_per_second; fall back to legacy grams_per_drop as rough estimate
                grams_per_second = result.get('grams_per_second',
                                              result.get('grams_per_drop', DEFAULT_GRAMS_PER_SECOND))
                # Validate
                try:
                    grams_per_second = float(grams_per_second)
                    if grams_per_second <= 0 or grams_per_second > 50:
                        grams_per_second = DEFAULT_GRAMS_PER_SECOND
                except (ValueError, TypeError):
                    grams_per_second = DEFAULT_GRAMS_PER_SECOND

                # Dispense if any amount is needed
                if grams_to_dispense > 0:
                    # Calculate how long to keep the valve open
                    dispense_seconds = grams_to_dispense / grams_per_second
                    # Round up to nearest 0.1s so we slightly overfeed rather than underfeed
                    dispense_seconds = math.ceil(dispense_seconds * 10) / 10.0
                    # Safety cap
                    if dispense_seconds > MAX_DISPENSE_SECONDS:
                        print(f"Warning: capping {dispense_seconds}s to {MAX_DISPENSE_SECONDS}s")
                        dispense_seconds = MAX_DISPENSE_SECONDS
                    actual_dispensed = dispense_seconds * grams_per_second
                    print(f"Dispensing ~{actual_dispensed:.1f}g — valve open for {dispense_seconds}s ({grams_per_second} g/s)…")

                    # Run servo in background thread to respond quickly
                    def run_servo_cycle():
                        with servo_activation_lock:
                            try:
                                print(f"Starting feed cycle: valve open {dispense_seconds}s")
                                activate_servo(duration_seconds=dispense_seconds)
                                print(f"Feed cycle complete: dispensed ~{actual_dispensed:.1f}g")
                            except Exception as e:
                                print(f"Servo thread error: {e}")

                    thread = threading.Thread(target=run_servo_cycle, daemon=True)
                    thread.start()

                    return jsonify({
                        "status": "success",
                        "dispensed": round(actual_dispensed, 1),
                        "duration_seconds": dispense_seconds,
                        "grams_per_second": grams_per_second,
                        "response": result
                    })
                else:
                    print(f"No feed needed (grams_to_dispense={grams_to_dispense}). Skipping.")
                    return jsonify({"status": "no_dispense", "response": result})
            else:
                return jsonify({"status": "failed", "error": res.text}), 500
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/dispense', methods=['POST'])
def dispense_route():
    """Accept JSON {"amount_grams": int} or {"duration_seconds": float} and open
    the valve for the calculated/given duration.
    Returns JSON immediately while servo runs in background.
    """
    try:
        data = request.get_json() or {}

        # Option A: caller specifies duration directly
        duration = data.get('duration_seconds')

        if duration is not None:
            try:
                duration = float(duration)
            except (ValueError, TypeError):
                return jsonify({'error': 'duration_seconds must be a number'}), 400
            if duration <= 0 or duration > MAX_DISPENSE_SECONDS:
                return jsonify({'error': f'duration_seconds must be between 0 and {MAX_DISPENSE_SECONDS}'}), 400
        else:
            # Option B: caller specifies grams — we convert to duration
            amount = data.get('amount_grams') if data.get('amount_grams') is not None else data.get('amount')
            if amount is None:
                return jsonify({'error': 'amount_grams or duration_seconds required'}), 400
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return jsonify({'error': 'amount_grams must be a number'}), 400

            if amount < 1 or amount > 150:
                return jsonify({'error': 'Amount must be between 1 and 150 grams'}), 400

            # Read flow rate from request or use default
            grams_per_second = data.get('grams_per_second',
                                        data.get('grams_per_drop', DEFAULT_GRAMS_PER_SECOND))
            try:
                grams_per_second = float(grams_per_second)
                if grams_per_second <= 0 or grams_per_second > 50:
                    grams_per_second = DEFAULT_GRAMS_PER_SECOND
            except (ValueError, TypeError):
                grams_per_second = DEFAULT_GRAMS_PER_SECOND

            # Round up to nearest 0.1s
            duration = math.ceil((amount / grams_per_second) * 10) / 10.0
            if duration > MAX_DISPENSE_SECONDS:
                return jsonify({'error': f'Requested amount requires {duration}s (max {MAX_DISPENSE_SECONDS}s)'}), 400

        estimated_grams = round(duration * DEFAULT_GRAMS_PER_SECOND, 1)

        # Start servo in background thread so we can respond immediately
        def run_servo():
            with servo_activation_lock:
                try:
                    print(f"Starting dispense: valve open {duration}s (~{estimated_grams}g)")
                    activate_servo(duration_seconds=duration)
                    print(f"Dispensing complete: valve was open {duration}s")
                except Exception as e:
                    print(f"Servo thread error: {e}")

        thread = threading.Thread(target=run_servo, daemon=True)
        thread.start()

        return jsonify({'success': True, 'duration_seconds': duration, 'estimated_grams': estimated_grams}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
