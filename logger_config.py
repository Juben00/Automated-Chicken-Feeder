import logging

logger = logging.getLogger("chickenfeeder")
logger.setLevel(logging.INFO)

# Optional: console log formatting
console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

logger.addHandler(console_handler)
