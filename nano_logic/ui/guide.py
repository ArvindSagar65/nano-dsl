"""Guide text used by the Nano Logic TUI."""

from __future__ import annotations


def render_guide() -> str:
    """Return a short in-app guide for available DSL commands."""
    lines = [
        "Guide for NanoLogic",
        "",
        "CPU Commands",
        "- cpu.util: CPU usage %",
        "- cpu.load: 1/5/15m load avg",
        "- cpu.cores: CPU cores info",
        "- cpu.top: Top 5 CPU processes",
        "",
        "Memory Commands",
        "- mem.util: Memory usage %",
        "- mem.stats: Memory details",
        "- mem.swap: Swap memory info",
        "- mem.top: Top 5 memory procs",
        "",
        "Disk Commands",
        "- disk.free: Root FS free space",
        "- disk.usage: All partitions %",
        "- disk.io: I/O stats",
        "- disk.top: Dir storage usage",
        "",
        "Process/Network/System",
        "- proc.list: List processes",
        "- proc.kill <pid>: Kill process",
        "- net.interfaces: Network ifaces",
        "- net.bandwidth: Net stats",
        "- net.connections: Active conns",
        "- system.uptime: System uptime",
        "- system.info: OS/hostname info",
        "- system.processes: Proc/thread cnt",
        "",
        "Tips",
        "- Press q to quit",
        "- Max 15 recent commands shown",
    ]
    return "\n".join(lines)
