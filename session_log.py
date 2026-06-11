"""Session-scoped detailed logging + success/fail Excel tracking.

Live logs are kept in memory only, so they are wiped whenever the server
process restarts (a fresh "session"). The detail log file is truncated at the
start of every session as well, while the success/fail Excel workbooks are an
append-only audit trail that persists across sessions.
"""

import os
import threading
from collections import deque
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')

DETAIL_LOG_FILE = os.path.join(LOG_DIR, 'detail_log.log')
SUCCESS_XLSX = os.path.join(LOG_DIR, 'success.xlsx')
FAILED_XLSX = os.path.join(LOG_DIR, 'failed.xlsx')

_lock = threading.Lock()

# In-memory ring buffer of the current session's live log lines. Because it is
# only held in memory, restarting the server starts it empty.
LIVE_LOGS = deque(maxlen=5000)

# Monotonic id so the frontend can fetch only new lines on each poll.
_seq = 0


def init_session():
    """Start a fresh session: clear live logs and truncate the detail file."""
    global _seq
    os.makedirs(LOG_DIR, exist_ok=True)
    with _lock:
        LIVE_LOGS.clear()
        _seq = 0
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(DETAIL_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"================ SESSION STARTED {stamp} ================\n")
    except Exception:
        pass


def clear_live():
    """Drop all live logs (used by the frontend 'clear logs' / restart flows)."""
    global _seq
    with _lock:
        LIVE_LOGS.clear()
        _seq = 0


def detail(message, level="INFO", avail_id=None):
    """Record one detailed line to both the live buffer and the detail file."""
    global _seq
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = f"[{avail_id}] " if avail_id else ""
    file_line = f"{ts} [{level}] {prefix}{message}"
    with _lock:
        _seq += 1
        LIVE_LOGS.append({
            'id': _seq,
            'ts': ts,
            'level': level,
            'avail_id': avail_id,
            'message': message,
        })
        try:
            with open(DETAIL_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(file_line + "\n")
        except Exception:
            pass


def get_live(after_id=0, limit=500):
    """Return live log entries with id > after_id (most recent `limit`)."""
    with _lock:
        items = [e for e in LIVE_LOGS if e['id'] > after_id]
    return items[-limit:]


def record_result(avail_id, internship_id, status, message, spec_count=0):
    """Append a processed record to the success or failed Excel workbook."""
    path = SUCCESS_XLSX if str(status).upper() == 'SUCCESS' else FAILED_XLSX
    row = {
        'availability_id': str(avail_id),
        'internship_id': str(internship_id),
        'status': status,
        'specializations': spec_count,
        'message': message,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    with _lock:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            if os.path.exists(path):
                df = pd.read_excel(path)
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            else:
                df = pd.DataFrame([row])
            df.to_excel(path, index=False)
        except Exception as e:
            detail(f"Could not write {os.path.basename(path)}: {e}", level="ERROR",
                   avail_id=avail_id)
