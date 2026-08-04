# nano_logic/engine.py
import json
import os
import time
import psutil
from dataclasses import asdict
from nano_logic.logging_config import configure_logging
from nano_logic.models import Rule
from nano_logic.paths import get_rules_file

logger = configure_logging(__name__)

# Master list of all running rules
ACTIVE_RULES: list[Rule] = []
RULES_FILE = get_rules_file()

# ──────────────────────────────────────────────
#  Persistence
# ──────────────────────────────────────────────

def save_rules() -> None:
    """Save ACTIVE_RULES to a JSON file."""
    try:
        with open(RULES_FILE, "w") as f:
            json.dump([asdict(r) for r in ACTIVE_RULES], f, indent=4)
    except OSError:
        logger.exception("Failed to save rules to %s", RULES_FILE)


def load_rules() -> None:
    """Load ACTIVE_RULES from a JSON file."""
    global ACTIVE_RULES
    if not RULES_FILE.exists():
        return
    try:
        with open(RULES_FILE) as f:
            data = json.load(f)
            ACTIVE_RULES.clear()
            ACTIVE_RULES.extend([Rule(**r) for r in data])
    except (OSError, json.JSONDecodeError, TypeError):
        logger.exception("Failed to load rules from %s", RULES_FILE)

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

# Once a rule fires, suppress repeat firings for this long. Without this,
# a persistently-breached rule (e.g. a full disk) re-fires every
# evaluation tick forever, flooding its log file and ringing the bell
# once per second indefinitely.
DEFAULT_ALERT_COOLDOWN_SECONDS = 60.0

# Per-rule-id timestamp of the last time it fired. Cleared for a rule
# once its condition stops being breached, so it re-arms immediately
# rather than staying suppressed until an old cooldown window lapses.
_last_triggered_at: dict[int, float] = {}


def evaluate_active_rules(cooldown_seconds: float = DEFAULT_ALERT_COOLDOWN_SECONDS) -> list[tuple[Rule, float]]:
    """
    Evaluate all rules in ACTIVE_RULES against current metric values.
    Returns a list of (Rule, current_value) tuples for every breached rule
    that hasn't already fired within the cooldown window.
    """
    now = time.time()
    triggered = []
    # Fetch each distinct metric at most once per tick. Some metrics (e.g.
    # cpu.util, via psutil.cpu_percent(interval=None)) measure "since the
    # last time this was called" — calling fetch_metric_value() separately
    # per rule meant the second/third rule watching the same metric in one
    # tick measured a near-zero elapsed slice and got quantized garbage
    # (0%, 50%, 100%) instead of a real reading.
    metric_values: dict[str, float | None] = {}
    for rule in ACTIVE_RULES:
        if rule.metric not in metric_values:
            metric_values[rule.metric] = fetch_metric_value(rule.metric)
        current_val = metric_values[rule.metric]
        if current_val is None:
            continue

        op_fn = _OPERATORS.get(rule.operator)
        if op_fn is None:
            continue  # unknown operator, skip

        if not op_fn(current_val, rule.threshold):
            _last_triggered_at.pop(rule.id, None)
            continue

        last_fired = _last_triggered_at.get(rule.id, 0.0)
        if now - last_fired < cooldown_seconds:
            continue

        _last_triggered_at[rule.id] = now
        triggered.append((rule, current_val))

    return triggered


# ──────────────────────────────────────────────
#  Rule management
# ──────────────────────────────────────────────

def add_rule(rule: Rule) -> Rule:
    """Assign a unique id (and a default name, if none was given), register the
    rule, and persist it. Centralizes rule creation so id assignment isn't
    duplicated by every caller — previously the dashboard tracked its own
    `rule_counter` independent of engine state, with no shared invariant
    that ids stay unique.
    """
    rule.id = max((r.id for r in ACTIVE_RULES), default=0) + 1
    if not rule.name:
        rule.name = f"rule_{rule.id}"
    ACTIVE_RULES.append(rule)
    save_rules()
    return rule


def remove_rule(identifier: str) -> bool:
    """Remove a rule by its ID (as string) or name. Returns True if removed.

    An id match takes priority over a name match, so a rule whose name
    happens to be an all-digit string (e.g. "3") can't shadow removal of
    the rule whose actual id is 3.
    """
    global ACTIVE_RULES
    for i, rule in enumerate(ACTIVE_RULES):
        if str(rule.id) == identifier:
            ACTIVE_RULES.pop(i)
            _last_triggered_at.pop(rule.id, None)
            save_rules()
            return True
    for i, rule in enumerate(ACTIVE_RULES):
        if rule.name == identifier:
            ACTIVE_RULES.pop(i)
            _last_triggered_at.pop(rule.id, None)
            save_rules()
            return True
    return False


def get_metric_names() -> list[str]:
    """Return all registered metric names — useful for autocomplete / guide."""
    return sorted(_METRIC_REGISTRY.keys())
