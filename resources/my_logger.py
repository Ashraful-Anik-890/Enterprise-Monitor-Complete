import logging
from concurrent_log_handler import ConcurrentRotatingFileHandler

from file_utils import get_log_file_path

log_file = get_log_file_path()

def mylogger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # File handler with rotation
    file_handler = ConcurrentRotatingFileHandler(
        filename=log_file,
        mode='a',  # append mode
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,  # Keep 10 backups
        encoding='utf-8',
        use_gzip=True,  # Compress rotated logs
        # Optional: specify lock file directory
        # lockPath='/var/lock'   # For Linux systems
    )
    file_handler.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Formatters
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')

    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger