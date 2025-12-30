from flask import Flask, jsonify, request
import requests, json, os
from servo import activate_servo
from camera import capture_image
import time

app = Flask(__name__)

# Load configuration
with open("config.json") as f:
    config = json.load(f)

UPLOAD_ENDPOINT = config["upload_endpoint"]
DEVICE_ID = config["device_id"]
USER_TOKEN = config["user_token"]

@app.route('/')
def home():
    return jsonify({"message": f"IoT device {DEVICE_ID} online."})

@app.route('/activate_servo', methods=['POST'])
def servo_route():
    activate_servo()
    return jsonify({"status": "success", "message": "Servo activated."})

@app.route('/capture_image', methods=['POST'])
def capture_route():
    image_path = capture_image()
    return jsonify({"status": "success", "image_path": image_path})


# New route: full feed cycle (capture, upload, dispense)
@app.route('/feed_cycle', methods=['POST'])
def feed_cycle():
    """Capture image, upload to website, receive amount to dispense, then activate servo in 5g increments."""
    # Accept optional schedule_id forwarded from the main server
    req = request.get_json(silent=True) or {}
    schedule_id = req.get('schedule_id')

    image_path = capture_image()
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
                # Only dispense if >= 5g
                if grams_to_dispense >= 5:
                    # Round down to nearest 5g
                    num_cycles = int(grams_to_dispense // 5)
                    actual_dispensed = num_cycles * 5
                    print(f"Dispensing {actual_dispensed} grams in {num_cycles} cycles...")
                    for i in range(num_cycles):
                        print(f"Cycle {i+1}: Rotating servo to 0° (fill cup)")
                        activate_servo(position=0)
                        time.sleep(0.5)
                        print(f"Cycle {i+1}: Rotating servo to 180° (drop cup)")
                        activate_servo(position=180)
                        time.sleep(0.5)
                    return jsonify({"status": "success", "dispensed": actual_dispensed, "response": result})
                else:
                    print("Requested amount less than 5g. No dispensing.")
                    return jsonify({"status": "no_dispense", "response": result})
            else:
                return jsonify({"status": "failed", "error": res.text}), 500
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/dispense', methods=['POST'])
def dispense_route():
    """Accept JSON {"amount_grams": int} and run servo cycles accordingly.
    Returns JSON immediately while servo runs in background.
    """
    try:
        data = request.get_json() or {}
        # accept either amount_grams or legacy 'amount'
        amount = data.get('amount_grams') if data.get('amount_grams') is not None else data.get('amount')
        if amount is None:
            return jsonify({'error': 'amount_grams required'}), 400
        try:
            amount = int(amount)
        except ValueError:
            return jsonify({'error': 'amount_grams must be an integer'}), 400

        if amount < 5 or amount > 150:
            return jsonify({'error': 'Amount must be between 5 and 150 grams'}), 400

        # run servo in 5g cycles (non-blocking - return response first)
        num_cycles = amount // 5
        actual_dispensed = num_cycles * 5
        
        # Start servo in background thread so we can respond immediately
        import threading
        def run_servo():
            try:
                for i in range(num_cycles):
                    # move to fill position, then drop
                    activate_servo(position=0)
                    activate_servo(position=180)
            except Exception as e:
                print(f"Servo thread error: {e}")
        
        thread = threading.Thread(target=run_servo, daemon=True)
        thread.start()
        
        # Return response immediately (don't wait for servo to finish)
        return jsonify({'success': True, 'dispensed': actual_dispensed}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
