import logging

logger = logging.getLogger('chickenfeeder')
logger.setLevel(logging.INFO)
import logging

# Setup simple logging (disable verbose werkzeug and apscheduler logs)
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Create a simple logger for app-specific messages
logger = logging.getLogger('chickenfeeder')
logger.setLevel(logging.INFO)
