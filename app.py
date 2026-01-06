from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from models import db, User, Device, FeedSchedule, DispenseLog
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from scheduler import start_scheduler
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

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'secret_key')
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'chickenfeeder.sqlite')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Move this import here to avoid circular import
    from routes.api import api_bp
    app.register_blueprint(api_bp)

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

def start_scheduler_once():
    if not scheduler.running:
        scheduler.start()


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
    device_url = None
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

                    # Log successful dispense
                    log_entry = DispenseLog(
                        amount_grams=dispensed_val,
                        trigger_type='scheduled',
                        schedule_id=schedule_id,
                        status='success',
                        error_message=None,
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


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
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
                flash('Email already registered.', 'error')
                return redirect(url_for('profile'))
        
        # Handle password change
        if new_password or current_password or confirm_password:
            # Password change requested
            if not current_password:
                flash('Current password required to change password.', 'error')
                return redirect(url_for('profile'))
            
            if not check_password_hash(current_user.password_hash, current_password):
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('profile'))
            
            if len(new_password) < 6:
                flash('New password must be at least 6 characters long.', 'error')
                return redirect(url_for('profile'))
            
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'error')
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
def register():
    """
    Public registration: create a new user account.
    Admin accounts should be created via the admin dashboard.
    """
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        iot_device_url = request.form.get('iot_device_url', '').strip()
        if not username or not email or not password:
            flash('All fields are required.')
            return redirect(url_for('register'))
        # uniqueness checks
        if User.query.filter_by(username=username).first():
            flash('Username already taken.')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
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
        flash('Account created. You may now log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

# Helper: require admin
def require_admin():
    if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
        flash('Unauthorized: admin access required.')
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
            flash('Username, email and password are required.')
            return redirect(url_for('admin_create_user'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('admin_create_user'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
            return redirect(url_for('admin_create_user'))
        u = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_admin=is_admin
        )
        db.session.add(u)
        db.session.commit()
        flash('User created successfully.')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/create_user.html')

@app.route('/admin/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if not require_admin():
        return redirect(url_for('dashboard'))
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.')
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', None)
        is_admin = bool(request.form.get('is_admin'))
        # uniqueness checks (exclude this user)
        if username and username != user.username and User.query.filter_by(username=username).first():
            flash('Username already taken.')
            return redirect(url_for('admin_edit_user', user_id=user_id))
        if email and email != user.email and User.query.filter_by(email=email).first():
            flash('Email already registered.')
            return redirect(url_for('admin_edit_user', user_id=user_id))
        if username:
            user.username = username
        if email:
            user.email = email
        user.is_admin = is_admin
        if password:
            user.password_hash = generate_password_hash(password)
        db.session.commit()
        flash('User updated.')
        return redirect(url_for('admin_dashboard'))
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
        
        # Validate amount
        if amount_grams < 5 or amount_grams > 150:
            return jsonify({'error': 'Amount must be between 5 and 150 grams'}), 400
        
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
            # Update the schedule with remaining amount
            schedule.amount_grams = remaining_grams
            db.session.commit()
        
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
        flash('User not found.')
        return redirect(url_for('admin_dashboard'))
    # Prevent deleting yourself
    if user.id == current_user.id:
        flash('You cannot delete your own account.')
        return redirect(url_for('admin_dashboard'))
    # Ensure at least one admin remains
    if user.is_admin:
        other_admins = User.query.filter(User.is_admin == True, User.id != user.id).count()
        if other_admins == 0:
            flash('Cannot delete the last admin user.')
            return redirect(url_for('admin_dashboard'))
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted.')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting user.')
    return redirect(url_for('admin_dashboard'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
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
    return render_template('dashboard.html', 
                         schedules=today_schedules,
                         logs=today_logs,
                         total_today=total_today)

@app.route('/devices', methods=['GET', 'POST'])
@login_required
def devices():
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
            if not device_id:
                device_message = 'Device ID is required.'
            else:
                existing = Device.query.filter_by(device_id=device_id, user_id=current_user.id).first()
                if existing:
                    device_message = f'Device already registered. Token: {existing.token}'
                else:
                    import secrets
                    token = secrets.token_urlsafe(32)
                    device = Device(device_id=device_id, user_id=current_user.id, token=token)
                    db.session.add(device)
                    db.session.commit()
                    device_message = f'Device registered! Token: {token}'
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
    if request.method == 'POST':
        name = request.form['name']
        feed_time_str = request.form['feed_time']
        amount_grams = int(request.form['amount_grams'])
        
        # Parse time
        feed_time = datetime.strptime(feed_time_str, '%H:%M').time()
        
        # --- Limit: 20-150 grams per feeding ---
        if amount_grams < 20 or amount_grams > 150:
            flash('Amount must be between 20 and 150 grams (for 1-5 chickens, 20-30g each).')
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
            flash('Schedule created but failed to add to scheduler. Please restart the app.')
            return redirect(url_for('schedules'))
        
        flash('Schedule added successfully!')
        return redirect(url_for('schedules'))
    
    return render_template('add_schedule.html')

@app.route('/schedules/<int:schedule_id>/delete', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    schedule = db.session.get(FeedSchedule, schedule_id)
    if not schedule:
        flash('Schedule not found')
        return redirect(url_for('schedules'))
    if schedule.created_by != current_user.id:
        flash('Unauthorized')
        return redirect(url_for('schedules'))
    
    # Remove from scheduler
    try:
        scheduler.remove_job(f'schedule_{schedule_id}')
    except:
        pass
    
    db.session.delete(schedule)
    db.session.commit()
    
    flash('Schedule deleted successfully!')
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
        except:
            pass
    
    return jsonify({'success': True, 'is_active': schedule.is_active})

@app.route('/dispense', methods=['POST'])
@login_required
def manual_dispense():
    """
    API endpoint for manual feed dispensing
    Also serves as IoT integration endpoint
    """
    data = request.get_json()
    amount_grams = data.get('amount', 0)
    
    # --- Limit: 20-150 grams per feeding ---
    if amount_grams < 20 or amount_grams > 150:
        return jsonify({'error': 'Invalid amount. Must be between 20 and 150 grams (for 1-5 chickens, 20-30g each)'}), 400
    
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
            page=page, per_page=50, error_out=False
        )
    else:
        logs = DispenseLog.query.order_by(DispenseLog.timestamp.desc()).paginate(
            page=page, per_page=50, error_out=False
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
        admin = User(
            username='admin',
            email='admin@chickenfeeder.com',
            password_hash=generate_password_hash('admin123'),
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

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

def get_feed_ratio():
    if not os.path.exists(CONFIG_PATH):
        return {'pellets': 50, 'grams': 10}
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def set_feed_ratio(pellets, grams):
    with open(CONFIG_PATH, 'w') as f:
        json.dump({'pellets': pellets, 'grams': grams}, f)

@app.route('/admin/feed-ratio', methods=['GET', 'POST'])
@login_required
def admin_feed_ratio():
    if not require_admin():
        return redirect(url_for('dashboard'))
    ratio = get_feed_ratio()
    if request.method == 'POST':
        try:
            pellets = int(request.form.get('pellets', 50))
            grams = float(request.form.get('grams', 10))
            if pellets <= 0 or grams <= 0:
                flash('Values must be positive.', 'danger')
            else:
                set_feed_ratio(pellets, grams)
                flash('Feed-to-gram ratio updated!', 'success')
                return redirect(url_for('admin_feed_ratio'))
        except Exception:
            flash('Invalid input.', 'danger')
    return render_template('admin/feed_ratio.html', ratio=ratio)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin_user()
        setup_scheduled_jobs()
    
    # Run without debug mode to avoid verbose reloader logs
    print("\n" + "=" * 70)
    print("CHICKEN FEEDER - Main Flask Server")
    print("=" * 70)
    print("Server running on http://0.0.0.0:5000")
    print("Access at: http://localhost:5000")
    print("=" * 70 + "\n")
    app.run(debug=True)
