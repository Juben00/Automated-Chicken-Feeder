#!/usr/bin/env python3
"""
Reset database script
WARNING: This will delete all data! Use with caution.
"""
import os
import secrets
from dotenv import load_dotenv
load_dotenv()

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
    
    # Get admin credentials from environment or generate secure defaults
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@chickenfeeder.com')
    admin_password = os.getenv('ADMIN_PASSWORD')
    
    # Generate secure random password if not provided
    if not admin_password:
        admin_password = secrets.token_urlsafe(16)
        print("\n" + "=" * 70)
        print("WARNING: No ADMIN_PASSWORD set in environment!")
        print(f"Generated temporary password: {admin_password}")
        print("Please change this password immediately after login!")
        print("Set ADMIN_PASSWORD in .env to avoid this message.")
        print("=" * 70 + "\n")
    
    # Create default admin user
    admin = User(
        username=admin_username,
        email=admin_email,
        password_hash=generate_password_hash(admin_password),
        is_admin=True
    )
    db.session.add(admin)
    db.session.commit()
    print(f"✓ Created admin user (username: {admin_username})")
    
    print(f'\n✓ Database reset successfully!')
    print(f'\nCurrent counts:')
    print(f'  Users: {User.query.count()}')
    print(f'  Devices: {Device.query.count()}')
    print(f'  Schedules: {FeedSchedule.query.count()}')
    print(f'  Logs: {DispenseLog.query.count()}')
