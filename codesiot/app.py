from flask import Flask, jsonify, request
import requests, json, os
from servo import activate_servo
from camera import capture_image
import time
import math
import threading

app = Flask(__name__)

# Track servo position to ensure every drop command results in actual movement
# This persists across requests so we always know where the servo is
SERVO_STATE_FILE = "/tmp/servo_position.txt"

# Thread locks for servo safety
servo_position_lock = threading.Lock()
servo_activation_lock = threading.Lock()

# Safety limit: maximum number of drops per single dispense operation
MAX_DROPS_PER_DISPENSE = 50

def get_servo_position():
    """Get last known servo position (0 or 175). Defaults to 0."""
    with servo_position_lock:
        try:
            with open(SERVO_STATE_FILE, 'r') as f:
                pos = int(f.read().strip())
                return pos if pos in [0, 175] else 0
        except:
            return 0  # Default: assume at 0

def set_servo_position(position):
    """Save current servo position to state file."""
    with servo_position_lock:
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

# Default grams per servo drop (fallback only — server always sends the live value)
DEFAULT_GRAMS_PER_DROP = 6.0

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
    """Capture image, upload to website, receive amount to dispense, then activate servo using configured grams_per_drop."""
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
                grams_per_drop = result.get('grams_per_drop', DEFAULT_GRAMS_PER_DROP)
                # Validate grams_per_drop from server
                try:
                    grams_per_drop = float(grams_per_drop)
                    if grams_per_drop <= 0 or grams_per_drop > 50:
                        grams_per_drop = DEFAULT_GRAMS_PER_DROP
                except (ValueError, TypeError):
                    grams_per_drop = DEFAULT_GRAMS_PER_DROP

                # Dispense if any amount is needed (rounds up to at least 1 drop)
                if grams_to_dispense > 0:
                    # Each servo rotation (0→175 or 175→0) drops grams_per_drop of feed
                    # Round UP - always overfeed slightly rather than underfeed
                    num_drops = math.ceil(grams_to_dispense / grams_per_drop)
                    # Safety cap
                    if num_drops > MAX_DROPS_PER_DISPENSE:
                        print(f"Warning: capping {num_drops} drops to {MAX_DROPS_PER_DISPENSE}")
                        num_drops = MAX_DROPS_PER_DISPENSE
                    actual_dispensed = num_drops * grams_per_drop
                    print(f"Dispensing {actual_dispensed}g in {num_drops} drops ({grams_per_drop}g each)...")
                    
                    # Run servo in background thread to respond quickly
                    def run_servo_cycle():
                        with servo_activation_lock:
                            try:
                                current_position = get_servo_position()
                                print(f"Starting feed cycle: {num_drops} drops, servo currently at {current_position}°")
                                
                                for i in range(num_drops):
                                    next_position = 0 if current_position == 175 else 175
                                    print(f"Drop {i+1}/{num_drops}: Moving {current_position}° → {next_position}° (dispensing {grams_per_drop}g)")
                                    activate_servo(position=next_position)
                                    time.sleep(0.5)  # Wait for feed to settle
                                    current_position = next_position
                                    set_servo_position(current_position)
                                print(f"Feed cycle complete: dispensed {actual_dispensed}g")
                            except Exception as e:
                                print(f"Servo thread error: {e}")
                    
                    thread = threading.Thread(target=run_servo_cycle, daemon=True)
                    thread.start()
                    
                    return jsonify({"status": "success", "dispensed": actual_dispensed, "drops": num_drops, "grams_per_drop": grams_per_drop, "response": result})
                else:
                    print(f"No feed needed (grams_to_dispense={grams_to_dispense}). Skipping.")
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

        # Read grams_per_drop from request or use default
        grams_per_drop = data.get('grams_per_drop', DEFAULT_GRAMS_PER_DROP)
        try:
            grams_per_drop = float(grams_per_drop)
            if grams_per_drop <= 0 or grams_per_drop > 50:
                grams_per_drop = DEFAULT_GRAMS_PER_DROP
        except (ValueError, TypeError):
            grams_per_drop = DEFAULT_GRAMS_PER_DROP

        if amount < 1 or amount > 150:
            return jsonify({'error': 'Amount must be between 1 and 150 grams'}), 400

        # Each servo rotation (0→175 or 175→0) drops grams_per_drop of feed
        # Round UP - always overfeed slightly rather than underfeed
        num_drops = math.ceil(amount / grams_per_drop)
        # Safety cap
        if num_drops > MAX_DROPS_PER_DISPENSE:
            return jsonify({'error': f'Requested amount requires {num_drops} drops (max {MAX_DROPS_PER_DISPENSE})'}), 400
        actual_dispensed = num_drops * grams_per_drop
        
        # Start servo in background thread so we can respond immediately
        def run_servo():
            with servo_activation_lock:
                try:
                    current_position = get_servo_position()
                    print(f"Starting dispense: {num_drops} drops, servo currently at {current_position}°")
                    
                    for i in range(num_drops):
                        next_position = 0 if current_position == 175 else 175
                        print(f"Drop {i+1}/{num_drops}: Moving {current_position}° → {next_position}° ({grams_per_drop}g)")
                        activate_servo(position=next_position)
                        time.sleep(0.5)  # Wait for feed to settle
                        current_position = next_position
                        set_servo_position(current_position)
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
