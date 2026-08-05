"""Textual terminal dashboard showing system metrics and logs."""
from __future__ import annotations
import asyncio
import textwrap
from datetime import datetime
import psutil
import subprocess
import sys
import shutil
from lark.exceptions import LarkError
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Log, Static
from textual import events
from nano_logic.dsl import execute_command
from nano_logic.models import Rule, StopRule
from nano_logic.engine import ACTIVE_RULES, add_rule, remove_rule, load_rules
from nano_logic.logging_config import configure_logging
from nano_logic.monitoring.probes import (
    get_disk_free_bytes,
    get_disk_usage_percent,
    get_net_totals_mib,
)
from nano_logic.paths import get_logs_dir
from nano_logic.ui.guide import render_guide

logger = configure_logging(__name__)


def _copy_text_to_clipboard(text: str) -> None:
    """Copy text to the system clipboard.

    Tries `pyperclip` first, then falls back to `wl-copy` or `xclip` if available.
    Raises a RuntimeError if no backend is found.
    """
    try:
        import pyperclip

        pyperclip.copy(text)
        return
    except Exception:
        pass

    # Try Wayland
    if shutil.which("wl-copy"):
        p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        p.communicate(text.encode())
        if p.returncode == 0:
            return

    # Try X11 xclip
    if shutil.which("xclip"):
        p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
        p.communicate(text.encode())
        if p.returncode == 0:
            return

    raise RuntimeError("No clipboard backend available (install pyperclip, wl-copy, or xclip)")


class SystemDashboardApp(App[None]):
    """Beginner-friendly Textual dashboard app."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #app-layout {
        layout: horizontal;
        height: 1fr;
        padding: 1;
        background: #10141b;
    }

    .panel {
        border: round #4cc9f0;
        padding: 1 2;
        margin-bottom: 1;
        background: #141a24;
        width: 1fr;
        height: 10;
    }

    .metric-panel {
        width: 1fr;
        height: 10;
    }

    #guide-panel {
        width: 38;
        min-width: 30;
        border: round #8ac926;
        padding: 1 2;
        background: #152113;
        height: 1fr;
    }

    #main-layout {
        layout: vertical;
        width: 1fr;
        padding-left: 1;
    }

    .metrics-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
        width: 1fr;
    }

    #disk-panel {
        margin-right: 1;
    }

    #net-panel {
        margin-right: 1;
    }

    #command-panel {
        height: 1fr;
        min-height: 10;
        border: round #ff006e;
        background: #241017;
        color: #f5f7fa;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
    }

    #rules-panel {
        height: auto;
        min-height: 6;
        max-height: 12;
        border: round #ff9f1c;
        background: #141a24;
        margin-bottom: 1;
        overflow-y: auto;
    }

    #command-input {
        margin-top: 0;
        height: 3;
        border: round #06d6d0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+shift+c", "copy_console", "Copy Console to Clipboard"),
        Binding("f6", "copy_console", "Copy Console (Fallback)"),
    ]

    command_history: list[str]
    commands_typed: list[str]
    history_index: int

    def __init__(self) -> None:
        super().__init__()
        self.command_history = [
            "Command Console",
            "Try: cpu.util | disk.free | net.ports | sensor.temp",
            "Alerts: my_rule: alert cpu.util > 80 -> log",
            "Utility: help | rules | status | clear",
            "Type 'exit' to quit",
        ]
        self.commands_typed = []
        self.history_index = -1
        # Byte offset already read in each rule's log file, keyed by rule
        # id. The daemon is a separate process and the only thing that
        # evaluates rules, so tailing the log file it writes is how the
        # dashboard learns a rule fired — there's no other channel between
        # the two beyond the files they both read/write.
        self._alert_log_offsets: dict[int, int] = {}

    def compose(self) -> ComposeResult:
        """Build the app layout."""
        with Horizontal(id="app-layout"):
            yield Static(render_guide(), id="guide-panel")

            with Vertical(id="main-layout"):
                with Horizontal(classes="metrics-row"):
                    yield Static("Disk Usage\nLoading...", id="disk-panel", classes="panel metric-panel")
                    yield Static("Network\nLoading...", id="net-panel", classes="panel metric-panel")
                    yield Static("System\nLoading...", id="system-panel", classes="panel metric-panel")

                # Active Rules panel
                yield Static("Active Rules:\nNo active rules.", id="rules-panel", classes="panel")

                # Command panel
                yield Log(id="command-panel", classes="panel", highlight=False, auto_scroll=True)

                yield Input(placeholder="Enter command (type 'exit' to quit)", id="command-input")

    def on_mount(self) -> None:
        """Start periodic async metric updates, load rules, and ensure daemon is running."""
        # Always attempt to spawn the daemon — it uses an flock()'d PID file
        # to enforce a single instance, so a redundant spawn just exits
        # immediately rather than racing with an already-running daemon.
        try:
            subprocess.Popen(
                [sys.executable, "-m", "nano_logic.daemon"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            logger.exception("Failed to spawn background daemon")

        load_rules()
        self.update_rules_panel()
        self.refresh_metrics()
        self.run_worker(self._metrics_loop(), name="metrics-loop", exclusive=True)

        for line in self.command_history:
            self._write_console_wrapped(line)
        self.query_one("#command-input", Input).focus()

    async def _metrics_loop(self) -> None:
        """Refresh system values every second."""
        while True:
            self.refresh_metrics()
            self._check_for_new_alerts()
            await asyncio.sleep(1)

    def _check_for_new_alerts(self) -> None:
        """Surface alert lines the daemon has written since the last tick.

        Reads only the bytes appended to each active rule's log file since
        it was last checked, so this stays cheap regardless of how large
        the log grows.
        """
        active_ids = set()
        for rule in ACTIVE_RULES:
            active_ids.add(rule.id)
            log_path = get_logs_dir() / f"{rule.name}.log"

            if rule.id not in self._alert_log_offsets:
                # First time seeing this rule this session — start from the
                # current end of file so we don't replay alerts that fired
                # before the dashboard started watching it.
                self._alert_log_offsets[rule.id] = log_path.stat().st_size if log_path.exists() else 0
                continue

            if not log_path.exists():
                continue

            try:
                size = log_path.stat().st_size
                offset = self._alert_log_offsets[rule.id]
                if size < offset:
                    offset = 0  # log was rotated/truncated — restart from the top
                if size == offset:
                    continue
                with open(log_path) as f:
                    f.seek(offset)
                    new_content = f.read()
                self._alert_log_offsets[rule.id] = size
            except OSError:
                logger.exception("Failed to tail alert log for rule '%s'", rule.name)
                continue

            for line in new_content.splitlines():
                if "[ALERT]" not in line:
                    continue
                # Log lines are already timestamped ("[HH:MM:SS] message");
                # drop that prefix since _append_console adds its own.
                _, _, message = line.partition("] ")
                self._append_console(f"{rule.name}: {message or line}")
                self.bell()

        # Stop tracking rules that were removed or renamed.
        for stale_id in set(self._alert_log_offsets) - active_ids:
            del self._alert_log_offsets[stale_id]

    def refresh_metrics(self) -> None:
        """Read system metrics and update the UI panels."""
        disk_percent = get_disk_usage_percent("/")
        disk_free, disk_total = get_disk_free_bytes("/")
        sent_mib, recv_mib = get_net_totals_mib()
        process_count = len(psutil.pids())
        uptime_seconds = int(max(0.0, datetime.now().timestamp() - psutil.boot_time()))

        disk_widget = self.query_one("#disk-panel", Static)
        net_widget = self.query_one("#net-panel", Static)
        system_widget = self.query_one("#system-panel", Static)

        disk_widget.update(self._render_disk_panel(disk_percent, disk_free, disk_total))
        net_widget.update(self._render_net_panel(sent_mib, recv_mib))
        system_widget.update(self._render_system_panel(process_count, uptime_seconds))

    def _render_disk_panel(self, disk_percent: float, free_bytes: int, total_bytes: int) -> str:
        free_gb = free_bytes / (1024 ** 3)
        total_gb = total_bytes / (1024 ** 3)
        bar = self._progress_bar(disk_percent)
        return (
            "Disk Usage\n"
            f"Root FS: {disk_percent:5.1f}%\n"
            f"Free: {free_gb:.1f} GB / {total_gb:.1f} GB\n"
            f"{bar}"
        )

    def _render_net_panel(self, sent_mib: float, recv_mib: float) -> str:
        return (
            "Network\n"
            f"Sent: {sent_mib:8.1f} MiB\n"
            f"Recv: {recv_mib:8.1f} MiB"
        )

    def _render_system_panel(self, process_count: int, uptime_seconds: int) -> str:
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        return (
            "System\n"
            f"Processes: {process_count}\n"
            f"Uptime: {hours}h {minutes}m"
        )

    def _append_console(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.command_history.append(line)
        self._write_console_wrapped(line)

    def _write_console_wrapped(self, line: str) -> None:
        """Write wrapped lines to keep the console readable in narrow terminals."""
        log = self.query_one("#command-panel", Log)
        for part in textwrap.wrap(line, width=86, replace_whitespace=False) or [""]:
            log.write_line(part)

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._history_up()
        elif event.key == "down":
            self._history_down()

    def _history_up(self) -> None:
        input_widget = self.query_one("#command-input", Input)
        if not input_widget.has_focus or not self.commands_typed:
            return
        if self.history_index == -1:
            self.history_index = len(self.commands_typed) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        input_widget.value = self.commands_typed[self.history_index]
        input_widget.cursor_position = len(input_widget.value)

    def _history_down(self) -> None:
        input_widget = self.query_one("#command-input", Input)
        if not input_widget.has_focus or not self.commands_typed:
            return
        if self.history_index == -1 or self.history_index >= len(self.commands_typed) - 1:
            self.history_index = -1
            input_widget.value = ""
        else:
            self.history_index = min(len(self.commands_typed) - 1, self.history_index + 1)
            input_widget.value = self.commands_typed[self.history_index]
            input_widget.cursor_position = len(input_widget.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command_text = event.value.strip()
        event.input.value = ""

        if not command_text:
            return
        if command_text.lower() in {"exit", "quit"}:
            self.exit()
            return

        if not self.commands_typed or self.commands_typed[-1] != command_text:
            self.commands_typed.append(command_text)
        self.history_index = -1

        self._append_console(f"> {command_text}")

        try:
            result = execute_command(command_text)

            if isinstance(result, Rule):
                add_rule(result)
                self._append_console(
                    f"✅ Rule '{result.name}' (ID: {result.id}) activated: "
                    f"Monitor {result.metric} {result.operator} {result.threshold}"
                )
                self.update_rules_panel()
                # Initialize the log file for this specific rule
                try:
                    with open(get_logs_dir() / f"{result.name}.log", "a") as f:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        f.write(f"[{timestamp}] --- Rule '{result.name}' Activated ---\n")
                except OSError as e:
                    logger.exception("Failed to create log file for rule '%s'", result.name)
                    self._append_console(f"⚠️ Error creating log file for '{result.name}': {e}")

            elif isinstance(result, StopRule):
                if remove_rule(result.identifier):
                    self._append_console(f"🛑 Rule '{result.identifier}' stopped.")
                    self.update_rules_panel()
                else:
                    self._append_console(f"⚠️ Rule '{result.identifier}' not found.")

            # ── Handle utility command sentinels ──
            elif result == "__CLEAR__":
                self.query_one("#command-panel", Log).clear()
                self.command_history.clear()
                # Re-show the header
                self._write_console_wrapped("Command Console")
                self._write_console_wrapped("Try: cpu.util | disk.free | net.ports | sensor.temp")

            elif result:
                self._append_console(str(result))

            else:
                self._append_console("No output")

        except LarkError as exc:
            self._append_console(f"Parse error: {exc}")
        except Exception as exc:
            self._append_console(f"Execution error: {exc}")

    def update_rules_panel(self) -> None:
        rules_widget = self.query_one("#rules-panel", Static)
        if not ACTIVE_RULES:
            rules_widget.update("Active Rules:\nNo active rules.")
            return
        content = "Active Rules:\n"
        for r in ACTIVE_RULES:
            content += f"[{r.id}] {r.name}: alert {r.metric} {r.operator} {r.threshold} -> {r.action}\n"
        rules_widget.update(content.strip())

    def action_copy_console(self) -> None:
        """Copy the current console contents to the system clipboard.

        Bound to `Ctrl+Shift+C`. Falls back to notifying the user on failure.
        """
        try:
            text = "\n".join(self.command_history)
            _copy_text_to_clipboard(text)
            # Provide user feedback in the console
            self._append_console("✅ Console copied to clipboard.")
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            self._append_console(f"⚠️ Copy failed: {exc}")

    @staticmethod
    def _progress_bar(percent: float, width: int = 30) -> str:
        filled = int((percent / 100) * width)
        return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def main() -> None:
    """Run the Textual dashboard application."""
    SystemDashboardApp().run()


if __name__ == "__main__":
    main()
