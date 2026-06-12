import sqlite3
import json
import os

from logging_config import get_logger

log = get_logger(__name__)

# Resolve the DB next to this file so the path is stable regardless of the
# process working directory.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state_tracker.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS internships (
            availability_id TEXT PRIMARY KEY,
            internship_id TEXT,
            tenant_id TEXT,
            facility_type TEXT,
            disciplines_to_set TEXT, -- JSON array of specializations
            status TEXT DEFAULT 'PENDING',
            logs TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            availability_name TEXT DEFAULT ''
        )
    ''')
    try:
        c.execute("ALTER TABLE internships ADD COLUMN availability_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass # Column already exists
    conn.commit()
    conn.close()

def insert_or_ignore(availability_id, internship_id, facility_type, disciplines, availability_name=''):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO internships (availability_id, internship_id, facility_type, disciplines_to_set, status, availability_name)
        VALUES (?, ?, ?, ?, 'PENDING', ?)
        ON CONFLICT(availability_id) DO UPDATE SET
            internship_id = excluded.internship_id,
            facility_type = excluded.facility_type,
            disciplines_to_set = excluded.disciplines_to_set,
            availability_name = excluded.availability_name,
            status = 'PENDING',
            logs = logs || '\nRe-queued for processing.',
            updated_at = CURRENT_TIMESTAMP
        WHERE internships.status = 'FAILED'
    ''', (str(availability_id), str(internship_id), str(facility_type), json.dumps(disciplines), str(availability_name)))
    conn.commit()
    conn.close()

def append_log(availability_id, message):
    """Append a progress line to a record's log without changing its status."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE internships SET logs = logs || ? || '\n', updated_at = CURRENT_TIMESTAMP WHERE availability_id = ?",
        (message, str(availability_id)),
    )
    conn.commit()
    conn.close()
    log.info("[%s] %s", availability_id, message)


def get_next_pending():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT availability_id, internship_id, disciplines_to_set, availability_name FROM internships WHERE status = 'PENDING' LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'availability_id': row[0],
            'internship_id': row[1],
            'disciplines_to_set': json.loads(row[2]),
            'availability_name': row[3] if len(row) > 3 else ''
        }
    return None

def get_all_pending():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT availability_id, internship_id, disciplines_to_set, availability_name FROM internships WHERE status = 'PENDING'")
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'availability_id': row[0],
            'internship_id': row[1],
            'disciplines_to_set': json.loads(row[2]),
            'availability_name': row[3] if len(row) > 3 else ''
        })
    return results

def update_status(availability_id, status, log_message=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if log_message:
        c.execute("UPDATE internships SET status = ?, logs = logs || ? || '\n', updated_at = CURRENT_TIMESTAMP WHERE availability_id = ?", 
                  (status, log_message, availability_id))
    else:
        c.execute("UPDATE internships SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE availability_id = ?", 
                  (status, availability_id))
    conn.commit()
    conn.close()
    log.info("[%s] status=%s %s", availability_id, status, log_message)

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM internships GROUP BY status")
    rows = c.fetchall()
    conn.close()
    stats = {'PENDING': 0, 'SUCCESS': 0, 'FAILED': 0, 'TOTAL': 0}
    for row in rows:
        stats[row[0]] = row[1]
        stats['TOTAL'] += row[1]
    return stats

def clear_all():
    """Delete every queued/processed record. Used by the dashboard 'Clear DB'
    button (guarded by a confirmation popup on the frontend)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM internships")
    deleted = c.rowcount
    conn.commit()
    conn.close()
    log.warning("Cleared database: %d record(s) deleted.", deleted)
    return deleted

def get_recent_logs(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT availability_id, status, logs, updated_at FROM internships WHERE logs != '' ORDER BY updated_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{'availability_id': r[0], 'status': r[1], 'logs': r[2], 'updated_at': r[3]} for r in rows]

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
