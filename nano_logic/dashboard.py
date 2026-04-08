"""Textual terminal dashboard showing CPU, RAM, and logs."""

from __future__ import annotations

import asyncio
from datetime import datetime

import psutil
from lark.exceptions import LarkError
from nano_logic.dsl import execute_command
from nano_logic.monitoring.probes import (
    get_cpu_load_average,
    get_disk_free_bytes,
    get_disk_usage_percent,
    get_gpu_utilization,
    get_net_totals_mib,
)
from nano_logic.ui.guide import render_guide
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static


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
    }

    #guide-panel {
        width: 34;
        min-width: 30;
        border: round #8ac926;
        padding: 1 2;
        background: #152113;
    }

    #main-layout {
        layout: vertical;
        width: 1fr;
        padding-left: 1;
    }

    .metrics-row {
        layout: horizontal;
        height: 8;
        margin-bottom: 1;
    }

    .metric-panel {
        width: 1fr;
    }

    #cpu-panel {
        margin-right: 1;
    }

    #ram-panel {
        margin-right: 1;
    }

    #disk-panel {
        margin-right: 1;
    }

    #net-panel {
        margin-right: 1;
    }

    #command-panel {
        height: 1fr;
    }

    #command-input {
        margin-top: 0;
    }
    """

    BINDINGS = [Binding("q", "quit", "Quit")]

    command_history: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.command_history = [
            "Command Console",
            "Ready. Try: cpu.util, cpu.load, mem.util, mem.stats, disk.free",
        ]

    def compose(self) -> ComposeResult:
        """Build the app layout."""
        yield Header(show_clock=True)
        with Horizontal(id="app-layout"):
            yield Static(render_guide(), id="guide-panel")
            with Vertical(id="main-layout"):
                with Horizontal(classes="metrics-row"):
                    yield Static("CPU Usage\nLoading...", id="cpu-panel", classes="panel metric-panel")
                    yield Static("RAM Usage\nLoading...", id="ram-panel", classes="panel metric-panel")
                    yield Static("GPU Usage\nLoading...", id="gpu-panel", classes="panel metric-panel")
                with Horizontal(classes="metrics-row"):
                    yield Static("Disk Usage\nLoading...", id="disk-panel", classes="panel metric-panel")
                    yield Static("Network\nLoading...", id="net-panel", classes="panel metric-panel")
                    yield Static("System\nLoading...", id="system-panel", classes="panel metric-panel")
                yield Static(self._render_command_panel(), id="command-panel", classes="panel")
                yield Input(placeholder="Enter command: cpu.util, cpu.load, mem.util, mem.stats, disk.free", id="command-input")
        yield Footer()

    def on_mount(self) -> None:
        """Start periodic async metric updates."""
        psutil.cpu_percent(interval=None)
        self.refresh_metrics()
        self.run_worker(self._metrics_loop(), name="metrics-loop", exclusive=True)
        self.query_one("#command-input", Input).focus()

    async def _metrics_loop(self) -> None:
        """Refresh system values every second."""
        while True:
            self.refresh_metrics()
            await asyncio.sleep(1)

    def refresh_metrics(self) -> None:
        """Read system metrics and update the UI panels."""
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        gpu_percent = get_gpu_utilization()
        disk_percent = get_disk_usage_percent("/")
        disk_free, disk_total = get_disk_free_bytes("/")
        cpu_load = get_cpu_load_average()
        sent_mib, recv_mib = get_net_totals_mib()
        process_count = len(psutil.pids())
        uptime_seconds = int(max(0.0, datetime.now().timestamp() - psutil.boot_time()))

        cpu_widget = self.query_one("#cpu-panel", Static)
        ram_widget = self.query_one("#ram-panel", Static)
        gpu_widget = self.query_one("#gpu-panel", Static)
        disk_widget = self.query_one("#disk-panel", Static)
        net_widget = self.query_one("#net-panel", Static)
        system_widget = self.query_one("#system-panel", Static)

        cpu_widget.update(self._render_cpu_panel(cpu_percent, cpu_load))
        ram_widget.update(self._render_ram_panel(memory.percent, memory.used, memory.total, swap.percent))
        gpu_widget.update(self._render_gpu_panel(gpu_percent))
        disk_widget.update(self._render_disk_panel(disk_percent, disk_free, disk_total))
        net_widget.update(self._render_net_panel(sent_mib, recv_mib))
        system_widget.update(self._render_system_panel(process_count, uptime_seconds))

    def _render_cpu_panel(self, cpu_percent: float, cpu_load: tuple[float, float, float] | None) -> str:
        bar = self._progress_bar(cpu_percent)
        if cpu_load is None:
            load_text = "Load: unavailable"
        else:
            load_text = f"Load 1/5/15: {cpu_load[0]:.2f} {cpu_load[1]:.2f} {cpu_load[2]:.2f}"
        return (
            "CPU Usage\n"
            f"Current: {cpu_percent:5.1f}%\n"
            f"{load_text}\n"
            f"{bar}"
        )

    def _render_ram_panel(self, ram_percent: float, used_bytes: int, total_bytes: int, swap_percent: float) -> str:
        used_gb = used_bytes / (1024 ** 3)
        total_gb = total_bytes / (1024 ** 3)
        bar = self._progress_bar(ram_percent)
        return (
            "RAM Usage\n"
            f"Current: {ram_percent:5.1f}%\n"
            f"Used: {used_gb:.2f} GB / {total_gb:.2f} GB\n"
            f"Swap: {swap_percent:5.1f}%\n"
            f"{bar}"
        )

    def _render_gpu_panel(self, gpu_percent: float | None) -> str:
        if gpu_percent is None:
            return (
                "GPU Usage\n"
                "Current: N/A\n"
                "nvidia-smi unavailable"
            )
        bar = self._progress_bar(gpu_percent)
        return (
            "GPU Usage\n"
            f"Current: {gpu_percent:5.1f}%\n"
            f"{bar}"
        )

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

    def _render_command_panel(self) -> str:
        return "\n".join(self.command_history[-14:])

    def _append_console(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_history.append(f"[{timestamp}] {message}")
        self.query_one("#command-panel", Static).update(self._render_command_panel())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command_text = event.value.strip()
        event.input.value = ""

        if not command_text:
            return

        self._append_console(f"> {command_text}")
        try:
            result = execute_command(command_text)
            if result:
                self._append_console(result)
            else:
                self._append_console("No output")
        except LarkError as exc:
            self._append_console(f"Parse error: {exc}")
        except Exception as exc:
            self._append_console(f"Execution error: {exc}")

    @staticmethod
    def _progress_bar(percent: float, width: int = 30) -> str:
        filled = int((percent / 100) * width)
        return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def main() -> None:
    """Run the Textual dashboard application."""
    SystemDashboardApp().run()


if __name__ == "__main__":
    main()
