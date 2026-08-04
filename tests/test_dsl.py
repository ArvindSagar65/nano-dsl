"""Comprehensive test suite for Nano-DSL grammar and engine."""
import pytest
from lark.exceptions import LarkError, UnexpectedInput
from nano_logic.dsl import execute_command, parse_command
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

    def test_net_dns_returns_string(self, monkeypatch):
        """Mocked so this test doesn't depend on outbound DNS actually working —
        this project explicitly targets offline/firewalled homelab environments."""
        monkeypatch.setattr(
            "socket.gethostbyname_ex",
            lambda host: (host, [], ["93.184.216.34"]),
        )
        result = execute_command("net.dns google.com")
        assert isinstance(result, str)
        assert "google.com" in result.lower()

    def test_net_dns_handles_lookup_failure(self, monkeypatch):
        import socket as socket_module

        def raise_gaierror(host):
            raise socket_module.gaierror("Name or service not known")

        monkeypatch.setattr("socket.gethostbyname_ex", raise_gaierror)
        result = execute_command("net.dns nonexistent.invalid")
        assert isinstance(result, str)
        assert "nonexistent.invalid" in result

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

    def test_add_rule_assigns_unique_incrementing_ids(self):
        from nano_logic.engine import add_rule

        r1 = add_rule(execute_command("alert cpu.util > 80 -> log"))
        r2 = add_rule(execute_command("alert mem.util > 80 -> log"))
        assert r1.id != r2.id
        assert r2.id == r1.id + 1

    def test_add_rule_survives_gaps_from_removed_rules(self):
        """New ids should never collide with an existing rule's id, even after removals."""
        from nano_logic.engine import add_rule

        r1 = add_rule(execute_command("alert cpu.util > 80 -> log"))
        r2 = add_rule(execute_command("alert mem.util > 80 -> log"))
        remove_rule(str(r1.id))
        r3 = add_rule(execute_command("alert disk.free < 5 -> log"))
        assert r3.id not in {r1.id, r2.id}

    def test_remove_rule_id_match_takes_priority_over_name_match(self):
        """A rule named the same as another rule's id shouldn't shadow the id-based removal."""
        by_id = Rule(metric="cpu.util", operator=">", threshold=1, action="log", id=7, name="seven")
        by_name = Rule(metric="mem.util", operator=">", threshold=1, action="log", id=99, name="7")
        ACTIVE_RULES.extend([by_id, by_name])

        assert remove_rule("7") is True
        assert by_id not in ACTIVE_RULES
        assert by_name in ACTIVE_RULES

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

    def test_evaluate_active_rules_fetches_shared_metric_only_once_per_tick(self):
        """Multiple rules watching the same metric must only fetch it once per
        tick. Fetching per-rule caused wrong readings for "since last call"
        metrics like psutil.cpu_percent(interval=None): a second call
        microseconds after the first measures a near-zero elapsed slice and
        Linux's clock-tick accounting quantizes that into garbage (0/50/100%)
        instead of a real value.
        """
        from nano_logic.engine import _METRIC_REGISTRY, _last_triggered_at

        call_count = {"n": 0}

        def fake_metric():
            call_count["n"] += 1
            return 42.0

        _METRIC_REGISTRY["test.shared_metric"] = fake_metric
        r1 = Rule(metric="test.shared_metric", operator=">", threshold=1, action="log", id=101)
        r2 = Rule(metric="test.shared_metric", operator=">", threshold=1, action="log", id=102)
        ACTIVE_RULES.extend([r1, r2])
        try:
            triggered = evaluate_active_rules(cooldown_seconds=60.0)
            assert call_count["n"] == 1, "shared metric was fetched more than once in a single tick"
            assert {r.id for r, _ in triggered} == {101, 102}
            assert all(val == 42.0 for _, val in triggered)
        finally:
            del _METRIC_REGISTRY["test.shared_metric"]
            _last_triggered_at.pop(101, None)
            _last_triggered_at.pop(102, None)

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


# ═══════════════════════════════════════════════
#  7. DASHBOARD — alert notification tailing
# ═══════════════════════════════════════════════

class TestDashboardAlertNotifications:
    """The dashboard runs in a separate process from the daemon that
    actually evaluates rules, so it learns a rule fired by tailing that
    rule's own log file. Driven directly with asyncio.run() around
    App.run_test() rather than pytest-asyncio, which isn't a dependency."""

    def setup_method(self):
        ACTIVE_RULES.clear()

    def teardown_method(self):
        ACTIVE_RULES.clear()

    def test_new_alert_line_is_surfaced_in_console_and_rings_bell(self):
        import asyncio
        from nano_logic.dashboard import SystemDashboardApp
        from nano_logic.paths import get_logs_dir

        async def scenario():
            rule = Rule(metric="cpu.util", operator=">", threshold=1, action="log", id=1, name="bell_test_rule")
            ACTIVE_RULES.append(rule)
            log_path = get_logs_dir() / f"{rule.name}.log"
            log_path.write_text("[00:00:00] --- Rule 'bell_test_rule' Activated ---\n")

            app = SystemDashboardApp()
            try:
                async with app.run_test():
                    # First poll only seeds the read offset — it must not
                    # replay the pre-existing "Activated" line as an alert.
                    app._check_for_new_alerts()
                    assert not any("ALERT" in line for line in app.command_history)

                    with open(log_path, "a") as f:
                        f.write("[00:00:05] \U0001f6a8 [ALERT] cpu.util reached 42.0 (Rule: > 1.0)\n")

                    rung = []
                    app.bell = lambda: rung.append(True)  # headless bell() is a no-op; observe the call instead
                    app._check_for_new_alerts()

                    console_text = "\n".join(app.command_history)
                    assert "bell_test_rule" in console_text
                    assert "42.0" in console_text
                    assert rung, "bell() was not called for a newly-fired alert"
            finally:
                log_path.unlink(missing_ok=True)

        asyncio.run(scenario())

    def test_removed_rule_stops_being_tracked(self):
        import asyncio
        from nano_logic.dashboard import SystemDashboardApp
        from nano_logic.paths import get_logs_dir

        async def scenario():
            rule = Rule(metric="cpu.util", operator=">", threshold=1, action="log", id=2, name="untracked_rule")
            ACTIVE_RULES.append(rule)
            log_path = get_logs_dir() / f"{rule.name}.log"
            log_path.write_text("[00:00:00] --- Rule 'untracked_rule' Activated ---\n")

            app = SystemDashboardApp()
            try:
                async with app.run_test():
                    app._check_for_new_alerts()
                    assert rule.id in app._alert_log_offsets

                    ACTIVE_RULES.remove(rule)
                    app._check_for_new_alerts()
                    assert rule.id not in app._alert_log_offsets
            finally:
                log_path.unlink(missing_ok=True)

        asyncio.run(scenario())
