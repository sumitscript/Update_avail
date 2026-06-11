import logging
import os
from logging.handlers import RotatingFileHandler

# Resolve the logs directory relative to this file so it works regardless of
# the process working directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')

_configured = False


def setup_logging(level=logging.INFO):
    """Configure root logging once: a rotating file in logs/ plus the console.

    Safe to call multiple times; only the first call installs handlers.
    """
    global _configured
    if _configured:
        return logging.getLogger()

    os.makedirs(LOG_DIR, exist_ok=True)

    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Rotating file handler: 5 files of 2 MB each.
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'automation.log'),
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Quiet down noisy third-party loggers (werkzeug request lines stay at WARNING).
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    _configured = True
    return root


def get_logger(name):
    """Return a module logger, ensuring logging has been configured."""
    setup_logging()
    return logging.getLogger(name)
