#!/usr/bin/env python3
"""
End-to-end communication test: Main Flask -> IoT Device

This script:
1. Checks if a user has iot_device_url configured
2. Calls dispense_feed() which will attempt to POST to the IoT /dispense endpoint
3. Prints the result and checks DispenseLog for success/failure

Usage:
  1) Ensure IoT app is running on the Pi at the URL configured in user profile
  2) python test_e2e_communication.py
"""

from app import app, db, dispense_feed
from models import User, DispenseLog
import sys

AMOUNT = 30  # grams to request

with app.app_context():
    print("=" * 70)
    print("END-TO-END COMMUNICATION TEST: Main Flask → IoT Device")
    print("=" * 70)
    
    # Find a non-admin user
    user = User.query.filter_by(is_admin=False).first() or User.query.first()
    if not user:
        print("\n✗ No users found in DB. Create a user first.")
        sys.exit(1)

    print(f"\nUser: {user.username} (ID: {user.id})")
    print(f"IoT Device URL: {user.iot_device_url}")

    if not user.iot_device_url:
        print("\n✗ User has no iot_device_url configured.")
        print("  Set it in Profile or via DB before testing.")
        sys.exit(1)

    print(f"\n{'=' * 70}")
    print(f"Requesting dispense of {AMOUNT}g from user {user.username}...")
    print(f"Target device: {user.iot_device_url}")
    print(f"{'=' * 70}\n")
    
    success, error_message, log_id = dispense_feed(
        amount_grams=AMOUNT,
        trigger_type='e2e-test',
        user_id=user.id
    )

    print(f"\nResult: {'SUCCESS ✓' if success else 'FAILURE ✗'}")
    if success:
        print(f"DispenseLog ID: {log_id}")
    else:
        print(f"Error: {error_message}")

    # Print the created log entry
    log = DispenseLog.query.get(log_id)
    if log:
        print(f"\n{'=' * 70}")
        print("DispenseLog Entry:")
        print(f"{'=' * 70}")
        print(f"  ID: {log.id}")
        print(f"  Timestamp: {log.timestamp}")
        print(f"  Amount: {log.amount_grams}g")
        print(f"  Trigger: {log.trigger_type}")
        print(f"  Status: {log.status}")
        print(f"  User: {log.user.username if log.user else 'N/A'}")
        if log.error_message:
            print(f"  Error: {log.error_message}")
    
    print(f"\n{'=' * 70}")
    
    if success:
        print("\n✓ COMMUNICATION SUCCESSFUL!")
        print("  Main Flask successfully sent dispense command to IoT device.")
        print("  Servo should have moved on the Pi.")
    else:
        print("\n✗ COMMUNICATION FAILED!")
        print("\nTroubleshooting steps:")
        print("  1. Check IoT app is running on Pi: python app.py")
        print("  2. Verify iot_device_url is reachable from main machine")
        print("  3. Check Pi firewall allows port 5000")
        print("  4. Test manually: curl -X POST http://<pi-ip>:5000/dispense \\")
        print("     -H 'Content-Type: application/json' \\")
        print("     -d '{\"amount_grams\":30}'")
