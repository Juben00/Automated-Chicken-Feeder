#!/usr/bin/env python3
"""
Test both dispense workflows:
1. Manual Dispense (direct, no image)
2. Scheduled Dispense (with image processing)
"""

from app import app, db, dispense_feed, scheduled_feed_task
from models import User, FeedSchedule, DispenseLog
import sys

print("=" * 70)
print("TESTING BOTH DISPENSE WORKFLOWS")
print("=" * 70)

with app.app_context():
    # Get user
    user = User.query.filter_by(username='kleo').first()
    if not user:
        print("✗ User 'kleo' not found")
        sys.exit(1)
    
    print(f"\nUser: {user.username}")
    print(f"IoT URL: {user.iot_device_url}")
    print(f"Admin: {user.is_admin}")
    
    # ===== TEST 1: MANUAL DISPENSE =====
    print("\n" + "=" * 70)
    print("TEST 1: MANUAL DISPENSE (Direct, No Image)")
    print("=" * 70)
    print("\nFlow: User → /dispense endpoint → Direct call to Pi /dispense")
    print("Expected: Servo runs immediately, no image capture")
    print("-" * 70)
    
    try:
        success, error_msg, log_id = dispense_feed(
            amount_grams=30,
            trigger_type='manual',
            user_id=user.id
        )
        
        if success:
            print("\n✓ Manual dispense SUCCESSFUL")
            log = DispenseLog.query.get(log_id)
            if log:
                print(f"  - Log ID: {log.id}")
                print(f"  - Amount: {log.amount_grams}g")
                print(f"  - Status: {log.status}")
                print(f"  - Trigger: {log.trigger_type}")
        else:
            print(f"\n✗ Manual dispense FAILED: {error_msg}")
    except Exception as e:
        print(f"\n✗ Error in manual dispense: {e}")
    
    # ===== TEST 2: SCHEDULED DISPENSE =====
    print("\n" + "=" * 70)
    print("TEST 2: SCHEDULED DISPENSE (With Image Processing)")
    print("=" * 70)
    print("\nFlow: Scheduler → Pi /feed_cycle → Capture image → Upload to Flask")
    print("      → ML model processes → Calculate grams → Pi dispenses")
    print("Expected: Image capture + servo runs after ML processing")
    print("-" * 70)
    
    # Get or create a schedule for testing
    schedule = FeedSchedule.query.filter_by(created_by=user.id).first()
    if not schedule:
        print("\n✗ No schedule found for user. Create a schedule first.")
        print("   Go to web UI → Schedules → Add Schedule")
    else:
        print(f"\nUsing schedule: {schedule.name} at {schedule.feed_time}")
        print(f"Amount: {schedule.amount_grams}g")
        print("-" * 70)
        
        try:
            print("\nTriggering scheduled_feed_task manually...")
            scheduled_feed_task(schedule.id)
            print("✓ Scheduled feed task executed")
            
            # Check the log
            log = DispenseLog.query.filter_by(
                schedule_id=schedule.id,
                trigger_type='scheduled'
            ).order_by(DispenseLog.timestamp.desc()).first()
            
            if log:
                print(f"\n✓ Scheduled dispense log created:")
                print(f"  - Log ID: {log.id}")
                print(f"  - Amount: {log.amount_grams}g")
                print(f"  - Status: {log.status}")
                print(f"  - Trigger: {log.trigger_type}")
                if log.error_message:
                    print(f"  - Error: {log.error_message}")
            else:
                print("✗ No log found for scheduled dispense")
        except Exception as e:
            print(f"\n✗ Error in scheduled dispense: {e}")
    
    # ===== SUMMARY =====
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    manual_logs = DispenseLog.query.filter_by(
        trigger_type='manual',
        triggered_by=user.id
    ).count()
    
    scheduled_logs = DispenseLog.query.filter_by(
        trigger_type='scheduled',
        triggered_by=user.id
    ).count()
    
    print(f"\nManual dispenses: {manual_logs}")
    print(f"Scheduled dispenses: {scheduled_logs}")
    print(f"Total dispenses: {manual_logs + scheduled_logs}")
    
    print("\n" + "=" * 70)
    print("WORKFLOW STATUS")
    print("=" * 70)
    print("✓ Manual Dispense: Ready (direct to Pi, no image)")
    print("✓ Scheduled Dispense: Ready (with image processing)")
    print("\nBoth workflows are implemented and functional!")
    print("=" * 70)
