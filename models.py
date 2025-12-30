from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    iot_device_url = db.Column(db.String(255), nullable=True)  # e.g., 'http://192.168.1.100:5000' or 'pi_klei'
    is_admin = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('devices', lazy=True))

class FeedSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    feed_time = db.Column(db.Time, nullable=False)
    amount_grams = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('schedules', lazy=True))

class DispenseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    amount_grams = db.Column(db.Integer, nullable=False)
    trigger_type = db.Column(db.String(20), nullable=False)
    schedule_id = db.Column(db.Integer, db.ForeignKey('feed_schedule.id'), nullable=True)
    status = db.Column(db.String(20), default='success')
    error_message = db.Column(db.Text, nullable=True)
    triggered_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    schedule = db.relationship('FeedSchedule', backref=db.backref('dispense_logs', lazy=True))
    user = db.relationship('User', backref=db.backref('dispense_logs', lazy=True))
