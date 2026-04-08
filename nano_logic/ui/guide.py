"""Guide text used by the Nano Logic TUI."""

from __future__ import annotations


def render_guide() -> str:
    """Return a short in-app guide for available DSL commands."""
    lines = [
        "Guide for NanoLogic",
        "",
        "Commands",
        "- cpu.util",
        "- cpu.load",
        "- mem.util",
        "- mem.stats",
        "- disk.free",
        "",
        "Palette",
        "- Sky blue border: live metric panels",
        "- Green border: guide and command hints",
        "- Deep slate background: dashboard canvas",
        "",
        "Command Info",
        "- cpu.util: current CPU utilization percent",
        "- cpu.load: uptime-style 1/5/15m system load",
        "- mem.util: current memory utilization percent",
        "- mem.stats: memory used/available/total + swap",
        "- disk.free: free and total space for /",
        "",
        "Tips",
        "- Press q to quit",
        "- Unknown commands show parser errors",
        "- GPU panel uses nvidia-smi when available",
    ]
    return "\n".join(lines)
