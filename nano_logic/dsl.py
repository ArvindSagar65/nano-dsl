"""Minimal DSL parser/executor for system utilization commands."""

from __future__ import annotations

import os
import psutil
from lark import Lark, Transformer
from lark.exceptions import LarkError
from lark.tree import Tree

DSL_GRAMMAR = r"""
start: command

command: "cpu" "." "util" -> cpu_util
    | "cpu" "." "load" -> cpu_load
       | "mem" "." "util" -> mem_util
    | "mem" "." "stats" -> mem_stats
    | "disk" "." "free" -> disk_free

%import common.WS
%ignore WS
"""

parser = Lark(DSL_GRAMMAR, parser="lalr")


class MetricsTransformer(Transformer[str, str]):
    """Executes matched DSL commands."""

    def start(self, children: list[str]) -> str:
        return children[0]

    def cpu_util(self, _children: list[str]) -> str:
        return f"CPU Usage: {psutil.cpu_percent(interval=0.5):.1f}%"

    def cpu_load(self, _children: list[str]) -> str:
        try:
            load_1, load_5, load_15 = os.getloadavg()
            cpu_count = max(1, psutil.cpu_count() or 1)
            return (
                "CPU Load: "
                f"1m={load_1:.2f}, 5m={load_5:.2f}, 15m={load_15:.2f} "
                f"(norm1m={(load_1 / cpu_count) * 100:.1f}%)"
            )
        except OSError:
            return "CPU Load: unavailable on this platform"

    def mem_util(self, _children: list[str]) -> str:
        return f"Memory Usage: {psutil.virtual_memory().percent:.1f}%"

    def mem_stats(self, _children: list[str]) -> str:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return (
            "Memory Stats: "
            f"used={_format_gib(mem.used):.2f}GiB, "
            f"avail={_format_gib(mem.available):.2f}GiB, "
            f"total={_format_gib(mem.total):.2f}GiB, "
            f"swap={swap.percent:.1f}%"
        )

    def disk_free(self, _children: list[str]) -> str:
        disk = psutil.disk_usage("/")
        return (
            "Disk Free: "
            f"free={_format_gib(disk.free):.2f}GiB / "
            f"total={_format_gib(disk.total):.2f}GiB"
        )


def _format_gib(value_bytes: int) -> float:
    return value_bytes / (1024 ** 3)



def parse_command(command_text: str):
    """Parse a DSL command and return its parse tree."""
    return parser.parse(command_text)



def execute_command(command_text: str) -> str:
    """Parse and execute a DSL command."""
    tree = parse_command(command_text)
    result = MetricsTransformer().transform(tree)
    if isinstance(result, Tree):
        return ""
    return result


if __name__ == "__main__":
    while True:
        try:
            text = input("dsl> ").strip()
        except EOFError:
            break

        if not text:
            continue
        if text in {"quit", "exit"}:
            break

        try:
            tree = parse_command(text)
            print(tree.pretty().strip())
            print(execute_command(text))
        except LarkError as exc:
            print(f"Parse error: {exc}")
