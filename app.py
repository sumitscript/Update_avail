from flask import Flask, render_template, jsonify, request
import threading
import db
import worker
import ingest
import session_log
import os

from logging_config import get_logger

log = get_logger(__name__)

app = Flask(__name__)

worker_thread = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stats')
def api_stats():
    # `after` lets the client fetch only new live-log lines since its last poll.
    try:
        after_id = int(request.args.get('after', 0))
    except (TypeError, ValueError):
        after_id = 0
    stats = db.get_stats()
    live = session_log.get_live(after_id=after_id)
    return jsonify({
        'stats': stats,
        'logs': live,
        'worker_running': worker.is_running,
        'worker_paused': worker.is_paused
    })

@app.route('/api/logs/clear', methods=['POST'])
def api_logs_clear():
    session_log.clear_live()
    return jsonify({'status': 'success'})

@app.route('/api/db/clear', methods=['POST'])
def api_db_clear():
    if worker.is_running:
        return jsonify({'status': 'error',
                        'message': 'Stop the engine before clearing the database.'}), 409
    deleted = db.clear_all()
    session_log.detail(f"Database cleared from dashboard: {deleted} record(s) removed.",
                       level="WARN")
    return jsonify({'status': 'success', 'message': f'Cleared {deleted} record(s).'})

@app.route('/api/ingest', methods=['POST'])
def api_ingest():
    try:
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                os.makedirs(ingest.INPUT_DIR, exist_ok=True)
                filepath = os.path.join(ingest.INPUT_DIR, file.filename)
                file.save(filepath)
                ingest.process_file(filepath)
                return jsonify({'status': 'success', 'message': f'Ingested {file.filename}'})

        # Fallback to ingesting everything in the folder
        ingest.process_input_files()
        return jsonify({'status': 'success', 'message': 'Ingested all files in input directory'})
    except Exception as e:
        log.exception("Ingest failed")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/worker/start', methods=['POST'])
def api_worker_start():
    global worker_thread
    if not worker.is_running:
        worker_thread = threading.Thread(target=worker.start_worker)
        worker_thread.start()
        return jsonify({'status': 'success'})
    return jsonify({'status': 'already_running'})

@app.route('/api/worker/pause', methods=['POST'])
def api_worker_pause():
    worker.pause_worker()
    return jsonify({'status': 'success'})

@app.route('/api/worker/resume', methods=['POST'])
def api_worker_resume():
    worker.resume_worker()
    return jsonify({'status': 'success'})

@app.route('/api/worker/stop', methods=['POST'])
def api_worker_stop():
    worker.stop_worker()
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    # Initialize DB on startup
    db.init_db()
    # Create required dirs
    os.makedirs('input', exist_ok=True)
    os.makedirs('archive', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    # Start a fresh logging session: in-memory live logs are wiped and the
    # detail log file is truncated, so restarting the server clears live logs.
    session_log.init_session()

    app.run(debug=True, port=5000, use_reloader=False)
