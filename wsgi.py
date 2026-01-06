# wsgi.py for Render/WSGI deployment
import sys
import os

# Add project directory to sys.path if needed
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Import Flask app as 'application' for WSGI
from app import app as application
