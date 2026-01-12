from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import User
from flask import abort
from utils.model_utils import get_feed_ratio, set_feed_ratio
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            return abort(403)
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        pellets = int(request.form.get('pellets', 50))
        grams = float(request.form.get('grams', 10))
        set_feed_ratio(pellets, grams)
        flash('Feed ratio updated!', 'success')
        return redirect(url_for('admin.config'))
    ratio = get_feed_ratio()
    return render_template('admin_config.html', ratio=ratio)

@admin_bp.route('/dashboard')
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
@admin_required
def generate_report():
    # Placeholder: implement report logic here
    return 'Report generation coming soon!'

@admin_bp.route('/users')
@admin_required
def users():
    users = User.query.all()
    return render_template('admin/users.html', users=users)
