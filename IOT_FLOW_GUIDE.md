# IoT Dispensing System - Complete Flow Documentation

## System Overview

The Chicken Feeder system implements an automated dispensing flow:

```
Schedule Created (Web UI)
        ↓
Scheduled Time Reached
        ↓
Flask Server Scheduler Triggers
        ↓
Flask Server Sends Dispense Command to IoT Device
        ↓
IoT Device Receives Command
        ↓
IoT Device Activates Servo (Dispenses Feed)
        ↓
IoT Device Confirms to Flask Server
        ↓
Flask Server Logs the Action
        ↓
Dashboard Updates with New Log Entry
```

## How It Works

### 1. **Create a Schedule** (Web UI)
- Navigate to "Schedules" → "Add Schedule"
- Enter:
  - **Name**: e.g., "Morning Feed"
  - **Time**: e.g., 06:30 (24-hour format)
  - **Amount**: 20-150 grams
- Click "Add Schedule"

### 2. **Flask Server Schedules the Task**
- APScheduler registers a cron job for the specified time
- Stores schedule in database

### 3. **Scheduled Time Arrives**
- APScheduler automatically triggers `scheduled_feed_task(schedule_id)`
- Function calls `dispense_feed()` with schedule details

### 4. **Flask Server Sends Dispense Command**
- Looks up user's IoT device (from Device table)
- Gets device URL/hostname (e.g., `pi_klei` or `192.168.1.100`)
- Sends HTTP POST request to: `http://[device]:5000/dispense`
- Payload: `{"amount_grams": 30}`

### 5. **IoT Device Receives Command**
- `/dispense` endpoint receives the request
- Validates amount (must be 5-150g)
- Calculates servo cycles needed (5g per cycle)

### 6. **IoT Device Dispenses Feed**
- Activates servo motor:
  - Position 0° = Fill hopper cup
  - Position 180° = Drop cup into feeder
  - Repeats for each 5g cycle
- Returns success response with details

### 7. **Flask Server Logs the Action**
- Creates DispenseLog entry with:
  - Amount dispensed
  - Trigger type ("scheduled")
  - Status ("success" or "failure")
  - Error message (if any)
  - User ID and schedule ID

### 8. **Dashboard Updates**
- User sees new log entry in "Recent Activity"
- "Today's Feed" total updates
- Success count increases

## API Endpoints

### Main Flask Server

#### POST `/iot/authenticate`
Authenticate IoT device with server
```json
{
  "device_id": "pi_klei",
  "token": "your_device_token"
}
```

#### POST `/iot/dispense`
Send dispense command (called by server on schedule)
```json
{
  "device_id": "pi_klei",
  "amount_grams": 30
}
```

#### POST `/dispense`
Manual dispense (requires user login)
```json
{
  "amount": 30
}
```

### IoT Device

#### GET `/`
Check if device is online
```json
{
  "message": "IoT device pi_klei online."
}
```

#### POST `/dispense`
Receive dispense command from server
```json
{
  "amount_grams": 30
}
```

Response:
```json
{
  "status": "success",
  "amount_requested": 30,
  "amount_dispensed": 30,
  "cycles": 6,
  "device_id": "pi_klei"
}
```

#### POST `/feed_cycle`
Full cycle: capture image → upload → dispense
```json
(no parameters needed - device does everything)
```

## Setup Instructions

### 1. Register Your IoT Device

**Via Web UI:**
1. Log in to web UI
2. Go to "Devices"
3. Enter Device ID: `pi_klei`
4. Click "Register Device"
5. Copy the generated token

**Via API:**
```bash
curl -X POST http://localhost:5000/register_device \
  -H "Content-Type: application/json" \
  -d '{"device_id": "pi_klei"}'
```

### 2. Configure IoT Device

**On Raspberry Pi (codesiot/config.json):**
```json
{
  "device_id": "pi_klei",
  "user_token": "YOUR_TOKEN_FROM_STEP_1",
  "upload_endpoint": "http://YOUR_MAIN_SERVER:5000/api/count_pellets"
}
```

### 3. Start IoT Device App

```bash
cd codesiot
python app.py
```

IoT device will start on: `http://pi_klei:5000`

### 4. Create a Schedule

1. Log in to web UI
2. Go to "Schedules" → "Add Schedule"
3. Set time to a few minutes from now (for testing)
4. Click "Add Schedule"

### 5. Wait for Schedule Time

The system will automatically:
- Trigger at the scheduled time
- Send dispense command to IoT device
- Log the action
- Update dashboard

## Testing

### Quick Test Script

```bash
python test_iot_flow.py
```

This script:
- Checks if Flask server is running
- Checks if IoT device is accessible
- Sends a test dispense command to IoT device
- Displays results

### Manual Test

**Send dispense command directly to IoT device:**
```bash
curl -X POST http://pi_klei:5000/dispense \
  -H "Content-Type: application/json" \
  -d '{"amount_grams": 30}'
```

**Expected response:**
```json
{
  "status": "success",
  "amount_requested": 30,
  "amount_dispensed": 30,
  "cycles": 6,
  "device_id": "pi_klei"
}
```

## Troubleshooting

### Error: "Failed to connect to device pi_klei"
- **Cause**: IoT device is not running or not reachable
- **Solution**:
  1. Check if IoT app is running: `python app.py` in codesiot folder
  2. Check device IP/hostname: `ping pi_klei`
  3. Check network connectivity
  4. Verify device_id in config matches registration

### Error: "Unauthorized" when sending dispense command
- **Cause**: Invalid device token
- **Solution**:
  1. Re-register device in web UI
  2. Copy the new token
  3. Update config.json on IoT device
  4. Restart IoT app

### Dispense command sent but servo doesn't activate
- **Cause**: Servo not properly connected or GPIO pins misconfigured
- **Solution**:
  1. Check servo connection
  2. Test servo directly: `python -c "from servo import activate_servo; activate_servo()"`
  3. Verify GPIO pin numbers in servo.py

### Schedule not triggering
- **Cause**: Schedule time format issue or timezone mismatch
- **Solution**:
  1. Check schedule time in database: `SELECT * FROM feed_schedule`
  2. Verify system time on server: `date`
  3. Check APScheduler logs for errors
  4. Try creating schedule for time 1-2 minutes away

## Database Schema

### Device
```
- id (Primary Key)
- device_id (String, Unique)
- user_id (Foreign Key → User)
- token (String, Unique)
- created_at (DateTime)
```

### FeedSchedule
```
- id (Primary Key)
- name (String)
- feed_time (Time)
- amount_grams (Integer)
- is_active (Boolean)
- created_by (Foreign Key → User)
- created_at (DateTime)
```

### DispenseLog
```
- id (Primary Key)
- timestamp (DateTime)
- amount_grams (Integer)
- trigger_type (String: 'manual', 'scheduled', 'iot')
- schedule_id (Foreign Key → FeedSchedule, nullable)
- status (String: 'success', 'failure')
- error_message (Text, nullable)
- triggered_by (Foreign Key → User, nullable)
```

## Security Notes

1. **Device Tokens**: Stored securely in database, regenerate if compromised
2. **Network**: Ensure IoT device is on trusted network only
3. **Credentials**: Store device token in secure location
4. **Updates**: Update device token periodically for security

## Performance Considerations

- **Schedule Accuracy**: APScheduler checks every minute, so schedules are accurate ±1 minute
- **Network Latency**: Dispense command timeout is 10 seconds
- **Servo Timing**: Each 5g cycle takes ~1 second (0.5s fill + 0.5s drop)
- **Database**: Logs are persisted for audit trail

## Future Enhancements

- [ ] Image-based pellet counting for adaptive dispensing
- [ ] Multiple device support (fallback to second device)
- [ ] Email notifications on failure
- [ ] Mobile app for manual control
- [ ] Real-time monitoring dashboard
- [ ] Predictive feeding based on chicken behavior
