#!/usr/bin/env python3
"""
Debug script to check if schedule was added to scheduler and inspect job details.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db, scheduler
from models import FeedSchedule, DispenseLog
from datetime import datetime
import time

with app.app_context():
    print("=" * 70)
    print("SCHEDULER DEBUG - CHECK 6:56 PM SCHEDULE")
    print("=" * 70)
    
    now = datetime.now()
    print(f"\nCurrent time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Current time (24h): {now.strftime('%H:%M:%S')}")
    
    # Check if scheduler is running
    print(f"\nScheduler running: {scheduler.running}")
    print(f"Scheduler state: {scheduler.state}")
    
    # Get all jobs
    jobs = scheduler.get_jobs()
    print(f"\nTotal jobs in scheduler: {len(jobs)}")
    if jobs:
        for job in jobs:
            print(f"\n  Job ID: {job.id}")
            print(f"  Next run time: {job.next_run_time}")
            print(f"  Trigger: {job.trigger}")
            print(f"  Function: {job.func.__name__}")
            print(f"  Args: {job.args}")
    else:
        print("  (no jobs scheduled)")
    
    # Check all schedules in DB
    print(f"\n" + "=" * 70)
    print("SCHEDULES IN DATABASE")
    print("=" * 70)
    schedules = FeedSchedule.query.all()
    print(f"Total schedules: {len(schedules)}")
    for s in schedules:
        status = "ACTIVE" if s.is_active else "INACTIVE"
        job_id = f'schedule_{s.id}'
        job_exists = any(j.id == job_id for j in jobs)
        print(f"\n  ID: {s.id} | Name: {s.name}")
        print(f"  Time: {s.feed_time} | Amount: {s.amount_grams}g | Status: {status}")
        print(f"  Created by: user_id={s.created_by}")
        print(f"  Job in scheduler: {'YES' if job_exists else 'NO'}")
    
    # Check recent dispense logs
    print(f"\n" + "=" * 70)
    print("RECENT DISPENSE LOGS (last 10)")
    print("=" * 70)
    logs = DispenseLog.query.order_by(DispenseLog.timestamp.desc()).limit(10).all()
    if not logs:
        print("  (no logs)")
    for l in logs:
        status_icon = "✓" if l.status == "success" else "✗"
        print(f"\n  {status_icon} ID: {l.id} | Time: {l.timestamp}")
        print(f"    Amount: {l.amount_grams}g | Trigger: {l.trigger_type} | Status: {l.status}")
        if l.error_message:
            print(f"    Error: {l.error_message}")
    
    print(f"\n" + "=" * 70)
    print("\nDIAGNOSIS:")
    print("-" * 70)
    
    # Check if 6:56 PM schedule exists
    schedules_at_656 = [s for s in schedules if str(s.feed_time) == "18:56:00"]
    if schedules_at_656:
        print(f"✓ Found {len(schedules_at_656)} schedule(s) at 18:56 (6:56 PM)")
        for s in schedules_at_656:
            job_id = f'schedule_{s.id}'
            job_exists = any(j.id == job_id for j in jobs)
            if job_exists:
                print(f"  ✓ Job IS in scheduler")
                job = next(j for j in jobs if j.id == job_id)
                print(f"  Next run: {job.next_run_time}")
            else:
                print(f"  ✗ WARNING: Job NOT in scheduler! Schedule exists but no job was created.")
    else:
        print(f"✗ No schedule found at 18:56 (6:56 PM)")
        print(f"  Available times: {[str(s.feed_time) for s in schedules if s.is_active]}")
    
    # Check if we're past 6:56 PM today
    target_time = datetime.strptime("18:56:00", "%H:%M:%S").time()
    target_dt = datetime.combine(now.date(), target_time)
    if now > target_dt:
        print(f"\n⚠ Current time {now.strftime('%H:%M:%S')} is PAST 18:56:00")
        print(f"  The job will run tomorrow at 18:56 (unless it already ran today)")
    else:
        print(f"\n⏳ Current time {now.strftime('%H:%M:%S')} is BEFORE 18:56:00")
        print(f"  The job should run today at 18:56")
    
    print("\n" + "=" * 70)
