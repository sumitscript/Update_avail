import os
import sys
import subprocess
import asyncio
from worker import authenticate

def setup_env():
    print("Checking dependencies...")
    try:
        import playwright
        import flask
        import pandas
    except ImportError:
        print("Missing dependencies. Please run: pip install -r requirements.txt")
        sys.exit(1)

def run():
    setup_env()
    
    print("==================================================")
    print("   Exxat Curriculum Automation Engine    ")
    print("==================================================")
    print("1. Authenticate (Login to Exxat)")
    print("2. Start Local Dashboard & Engine")
    print("==================================================")
    
    choice = input("Select an option: ")
    
    if choice == '1':
        print("Starting Authentication Flow...")
        # Make sure Playwright browsers are installed
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
        asyncio.run(authenticate())
    elif choice == '2':
        print("Starting Flask Dashboard on http://localhost:5000 ...")
        from app import app
        import db
        import session_log
        db.init_db()
        os.makedirs('input', exist_ok=True)
        os.makedirs('archive', exist_ok=True)
        os.makedirs('logs', exist_ok=True)
        # Fresh session: clears in-memory live logs + truncates the detail log.
        session_log.init_session()
        app.run(debug=False, port=5000, use_reloader=False)
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    run()
