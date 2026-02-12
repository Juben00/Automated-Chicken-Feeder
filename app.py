from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from models import db, User, Device, FeedSchedule, DispenseLog
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
# Note: scheduler.py is not used - app manages its own scheduler dynamically
from datetime import datetime, time, timedelta
import os
import requests
import json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import secrets
import logging
# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

# Setup simple logging (disable verbose werkzeug and apscheduler logs)
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Create a simple logger for app-specific messages
logger = logging.getLogger('chickenfeeder')
logger.setLevel(logging.INFO)

# Disable werkzeug and apscheduler verbose logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

login_manager = LoginManager()

# Initialize rate limiter (will be configured with app later)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    
    # Generate secure secret key if not provided
    secret_key = os.getenv('SECRET_KEY')
    if not secret_key or secret_key == 'secret_key':
        # Generate a secure random key and save to .env if possible
        import secrets as sec
        secret_key = sec.token_hex(32)
        logger.warning("Using auto-generated SECRET_KEY. Set SECRET_KEY in .env for production!")
    app.config['SECRET_KEY'] = secret_key
    
    # Security settings for session cookies
    app.config['SESSION_COOKIE_SECURE'] = os.getenv('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'chickenfeeder.sqlite')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    limiter.init_app(app)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Move this import here to avoid circular import
    from routes.api import api_bp
    app.register_blueprint(api_bp)
    
    # Apply rate limits to API blueprint routes
    limiter.limit("30 per minute")(app.view_functions['api.upload_feed_image'])
    limiter.limit("30 per minute")(app.view_functions['api.count_pellets'])

    # Register blueprints
    from routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    # Main dashboard route for root "/"
    @app.route('/')
    def root_dashboard():
        from flask import render_template, redirect, url_for
        from flask_login import current_user
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        # ...fetch stats, logs, schedules...
        return render_template('dashboard.html')
    
    return app

app = create_app()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Initialize scheduler for automated feeding
scheduler = BackgroundScheduler()

@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

# IoT Communication Functions

def communicate_with_iot_device(amount_grams, device_url=None):
    """
    Communicate with IoT device to dispense feed.
    Sends dispense request to the IoT device endpoint.
    
    Args:
        amount_grams: Amount of feed to dispense
        device_url: Device ID or URL (e.g., 'http://192.168.1.100:5000' or 'pi_klei')
    
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    if not device_url:
        # logger.warning("No device URL provided for IoT communication")
        return True, None  # Silently succeed if no device configured
    
    try:
        # Normalize and construct the device endpoint
        device_url = device_url.rstrip('/')
        if device_url.startswith('http://') or device_url.startswith('https://'):
            endpoint = f"{device_url}/dispense"
        else:
            endpoint = f"http://{device_url}:5000/dispense"

        # Prepare the payload
        payload = {'amount_grams': amount_grams}

        # Send request with timeout
        # logger.info(f"Sending dispense request to {endpoint} for {amount_grams}g")
        response = requests.post(endpoint, json=payload, timeout=5)

        # Check response
        if response.status_code != 200:
            error_msg = f"Device returned status {response.status_code}: {response.text}"
            logger.error(error_msg)
            return False, error_msg

        # Try to parse JSON response (safe)
        try:
            result = response.json()
            logger.info(f"Device responded successfully: {result}")
            return True, None
        except ValueError:
            # Non-JSON response
            text = response.text
            error_msg = f"Device returned non-JSON response: {text!r}"
            logger.error(error_msg)
            return False, error_msg

    except requests.exceptions.Timeout:
        error_msg = f"Request to device {device_url} timed out"
        logger.error(error_msg)
        return False, error_msg
    except requests.exceptions.ConnectionError:
        error_msg = f"Failed to connect to device {device_url}. Device may be offline."
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Error communicating with IoT device: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def dispense_feed(amount_grams, trigger_type='manual', schedule_id=None, user_id=None):
    """
    Core function to dispense feed and log the action
    """
    from utils.email_notifications import send_feeding_notification, send_feeding_failure_notification
    
    device_url = None
    user = None
    if user_id:
        user = db.session.get(User, user_id)
        if user and user.iot_device_url:
            # Use the user's configured IoT device URL
            device_url = user.iot_device_url
    success, error_message = communicate_with_iot_device(amount_grams, device_url)
    # Log the dispense action
    log_entry = DispenseLog(
        amount_grams=amount_grams,
        trigger_type=trigger_type,
        schedule_id=schedule_id,
        status='success' if success else 'failure',
        error_message=error_message,
        triggered_by=user_id
    )
    db.session.add(log_entry)
    db.session.commit()
    
    # Send email notification
    if user and user.email:
        try:
            if success:
                send_feeding_notification(
                    user_email=user.email,
                    username=user.username,
                    amount_grams=amount_grams,
                    trigger_type=trigger_type
                )
            else:
                send_feeding_failure_notification(
                    user_email=user.email,
                    username=user.username,
                    error_message=error_message or 'Unknown error'
                )
        except Exception as e:
            logger.error(f"Failed to send email notification: {str(e)}")
    
    return success, error_message, log_entry.id

def scheduled_feed_task(schedule_id):
    """
    Task executed by scheduler for automatic feeding (WITH image processing).
    
    Flow:
    1. Tell Pi to capture image of current feed in tray
    2. Pi uploads image to /api/upload_feed_image
    3. Flask uses ML model to count pellets
    4. Flask calculates: grams_remaining = (pellet_count / pellets_per_gram_ratio)
    5. Flask calculates: grams_to_dispense = scheduled_amount - grams_remaining
    6. Flask responds to Pi with grams_to_dispense
    7. Pi receives amount and dispenses via servo
    """
    from utils.email_notifications import send_feeding_notification, send_feeding_failure_notification
    
    with app.app_context():
        schedule = db.session.get(FeedSchedule, schedule_id)
        if schedule and schedule.is_active:
            user = db.session.get(User, schedule.created_by)
            if not user or not user.iot_device_url:
                logger.error(f"Schedule {schedule_id}: User has no IoT device configured")
                return
            
            # Call Pi's /feed_cycle endpoint to capture and process image
            # Pi will upload image and receive grams_to_dispense in response
            try:
                device_url = user.iot_device_url.rstrip('/')
                feed_cycle_url = f"{device_url}/feed_cycle"
                
                logger.info(f"Scheduled feed {schedule_id}: Sending feed_cycle request to {feed_cycle_url}")
                
                # Include the schedule id so the server can reliably map this feed cycle
                response = requests.post(feed_cycle_url, json={'schedule_id': schedule_id}, timeout=30)  # Longer timeout for ML processing
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Feed cycle completed: {result}")

                    # The device may wrap the server response inside a 'response' key
                    inner = result.get('response') if isinstance(result, dict) and 'response' in result else result

                    # Determine amount actually dispensed (device returns 'dispensed' when it performed cycles)
                    dispensed = result.get('dispensed') if isinstance(result, dict) and result.get('dispensed') is not None else inner.get('dispensed') if isinstance(inner, dict) else None
                    # If device didn't return 'dispensed', fall back to the calculated grams_to_dispense from the inner response
                    if dispensed is None:
                        dispensed = inner.get('grams_to_dispense') if isinstance(inner, dict) else 0

                    try:
                        dispensed_val = int(dispensed) if dispensed is not None else 0
                    except Exception:
                        try:
                            dispensed_val = int(round(float(dispensed)))
                        except Exception:
                            dispensed_val = 0

                    # Get additional info from the server response (inside 'inner')
                    image_path = inner.get('image_path') if isinstance(inner, dict) else None
                    pellet_count = inner.get('pellet_count') if isinstance(inner, dict) else None
                    grams_detected = inner.get('grams_detected') if isinstance(inner, dict) else None
                    
                    # The actual grams dispensed by servo (from IoT device response)
                    grams_dispensed = result.get('dispensed') if isinstance(result, dict) else dispensed_val
                    
                    # Log successful dispense
                    log_entry = DispenseLog(
                        amount_grams=dispensed_val,
                        trigger_type='scheduled',
                        schedule_id=schedule_id,
                        status='success',
                        error_message=None,
                        image_path=image_path,
                        pellet_count=pellet_count,
                        grams_detected=grams_detected,
                        grams_dispensed=grams_dispensed,
                        triggered_by=user.id
                    )
                else:
                    error_msg = f"Device returned status {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    log_entry = DispenseLog(
                        amount_grams=schedule.amount_grams,
                        trigger_type='scheduled',
                        schedule_id=schedule_id,
                        status='failure',
                        error_message=error_msg,
                        triggered_by=user.id
                    )
            except requests.exceptions.Timeout:
                error_msg = f"Feed cycle request timed out for device {user.iot_device_url}"
                logger.error(error_msg)
                log_entry = DispenseLog(
                    amount_grams=schedule.amount_grams,
                    trigger_type='scheduled',
                    schedule_id=schedule_id,
                    status='failure',
                    error_message=error_msg,
                    triggered_by=user.id
                )
            except Exception as e:
                error_msg = f"Error in scheduled feed task: {str(e)}"
                logger.error(error_msg)
                log_entry = DispenseLog(
                    amount_grams=schedule.amount_grams,
                    trigger_type='scheduled',
                    schedule_id=schedule_id,
                    status='failure',
                    error_message=error_msg,
                    triggered_by=user.id
                )
            
            db.session.add(log_entry)
            db.session.commit()
            
            # Send email notification for scheduled feeds
            if user and user.email:
                try:
                    if log_entry.status == 'success':
                        send_feeding_notification(
                            user_email=user.email,
                            username=user.username,
                            amount_grams=log_entry.amount_grams,
                            trigger_type='scheduled',
                            schedule_name=schedule.name
                        )
                    else:
                        send_feeding_failure_notification(
                            user_email=user.email,
                            username=user.username,
                            error_message=log_entry.error_message or 'Unknown error',
                            schedule_name=schedule.name
                        )
                except Exception as e:
                    logger.error(f"Failed to send scheduled feed email notification: {str(e)}")

@app.route('/admin/users')
@login_required
def admin_user_dashboard():
    if not require_admin():
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """
    User profile page - allows users to edit their IoT device URL, email, and password
    """
    if request.method == 'POST':
        iot_device_url = request.form.get('iot_device_url', '').strip()
        email = request.form.get('email', '').strip().lower()
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validate email uniqueness (if changed)
        if email and email != current_user.email:
            if User.query.filter_by(email=email).first():
                flash('Email already registered.', 'danger')
                return redirect(url_for('profile'))
        
        # Handle password change
        if new_password or current_password or confirm_password:
            from utils.validators import validate_password
            
            # Password change requested
            if not current_password:
                flash('Current password required to change password.', 'danger')
                return redirect(url_for('profile'))
            
            if not check_password_hash(current_user.password_hash, current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('profile'))
            
            # Use the same password validation as registration
            is_valid, error_msg = validate_password(new_password)
            if not is_valid:
                flash(error_msg, 'danger')
                return redirect(url_for('profile'))
            
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'danger')
                return redirect(url_for('profile'))
            
            # Update password
            current_user.password_hash = generate_password_hash(new_password)
        
        # Update user profile
        if email:
            current_user.email = email
        current_user.iot_device_url = iot_device_url if iot_device_url else None
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
    
    return render_template('profile.html', user=current_user)

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def register():
    """
    Public registration: create a new user account.
    Admin accounts should be created via the admin dashboard.
    """
    from utils.validators import validate_username, validate_email, validate_password, validate_iot_url, sanitize_string
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        iot_device_url = request.form.get('iot_device_url', '').strip()
        
        # Validate username
        is_valid, error_msg = validate_username(username)
        if not is_valid:
            flash(error_msg, 'danger')
            return redirect(url_for('register'))
        
        # Validate email
        is_valid, error_msg = validate_email(email)
        if not is_valid:
            flash(error_msg, 'danger')
            return redirect(url_for('register'))
        
        # Validate password
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            flash(error_msg, 'danger')
            return redirect(url_for('register'))
        
        # Validate IoT URL if provided
        if iot_device_url:
            is_valid, error_msg = validate_iot_url(iot_device_url)
            if not is_valid:
                flash(error_msg, 'danger')
                return redirect(url_for('register'))
        
        # Check for duplicate username
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists. Please choose a different one.', 'danger')
            return redirect(url_for('register'))
        
        # Check for duplicate email
        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash('Email already registered. Please use a different email.', 'danger')
            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            iot_device_url=iot_device_url if iot_device_url else None,
            is_admin=False
        )
        db.session.add(user)
        db.session.commit()
        flash('Account created. You may now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

# --- OVERRIDE ALL USER ROUTES TO BLOCK ADMINS ---
from flask import abort
from flask_login import current_user

@app.before_request
def restrict_admin_from_user_pages():
    # Only block if admin is logged in and trying to access non-admin pages
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        if not request.path.startswith('/admin'):
            # Allow static and logout
            if not request.path.startswith('/static') and not request.path.startswith('/logout'):
                return redirect(url_for('admin.dashboard'))

# Helper: require admin
def require_admin():
    if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
        flash('Unauthorized: admin access required.', 'danger')
        return False
    return True

@app.route('/admin')
@login_required
def admin_dashboard():
    if not require_admin():
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/dashboard.html', users=users)

@app.route('/admin/create', methods=['GET', 'POST'])
@login_required
def admin_create_user():
    if not require_admin():
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        is_admin = bool(request.form.get('is_admin'))
        if not username or not email or not password:
            flash('Username, email and password are required.', 'danger')
            return redirect(url_for('admin_create_user'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger'  )
            return redirect(url_for('admin_create_user'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('admin_create_user'))
        u = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_admin=is_admin
        )
        db.session.add(u)
        db.session.commit()
        flash('User created successfully.', 'success')
        return redirect(url_for('admin_user_dashboard'))
    return render_template('admin/create_user.html')

@app.route('/admin/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if not require_admin():
        return redirect(url_for('dashboard'))
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', None)
        is_admin = bool(request.form.get('is_admin'))
        # uniqueness checks (exclude this user)
        if username and username != user.username and User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
            return redirect(url_for('admin_edit_user', user_id=user_id))
        if email and email != user.email and User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('admin_edit_user', user_id=user_id))
        if username:
            user.username = username
        if email:
            user.email = email
        user.is_admin = is_admin
        if password:
            user.password_hash = generate_password_hash(password)
        db.session.commit()
        flash('User updated.', 'success')
        return redirect(url_for('admin_user_dashboard'))
    return render_template('admin/edit_user.html', user=user)
# Device registration endpoint
@app.route('/register_device', methods=['POST'])
@login_required
def register_device():
    data = request.get_json()
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id required'}), 400
    # Generate a secure token
    token = secrets.token_urlsafe(32)
    device = Device(device_id=device_id, user_id=current_user.id, token=token)
    db.session.add(device)
    db.session.commit()
    return jsonify({'device_id': device_id, 'user_token': token})

# IoT Device API Endpoints
@app.route('/iot/authenticate', methods=['POST'])
@limiter.limit("10 per minute")
def iot_authenticate():
    """
    IoT device authentication endpoint.
    Device sends device_id and token to authenticate.
    """
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        token = data.get('token')
        
        if not device_id or not token:
            return jsonify({'error': 'device_id and token required'}), 400
        
        # Find device and verify token
        device = Device.query.filter_by(device_id=device_id, token=token).first()
        if not device:
            logger.warning(f"Failed authentication attempt for device {device_id}")
            return jsonify({'error': 'Invalid device_id or token'}), 401
        
        logger.info(f"Device {device_id} authenticated successfully")
        return jsonify({
            'success': True,
            'message': 'Device authenticated',
            'user_id': device.user_id,
            'device_id': device_id
        })
    except Exception as e:
        logger.error(f"Error in IoT authentication: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/iot/dispense', methods=['POST'])
@limiter.limit("20 per minute")
def iot_dispense():
    """
    IoT device dispense endpoint.
    Device sends dispense request with device_id and token.
    Server responds with amount to dispense.
    """
    try:
        # Get device credentials from header or body
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        device_id = request.form.get('device_id') or request.get_json().get('device_id')
        
        if not device_id or not token:
            return jsonify({'error': 'device_id and token required'}), 400
        
        # Authenticate device
        device = Device.query.filter_by(device_id=device_id, token=token).first()
        if not device:
            logger.warning(f"Unauthorized dispense request from device {device_id}")
            return jsonify({'error': 'Unauthorized'}), 401
        
        user = device.user
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get image if provided (for pellet counting)
        amount_grams = None
        if 'image' in request.files:
            # This is handled by the routes.api module for ML-based pellet counting
            # For now, just dispense the requested amount
            pass
        
        # Get amount from request
        amount_grams = request.form.get('amount_grams') or request.get_json().get('amount_grams')
        
        if not amount_grams:
            return jsonify({'error': 'amount_grams required'}), 400
        
        try:
            amount_grams = int(amount_grams)
        except ValueError:
            return jsonify({'error': 'amount_grams must be an integer'}), 400
        
        # Validate amount using configured grams_per_drop as minimum
        from utils.model_utils import get_feed_ratio
        feed_config = get_feed_ratio()
        min_grams = feed_config.get('grams_per_drop', 6.7)
        if amount_grams < min_grams or amount_grams > 150:
            return jsonify({'error': f'Amount must be between {min_grams} and 150 grams'}), 400
        
        # Find next active schedule for this user
        now = datetime.now().time()
        schedule = FeedSchedule.query.filter(
            FeedSchedule.created_by == user.id,
            FeedSchedule.is_active == True,
            FeedSchedule.feed_time >= now
        ).order_by(FeedSchedule.feed_time.asc()).first()
        
        scheduled_grams = None
        remaining_grams = None
        if schedule:
            scheduled_grams = schedule.amount_grams
            remaining_grams = max(0, scheduled_grams - amount_grams)
            # NOTE: Do NOT modify schedule.amount_grams - the schedule should keep its
            # original amount for recurring daily feeds. The remaining_grams is just
            # informational for this single feed session.
        
        # Log the dispense action
        log_entry = DispenseLog(
            amount_grams=amount_grams,
            trigger_type='iot',
            schedule_id=schedule.id if schedule else None,
            status='success',
            error_message=None,
            triggered_by=user.id
        )
        db.session.add(log_entry)
        db.session.commit()
        
        logger.info(f"Device {device_id} dispensed {amount_grams}g for user {user.username}")
        
        return jsonify({
            'success': True,
            'amount_dispensed': amount_grams,
            'scheduled_grams': scheduled_grams,
            'remaining_grams': remaining_grams,
            'log_id': log_entry.id
        })
    except Exception as e:
        logger.error(f"Error in IoT dispense endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not require_admin():
        return redirect(url_for('dashboard'))
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_user_dashboard'))
    # Prevent deleting yourself
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin_user_dashboard'))
    # Ensure at least one admin remains
    if user.is_admin:
        other_admins = User.query.filter(User.is_admin == True, User.id != user.id).count()
        if other_admins == 0:
            flash('Cannot delete the last admin user.', 'danger')
            return redirect(url_for('admin_user_dashboard'))
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting user.', 'danger')
    return redirect(url_for('admin_user_dashboard'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    from utils.model_utils import get_feed_ratio
    # Get today's schedules for current user
    today_schedules = FeedSchedule.query.filter_by(created_by=current_user.id, is_active=True).order_by(FeedSchedule.feed_time).all()
    # Get today's dispense logs for current user
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_logs = DispenseLog.query.filter(
        DispenseLog.timestamp >= today_start,
        DispenseLog.triggered_by == current_user.id
    ).order_by(DispenseLog.timestamp.desc()).all()
    # Calculate total feed dispensed today
    total_today = sum(log.amount_grams for log in today_logs if log.status == 'success')

    # Remove device registration UI logic and device list from here
    feed_config = get_feed_ratio()
    min_grams = feed_config.get('grams_per_drop', 6.7)
    return render_template('dashboard.html', 
                         schedules=today_schedules,
                         logs=today_logs,
                         total_today=total_today,
                         min_grams=min_grams)

@app.route('/devices', methods=['GET', 'POST'])
@login_required
def devices():
    from utils.validators import validate_device_id
    
    device_message = None
    if request.method == 'POST':
        if 'delete_device' in request.form:
            device_id = request.form.get('delete_device')
            device = Device.query.filter_by(device_id=device_id, user_id=current_user.id).first()
            if device:
                db.session.delete(device)
                db.session.commit()
                device_message = f'Device {device_id} deleted.'
            else:
                device_message = 'Device not found or unauthorized.'
        else:
            device_id = request.form.get('device_id', '').strip()
            
            # Validate device ID format
            is_valid, error_msg = validate_device_id(device_id)
            if not is_valid:
                device_message = error_msg
            else:
                # Check if user already has a device (limit to 1)
                user_device_count = Device.query.filter_by(user_id=current_user.id).count()
                if user_device_count >= 1:
                    device_message = 'You can only register 1 device. Please delete your existing device first.'
                else:
                    existing = Device.query.filter_by(device_id=device_id).first()
                    if existing:
                        device_message = 'This Device ID is already registered.'
                    else:
                        import secrets
                        token = secrets.token_urlsafe(32)
                        device = Device(device_id=device_id, user_id=current_user.id, token=token)
                        db.session.add(device)
                        db.session.commit()
                        # Don't expose token in message - user can view it via the eye icon
                        device_message = 'Device registered successfully! Click the eye icon to view your token.'
    user_devices = Device.query.filter_by(user_id=current_user.id).all()
    return render_template('devices.html',
                           user_devices=user_devices,
                           device_message=device_message)

@app.route('/schedules')
@login_required
def schedules():
    schedules = FeedSchedule.query.filter_by(created_by=current_user.id).order_by(FeedSchedule.feed_time).all()
    return render_template('schedules.html', schedules=schedules)

@app.route('/schedules/add', methods=['GET', 'POST'])
@login_required
def add_schedule():
    from utils.validators import validate_schedule_name, validate_amount_grams, sanitize_string
    from utils.model_utils import get_feed_ratio
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        feed_time_str = request.form.get('feed_time', '')
        
        # Validate and sanitize schedule name
        is_valid, error_msg = validate_schedule_name(name)
        if not is_valid:
            flash(error_msg, 'danger')
            return redirect(url_for('add_schedule'))
        name = sanitize_string(name, max_length=100)
        
        # Validate amount
        try:
            amount_grams = int(request.form.get('amount_grams', 0))
        except ValueError:
            flash('Amount must be a valid number.', 'danger')
            return redirect(url_for('add_schedule'))
        
        feed_config = get_feed_ratio()
        min_grams = feed_config.get('grams_per_drop', 6.7)
        is_valid, error_msg = validate_amount_grams(amount_grams, min_grams=min_grams)
        if not is_valid:
            flash(error_msg, 'danger')
            return redirect(url_for('add_schedule'))
        
        # Validate time format
        try:
            feed_time = datetime.strptime(feed_time_str, '%H:%M').time()
        except ValueError:
            flash('Invalid time format. Please use HH:MM format.', 'danger')
            return redirect(url_for('add_schedule'))
        
        schedule = FeedSchedule(
            name=name,
            feed_time=feed_time,
            amount_grams=amount_grams,
            created_by=current_user.id
        )
        
        db.session.add(schedule)
        db.session.commit()
        
        # Add to scheduler
        try:
            scheduler.add_job(
                func=scheduled_feed_task,
                trigger=CronTrigger(hour=feed_time.hour, minute=feed_time.minute),
                args=[schedule.id],
                id=f'schedule_{schedule.id}',
                replace_existing=True
            )
            logger.info(f"Added schedule {schedule.id} to scheduler for {feed_time}")
        except Exception as e:
            logger.error(f"Error adding job to scheduler: {str(e)}")
            flash('Schedule created but failed to add to scheduler. Please restart the app.', 'warning')
            return redirect(url_for('schedules'))
        
        flash('Schedule added successfully!', 'success')
        return redirect(url_for('schedules'))
    
    feed_config = get_feed_ratio()
    min_grams = feed_config.get('grams_per_drop', 6.7)
    return render_template('add_schedule.html', min_grams=min_grams)

@app.route('/schedules/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_schedule(schedule_id):
    from utils.validators import validate_schedule_name, validate_amount_grams, sanitize_string
    from utils.model_utils import get_feed_ratio
    
    schedule = db.session.get(FeedSchedule, schedule_id)
    if not schedule:
        flash('Schedule not found', 'danger')
        return redirect(url_for('schedules'))
    if schedule.created_by != current_user.id:
        flash('Unauthorized', 'danger')
        return redirect(url_for('schedules'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        feed_time_str = request.form.get('feed_time', '')
        is_active = 'is_active' in request.form
        
        # Validate and sanitize schedule name
        is_valid, error_msg = validate_schedule_name(name)
        if not is_valid:
            flash(error_msg, 'danger')
            return redirect(url_for('edit_schedule', schedule_id=schedule_id))
        name = sanitize_string(name, max_length=100)
        
        # Validate amount
        try:
            amount_grams = int(request.form.get('amount_grams', 0))
        except ValueError:
            flash('Amount must be a valid number.', 'danger')
            return redirect(url_for('edit_schedule', schedule_id=schedule_id))
        
        feed_config = get_feed_ratio()
        min_grams = feed_config.get('grams_per_drop', 6.7)
        is_valid, error_msg = validate_amount_grams(amount_grams, min_grams=min_grams)
        if not is_valid:
            flash(error_msg, 'danger')
            return redirect(url_for('edit_schedule', schedule_id=schedule_id))
        
        # Validate time format
        try:
            feed_time = datetime.strptime(feed_time_str, '%H:%M').time()
        except ValueError:
            flash('Invalid time format. Please use HH:MM format.', 'danger')
            return redirect(url_for('edit_schedule', schedule_id=schedule_id))
        
        # Check if time changed
        time_changed = schedule.feed_time != feed_time
        was_active = schedule.is_active
        
        # Update schedule
        schedule.name = name
        schedule.feed_time = feed_time
        schedule.amount_grams = amount_grams
        schedule.is_active = is_active
        
        db.session.commit()
        
        # Update scheduler if time changed or active status changed
        try:
            # Remove old job
            try:
                scheduler.remove_job(f'schedule_{schedule_id}')
            except Exception:
                pass  # Job may not exist
            
            # Add new job if active
            if is_active:
                scheduler.add_job(
                    func=scheduled_feed_task,
                    trigger=CronTrigger(hour=feed_time.hour, minute=feed_time.minute),
                    args=[schedule.id],
                    id=f'schedule_{schedule.id}',
                    replace_existing=True
                )
                logger.info(f"Updated schedule {schedule.id} in scheduler for {feed_time}")
        except Exception as e:
            logger.error(f"Error updating job in scheduler: {str(e)}")
            flash('Schedule updated but failed to update scheduler. Please restart the app.', 'warning')
            return redirect(url_for('schedules'))
        
        flash('Schedule updated successfully!', 'success')
        return redirect(url_for('schedules'))
    
    feed_config = get_feed_ratio()
    min_grams = feed_config.get('grams_per_drop', 6.7)
    return render_template('edit_schedule.html', schedule=schedule, min_grams=min_grams)

@app.route('/schedules/<int:schedule_id>/delete', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    schedule = db.session.get(FeedSchedule, schedule_id)
    if not schedule:
        flash('Schedule not found', 'danger')
        return redirect(url_for('schedules'))
    if schedule.created_by != current_user.id:
        flash('Unauthorized', 'danger')
        return redirect(url_for('schedules'))
    
    # Remove from scheduler
    try:
        scheduler.remove_job(f'schedule_{schedule_id}')
    except Exception:
        pass  # Job may not exist in scheduler
    
    db.session.delete(schedule)
    db.session.commit()
    
    flash('Schedule deleted successfully!', 'success')
    return redirect(url_for('schedules'))

@app.route('/schedules/<int:schedule_id>/toggle', methods=['POST'])
@login_required
def toggle_schedule(schedule_id):
    schedule = db.session.get(FeedSchedule, schedule_id)
    if not schedule:
        return jsonify({'error': 'Schedule not found'}), 404
    if schedule.created_by != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    schedule.is_active = not schedule.is_active
    db.session.commit()
    
    # Update scheduler
    if schedule.is_active:
        scheduler.add_job(
            func=scheduled_feed_task,
            trigger=CronTrigger(hour=schedule.feed_time.hour, minute=schedule.feed_time.minute),
            args=[schedule.id],
            id=f'schedule_{schedule.id}',
            replace_existing=True
        )
    else:
        try:
            scheduler.remove_job(f'schedule_{schedule_id}')
        except Exception:
            pass  # Job may not exist in scheduler
    
    return jsonify({'success': True, 'is_active': schedule.is_active})

@app.route('/dispense', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def manual_dispense():
    """
    API endpoint for manual feed dispensing
    Also serves as IoT integration endpoint
    """
    data = request.get_json()
    amount_grams = data.get('amount', 0)
    
    # --- Limit: grams_per_drop to 150 grams per feeding ---
    from utils.model_utils import get_feed_ratio
    feed_config = get_feed_ratio()
    min_grams = feed_config.get('grams_per_drop', 6.7)
    if amount_grams < min_grams or amount_grams > 150:
        return jsonify({'error': f'Invalid amount. Must be between {min_grams} and 150 grams'}), 400
    
    success, error_message, log_id = dispense_feed(
        amount_grams=amount_grams,
        trigger_type='manual',
        user_id=current_user.id
    )
    
    if success:
        return jsonify({
            'success': True,
            'message': f'Successfully dispensed {amount_grams}g of feed',
            'log_id': log_id
        })
    else:
        return jsonify({
            'success': False,
            'error': error_message
        }), 500

@app.route('/logs')
@login_required
def logs():
    page = request.args.get('page', 1, type=int)

    if not current_user.is_admin:
        logs = DispenseLog.query.filter_by(triggered_by=current_user.id).order_by(DispenseLog.timestamp.desc()).paginate(
            page=page, per_page=10, error_out=False
        )
    else:
        logs = DispenseLog.query.order_by(DispenseLog.timestamp.desc()).paginate(
            page=page, per_page=10, error_out=False
        )
    return render_template('logs.html', logs=logs)

@app.route('/api/stats')
@login_required
def api_stats():
    """
    API endpoint for dashboard statistics
    """
    # Today's stats
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_logs = DispenseLog.query.filter(DispenseLog.timestamp >= today_start).all()
    
    total_today = sum(log.amount_grams for log in today_logs if log.status == 'success')
    successful_today = len([log for log in today_logs if log.status == 'success'])
    failed_today = len([log for log in today_logs if log.status == 'failure'])
    
    # This week's stats
    week_start = today_start - timedelta(days=7)
    week_logs = DispenseLog.query.filter(DispenseLog.timestamp >= week_start).all()
    total_week = sum(log.amount_grams for log in week_logs if log.status == 'success')
    
    return jsonify({
        'today': {
            'total_grams': total_today,
            'successful_dispenses': successful_today,
            'failed_dispenses': failed_today
        },
        'week': {
            'total_grams': total_week
        }
    })

def create_admin_user():
    """Create default admin user if none exists"""
    if not User.query.first():
        # Use environment variables for admin credentials with secure defaults
        import secrets as sec
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@chickenfeeder.com')
        admin_password = os.getenv('ADMIN_PASSWORD')
        
        # Generate random password if not provided
        if not admin_password:
            admin_password = sec.token_urlsafe(16)
            print("\n" + "=" * 70)
            print("IMPORTANT: Default admin account created!")
            print(f"Username: {admin_username}")
            print(f"Password: {admin_password}")
            print("Please change this password immediately after first login!")
            print("Set ADMIN_PASSWORD in .env to avoid this message.")
            print("=" * 70 + "\n")
        
        admin = User(
            username=admin_username,
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()

def setup_scheduled_jobs():
    """Setup all active schedules in the scheduler"""
    active_schedules = FeedSchedule.query.filter_by(is_active=True).all()
    for schedule in active_schedules:
        scheduler.add_job(
            func=scheduled_feed_task,
            trigger=CronTrigger(hour=schedule.feed_time.hour, minute=schedule.feed_time.minute),
            args=[schedule.id],
            id=f'schedule_{schedule.id}',
            replace_existing=True
        )

@app.route('/admin/feed-ratio', methods=['GET', 'POST'])
@login_required
def admin_feed_ratio():
    from utils.model_utils import get_feed_ratio, set_feed_ratio
    if not require_admin():
        return redirect(url_for('dashboard'))
    ratio = get_feed_ratio()
    if request.method == 'POST':
        try:
            pellets = int(request.form.get('pellets', 50))
            grams = float(request.form.get('grams', 10))
            grams_per_drop = float(request.form.get('grams_per_drop', 6.7))
            if pellets <= 0 or grams <= 0 or grams_per_drop <= 0:
                flash('Values must be positive.', 'danger')
            elif grams_per_drop > 50:
                flash('Grams per drop must not exceed 50.', 'danger')
            else:
                set_feed_ratio(pellets, grams, grams_per_drop)
                flash('Feed-to-gram ratio updated!', 'success')
                return redirect(url_for('admin_feed_ratio'))
        except Exception:
            flash('Invalid input.', 'danger')
    return render_template('admin/feed_ratio.html', ratio=ratio)

def initialize_app():
    """Initialize database, admin user, and scheduler - called on startup"""
    with app.app_context():
        db.create_all()
        create_admin_user()
        setup_scheduled_jobs()
    
    # Start the scheduler
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started successfully")
    
    # Register shutdown handler
    atexit.register(lambda: scheduler.shutdown(wait=False))


if __name__ == '__main__':
    initialize_app()
    
    # Run with debug mode controlled by environment variable
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    print("\n" + "=" * 70)
    print("CHICKEN FEEDER - Main Flask Server")
    print("=" * 70)
    print("Server running on http://0.0.0.0:5000")
    print("Access at: http://localhost:5000")
    print(f"Debug mode: {'ENABLED' if debug_mode else 'DISABLED'}")
    print(f"Scheduler: RUNNING with {len(scheduler.get_jobs())} scheduled jobs")
    print("=" * 70 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
else:
    # When imported via WSGI (e.g., gunicorn), also initialize
    initialize_app()
