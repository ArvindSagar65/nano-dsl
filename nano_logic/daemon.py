"""Background daemon for monitoring alert rules independently of the UI."""

import time
import os
import sys
from datetime import datetime

from nano_logic.engine import evaluate_active_rules, load_rules, RULES_FILE

def run_daemon():
    last_mtime = 0
    
    while True:
        try:
            # Reload rules if the JSON file has been modified by the dashboard
            if os.path.exists(RULES_FILE):
                mtime = os.path.getmtime(RULES_FILE)
                if mtime > last_mtime:
                    load_rules()
                    last_mtime = mtime

            alerts = evaluate_active_rules()
            for rule, current_val in alerts:
                msg = f"🚨 [ALERT] {rule.metric} reached {current_val:.1f} (Rule: {rule.operator} {rule.threshold})"
                
                # Write to rule-specific log file
                try:
                    os.makedirs("logs", exist_ok=True)
                    with open(f"logs/{rule.name}.log", "a") as f:
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
