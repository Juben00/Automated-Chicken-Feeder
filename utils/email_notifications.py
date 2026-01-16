"""
Email notification utilities for the Chicken Feeder application.
Sends email notifications for successful feeding sessions.
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging

logger = logging.getLogger('chickenfeeder')

# Email configuration from environment variables
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
EMAIL_FROM = os.getenv('EMAIL_FROM', '')
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'


def send_email(to_email: str, subject: str, html_content: str, text_content: str = None) -> bool:
    """
    Send an email using SMTP.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML body content
        text_content: Plain text fallback (optional)
    
    Returns:
        True if email sent successfully, False otherwise
    """
    if not EMAIL_ENABLED:
        logger.info(f"Email notifications disabled. Would have sent to: {to_email}")
        return True
    
    if not all([SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM]):
        logger.warning("Email configuration incomplete. Set SMTP_USERNAME, SMTP_PASSWORD, and EMAIL_FROM in .env")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = to_email
        
        # Attach plain text and HTML versions
        if text_content:
            msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))
        
        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Email sent successfully to {to_email}")
        return True
    
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD.")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending email: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False


def send_feeding_notification(user_email: str, username: str, amount_grams: int, 
                               trigger_type: str, schedule_name: str = None,
                               timestamp: datetime = None) -> bool:
    """
    Send a notification email for a successful feeding session.
    
    Args:
        user_email: User's email address
        username: User's display name
        amount_grams: Amount of feed dispensed in grams
        trigger_type: Type of trigger ('manual', 'scheduled', 'iot')
        schedule_name: Name of the schedule (if scheduled)
        timestamp: Time of the feeding (defaults to now)
    
    Returns:
        True if email sent successfully, False otherwise
    """
    if not timestamp:
        timestamp = datetime.now()
    
    time_str = timestamp.strftime('%I:%M %p')
    date_str = timestamp.strftime('%B %d, %Y')
    
    # Determine trigger description
    if trigger_type == 'scheduled':
        trigger_desc = f"Scheduled Feed{f' ({schedule_name})' if schedule_name else ''}"
    elif trigger_type == 'manual':
        trigger_desc = "Manual Dispense"
    else:
        trigger_desc = "IoT Device"
    
    subject = f"🐔 Feeding Complete - {amount_grams}g dispensed"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(90deg, #4f8cff 0%, #2357d5 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
            .stats {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .stat-item {{ display: inline-block; text-align: center; padding: 10px 20px; }}
            .stat-value {{ font-size: 28px; font-weight: bold; color: #2357d5; }}
            .stat-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
            .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
            .success-badge {{ background: #28a745; color: white; padding: 5px 15px; border-radius: 20px; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🐔 Chicken Feeder</h1>
                <span class="success-badge">✓ Feeding Complete</span>
            </div>
            <div class="content">
                <p>Hi <strong>{username}</strong>,</p>
                <p>Your chickens have been fed! Here are the details:</p>
                
                <div class="stats">
                    <div class="stat-item">
                        <div class="stat-value">{amount_grams}g</div>
                        <div class="stat-label">Feed Dispensed</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">{time_str}</div>
                        <div class="stat-label">Time</div>
                    </div>
                </div>
                
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Date:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{date_str}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Trigger:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{trigger_desc}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px;"><strong>Status:</strong></td>
                        <td style="padding: 10px;"><span style="color: #28a745;">✓ Success</span></td>
                    </tr>
                </table>
                
                <p style="margin-top: 20px; color: #666; font-size: 14px;">
                    You can view your complete feeding history in the 
                    <a href="#" style="color: #2357d5;">Chicken Feeder Dashboard</a>.
                </p>
            </div>
            <div class="footer">
                <p>This is an automated notification from your Chicken Feeder system.</p>
                <p>To disable these notifications, update your preferences in the app settings.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
    Chicken Feeder - Feeding Complete
    
    Hi {username},
    
    Your chickens have been fed! Here are the details:
    
    - Amount: {amount_grams}g
    - Time: {time_str}
    - Date: {date_str}
    - Trigger: {trigger_desc}
    - Status: Success
    
    You can view your complete feeding history in the Chicken Feeder Dashboard.
    
    ---
    This is an automated notification from your Chicken Feeder system.
    """
    
    return send_email(user_email, subject, html_content, text_content)


def send_feeding_failure_notification(user_email: str, username: str, 
                                       error_message: str, schedule_name: str = None,
                                       timestamp: datetime = None) -> bool:
    """
    Send a notification email for a failed feeding attempt.
    
    Args:
        user_email: User's email address
        username: User's display name
        error_message: Description of what went wrong
        schedule_name: Name of the schedule (if scheduled)
        timestamp: Time of the attempt (defaults to now)
    
    Returns:
        True if email sent successfully, False otherwise
    """
    if not timestamp:
        timestamp = datetime.now()
    
    time_str = timestamp.strftime('%I:%M %p')
    date_str = timestamp.strftime('%B %d, %Y')
    
    subject = f"⚠️ Feeding Failed - Action Required"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #dc3545; color: white; padding: 20px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
            .error-box {{ background: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 8px; margin: 20px 0; }}
            .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>⚠️ Feeding Failed</h1>
            </div>
            <div class="content">
                <p>Hi <strong>{username}</strong>,</p>
                <p>A scheduled feeding attempt has failed. Please check your system.</p>
                
                <div class="error-box">
                    <strong>Error Details:</strong><br>
                    {error_message}
                </div>
                
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Time:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{time_str}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Date:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{date_str}</td>
                    </tr>
                    {f'<tr><td style="padding: 10px;"><strong>Schedule:</strong></td><td style="padding: 10px;">{schedule_name}</td></tr>' if schedule_name else ''}
                </table>
                
                <p style="margin-top: 20px;">
                    <strong>Recommended Actions:</strong>
                </p>
                <ul>
                    <li>Check if your IoT device is powered on and connected</li>
                    <li>Verify the device URL in your profile settings</li>
                    <li>Check the feed hopper level</li>
                    <li>Review the logs in your dashboard</li>
                </ul>
            </div>
            <div class="footer">
                <p>This is an automated notification from your Chicken Feeder system.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
    Chicken Feeder - Feeding Failed
    
    Hi {username},
    
    A scheduled feeding attempt has failed. Please check your system.
    
    Error: {error_message}
    Time: {time_str}
    Date: {date_str}
    {f'Schedule: {schedule_name}' if schedule_name else ''}
    
    Recommended Actions:
    - Check if your IoT device is powered on and connected
    - Verify the device URL in your profile settings
    - Check the feed hopper level
    - Review the logs in your dashboard
    
    ---
    This is an automated notification from your Chicken Feeder system.
    """
    
    return send_email(user_email, subject, html_content, text_content)
