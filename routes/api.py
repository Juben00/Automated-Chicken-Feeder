from flask import Blueprint, request, jsonify
from utils.model_utils import get_model, predict_pellets
from utils.model_utils import get_feed_ratio
from flask_login import current_user
import datetime
from utils.logger import logger

api_bp = Blueprint('api', __name__, url_prefix='/api')

# New endpoint for pellet counting
@api_bp.route('/count_pellets', methods=['POST'])
def count_pellets():
    from models import db, FeedSchedule
    
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    image = request.files['image']
    if not image or image.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    try:
        model = get_model()
        pellet_count = predict_pellets(model, image)
        config = get_feed_ratio()
        pellets = float(config.get('pellets', 1))
        grams = float(config.get('grams', 1))
        if pellets <= 0:
            return jsonify({'error': 'Invalid pellets value in config'}), 500
        grams_to_dispense = round(grams * (pellet_count / pellets), 2)

        # Get user's next active schedule and subtract dispensed grams
        scheduled_grams = None
        remaining_grams = None
        if current_user.is_authenticated:
            now = datetime.datetime.now().time()
            schedule = db.session.query(FeedSchedule).filter(
                FeedSchedule.created_by == current_user.id,
                FeedSchedule.is_active == True,
                FeedSchedule.feed_time >= now
            ).order_by(FeedSchedule.feed_time.asc()).first()
            if schedule:
                scheduled_grams = schedule.amount_grams
                remaining_grams = round(scheduled_grams - grams_to_dispense, 2)

        return jsonify({
            'pellet_count': pellet_count,
            'grams_to_dispense': grams_to_dispense,
            'scheduled_grams': scheduled_grams,
            'remaining_grams': remaining_grams
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# New endpoint for IoT feed image upload and dispensing logic
@api_bp.route('/upload_feed_image', methods=['POST'])
def upload_feed_image():
    from models import db, FeedSchedule, Device

    # IoT device uploads image, expects amount to dispense in response
    image = request.files.get('image')
    device_id = request.form.get('device_id') or (request.get_json() or {}).get('device_id')
    # Authenticate using token in Authorization header if provided
    try:
        if not image:
            return jsonify({'error': 'No image uploaded'}), 400

        token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
        if not device_id or not token:
            return jsonify({'error': 'device_id and token required'}), 400

        # Verify device
        device = Device.query.filter_by(device_id=device_id, token=token).first()
        if not device:
            return jsonify({'error': 'Invalid device_id or token'}), 401

        user = device.user

        model = get_model()
        pellet_count = predict_pellets(model, image)
        config = get_feed_ratio()
        pellets = float(config.get('pellets', 1))
        grams = float(config.get('grams', 1))
        if pellets <= 0:
            return jsonify({'error': 'Invalid pellets value in config'}), 500

        # First try to honor an explicit schedule_id forwarded by the scheduler -> device -> server flow
        scheduled_grams = None
        grams_to_dispense = None
        remaining_grams = None
        schedule_lookup_log = []

        schedule_id = request.form.get('schedule_id') or (request.get_json(silent=True) or {}).get('schedule_id')
        schedule = None
        if schedule_id:
            try:
                schedule = db.session.get(FeedSchedule, int(schedule_id))
                if schedule:
                    if schedule.created_by != user.id:
                        schedule_lookup_log.append(f"Schedule {schedule_id} does not belong to user {user.id}")
                        schedule = None
                    else:
                        schedule_lookup_log.append(f"Found schedule by ID: {schedule_id}")
                else:
                    schedule_lookup_log.append(f"No schedule found for ID: {schedule_id}")
            except Exception as e:
                schedule_lookup_log.append(f"Exception during schedule_id lookup: {e}")

        if not schedule:
            # First time-based lookup: find next active schedule later today
            now_dt = datetime.datetime.now()
            now = now_dt.time()
            schedule = db.session.query(FeedSchedule).filter(
                FeedSchedule.created_by == user.id,
                FeedSchedule.is_active == True,
                FeedSchedule.feed_time >= now
            ).order_by(FeedSchedule.feed_time.asc()).first()
            if schedule:
                schedule_lookup_log.append(f"Found next active schedule for today: {schedule.id}")
            # If not found, try to find the nearest active schedule by absolute time difference (within a small window).
            if not schedule:
                try:
                    candidates = db.session.query(FeedSchedule).filter(
                        FeedSchedule.created_by == user.id,
                        FeedSchedule.is_active == True
                    ).all()
                    best = None
                    best_delta = None
                    for cand in candidates:
                        cand_dt = datetime.datetime.combine(now_dt.date(), cand.feed_time)
                        delta = abs((cand_dt - now_dt).total_seconds())
                        if best is None or delta < best_delta:
                            best = cand
                            best_delta = delta
                    if best and best_delta is not None and best_delta <= 120:
                        schedule = best
                        schedule_lookup_log.append(f"Selected nearest schedule id={schedule.id} delta_seconds={best_delta}")
                except Exception as e:
                    schedule_lookup_log.append(f"Exception during nearest-schedule search: {e}")

        if schedule:
            scheduled_grams = schedule.amount_grams
            grams_present = round(pellet_count * (grams / pellets), 2)
            grams_to_dispense = max(0, round(scheduled_grams - grams_present, 2))
            remaining_grams = max(0, round(scheduled_grams - grams_to_dispense, 2))
            logger.info(f"upload_feed_image: schedule_id={schedule.id} scheduled_grams={scheduled_grams} pellet_count={pellet_count} grams_present={grams_present} grams_to_dispense={grams_to_dispense} remaining_grams={remaining_grams}")
            schedule.amount_grams = remaining_grams
            db.session.commit()
        else:
            # No schedule found at all, log and return error
            schedule_lookup_log.append(f"No valid schedule found for user {user.id}. Returning error.")
            logger.error(f"upload_feed_image: {schedule_lookup_log}")
            return jsonify({
                'error': 'No valid schedule found for dispensing.',
                'pellet_count': pellet_count,
                'grams_to_dispense': 0,
                'scheduled_grams': 0,
                'remaining_grams': 0,
                'schedule_lookup_log': schedule_lookup_log
            }), 400

        logger.info(f"upload_feed_image: {schedule_lookup_log}")
        return jsonify({
            'pellet_count': pellet_count,
            'grams_to_dispense': grams_to_dispense,
            'scheduled_grams': scheduled_grams,
            'remaining_grams': remaining_grams,
            'schedule_lookup_log': schedule_lookup_log
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
