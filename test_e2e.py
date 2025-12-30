"""
End-to-end test script for CHICKENFEEDER.

This script runs inside the Flask app context and calls `dispense_feed(...)`
so the main server will attempt to contact the IoT device at the URL
stored on the user record (`user.iot_device_url`).

Usage:
  1) Ensure the IoT device app is running and reachable at the URL set in the user's profile
     (e.g. http://127.0.0.1:5000)
  2) Ensure main app DB has a non-admin user with schedules or at least an `iot_device_url` set
  3) Run:
     python test_e2e.py

The script prints the result of the `dispense_feed` call and the created DispenseLog id.
"""

from app import app, db, dispense_feed
from models import User

AMOUNT = 30  # grams to request

with app.app_context():
    # Find a non-admin user, otherwise any user
    user = User.query.filter_by(is_admin=False).first() or User.query.first()
    if not user:
        print('No users found in DB. Create a user first.')
        raise SystemExit(1)

    print(f"Using user: id={user.id}, username={user.username}, iot_device_url={user.iot_device_url}")

    if not user.iot_device_url:
        print('User has no `iot_device_url` configured. Set it in profile or via DB before testing.')
        raise SystemExit(1)

    print(f"Requesting dispense of {AMOUNT}g for user {user.username}...")
    success, error_message, log_id = dispense_feed(amount_grams=AMOUNT, trigger_type='e2e-test', user_id=user.id)

    if success:
        print(f"Success. DispenseLog id={log_id}")
    else:
        print('Failed to dispense.')
        print('Error message from communicate_with_iot_device:')
        print(error_message)

    # Print the last log entry for quick reference
    from models import DispenseLog
    last = DispenseLog.query.order_by(DispenseLog.timestamp.desc()).first()
    if last:
        print('Last DispenseLog:')
        print(f'  id={last.id}, time={last.timestamp}, amount={last.amount_grams}, status={last.status}, error={last.error_message}')
