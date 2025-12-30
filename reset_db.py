#!/usr/bin/env python3
"""
Reset database script
"""
import os
from app import app, db
from models import User, Device, FeedSchedule, DispenseLog
from werkzeug.security import generate_password_hash

with app.app_context():
    # Drop all tables
    db.drop_all()
    print("✓ Dropped all tables")
    
    # Create all tables
    db.create_all()
    print("✓ Created all tables")
    
    # Create default admin user
    admin = User(
        username='admin',
        email='admin@chickenfeeder.com',
        password_hash=generate_password_hash('admin123'),
        is_admin=True
    )
    db.session.add(admin)
    db.session.commit()
    print("✓ Created admin user (username: admin, password: admin123)")
    
    print(f'\n✓ Database reset successfully!')
    print(f'\nCurrent counts:')
    print(f'  Users: {User.query.count()}')
    print(f'  Devices: {Device.query.count()}')
    print(f'  Schedules: {FeedSchedule.query.count()}')
    print(f'  Logs: {DispenseLog.query.count()}')
