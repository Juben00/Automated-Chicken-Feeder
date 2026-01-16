"""
Input validation and sanitization utilities for the Chicken Feeder application.
"""
import re
import html
from typing import Tuple, Optional


def sanitize_string(value: str, max_length: int = 255) -> str:
    """
    Sanitize a string by escaping HTML characters and limiting length.
    
    Args:
        value: The input string to sanitize
        max_length: Maximum allowed length
    
    Returns:
        Sanitized string
    """
    if not value:
        return ''
    # Strip whitespace
    value = value.strip()
    # Escape HTML characters to prevent XSS
    value = html.escape(value)
    # Limit length
    return value[:max_length]


def validate_username(username: str) -> Tuple[bool, Optional[str]]:
    """
    Validate username format.
    
    Rules:
    - 3-50 characters
    - Alphanumeric and underscores only
    - Must start with a letter
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not username:
        return False, 'Username is required.'
    
    username = username.strip()
    
    if len(username) < 3:
        return False, 'Username must be at least 3 characters long.'
    
    if len(username) > 50:
        return False, 'Username must be less than 50 characters.'
    
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', username):
        return False, 'Username must start with a letter and contain only letters, numbers, and underscores.'
    
    return True, None


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Validate email format.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not email:
        return False, 'Email is required.'
    
    email = email.strip().lower()
    
    # Basic email regex pattern
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, 'Please enter a valid email address.'
    
    if len(email) > 120:
        return False, 'Email must be less than 120 characters.'
    
    return True, None


def validate_password(password: str, require_strong: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Validate password strength.
    
    Rules (when require_strong=True):
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not password:
        return False, 'Password is required.'
    
    if len(password) < 8:
        return False, 'Password must be at least 8 characters long.'
    
    if len(password) > 128:
        return False, 'Password must be less than 128 characters.'
    
    if require_strong:
        if not re.search(r'[A-Z]', password):
            return False, 'Password must contain at least one uppercase letter.'
        
        if not re.search(r'[a-z]', password):
            return False, 'Password must contain at least one lowercase letter.'
        
        if not re.search(r'\d', password):
            return False, 'Password must contain at least one number.'
    
    return True, None


def validate_device_id(device_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate device ID format.
    
    Rules:
    - 3-64 characters
    - Alphanumeric, underscores, and hyphens only
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not device_id:
        return False, 'Device ID is required.'
    
    device_id = device_id.strip()
    
    if len(device_id) < 3:
        return False, 'Device ID must be at least 3 characters long.'
    
    if len(device_id) > 64:
        return False, 'Device ID must be less than 64 characters.'
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', device_id):
        return False, 'Device ID can only contain letters, numbers, underscores, and hyphens.'
    
    return True, None


def validate_schedule_name(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate schedule name.
    
    Rules:
    - 1-100 characters
    - No HTML/script tags
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, 'Schedule name is required.'
    
    name = name.strip()
    
    if len(name) < 1:
        return False, 'Schedule name is required.'
    
    if len(name) > 100:
        return False, 'Schedule name must be less than 100 characters.'
    
    # Check for potential XSS patterns
    dangerous_patterns = [
        r'<script',
        r'javascript:',
        r'on\w+\s*=',
        r'<iframe',
        r'<object',
        r'<embed'
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return False, 'Schedule name contains invalid characters.'
    
    return True, None


def validate_amount_grams(amount: int, min_grams: int = 20, max_grams: int = 150) -> Tuple[bool, Optional[str]]:
    """
    Validate feed amount in grams.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        amount = int(amount)
    except (ValueError, TypeError):
        return False, 'Amount must be a valid number.'
    
    if amount < min_grams:
        return False, f'Amount must be at least {min_grams} grams.'
    
    if amount > max_grams:
        return False, f'Amount must not exceed {max_grams} grams.'
    
    return True, None


def validate_iot_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate IoT device URL format.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return True, None  # URL is optional
    
    url = url.strip()
    
    if len(url) > 255:
        return False, 'IoT device URL must be less than 255 characters.'
    
    # Allow IP addresses, hostnames, or full URLs
    valid_patterns = [
        r'^https?://[a-zA-Z0-9.-]+(?::\d+)?(?:/.*)?$',  # Full URL
        r'^[a-zA-Z0-9.-]+(?::\d+)?$',  # Hostname with optional port
        r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?$'  # IP address with optional port
    ]
    
    for pattern in valid_patterns:
        if re.match(pattern, url):
            return True, None
    
    return False, 'Please enter a valid device URL or IP address.'
