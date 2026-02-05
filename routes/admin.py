from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from models import User, FeedSchedule, DispenseLog, Device
from flask import abort
from utils.model_utils import get_feed_ratio, set_feed_ratio
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func
import csv
import io

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            return abort(403)
        return f(*args, **kwargs)
    return decorated_function

# Note: Feed ratio config is handled by /admin/feed-ratio route in app.py
# This route redirects to maintain backward compatibility
@admin_bp.route('/config', methods=['GET', 'POST'])
@login_required
@admin_required
def config():
    # Redirect to the main feed-ratio page in app.py
    return redirect(url_for('admin_feed_ratio'))

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    users = User.query.all()
    total_users = len(users)
    # User breakdown
    today = datetime.now().date()
    new_today = User.query.filter(func.date(User.created_at) == today).count()
    active_users = total_users  # Placeholder: all users are active unless you have an 'active' field
    inactive_users = 0  # Placeholder
    admin_count = User.query.filter_by(is_admin=True).count()
    customer_count = User.query.filter_by(is_admin=False).count()
    # User growth (last 7 days)
    last_week = today - timedelta(days=7)
    new_last_week = User.query.filter(User.created_at >= last_week).count()
    # Feed schedule stats
    from models import FeedSchedule, DispenseLog
    total_schedules = FeedSchedule.query.count()
    avg_schedules_per_user = round(total_schedules / total_users, 2) if total_users else 0
    # Feed consumption analytics
    today_logs = DispenseLog.query.filter(func.date(DispenseLog.timestamp) == today).all()
    daily_feed = sum(log.amount_grams for log in today_logs if log.status == 'success')
    week_ago = today - timedelta(days=7)
    week_logs = DispenseLog.query.filter(DispenseLog.timestamp >= week_ago).all()
    weekly_feed = sum(log.amount_grams for log in week_logs if log.status == 'success')
    # Last 7 days feed for chart
    feed_chart = []
    for i in range(7):
        day = today - timedelta(days=i)
        logs = DispenseLog.query.filter(func.date(DispenseLog.timestamp) == day).all()
        feed_chart.append({
            'date': day.strftime('%Y-%m-%d'),
            'amount': sum(log.amount_grams for log in logs if log.status == 'success')
        })
    feed_chart.reverse()
    # Placeholder for pending approvals, open issues, system alerts
    pending_approvals = 0
    open_issues = 0
    system_alerts = []
    return render_template(
        'admin/dashboard.html',
        users=users,
        total_users=total_users,
        new_today=new_today,
        active_users=active_users,
        inactive_users=inactive_users,
        admin_count=admin_count,
        customer_count=customer_count,
        new_last_week=new_last_week,
        avg_schedules_per_user=avg_schedules_per_user,
        daily_feed=daily_feed,
        weekly_feed=weekly_feed,
        feed_chart=feed_chart,
        pending_approvals=pending_approvals,
        open_issues=open_issues,
        system_alerts=system_alerts
    )

@admin_bp.route('/generate_report')
@login_required
@admin_required
def generate_report():
    report_type = request.args.get('type', 'all')
    start_month = request.args.get('start_month')  # Format: YYYY-MM
    end_month = request.args.get('end_month')      # Format: YYYY-MM
    
    # Parse date range
    if start_month:
        start_date = datetime.strptime(start_month, '%Y-%m').replace(day=1)
    else:
        start_date = datetime(2020, 1, 1)  # Default to earliest possible
    
    if end_month:
        # Get last day of end month
        end_date = datetime.strptime(end_month, '%Y-%m')
        if end_date.month == 12:
            end_date = end_date.replace(year=end_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_date = end_date.replace(month=end_date.month + 1, day=1) - timedelta(days=1)
        end_date = end_date.replace(hour=23, minute=59, second=59)
    else:
        end_date = datetime.now()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    filename_parts = ['report']
    if start_month:
        filename_parts.append(start_month)
    if end_month:
        filename_parts.append(f'to_{end_month}')
    
    if report_type == 'dispense_logs' or report_type == 'all':
        # Dispense Logs Report
        writer.writerow(['=== DISPENSE LOGS REPORT ==='])
        writer.writerow(['ID', 'Timestamp', 'Amount (grams)', 'Trigger Type', 'Schedule ID', 'Schedule Name', 'Status', 'Error Message', 'Triggered By User ID', 'Triggered By Username'])
        logs = DispenseLog.query.filter(
            DispenseLog.timestamp >= start_date,
            DispenseLog.timestamp <= end_date
        ).order_by(DispenseLog.timestamp.desc()).all()
        for log in logs:
            schedule_name = log.schedule.name if log.schedule else 'N/A'
            username = log.user.username if log.user else 'N/A'
            writer.writerow([
                log.id,
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                log.amount_grams,
                log.trigger_type,
                log.schedule_id or 'N/A',
                schedule_name,
                log.status,
                log.error_message or '',
                log.triggered_by or 'N/A',
                username
            ])
        writer.writerow([])
    
    if report_type == 'schedules' or report_type == 'all':
        # Feed Schedules Report
        writer.writerow(['=== FEED SCHEDULES REPORT ==='])
        writer.writerow(['ID', 'Name', 'Feed Time', 'Amount (grams)', 'Is Active', 'Created By User ID', 'Created By Username', 'Created At'])
        schedules = FeedSchedule.query.filter(
            FeedSchedule.created_at >= start_date,
            FeedSchedule.created_at <= end_date
        ).order_by(FeedSchedule.created_at.desc()).all()
        for schedule in schedules:
            username = schedule.user.username if schedule.user else 'N/A'
            writer.writerow([
                schedule.id,
                schedule.name,
                schedule.feed_time.strftime('%H:%M'),
                schedule.amount_grams,
                'Yes' if schedule.is_active else 'No',
                schedule.created_by,
                username,
                schedule.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        writer.writerow([])
    
    if report_type == 'users' or report_type == 'all':
        # Users Report
        writer.writerow(['=== USERS REPORT ==='])
        writer.writerow(['ID', 'Username', 'Email', 'Is Admin', 'IoT Device URL', 'Created At', 'Total Schedules', 'Total Dispenses'])
        users = User.query.filter(
            User.created_at >= start_date,
            User.created_at <= end_date
        ).order_by(User.created_at.desc()).all()
        for user in users:
            total_schedules = FeedSchedule.query.filter_by(created_by=user.id).count()
            total_dispenses = DispenseLog.query.filter_by(triggered_by=user.id).count()
            writer.writerow([
                user.id,
                user.username,
                user.email,
                'Yes' if user.is_admin else 'No',
                user.iot_device_url or 'N/A',
                user.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                total_schedules,
                total_dispenses
            ])
        writer.writerow([])
    
    if report_type == 'devices' or report_type == 'all':
        # Devices Report
        writer.writerow(['=== DEVICES REPORT ==='])
        writer.writerow(['ID', 'Device ID', 'User ID', 'Username', 'Token', 'Created At'])
        devices = Device.query.filter(
            Device.created_at >= start_date,
            Device.created_at <= end_date
        ).order_by(Device.created_at.desc()).all()
        for device in devices:
            username = device.user.username if device.user else 'N/A'
            writer.writerow([
                device.id,
                device.device_id,
                device.user_id,
                username,
                '[REDACTED]',  # Token hidden for security
                device.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        writer.writerow([])
    
    if report_type == 'summary' or report_type == 'all':
        # Summary Statistics
        writer.writerow(['=== SUMMARY STATISTICS ==='])
        writer.writerow(['Metric', 'Value'])
        
        # User stats
        total_users = User.query.count()
        admin_count = User.query.filter_by(is_admin=True).count()
        regular_users = User.query.filter_by(is_admin=False).count()
        
        # Schedule stats
        total_schedules = FeedSchedule.query.count()
        active_schedules = FeedSchedule.query.filter_by(is_active=True).count()
        
        # Dispense stats in date range
        logs_in_range = DispenseLog.query.filter(
            DispenseLog.timestamp >= start_date,
            DispenseLog.timestamp <= end_date
        ).all()
        total_dispenses = len(logs_in_range)
        successful_dispenses = len([l for l in logs_in_range if l.status == 'success'])
        failed_dispenses = len([l for l in logs_in_range if l.status != 'success'])
        total_feed_dispensed = sum(l.amount_grams for l in logs_in_range if l.status == 'success')
        
        # Device stats
        total_devices = Device.query.count()
        
        writer.writerow(['Report Period', f'{start_date.strftime("%Y-%m-%d")} to {end_date.strftime("%Y-%m-%d")}'])
        writer.writerow(['Total Users (All Time)', total_users])
        writer.writerow(['Admin Users', admin_count])
        writer.writerow(['Regular Users', regular_users])
        writer.writerow(['Total Schedules (All Time)', total_schedules])
        writer.writerow(['Active Schedules', active_schedules])
        writer.writerow(['Total Dispenses (In Period)', total_dispenses])
        writer.writerow(['Successful Dispenses', successful_dispenses])
        writer.writerow(['Failed Dispenses', failed_dispenses])
        writer.writerow(['Total Feed Dispensed (grams)', total_feed_dispensed])
        writer.writerow(['Total Devices', total_devices])
        writer.writerow(['Generated At', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    
    output.seek(0)
    filename = '_'.join(filename_parts) + f'_{report_type}.csv'
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

# Note: /admin/users route is defined in app.py as admin_user_dashboard
# to maintain consistency with the user management flow
