"""Background daemon for monitoring alert rules independently of the UI."""

import time
import os
import sys
from datetime import datetime

from nano_logic.daemon_lock import acquire_daemon_lock
from nano_logic.engine import evaluate_active_rules, load_rules, RULES_FILE
from nano_logic.paths import get_logs_dir

def run_daemon():
    with acquire_daemon_lock() as acquired:
        if not acquired:
            # Another daemon instance already holds the lock — nothing to do.
            return
        _monitor_loop()


def _monitor_loop():
    last_mtime = 0

    while True:
        try:
            # Reload rules if the JSON file has been modified by the dashboard
            if RULES_FILE.exists():
                mtime = RULES_FILE.stat().st_mtime
                if mtime > last_mtime:
                    load_rules()
                    last_mtime = mtime

            alerts = evaluate_active_rules()
            for rule, current_val in alerts:
                msg = f"🚨 [ALERT] {rule.metric} reached {current_val:.1f} (Rule: {rule.operator} {rule.threshold})"
                
                # Write to rule-specific log file
                try:
                    with open(get_logs_dir() / f"{rule.name}.log", "a") as f:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        f.write(f"[{timestamp}] {msg}\n")
                except Exception:
                    pass
                
                # Ring terminal bell (Audio Feedback)
                try:
                    sys.stdout.write('\a')
                    sys.stdout.flush()
                except Exception:
                    pass
                    
        except Exception:
            # Keep daemon alive even if temporary errors occur
            pass
            
        time.sleep(1)

if __name__ == "__main__":
    run_daemon()
