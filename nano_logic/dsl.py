"""Minimal DSL parser/executor for system utilization commands."""

from __future__ import annotations

import os
import signal
import platform
import psutil
from lark import Lark, Transformer
from lark.exceptions import LarkError
from lark.tree import Tree

DSL_GRAMMAR = r"""
start: command

command: "cpu" "." "util" -> cpu_util
    | "cpu" "." "load" -> cpu_load
    | "cpu" "." "cores" -> cpu_cores
    | "cpu" "." "top" -> cpu_top
    | "mem" "." "util" -> mem_util
    | "mem" "." "stats" -> mem_stats
    | "mem" "." "swap" -> mem_swap
    | "mem" "." "top" -> mem_top
    | "disk" "." "free" -> disk_free
    | "disk" "." "usage" -> disk_usage
    | "disk" "." "io" -> disk_io
    | "disk" "." "top" -> disk_top
    | "proc" "." "list" -> proc_list
    | "proc" "." "kill" INT -> proc_kill
    | "net" "." "interfaces" -> net_interfaces
    | "net" "." "bandwidth" -> net_bandwidth
    | "net" "." "connections" -> net_connections
    | "system" "." "uptime" -> system_uptime
    | "system" "." "info" -> system_info
    | "system" "." "processes" -> system_processes

%import common.WS
%import common.INT
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

    def cpu_cores(self, _children: list[str]) -> str:
        physical_cores = psutil.cpu_count(logical=False) or 1
        logical_cores = psutil.cpu_count(logical=True) or 1
        return f"CPU Cores: {physical_cores} physical, {logical_cores} logical"

    def cpu_top(self, _children: list[str]) -> str:
        """Get top 5 processes by CPU usage."""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    processes.append((proc.info['pid'], proc.info['name'], proc.cpu_percent()))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    pass
            
            processes.sort(key=lambda x: x[2], reverse=True)
            top_5 = processes[:5]
            
            result = "Top 5 CPU Processes:\n"
            for pid, name, cpu_pct in top_5:
                result += f"  {pid:6d} | {name:20s} | {cpu_pct:6.1f}%\n"
            return result.strip()
        except Exception as e:
            return f"CPU Top: Error retrieving processes - {e}"

    def mem_swap(self, _children: list[str]) -> str:
        swap = psutil.swap_memory()
        return (
            "Swap Memory: "
            f"used={_format_gib(swap.used):.2f}GiB, "
            f"free={_format_gib(swap.free):.2f}GiB, "
            f"total={_format_gib(swap.total):.2f}GiB, "
            f"percent={swap.percent:.1f}%"
        )

    def mem_top(self, _children: list[str]) -> str:
        """Get top 5 processes by memory usage."""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
                try:
                    processes.append((proc.info['pid'], proc.info['name'], proc.memory_percent()))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    pass
            
            processes.sort(key=lambda x: x[2], reverse=True)
            top_5 = processes[:5]
            
            result = "Top 5 Memory Processes:\n"
            for pid, name, mem_pct in top_5:
                result += f"  {pid:6d} | {name:20s} | {mem_pct:6.1f}%\n"
            return result.strip()
        except Exception as e:
            return f"Memory Top: Error retrieving processes - {e}"

    def disk_usage(self, _children: list[str]) -> str:
        """Get disk usage for all mounted partitions."""
        try:
            partitions = psutil.disk_partitions()
            result = "Disk Usage (All Partitions):\n"
            for partition in partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    result += (
                        f"  {partition.device:15s} @ {partition.mountpoint:15s} | "
                        f"{usage.percent:5.1f}% | {_format_gib(usage.used):.1f}/{_format_gib(usage.total):.1f}GiB\n"
                    )
                except (OSError, PermissionError):
                    pass
            return result.strip()
        except Exception as e:
            return f"Disk Usage: Error - {e}"

    def disk_io(self, _children: list[str]) -> str:
        """Get disk I/O read/write rates."""
        try:
            io_counters = psutil.disk_io_counters()
            return (
                "Disk I/O: "
                f"read_count={io_counters.read_count}, "
                f"write_count={io_counters.write_count}, "
                f"read_bytes={_format_gib(io_counters.read_bytes):.2f}GiB, "
                f"write_bytes={_format_gib(io_counters.write_bytes):.2f}GiB"
            )
        except Exception as e:
            return f"Disk I/O: Error - {e}"

    def disk_top(self, _children: list[str]) -> str:
        """Get top directories by storage usage (requires du command)."""
        try:
            import subprocess
            result = subprocess.run(
                ["du", "-sh", "/home", "/opt", "/var", "/usr"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return "Top Disk Usage:\n" + result.stdout.strip()
            else:
                return "Disk Top: Unable to calculate directory sizes"
        except Exception:
            return "Disk Top: du command not available or error occurred"

    def proc_list(self, _children: list[str]) -> str:
        """List all processes with PID and basic info."""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'status']):
                try:
                    processes.append((proc.info['pid'], proc.info['name'], proc.info['status']))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    pass
            
            processes.sort(key=lambda x: x[0])
            result = f"Total Processes: {len(processes)}\n"
            result += "PID     | Name (first 20 shown)\n"
            result += "--------|---\n"
            for pid, name, status in processes[:20]:
                result += f"{pid:7d} | {name[:30]:30s}\n"
            result += f"... and {max(0, len(processes) - 20)} more" if len(processes) > 20 else ""
            return result.strip()
        except Exception as e:
            return f"Process List: Error - {e}"

    def proc_kill(self, children: list) -> str:
        """Kill a process by PID."""
        try:
            pid = int(children[0])
            proc = psutil.Process(pid)
            name = proc.name()
            proc.terminate()
            return f"Process killed: PID {pid} ({name})"
        except psutil.NoSuchProcess:
            return f"Process Kill: PID {pid} does not exist"
        except psutil.AccessDenied:
            return f"Process Kill: Permission denied to kill PID {pid}"
        except Exception as e:
            return f"Process Kill: Error - {e}"

    def net_interfaces(self, _children: list[str]) -> str:
        """List all network interfaces and stats."""
        try:
            interfaces = psutil.net_if_stats()
            result = "Network Interfaces:\n"
            for iface, stats in interfaces.items():
                status = "UP" if stats.isup else "DOWN"
                result += f"  {iface:10s} | {status:4s} | MTU: {stats.mtu}\n"
            return result.strip()
        except Exception as e:
            return f"Net Interfaces: Error - {e}"

    def net_bandwidth(self, _children: list[str]) -> str:
        """Get current network bandwidth usage."""
        try:
            net_io = psutil.net_io_counters()
            return (
                "Network Bandwidth: "
                f"sent={_format_gib(net_io.bytes_sent):.2f}GiB, "
                f"recv={_format_gib(net_io.bytes_recv):.2f}GiB, "
                f"packets_sent={net_io.packets_sent}, "
                f"packets_recv={net_io.packets_recv}"
            )
        except Exception as e:
            return f"Net Bandwidth: Error - {e}"

    def net_connections(self, _children: list[str]) -> str:
        """Get active network connections count."""
        try:
            connections = psutil.net_connections()
            established = len([c for c in connections if c.status == 'ESTABLISHED'])
            listening = len([c for c in connections if c.status == 'LISTEN'])
            total = len(connections)
            return (
                "Network Connections: "
                f"total={total}, established={established}, listening={listening}"
            )
        except Exception as e:
            return f"Net Connections: Error - {e}"

    def system_uptime(self, _children: list[str]) -> str:
        """Get system uptime."""
        try:
            uptime_seconds = int(max(0.0, psutil.boot_time() + 86400 * 10000 - os.times()[4]))
            # Better approach using direct timestamp
            import time
            boot_time = psutil.boot_time()
            current_time = time.time()
            uptime_seconds = int(current_time - boot_time)
            
            days = uptime_seconds // 86400
            hours = (uptime_seconds % 86400) // 3600
            minutes = (uptime_seconds % 3600) // 60
            
            return f"System Uptime: {days}d {hours}h {minutes}m"
        except Exception as e:
            return f"System Uptime: Error - {e}"

    def system_info(self, _children: list[str]) -> str:
        """Get system information."""
        try:
            system = platform.system()
            release = platform.release()
            hostname = platform.node()
            processor = platform.processor() or "Unknown"
            
            return (
                f"System Info: "
                f"OS={system} {release}, "
                f"Hostname={hostname}, "
                f"Processor={processor}"
            )
        except Exception as e:
            return f"System Info: Error - {e}"

    def system_processes(self, _children: list[str]) -> str:
        """Get total process and thread count."""
        try:
            total_processes = len(psutil.pids())
            total_threads = sum(
                proc.num_threads() 
                for proc in psutil.process_iter(['num_threads']) 
                if proc.num_threads() is not None
            )
            return f"System Processes: total={total_processes}, threads={total_threads}"
        except Exception as e:
            return f"System Processes: Error - {e}"


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
