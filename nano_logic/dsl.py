"""Minimal DSL parser/executor for system utilization commands."""
from __future__ import annotations
import os
import time
import platform
import socket
import subprocess
import psutil
from lark import Lark, Transformer
from lark.exceptions import LarkError
from lark.tree import Tree
from nano_logic.models import Rule, StopRule
from nano_logic.engine import ACTIVE_RULES

DSL_GRAMMAR = r"""
?start: rule | command | rule_cmd

# ── Alert Rule Structure ──
?rule: named_rule | anon_rule
named_rule: RULE_NAME ":" ALERT METRIC_NAME OPERATOR NUMBER ARROW ACTION
anon_rule: ALERT METRIC_NAME OPERATOR NUMBER ARROW ACTION

rule_cmd: "stop" [RULE_KW] (INT | RULE_NAME) -> stop_rule

ALERT: "alert"i
ARROW: "->"
RULE_KW.2: "rule"
RULE_NAME: /[a-zA-Z_][a-zA-Z0-9_-]*/
METRIC_NAME: /[a-zA-Z_]+\.[a-zA-Z_]+/
OPERATOR: ">" | "<" | "==" | ">=" | "<="
ACTION: /[a-zA-Z_]+/

# ── Commands organized by namespace ──
?command: cpu_cmd | mem_cmd | disk_cmd | gpu_cmd | proc_cmd 
        | net_cmd | sys_cmd | sensor_cmd | docker_cmd | service_cmd
        | utility_cmd

# Using proven three-token "cpu" "." "metric" pattern throughout
cpu_cmd: "cpu" "." "util"    -> cpu_util
       | "cpu" "." "load"    -> cpu_load
       | "cpu" "." "cores"   -> cpu_cores
       | "cpu" "." "top"     -> cpu_top
       | "cpu" "." "avg"     -> cpu_avg

mem_cmd: "mem" "." "util"    -> mem_util
       | "mem" "." "stats"   -> mem_stats
       | "mem" "." "swap"    -> mem_swap
       | "mem" "." "top"     -> mem_top
       | "mem" "." "cached"  -> mem_cached

disk_cmd: "disk" "." "free"  -> disk_free
        | "disk" "." "usage" -> disk_usage
        | "disk" "." "io"    -> disk_io
        | "disk" "." "top"   -> disk_top
        | "disk" "." "inode" -> disk_inode

gpu_cmd: "gpu" "." "util"    -> gpu_util

proc_cmd: "proc" "." "list"          -> proc_list
        | "proc" "." "kill" INT      -> proc_kill
        | "proc" "." "search" CMD    -> proc_search
        | "proc" "." "tree"          -> proc_tree
        | "proc" "." "info" INT      -> proc_info

net_cmd: "net" "." "interfaces"   -> net_interfaces
       | "net" "." "bandwidth"    -> net_bandwidth
       | "net" "." "connections"  -> net_connections
       | "net" "." "ports"        -> net_ports
       | "net" "." "dns" CMD      -> net_dns

sys_cmd: "system" "." "uptime"     -> system_uptime
       | "system" "." "info"       -> system_info
       | "system" "." "processes"  -> system_processes
       | "system" "." "users"      -> system_users
       | "system" "." "load"       -> system_load

sensor_cmd: "sensor" "." "temp"    -> sensor_temp
          | "sensor" "." "fans"    -> sensor_fans
          | "sensor" "." "battery" -> sensor_battery

docker_cmd: "docker" "." "ps"      -> docker_ps
          | "docker" "." "stats"   -> docker_stats

service_cmd: "service" "." "list"          -> service_list
           | "service" "." "status" CMD    -> service_status

utility_cmd: "clear"   -> cmd_clear
           | "help"    -> cmd_help
           | "rules"   -> cmd_rules
           | "status"  -> cmd_status
           | "history" -> cmd_history
           | "guide"   -> cmd_guide

CMD: /[a-zA-Z0-9_.\-\/]+/

%import common.WS
%import common.INT
%import common.NUMBER
%ignore WS
"""

parser = Lark(DSL_GRAMMAR, parser="lalr")

# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _format_gib(value_bytes: int) -> float:
    return value_bytes / (1024 ** 3)


def _run_cmd(cmd: list[str], timeout: int = 5) -> str:
    """Run a shell command safely, return stdout or error message."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()
        return f"Error: {result.stderr.strip() or 'command failed'}"
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return f"Timeout: {cmd[0]} did not respond in {timeout}s"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────
#  Transformer
# ──────────────────────────────────────────────

class MetricsTransformer(Transformer):
    """Executes matched DSL commands."""

    # ── Rules ──
    def anon_rule(self, items: list) -> Rule:
        return Rule(
            metric=str(items[1]),
            operator=str(items[2]),
            threshold=float(items[3]),
            action=str(items[5]),
        )

    def named_rule(self, items: list) -> Rule:
        return Rule(
            name=str(items[0]),
            metric=str(items[2]),
            operator=str(items[3]),
            threshold=float(items[4]),
            action=str(items[6]),
        )

    def stop_rule(self, items: list) -> StopRule:
        return StopRule(identifier=str(items[-1]))

    # ── CPU ──
    def cpu_util(self, _children: list) -> str:
        return f"CPU Usage: {psutil.cpu_percent(interval=0.5):.1f}%"

    def cpu_load(self, _children: list) -> str:
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

    def cpu_cores(self, _children: list) -> str:
        physical = psutil.cpu_count(logical=False) or 1
        logical = psutil.cpu_count(logical=True) or 1
        return f"CPU Cores: {physical} physical, {logical} logical"

    def cpu_top(self, _children: list) -> str:
        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent"]):
                try:
                    processes.append((proc.info["pid"], proc.info["name"], proc.cpu_percent()))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            processes.sort(key=lambda x: x[2], reverse=True)
            top5 = processes[:5]
            result = "Top 5 CPU Processes:\n"
            for pid, name, cpu in top5:
                result += f"  {pid:6d} | {name:20s} | {cpu:6.1f}%\n"
            return result.strip()
        except Exception as e:
            return f"CPU Top: Error - {e}"

    def cpu_avg(self, _children: list) -> str:
        """Normalised average CPU load over 1/5/15 minutes."""
        try:
            load_1, load_5, load_15 = os.getloadavg()
            cores = psutil.cpu_count() or 1
            return (
                f"CPU Avg Load (normalised): "
                f"1m={load_1/cores*100:.1f}%, "
                f"5m={load_5/cores*100:.1f}%, "
                f"15m={load_15/cores*100:.1f}%"
            )
        except OSError:
            return "CPU Avg: unavailable on this platform"

    # ── Memory ──
    def mem_util(self, _children: list) -> str:
        return f"Memory Usage: {psutil.virtual_memory().percent:.1f}%"

    def mem_stats(self, _children: list) -> str:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return (
            "Memory Stats: "
            f"used={_format_gib(mem.used):.2f}GiB, "
            f"avail={_format_gib(mem.available):.2f}GiB, "
            f"total={_format_gib(mem.total):.2f}GiB, "
            f"swap={swap.percent:.1f}%"
        )

    def mem_swap(self, _children: list) -> str:
        swap = psutil.swap_memory()
        return (
            "Swap Memory: "
            f"used={_format_gib(swap.used):.2f}GiB, "
            f"free={_format_gib(swap.free):.2f}GiB, "
            f"total={_format_gib(swap.total):.2f}GiB, "
            f"percent={swap.percent:.1f}%"
        )

    def mem_top(self, _children: list) -> str:
        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
                try:
                    processes.append((proc.info["pid"], proc.info["name"], proc.memory_percent()))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            processes.sort(key=lambda x: x[2], reverse=True)
            top5 = processes[:5]
            result = "Top 5 Memory Processes:\n"
            for pid, name, mem in top5:
                result += f"  {pid:6d} | {name:20s} | {mem:6.1f}%\n"
            return result.strip()
        except Exception as e:
            return f"Memory Top: Error - {e}"

    def mem_cached(self, _children: list) -> str:
        mem = psutil.virtual_memory()
        return (
            "Memory Cached/Buffers: "
            f"cached={_format_gib(mem.cached):.2f}GiB, "
            f"buffers={_format_gib(mem.buffers) if hasattr(mem, 'buffers') else 0:.2f}GiB"
        )

    # ── Disk ──
    def disk_free(self, _children: list) -> str:
        disk = psutil.disk_usage("/")
        return (
            "Disk Free: "
            f"free={_format_gib(disk.free):.2f}GiB / "
            f"total={_format_gib(disk.total):.2f}GiB"
        )

    def disk_usage(self, _children: list) -> str:
        try:
            partitions = psutil.disk_partitions()
            result = "Disk Usage (All Partitions):\n"
            for p in partitions:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    result += (
                        f"  {p.device:15s} @ {p.mountpoint:15s} | "
                        f"{usage.percent:5.1f}% | "
                        f"{_format_gib(usage.used):.1f}/{_format_gib(usage.total):.1f}GiB\n"
                    )
                except (OSError, PermissionError):
                    pass
            return result.strip()
        except Exception as e:
            return f"Disk Usage: Error - {e}"

    def disk_io(self, _children: list) -> str:
        try:
            io = psutil.disk_io_counters()
            return (
                "Disk I/O: "
                f"read_count={io.read_count}, write_count={io.write_count}, "
                f"read_bytes={_format_gib(io.read_bytes):.2f}GiB, "
                f"write_bytes={_format_gib(io.write_bytes):.2f}GiB"
            )
        except Exception as e:
            return f"Disk I/O: Error - {e}"

    def disk_top(self, _children: list) -> str:
        return _run_cmd(["du", "-sh", "/home", "/opt", "/var", "/usr"])

    def disk_inode(self, _children: list) -> str:
        """Show inode usage on root filesystem."""
        try:
            st = os.statvfs("/")
            total = st.f_files
            free = st.f_favail
            used = total - free
            pct = (used / total) * 100 if total else 0
            return f"Inodes: {used}/{total} used ({pct:.1f}%)"
        except Exception as e:
            return f"Disk Inode: Error - {e}"

    # ── GPU ──
    def gpu_util(self, _children: list) -> str:
        return _run_cmd([
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ])

    # ── Process ──
    def proc_list(self, _children: list) -> str:
        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "status"]):
                try:
                    processes.append((proc.info["pid"], proc.info["name"], proc.info["status"]))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            processes.sort(key=lambda x: x[0])
            result = f"Total Processes: {len(processes)}\n"
            result += "PID     | Name\n"
            result += "--------|----\n"
            for pid, name, _ in processes[:20]:
                result += f"{pid:7d} | {name[:30]:30s}\n"
            if len(processes) > 20:
                result += f"... and {len(processes) - 20} more"
            return result.strip()
        except Exception as e:
            return f"Process List: Error - {e}"

    def proc_kill(self, children: list) -> str:
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

    def proc_search(self, children: list) -> str:
        """Search for processes by name substring."""
        name = str(children[0]).lower()
        matches = []
        for proc in psutil.process_iter(["pid", "name", "status"]):
            try:
                if name in proc.info["name"].lower():
                    matches.append((proc.info["pid"], proc.info["name"], proc.info["status"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if not matches:
            return f"No processes found matching '{name}'"
        result = f"Processes matching '{name}':\n"
        for pid, pname, status in matches:
            result += f"  {pid:7d} | {pname:30s} | {status}\n"
        return result.strip()

    def proc_tree(self, _children: list) -> str:
        """Show process tree via ps auxf."""
        return _run_cmd(["ps", "auxf", "--sort=-%cpu"])

    def proc_info(self, children: list) -> str:
        """Show detailed info for a specific PID."""
        try:
            pid = int(children[0])
            p = psutil.Process(pid)
            with p.oneshot():
                mem = p.memory_info()
                return (
                    f"Process Info - PID {pid}\n"
                    f"  Name:         {p.name()}\n"
                    f"  Status:       {p.status()}\n"
                    f"  CPU %:        {p.cpu_percent():.1f}%\n"
                    f"  Memory RSS:   {mem.rss / 1024**2:.1f} MiB\n"
                    f"  Memory VMS:   {mem.vms / 1024**2:.1f} MiB\n"
                    f"  Threads:      {p.num_threads()}\n"
                    f"  Created:      {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(p.create_time()))}\n"
                    f"  Cmdline:      {' '.join(p.cmdline())}"
                )
        except psutil.NoSuchProcess:
            return f"Process Info: PID {pid} not found"
        except psutil.AccessDenied:
            return f"Process Info: Permission denied for PID {pid}"
        except Exception as e:
            return f"Process Info: Error - {e}"

    # ── Network ──
    def net_interfaces(self, _children: list) -> str:
        try:
            interfaces = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            result = "Network Interfaces:\n"
            for iface, stats in interfaces.items():
                status = "UP" if stats.isup else "DOWN"
                ips = ", ".join(a.address for a in addrs.get(iface, []) if a.family == socket.AF_INET)
                result += f"  {iface:10s} | {status:4s} | MTU: {stats.mtu:5d} | IP: {ips}\n"
            return result.strip()
        except Exception as e:
            return f"Net Interfaces: Error - {e}"

    def net_bandwidth(self, _children: list) -> str:
        try:
            net = psutil.net_io_counters()
            return (
                "Network Bandwidth:\n"
                f"  Sent: {_format_gib(net.bytes_sent):.2f} GiB ({net.packets_sent} packets)\n"
                f"  Recv: {_format_gib(net.bytes_recv):.2f} GiB ({net.packets_recv} packets)"
            )
        except Exception as e:
            return f"Net Bandwidth: Error - {e}"

    def net_connections(self, _children: list) -> str:
        try:
            conns = psutil.net_connections()
            established = sum(1 for c in conns if c.status == "ESTABLISHED")
            listening = sum(1 for c in conns if c.status == "LISTEN")
            return f"Network Connections: total={len(conns)}, established={established}, listening={listening}"
        except Exception as e:
            return f"Net Connections: Error - {e}"

    def net_ports(self, _children: list) -> str:
        """Show all listening TCP ports."""
        try:
            conns = psutil.net_connections(kind="tcp")
            ports = sorted({c.laddr.port for c in conns if c.status == "LISTEN"})
            if not ports:
                return "No listening TCP ports found"
            return f"Listening TCP ports ({len(ports)}):\n  " + ", ".join(map(str, ports[:30]))
        except Exception as e:
            return f"Net Ports: Error - {e}"

    def net_dns(self, children: list) -> str:
        """DNS lookup for a hostname."""
        host = str(children[0])
        try:
            ips = socket.gethostbyname_ex(host)
            return f"DNS lookup: {host}\n  Aliases: {', '.join(ips[1]) or 'none'}\n  Addresses: {', '.join(ips[2])}"
        except socket.gaierror as e:
            return f"DNS lookup: {host} - {e}"
        except Exception as e:
            return f"DNS lookup: Error - {e}"

    # ── System ──
    def system_uptime(self, _children: list) -> str:
        try:
            uptime_secs = int(time.time() - psutil.boot_time())
            days = uptime_secs // 86400
            hours = (uptime_secs % 86400) // 3600
            minutes = (uptime_secs % 3600) // 60
            return f"System Uptime: {days}d {hours}h {minutes}m"
        except Exception as e:
            return f"System Uptime: Error - {e}"

    def system_info(self, _children: list) -> str:
        try:
            uname = platform.uname()
            return (
                f"System Info:\n"
                f"  OS:        {uname.system} {uname.release}\n"
                f"  Version:   {uname.version}\n"
                f"  Hostname:  {uname.node}\n"
                f"  Arch:      {uname.machine}\n"
                f"  Processor: {uname.processor or 'Unknown'}"
            )
        except Exception as e:
            return f"System Info: Error - {e}"

    def system_processes(self, _children: list) -> str:
        try:
            total = len(psutil.pids())
            threads = sum(
                p.num_threads()
                for p in psutil.process_iter(["num_threads"])
                if p.num_threads() is not None
            )
            return f"System Processes: total={total}, threads={threads}"
        except Exception as e:
            return f"System Processes: Error - {e}"

    def system_users(self, _children: list) -> str:
        """List logged-in users."""
        try:
            users = psutil.users()
            if not users:
                return "No users logged in"
            result = "Logged-in Users:\n"
            for u in users:
                if u.host:
                    result += f"  {u.name:12s} | since {time.strftime('%H:%M', time.localtime(u.started))} | {u.host}\n"
                else:
                    result += f"  {u.name:12s} | since {time.strftime('%H:%M', time.localtime(u.started))}\n"
            return result.strip()
        except Exception as e:
            return f"System Users: Error - {e}"

    def system_load(self, _children: list) -> str:
        """Quick system load overview."""
        try:
            load_1, load_5, load_15 = os.getloadavg()
            cpu_pct = psutil.cpu_percent(interval=0.2)
            mem_pct = psutil.virtual_memory().percent
            return (
                f"System Load: load={load_1:.2f}/{load_5:.2f}/{load_15:.2f} | "
                f"CPU: {cpu_pct:.1f}% | RAM: {mem_pct:.1f}%"
            )
        except OSError:
            return "System Load: unavailable on this platform"

    # ── Sensors ──
    def sensor_temp(self, _children: list) -> str:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return "No temperature sensors detected"
            result = "Temperatures:\n"
            for name, entries in temps.items():
                for s in entries:
                    label = s.label or name
                    result += f"  {label:20s}: {s.current:5.1f}°C  (high={s.high or 'N/A'}, crit={s.critical or 'N/A'})\n"
            return result.strip()
        except AttributeError:
            return "Temperature sensors: not supported on this platform"
        except Exception as e:
            return f"Sensor Temp: Error - {e}"

    def sensor_fans(self, _children: list) -> str:
        try:
            fans = psutil.sensors_fans()
            if not fans:
                return "No fan sensors detected"
            result = "Fans:\n"
            for name, entries in fans.items():
                for s in entries:
                    result += f"  {s.label or name:20s}: {s.current} RPM\n"
            return result.strip()
        except AttributeError:
            return "Fan sensors: not supported on this platform"
        except Exception as e:
            return f"Sensor Fans: Error - {e}"

    def sensor_battery(self, _children: list) -> str:
        try:
            batt = psutil.sensors_battery()
            if not batt:
                return "No battery detected"
            status = "charging" if batt.power_plugged else "discharging"
            remaining = ""
            if batt.secsleft != -1 and not batt.power_plugged:
                remaining = f", {batt.secsleft // 60}min remaining"
            return f"Battery: {batt.percent:.0f}% ({status}{remaining})"
        except AttributeError:
            return "Battery sensor: not supported on this platform"
        except Exception as e:
            return f"Sensor Battery: Error - {e}"

    # ── Docker ──
    def docker_ps(self, _children: list) -> str:
        result = _run_cmd([
            "docker", "ps", "--format", "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"
        ])
        if "Command not found" in result:
            return "Docker: not available"
        return "Docker Containers:\n" + result

    def docker_stats(self, _children: list) -> str:
        result = _run_cmd([
            "docker", "stats", "--no-stream", "--format",
            "table {{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}\t{{.MemUsage}}"
        ])
        if "Command not found" in result:
            return "Docker: not available"
        return "Docker Stats:\n" + result

    # ── Service ──
    def service_list(self, _children: list) -> str:
        """List running systemd services."""
        return _run_cmd([
            "systemctl", "list-units", "--type=service", "--state=running",
            "--no-pager", "--no-legend"
        ])

    def service_status(self, children: list) -> str:
        """Check status of a specific service."""
        service = str(children[0])
        if not service.endswith(".service"):
            service += ".service"
        return _run_cmd(["systemctl", "status", service, "--no-pager", "--lines=10"])

    # ── Utility ──
    def cmd_clear(self, _children: list) -> str:
        """Sentinel — the dashboard intercepts this."""
        return "__CLEAR__"

    def cmd_help(self, _children: list) -> str:
        """Show brief usage summary."""
        return (
            "Available commands:\n\n"
            "  CPU:        cpu.util, cpu.load, cpu.cores, cpu.top, cpu.avg\n"
            "  Memory:     mem.util, mem.stats, mem.swap, mem.top, mem.cached\n"
            "  Disk:       disk.free, disk.usage, disk.io, disk.top, disk.inode\n"
            "  GPU:        gpu.util\n"
            "  Process:    proc.list, proc.kill <pid>, proc.search <name>, proc.tree, proc.info <pid>\n"
            "  Network:    net.interfaces, net.bandwidth, net.connections, net.ports, net.dns <host>\n"
            "  System:     system.uptime, system.info, system.processes, system.users, system.load\n"
            "  Sensors:    sensor.temp, sensor.fans, sensor.battery\n"
            "  Docker:     docker.ps, docker.stats\n"
            "  Services:   service.list, service.status <name>\n"
            "  Utility:    clear, help, rules, status, history, guide\n\n"
            "  Alerts:     <name>: alert <metric> <op> <val> -> <action>\n"
            "              stop [rule] <id_or_name>\n"
            "  Operators:  >, <, ==, >=, <=\n"
            "  Metrics:    cpu.util, mem.util, disk.free, sensor.temp ..."
        )

    def cmd_rules(self, _children: list) -> str:
        if not ACTIVE_RULES:
            return "No active rules."
        lines = [f"Active Rules ({len(ACTIVE_RULES)}):"]
        for r in ACTIVE_RULES:
            lines.append(f"  [{r.id}] {r.name}: alert {r.metric} {r.operator} {r.threshold} -> {r.action}")
        return "\n".join(lines)

    def cmd_status(self, _children: list) -> str:
        """Quick system status overview."""
        try:
            cpu = psutil.cpu_percent(interval=0.3)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            uptime_secs = int(time.time() - psutil.boot_time())
            days = uptime_secs // 86400
            hours = (uptime_secs % 86400) // 3600
            load_1, load_5, load_15 = os.getloadavg()
            return (
                f"System Status Overview\n"
                f"{'='*50}\n"
                f"  Uptime:   {days}d {hours}h\n"
                f"  Load:     {load_1:.2f} / {load_5:.2f} / {load_15:.2f}\n"
                f"  CPU:      {cpu:.1f}%\n"
                f"  RAM:      {mem.percent:.1f}% ({_format_gib(mem.used):.1f}/{_format_gib(mem.total):.1f} GiB)\n"
                f"  Disk:     {disk.percent:.1f}% ({_format_gib(disk.used):.1f}/{_format_gib(disk.total):.1f} GiB)\n"
                f"  Rules:    {len(ACTIVE_RULES)} active\n"
                f"  Procs:    {len(psutil.pids())}"
            )
        except Exception as e:
            return f"Status: Error - {e}"

    def cmd_history(self, _children: list) -> str:
        """History is managed by the dashboard (up/down arrows)."""
        return "History is managed by the dashboard (use up/down arrows)."

    def cmd_guide(self, _children: list) -> str:
        """Show the in-app guide."""
        from nano_logic.ui.guide import render_guide
        return render_guide()


# ──────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────

def parse_command(command_text: str):
    """Parse a DSL command and return its parse tree."""
    return parser.parse(command_text)


def execute_command(command_text: str) -> str | Rule | StopRule:
    """Parse and execute a DSL command.

    Returns a string for queries, or a Rule / StopRule for alert operations.
    """
    tree = parse_command(command_text)
    result = MetricsTransformer().transform(tree)
    if isinstance(result, Tree):
        return ""
    return result


if __name__ == "__main__":
    print("Nano-DSL Interactive Shell — type 'help' or 'exit'\n")
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
