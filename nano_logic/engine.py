# nano_logic/engine.py
import json
import os
import psutil
from dataclasses import asdict
from nano_logic.models import Rule

# This is the master list holding all rules currently running in the background
ACTIVE_RULES: list[Rule] = []
RULES_FILE = "rules.json"

def save_rules() -> None:
    """Save ACTIVE_RULES to a JSON file."""
    try:
        with open(RULES_FILE, "w") as f:
            json.dump([asdict(r) for r in ACTIVE_RULES], f, indent=4)
    except Exception as e:
        pass  # Running in background thread or dashboard, print might corrupt TUI

def load_rules() -> None:
    """Load ACTIVE_RULES from a JSON file."""
    global ACTIVE_RULES
    if not os.path.exists(RULES_FILE):
        return
    try:
        with open(RULES_FILE, "r") as f:
            data = json.load(f)
            ACTIVE_RULES.clear()
            ACTIVE_RULES.extend([Rule(**r) for r in data])
    except Exception as e:
        pass

def fetch_metric_value(metric_name: str) -> float | None:
    """
    Takes a metric name (e.g., 'cpu.util') and returns the current system value.
    Returns None if the metric doesn't exist or fails to read.
    """
    try:
        if metric_name == "cpu.util":
            return psutil.cpu_percent(interval=None) 
        elif metric_name == "mem.util":
            return psutil.virtual_memory().percent
        elif metric_name == "disk.free":
            # Returns free space of root directory in Gigabytes
            return psutil.disk_usage("/").free / (1024 ** 3) 
        # Add more metric probes here as needed!
    except Exception:
        return None
        
    return None

def evaluate_active_rules() -> list[tuple[Rule, float]]:
    """
    Evaluates all rules in ACTIVE_RULES.
    Returns a list of tuples containing the breached Rule and the value that triggered it.
    """
    triggered_alerts = []
    
    for rule in ACTIVE_RULES:
        current_val = fetch_metric_value(rule.metric)
        if current_val is None:
            continue
            
        is_breached = False
        if rule.operator == ">" and current_val > rule.threshold:
            is_breached = True
        elif rule.operator == "<" and current_val < rule.threshold:
            is_breached = True
        elif rule.operator == "==" and current_val == rule.threshold:
            is_breached = True
            
        if is_breached:
            triggered_alerts.append((rule, current_val))
            
    return triggered_alerts

def remove_rule(identifier: str) -> bool:
    """Removes a rule by its ID (as a string) or name. Returns True if removed."""
    global ACTIVE_RULES
    for i, rule in enumerate(ACTIVE_RULES):
        if str(rule.id) == identifier or rule.name == identifier:
            ACTIVE_RULES.pop(i)
            save_rules()
            return True
    return False
