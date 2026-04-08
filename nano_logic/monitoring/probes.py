"""System probe helpers used by the TUI dashboard."""

from __future__ import annotations

import subprocess
import time
import os

import psutil


def get_gpu_utilization() -> float | None:
    """Return average GPU utilization for NVIDIA GPUs, if available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=0.8,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None

    values: list[float] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue

    if not values:
        return None
    return sum(values) / len(values)


def get_disk_usage_percent(path: str = "/") -> float:
    """Return disk usage percentage for the selected filesystem path."""
    return psutil.disk_usage(path).percent


def get_disk_free_bytes(path: str = "/") -> tuple[int, int]:
    """Return free and total bytes for a filesystem path."""
    usage = psutil.disk_usage(path)
    return usage.free, usage.total


def get_net_totals_mib() -> tuple[float, float]:
    """Return total network sent and received in MiB."""
    net = psutil.net_io_counters()
    sent_mib = net.bytes_sent / (1024 * 1024)
    recv_mib = net.bytes_recv / (1024 * 1024)
    return sent_mib, recv_mib


def get_system_snapshot() -> tuple[int, float]:
    """Return process count and system uptime seconds."""
    process_count = len(psutil.pids())
    uptime_seconds = max(0.0, time.time() - psutil.boot_time())
    return process_count, uptime_seconds


def get_cpu_load_average() -> tuple[float, float, float] | None:
    """Return 1m/5m/15m load averages, if supported."""
    try:
        return os.getloadavg()
    except OSError:
        return None
