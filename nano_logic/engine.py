# nano_logic/engine.py
import json
import os
import time
import psutil
from dataclasses import asdict
from nano_logic.models import Rule

# Master list of all running rules
ACTIVE_RULES: list[Rule] = []
RULES_FILE = "rules.json"

# ──────────────────────────────────────────────
#  Persistence
# ──────────────────────────────────────────────

def save_rules() -> None:
    """Save ACTIVE_RULES to a JSON file."""
    try:
        with open(RULES_FILE, "w") as f:
            json.dump([asdict(r) for r in ACTIVE_RULES], f, indent=4)
    except Exception:
        pass  # Running in background — don't corrupt TUI


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
    except Exception:
        pass

# ──────────────────────────────────────────────
#  Metric fetching — single source of truth
#  for both dashboard queries AND alert rules
# ──────────────────────────────────────────────

_METRIC_REGISTRY: dict[str, callable] = {}


def _register_metric(name: str, fn: callable) -> None:
    """Register a metric so it's available for both queries and alerts."""
    _METRIC_REGISTRY[name] = fn


def fetch_metric_value(metric_name: str) -> float | None:
    """
    Return the current numeric value of a metric, or None if unavailable.
    This powers alert rule evaluation.
    """
    if metric_name in _METRIC_REGISTRY:
        try:
            return _METRIC_REGISTRY[metric_name]()
        except Exception:
            return None
    return None


# ── Register built-in metrics ──────────────────

_register_metric("cpu.util", lambda: psutil.cpu_percent(interval=None))

_register_metric("mem.util", lambda: psutil.virtual_memory().percent)

_register_metric("disk.free", lambda: psutil.disk_usage("/").free / (1024 ** 3))

_register_metric("disk.usage", lambda: psutil.disk_usage("/").percent)

_register_metric("mem.used", lambda: psutil.virtual_memory().used / (1024 ** 3))

_register_metric("mem.avail", lambda: psutil.virtual_memory().available / (1024 ** 3))

_register_metric("swap.util", lambda: psutil.swap_memory().percent)

_register_metric("cpu.load1", lambda: os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0)

_register_metric("cpu.load5", lambda: os.getloadavg()[1] if hasattr(os, "getloadavg") else 0.0)

_register_metric("cpu.load15", lambda: os.getloadavg()[2] if hasattr(os, "getloadavg") else 0.0)


# ── Sensor metrics (temperature sensing) ──────

def _sensor_temp_max() -> float | None:
    """Return the highest core temperature, or None if unavailable."""
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        # Pick the highest reading across all sensors
        highest = -273.0
        for entries in temps.values():
            for s in entries:
                if s.current > highest:
                    highest = s.current
        return highest if highest > -273.0 else None
    except (AttributeError, Exception):
        return None


_register_metric("sensor.temp", _sensor_temp_max)


def _battery_percent() -> float | None:
    """Return battery percentage, or None if no battery."""
    try:
        batt = psutil.sensors_battery()
        return batt.percent if batt else None
    except (AttributeError, Exception):
        return None


_register_metric("sensor.battery", _battery_percent)


# ── Process count ─────────────────────────────

_register_metric("proc.count", lambda: float(len(psutil.pids())))


def _net_connections_count() -> float | None:
    """Return total number of network connections."""
    try:
        return float(len(psutil.net_connections()))
    except (AttributeError, Exception):
        return None


_register_metric("net.connections", _net_connections_count)


# ──────────────────────────────────────────────
#  Rule evaluation
# ──────────────────────────────────────────────

_OPERATORS = {
    ">":  lambda v, t: v > t,
    "<":  lambda v, t: v < t,
    "==": lambda v, t: v == t,
    ">=": lambda v, t: v >= t,   # ← FIXED: was missing
    "<=": lambda v, t: v <= t,   # ← FIXED: was missing
}


def evaluate_active_rules() -> list[tuple[Rule, float]]:
    """
    Evaluate all rules in ACTIVE_RULES against current metric values.
    Returns a list of (Rule, current_value) tuples for every breached rule.
    """
    triggered = []
    for rule in ACTIVE_RULES:
        current_val = fetch_metric_value(rule.metric)
        if current_val is None:
            continue

        op_fn = _OPERATORS.get(rule.operator)
        if op_fn is None:
            continue  # unknown operator, skip

        if op_fn(current_val, rule.threshold):
            triggered.append((rule, current_val))

    return triggered


# ──────────────────────────────────────────────
#  Rule management
# ──────────────────────────────────────────────

def remove_rule(identifier: str) -> bool:
    """Remove a rule by its ID (as string) or name. Returns True if removed."""
    global ACTIVE_RULES
    for i, rule in enumerate(ACTIVE_RULES):
        if str(rule.id) == identifier or rule.name == identifier:
            ACTIVE_RULES.pop(i)
            save_rules()
            return True
    return False


def get_metric_names() -> list[str]:
    """Return all registered metric names — useful for autocomplete / guide."""
    return sorted(_METRIC_REGISTRY.keys())
