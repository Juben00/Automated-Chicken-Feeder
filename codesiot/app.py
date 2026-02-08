from flask import Flask, jsonify, request
import requests, json, os
from servo import activate_servo
from camera import capture_image
import time

app = Flask(__name__)

# Track servo position to ensure every drop command results in actual movement
# This persists across requests so we always know where the servo is
SERVO_STATE_FILE = "/tmp/servo_position.txt"

def get_servo_position():
    """Get last known servo position (0 or 90). Defaults to 90."""
    try:
        with open(SERVO_STATE_FILE, 'r') as f:
            pos = int(f.read().strip())
            return pos if pos in [0, 90] else 90
    except:
        return 90  # Default: assume at 90

def set_servo_position(position):
    """Save current servo position to state file."""
    try:
        with open(SERVO_STATE_FILE, 'w') as f:
            f.write(str(position))
    except Exception as e:
        print(f"Warning: Could not save servo position: {e}")

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
    if image_path is None:
        return jsonify({"status": "error", "message": "Failed to capture image"}), 500
    return jsonify({"status": "success", "image_path": image_path})


# New route: full feed cycle (capture, upload, dispense)
@app.route('/feed_cycle', methods=['POST'])
def feed_cycle():
    """Capture image, upload to website, receive amount to dispense, then activate servo in 5g increments."""
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
                # Only dispense if >= 5g
                if grams_to_dispense >= 5:
                    # Each position (0° and 90°) drops 5g of feed
                    # Round UP to nearest 5g - always overfeed slightly rather than underfeed
                    # e.g., 27g -> 30g (6 drops), 25g -> 25g (5 drops)
                    import math
                    num_drops = math.ceil(grams_to_dispense / 5)
                    actual_dispensed = num_drops * 5
                    print(f"Dispensing {actual_dispensed} grams in {num_drops} drops...")
                    
                    # Run servo in background thread to respond quickly
                    import threading
                    def run_servo_cycle():
                        try:
                            # Get last known position so every command results in actual movement
                            current_position = get_servo_position()
                            print(f"Starting feed cycle: {num_drops} drops, servo currently at {current_position}°")
                            
                            for i in range(num_drops):
                                # Alternate between 0° and 90°, each drop dispenses 5g
                                next_position = 0 if current_position == 90 else 90
                                print(f"Drop {i+1}/{num_drops}: Moving {current_position}° → {next_position}° (dispensing 5g)")
                                activate_servo(position=next_position)
                                time.sleep(0.5)
                                current_position = next_position
                                set_servo_position(current_position)  # Save position after each move
                            print(f"Feed cycle complete: dispensed {actual_dispensed}g")
                        except Exception as e:
                            print(f"Servo thread error: {e}")
                    
                    thread = threading.Thread(target=run_servo_cycle, daemon=True)
                    thread.start()
                    
                    # Return immediately (don't wait for servo to finish)
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

        # Each position (0° and 90°) drops 5g of feed
        # Round UP to nearest 5g - always overfeed slightly rather than underfeed
        # e.g., 27g -> 30g (6 drops), 25g -> 25g (5 drops)
        import math
        num_drops = math.ceil(amount / 5)
        actual_dispensed = num_drops * 5
        
        # Start servo in background thread so we can respond immediately
        import threading
        def run_servo():
            try:
                # Get last known position so every command results in actual movement
                current_position = get_servo_position()
                print(f"Starting dispense: {num_drops} drops, servo currently at {current_position}°")
                
                for i in range(num_drops):
                    # Alternate between 0° and 90°, each drop dispenses 5g
                    next_position = 0 if current_position == 90 else 90
                    print(f"Drop {i+1}/{num_drops}: Moving {current_position}° → {next_position}°")
                    activate_servo(position=next_position)
                    current_position = next_position
                    set_servo_position(current_position)  # Save position after each move
                print(f"Dispensing complete: {actual_dispensed}g in {num_drops} drops")
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
