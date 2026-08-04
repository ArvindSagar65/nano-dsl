"""Comprehensive test suite for Nano-DSL grammar and engine."""
import pytest
from lark.exceptions import LarkError, UnexpectedInput
from nano_logic.dsl import execute_command, parse_command, DSL_GRAMMAR, parser
from nano_logic.models import Rule, StopRule
from nano_logic.engine import (
    ACTIVE_RULES, save_rules, load_rules, remove_rule,
    evaluate_active_rules, fetch_metric_value, _OPERATORS, _METRIC_REGISTRY,
)
from nano_logic.monitoring import probes


# ═══════════════════════════════════════════════
#  1. GRAMMAR — parse tree smoke tests
# ═══════════════════════════════════════════════

class TestGrammarParsing:
    """Verify every command in the grammar can be parsed without error."""

    # ── CPU ──
    @pytest.mark.parametrize("cmd", [
        "cpu.util", "cpu.load", "cpu.cores", "cpu.top", "cpu.avg",
    ])
    def test_cpu_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None
        assert t.data in ("cpu_util", "cpu_load", "cpu_cores", "cpu_top", "cpu_avg")

    # ── Memory ──
    @pytest.mark.parametrize("cmd", [
        "mem.util", "mem.stats", "mem.swap", "mem.top", "mem.cached",
    ])
    def test_mem_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── Disk ──
    @pytest.mark.parametrize("cmd", [
        "disk.free", "disk.usage", "disk.io", "disk.top", "disk.inode",
    ])
    def test_disk_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── GPU ──
    def test_gpu_command_parses(self):
        t = parse_command("gpu.util")
        assert t is not None

    # ── Process ──
    @pytest.mark.parametrize("cmd", [
        "proc.list", "proc.kill 1", "proc.search bash",
        "proc.tree", "proc.info 1",
    ])
    def test_proc_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── Network ──
    @pytest.mark.parametrize("cmd", [
        "net.interfaces", "net.bandwidth", "net.connections",
        "net.ports", "net.dns google.com",
    ])
    def test_net_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── System ──
    @pytest.mark.parametrize("cmd", [
        "system.uptime", "system.info", "system.processes",
        "system.users", "system.load",
    ])
    def test_sys_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── Sensors ──
    @pytest.mark.parametrize("cmd", [
        "sensor.temp", "sensor.fans", "sensor.battery",
    ])
    def test_sensor_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── Docker ──
    @pytest.mark.parametrize("cmd", ["docker.ps", "docker.stats"])
    def test_docker_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── Service ──
    @pytest.mark.parametrize("cmd", [
        "service.list", "service.status sshd",
        "service.status sshd.service",
    ])
    def test_service_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── Utility ──
    @pytest.mark.parametrize("cmd", [
        "clear", "help", "rules", "status", "history", "guide",
    ])
    def test_utility_commands_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None

    # ── Alert rules ──
    @pytest.mark.parametrize("cmd", [
        "alert cpu.util > 80 -> log",
        "my_rule: alert mem.util < 20 -> log",
        "alert disk.free >= 10 -> log",
        "alert sensor.temp <= 85 -> log",
        "alert cpu.util == 100 -> log",
    ])
    def test_alert_rules_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None
        assert t.data in ("anon_rule", "named_rule")

    # ── Stop rules ──
    @pytest.mark.parametrize("cmd", [
        "stop 1", "stop rule 1",
        "stop my_rule", "stop rule my_rule",
    ])
    def test_stop_rules_parse(self, cmd):
        t = parse_command(cmd)
        assert t is not None
        assert t.data == "stop_rule"


# ═══════════════════════════════════════════════
#  2. EXECUTION — verify commands return data
# ═══════════════════════════════════════════════

class TestCommandExecution:
    """Execute every command and verify it returns a result."""

    @pytest.mark.parametrize("cmd", [
        "cpu.util", "cpu.load", "cpu.cores", "cpu.top", "cpu.avg",
        "mem.util", "mem.stats", "mem.swap", "mem.top", "mem.cached",
        "disk.free", "disk.usage", "disk.io", "disk.inode",
        "system.uptime", "system.info", "system.processes",
        "system.users", "system.load",
        "net.interfaces", "net.bandwidth", "net.connections", "net.ports",
        "sensor.temp", "sensor.fans", "sensor.battery",
        "help", "rules", "status", "guide", "clear",
    ])
    def test_metric_commands_return_string(self, cmd):
        result = execute_command(cmd)
        assert isinstance(result, str), f"{cmd} should return str, got {type(result)}"

    def test_clear_returns_sentinel(self):
        assert execute_command("clear") == "__CLEAR__"

    def test_proc_search_returns_string(self):
        result = execute_command("proc.search python")
        assert isinstance(result, str)

    def test_proc_info_returns_string(self):
        result = execute_command("proc.info 1")
        assert isinstance(result, str)
        # PID 1 should exist on any Unix system
        assert "Process Info" in result or "not found" in result

    def test_net_dns_returns_string(self):
        result = execute_command("net.dns google.com")
        assert isinstance(result, str)
        assert "google.com" in result.lower() or "Error" in result

    def test_docker_commands_graceful(self):
        """Docker may not be installed — should not crash."""
        for cmd in ["docker.ps", "docker.stats"]:
            result = execute_command(cmd)
            assert isinstance(result, str)

    def test_service_commands_graceful(self):
        """systemctl may not be available — should not crash."""
        result = execute_command("service.list")
        assert isinstance(result, str)

    def test_alert_named_rule_returns_rule(self):
        result = execute_command("test_rule: alert cpu.util > 80 -> log")
        assert isinstance(result, Rule)
        assert result.name == "test_rule"
        assert result.metric == "cpu.util"
        assert result.operator == ">"
        assert result.threshold == 80.0
        assert result.action == "log"

    def test_alert_anon_rule_returns_rule(self):
        result = execute_command("alert mem.util < 20 -> log")
        assert isinstance(result, Rule)
        assert result.name is None
        assert result.metric == "mem.util"

    @pytest.mark.parametrize("op", [">", "<", "==", ">=", "<="])
    def test_alert_all_operators(self, op):
        cmd = f"alert cpu.util {op} 50 -> log"
        result = execute_command(cmd)
        assert isinstance(result, Rule)
        assert result.operator == op


# ═══════════════════════════════════════════════
#  3. EDGE CASES & ERROR HANDLING
# ═══════════════════════════════════════════════

class TestEdgeCases:
    """Verify graceful handling of invalid input."""

    @pytest.mark.parametrize("cmd", [
        "",                     # empty
        "   ",                  # whitespace only
        "invalid gibberish",    # nonsense
        "cpu.invalid",          # valid prefix, invalid metric
        "mem.nonexistent",      # valid prefix, invalid metric
        ":::",                  # random symbols
        "alert > 80 -> log",    # missing metric
        "stop",                 # missing identifier
    ])
    def test_invalid_commands_raise_lark_error(self, cmd):
        with pytest.raises((LarkError, UnexpectedInput)):
            execute_command(cmd)

    def test_case_sensitivity(self):
        """Command names are case-sensitive."""
        with pytest.raises(LarkError):
            execute_command("CPU.UTIL")
        with pytest.raises(LarkError):
            execute_command("Cpu.Util")

    def test_alert_rule_case_insensitive_keyword(self):
        """The 'alert' keyword itself is case-insensitive (due to 'i' flag)."""
        result = execute_command("ALERT cpu.util > 80 -> log")
        assert isinstance(result, Rule)
        result = execute_command("Alert cpu.util > 80 -> log")
        assert isinstance(result, Rule)

    def test_proc_kill_nonexistent_pid(self):
        """Killing a non-existent PID should return an error message, not crash."""
        result = execute_command("proc.kill 999999999")
        assert isinstance(result, str)
        # Should say it doesn't exist or error
        assert any(word in result.lower() for word in ["not exist", "error", "no such"])


# ═══════════════════════════════════════════════
#  4. ENGINE — rule life cycle
# ═══════════════════════════════════════════════

class TestEngine:
    """Test rule operations through the engine."""

    def setup_method(self):
        # Clean state before each test
        ACTIVE_RULES.clear()

    def test_add_and_list_rules(self):
        r = execute_command("test_alert: alert cpu.util > 80 -> log")
        assert isinstance(r, Rule)
        ACTIVE_RULES.append(r)
        assert len(ACTIVE_RULES) == 1
        assert ACTIVE_RULES[0].name == "test_alert"

    def test_remove_rule_by_name(self):
        r = execute_command("myrule: alert mem.util < 10 -> log")
        ACTIVE_RULES.append(r)
        assert remove_rule("myrule") is True
        assert len(ACTIVE_RULES) == 0

    def test_remove_rule_by_id(self):
        r = execute_command("alert disk.free > 5 -> log")
        r.id = 42
        ACTIVE_RULES.append(r)
        assert remove_rule("42") is True
        assert len(ACTIVE_RULES) == 0

    def test_remove_nonexistent_rule(self):
        assert remove_rule("nonexistent") is False

    def test_evaluate_no_crash(self):
        """evaluate_active_rules should never crash even with no rules."""
        alerts = evaluate_active_rules()
        assert isinstance(alerts, list)

    def test_alert_cooldown_suppresses_repeat_firing(self):
        """A persistently-breached rule should only fire once per cooldown window."""
        from nano_logic.engine import _last_triggered_at

        rule = Rule(metric="proc.count", operator=">", threshold=-1, action="log", id=1)
        ACTIVE_RULES.append(rule)
        try:
            first = evaluate_active_rules(cooldown_seconds=60.0)
            assert any(r.id == 1 for r, _ in first)

            second = evaluate_active_rules(cooldown_seconds=60.0)
            assert not any(r.id == 1 for r, _ in second), "rule refired inside its cooldown window"

            # A near-zero cooldown should let it fire again immediately.
            third = evaluate_active_rules(cooldown_seconds=0.0)
            assert any(r.id == 1 for r, _ in third)
        finally:
            _last_triggered_at.pop(1, None)

    def test_alert_cooldown_resets_when_condition_clears(self):
        """A rule that stops breaching should re-arm instead of staying suppressed."""
        from nano_logic.engine import _last_triggered_at

        rule = Rule(metric="proc.count", operator=">", threshold=-1, action="log", id=2)
        ACTIVE_RULES.append(rule)
        try:
            evaluate_active_rules(cooldown_seconds=60.0)
            assert 2 in _last_triggered_at

            rule.threshold = 10 ** 9  # condition no longer breached
            evaluate_active_rules(cooldown_seconds=60.0)
            assert 2 not in _last_triggered_at
        finally:
            _last_triggered_at.pop(2, None)

    @pytest.mark.parametrize("operator", [">", "<", "==", ">=", "<="])
    def test_all_operators_in_engine(self, operator):
        """Verify that all operators exist in the engine's operator map."""
        assert operator in _OPERATORS

    def test_fetch_metric_value_returns_number(self):
        """Registered metrics should return float values."""
        for name in _METRIC_REGISTRY:
            val = fetch_metric_value(name)
            assert val is None or isinstance(val, (int, float)), f"{name} returned {type(val)}"

    def test_fetch_unknown_metric(self):
        assert fetch_metric_value("nonexistent.metric") is None

    def test_rules_persistence(self):
        """Save and load cycle should preserve rule data."""
        r = execute_command("persist_test: alert cpu.util > 90 -> log")
        r.id = 1
        ACTIVE_RULES.append(r)
        save_rules()
        ACTIVE_RULES.clear()
        load_rules()
        assert len(ACTIVE_RULES) >= 1
        # Clean up
        from nano_logic.engine import RULES_FILE
        if RULES_FILE.exists():
            RULES_FILE.unlink()


# ═══════════════════════════════════════════════
#  5. GRAMMAR INTEGRITY — no regressions
# ═══════════════════════════════════════════════

class TestGrammarIntegrity:
    """Ensure original commands still work after adding new ones."""

    # All original commands from the first version
    @pytest.mark.parametrize("cmd", [
        "cpu.util", "cpu.load", "cpu.cores", "cpu.top",
        "mem.util", "mem.stats", "mem.swap", "mem.top",
        "disk.free", "disk.usage", "disk.io", "disk.top",
        "gpu.util",
        "proc.list", "proc.kill 1",
        "net.interfaces", "net.bandwidth", "net.connections",
        "system.uptime", "system.info", "system.processes",
    ])
    def test_original_commands_still_work(self, cmd):
        result = execute_command(cmd)
        assert result is not None, f"{cmd} returned None"
        if isinstance(result, str):
            assert not result.startswith("Parse error"), f"{cmd} failed: {result}"

    def test_named_rule_syntax_preserved(self):
        """Original named_rule syntax '<name>: alert ...' still works."""
        r = execute_command("original_test: alert disk.free < 10 -> log")
        assert isinstance(r, Rule)
        assert r.name == "original_test"
        assert r.action == "log"

    def test_stop_rule_syntax_preserved(self):
        """Original stop syntax still works."""
        s = execute_command("stop 1")
        assert isinstance(s, StopRule)
        assert s.identifier == "1"

    def test_anon_rule_syntax_preserved(self):
        """Original anonymous rule syntax still works."""
        r = execute_command("alert cpu.util > 80 -> log")
        assert isinstance(r, Rule)
        assert r.name is None


# ═══════════════════════════════════════════════
#  6. PROBES — utility functions
# ═══════════════════════════════════════════════

class TestProbes:
    """Test the probe helper functions."""

    def test_disk_free_bytes(self):
        free, total = probes.get_disk_free_bytes()
        assert free > 0
        assert total > free

    def test_disk_usage_percent(self):
        pct = probes.get_disk_usage_percent()
        assert 0.0 <= pct <= 100.0

    def test_net_totals_mib(self):
        sent, recv = probes.get_net_totals_mib()
        assert sent >= 0
        assert recv >= 0

    def test_process_count(self):
        cnt = probes.get_process_count()
        assert cnt > 0  # At least the current process

    def test_listening_ports(self):
        ports = probes.get_listening_ports()
        assert isinstance(ports, list)

    def test_temperatures(self):
        temps = probes.get_temperatures()
        assert isinstance(temps, dict)

    def test_battery(self):
        batt = probes.get_battery()
        # May be None on desktops — just check it doesn't crash
        assert batt is None or isinstance(batt, dict)

    def test_system_load_summary(self):
        info = probes.get_system_load_summary()
        assert "cpu_percent" in info
        assert "mem_percent" in info
        assert 0 <= info["cpu_percent"] <= 100

    def test_logged_in_users(self):
        users = probes.get_logged_in_users()
        assert isinstance(users, list)
