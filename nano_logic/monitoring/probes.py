"""System monitoring probes — low-level metric collectors.

All functions in this module should be pure data gatherers:
they read a metric and return it, no formatting or display logic.
"""
from __future__ import annotations
import os
import time
import socket
import subprocess
import psutil

# ──────────────────────────────────────────────
#  Original probes (used by dashboard panels)
# ──────────────────────────────────────────────

def get_disk_free_bytes(path: str = "/") -> tuple[int, int]:
    """Return (free_bytes, total_bytes) for the given mount point."""
    try:
        usage = psutil.disk_usage(path)
        return usage.free, usage.total
    except (OSError, PermissionError):
        return 0, 0


def get_disk_usage_percent(path: str = "/") -> float:
    """Return disk usage as a percentage for the given mount point."""
    try:
        return psutil.disk_usage(path).percent
    except (OSError, PermissionError):
        return 0.0


def get_net_totals_mib() -> tuple[float, float]:
    """Return (sent_mib, recv_mib) totals since boot."""
    try:
        net = psutil.net_io_counters()
        return net.bytes_sent / (1024 ** 2), net.bytes_recv / (1024 ** 2)
    except Exception:
        return 0.0, 0.0


# ──────────────────────────────────────────────
#  CPU probes
# ──────────────────────────────────────────────

def get_cpu_normalised_load() -> tuple[float, float, float]:
    """Return (load_1min_pct, load_5min_pct, load_15min_pct) normalised to core count."""
    try:
        load_1, load_5, load_15 = os.getloadavg()
        cores = max(1, psutil.cpu_count() or 1)
        return (
            (load_1 / cores) * 100,
            (load_5 / cores) * 100,
            (load_15 / cores) * 100,
        )
    except OSError:
        return 0.0, 0.0, 0.0


# ──────────────────────────────────────────────
#  Memory probes
# ──────────────────────────────────────────────

def get_memory_cached_bytes() -> int:
    """Return cached + buffers memory in bytes."""
    try:
        mem = psutil.virtual_memory()
        return getattr(mem, "cached", 0) + getattr(mem, "buffers", 0)
    except Exception:
        return 0


# ──────────────────────────────────────────────
#  Disk probes
# ──────────────────────────────────────────────

def get_disk_inode_usage(path: str = "/") -> tuple[int, int, float]:
    """Return (used_inodes, total_inodes, percent)."""
    try:
        st = os.statvfs(path)
        total = st.f_files
        free = st.f_favail
        used = total - free
        pct = (used / total) * 100 if total else 0.0
        return used, total, pct
    except Exception:
        return 0, 0, 0.0


def get_disk_io_counters() -> dict:
    """Return disk I/O counter dict, or empty dict on failure."""
    try:
        io = psutil.disk_io_counters()
        return {
            "read_count": io.read_count,
            "write_count": io.write_count,
            "read_bytes": io.read_bytes,
            "write_bytes": io.write_bytes,
        }
    except Exception:
        return {}


# ──────────────────────────────────────────────
#  Process probes
# ──────────────────────────────────────────────

def get_process_count() -> int:
    """Return total number of running processes."""
    try:
        return len(psutil.pids())
    except Exception:
        return 0


def get_all_processes() -> list[dict]:
    """Return {pid, name, status} for every running process."""
    processes = []
    for proc in psutil.process_iter(["pid", "name", "status"]):
        try:
            processes.append({
                "pid": proc.info["pid"],
                "name": proc.info["name"],
                "status": proc.info["status"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return processes


def get_top_processes_by_cpu(limit: int = 5) -> list[tuple[int, str, float]]:
    """Return the top `limit` processes by CPU percent, as (pid, name, cpu_percent)."""
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent"]):
        try:
            processes.append((proc.info["pid"], proc.info["name"], proc.cpu_percent()))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    processes.sort(key=lambda p: p[2], reverse=True)
    return processes[:limit]


def get_top_processes_by_memory(limit: int = 5) -> list[tuple[int, str, float]]:
    """Return the top `limit` processes by memory percent, as (pid, name, memory_percent)."""
    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            processes.append((proc.info["pid"], proc.info["name"], proc.memory_percent()))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    processes.sort(key=lambda p: p[2], reverse=True)
    return processes[:limit]


def get_process_by_name(name: str) -> list[dict]:
    """Search processes by name substring. Returns list of {pid, name, status}."""
    matches = []
    name_lower = name.lower()
    for proc in psutil.process_iter(["pid", "name", "status"]):
        try:
            if name_lower in proc.info["name"].lower():
                matches.append({
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "status": proc.info["status"],
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return matches


def get_process_info(pid: int) -> dict | None:
    """Return detailed info dict for a PID, or None if not found."""
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            mem = p.memory_info()
            return {
                "pid": pid,
                "name": p.name(),
                "status": p.status(),
                "cpu_percent": p.cpu_percent(),
                "memory_rss": mem.rss,
                "memory_vms": mem.vms,
                "threads": p.num_threads(),
                "created": p.create_time(),
                "cmdline": " ".join(p.cmdline()),
            }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


# ──────────────────────────────────────────────
#  Network probes
# ──────────────────────────────────────────────

def get_listening_ports() -> list[int]:
    """Return sorted list of TCP ports in LISTEN state."""
    try:
        conns = psutil.net_connections(kind="tcp")
        return sorted({c.laddr.port for c in conns if c.status == "LISTEN"})
    except (AttributeError, Exception):
        return []


def get_connection_counts() -> dict[str, int]:
    """Return dict of connection status -> count."""
    try:
        conns = psutil.net_connections()
        counts: dict[str, int] = {}
        for c in conns:
            counts[c.status] = counts.get(c.status, 0) + 1
        return counts
    except Exception:
        return {}


def dns_lookup(hostname: str) -> dict:
    """DNS lookup returning aliases and addresses."""
    try:
        aliases, addresses = socket.gethostbyname_ex(hostname)[1:]
        return {"hostname": hostname, "aliases": aliases, "addresses": addresses}
    except socket.gaierror as e:
        return {"hostname": hostname, "error": str(e)}


# ──────────────────────────────────────────────
#  Sensor probes
# ──────────────────────────────────────────────

def get_temperatures() -> dict[str, list[dict]]:
    """Return temperature sensor data: {sensor_name: [{label, current, high, critical}, ...]}."""
    try:
        raw = psutil.sensors_temperatures()
        result = {}
        for name, entries in raw.items():
            result[name] = [
                {
                    "label": s.label or name,
                    "current": s.current,
                    "high": s.high,
                    "critical": s.critical,
                }
                for s in entries
            ]
        return result
    except (AttributeError, Exception):
        return {}


def get_max_temperature() -> float | None:
    """Return the highest core temperature across all sensors, or None."""
    temps = get_temperatures()
    highest = None
    for entries in temps.values():
        for s in entries:
            if highest is None or s["current"] > highest:
                highest = s["current"]
    return highest


def get_fan_speeds() -> dict[str, list[dict]]:
    """Return fan sensor data: {sensor_name: [{label, rpm}, ...]}."""
    try:
        raw = psutil.sensors_fans()
        result = {}
        for name, entries in raw.items():
            result[name] = [{"label": s.label or name, "rpm": s.current} for s in entries]
        return result
    except (AttributeError, Exception):
        return {}


def get_battery() -> dict | None:
    """Return battery info dict, or None if no battery."""
    try:
        batt = psutil.sensors_battery()
        if not batt:
            return None
        return {
            "percent": batt.percent,
            "power_plugged": batt.power_plugged,
            "secsleft": batt.secsleft,
        }
    except (AttributeError, Exception):
        return None


# ──────────────────────────────────────────────
#  Docker probes (subprocess)
# ──────────────────────────────────────────────

def _run_cmd(cmd: list[str], timeout: int = 5) -> tuple[str, bool]:
    """Run a command, return (output, success_flag)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.returncode == 0
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}", False
    except subprocess.TimeoutExpired:
        return f"Timeout: {cmd[0]} did not respond", False
    except Exception as e:
        return f"Error: {e}", False


def get_docker_containers() -> list[dict] | None:
    """Return list of running containers, or None if docker unavailable."""
    output, ok = _run_cmd([
        "docker", "ps", "--format",
        "{{.ID}}|{{.Names}}|{{.Status}}|{{.Ports}}",
    ])
    if not ok:
        return None
    containers = []
    for line in output.split("\n"):
        if "|" in line:
            parts = line.split("|")
            containers.append({
                "id": parts[0],
                "name": parts[1],
                "status": parts[2],
                "ports": parts[3] if len(parts) > 3 else "",
            })
    return containers


def get_docker_stats() -> list[dict] | None:
    """Return live stats for running containers, or None if docker unavailable."""
    output, ok = _run_cmd([
        "docker", "stats", "--no-stream", "--format",
        "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}",
    ])
    if not ok:
        return None
    stats = []
    for line in output.split("\n"):
        if "|" in line:
            parts = line.split("|")
            stats.append({
                "name": parts[0],
                "cpu_perc": parts[1],
                "mem_perc": parts[2],
                "mem_usage": parts[3] if len(parts) > 3 else "",
            })
    return stats


# ──────────────────────────────────────────────
#  Service probes (systemctl)
# ──────────────────────────────────────────────

def get_running_services() -> list[dict] | None:
    """Return list of active systemd services, or None if systemctl unavailable."""
    output, ok = _run_cmd([
        "systemctl", "list-units", "--type=service", "--state=running",
        "--no-pager", "--no-legend", "--output=json",
    ])
    if not ok or not output:
        # Fallback: try tabular format
        output, ok = _run_cmd([
            "systemctl", "list-units", "--type=service", "--state=running",
            "--no-pager", "--no-legend",
        ])
        if not ok or not output:
            return None
        services = []
        for line in output.split("\n")[:30]:  # limit to 30
            parts = line.split(None, 4)
            if len(parts) >= 2:
                services.append({"name": parts[0], "status": parts[1] if len(parts) > 1 else ""})
        return services
    return None


def get_service_status(service_name: str) -> dict | None:
    """Return status info for a specific service, or None."""
    if not service_name.endswith(".service"):
        service_name += ".service"
    output, ok = _run_cmd([
        "systemctl", "status", service_name, "--no-pager", "--lines=5",
    ])
    if not ok:
        return None
    lines = output.split("\n")
    info: dict[str, str] = {"name": service_name, "raw": output[:500]}
    for line in lines:
        if "Loaded:" in line:
            info["loaded"] = line.strip()
        elif "Active:" in line:
            info["active"] = line.strip()
        elif "Main PID:" in line:
            info["pid"] = line.strip()
    return info


# ──────────────────────────────────────────────
#  System probes
# ──────────────────────────────────────────────

def get_logged_in_users() -> list[dict]:
    """Return list of logged-in users with name, terminal, host, started."""
    try:
        users = psutil.users()
        return [
            {
                "name": u.name,
                "terminal": u.terminal,
                "host": u.host,
                "started": u.started,
            }
            for u in users
        ]
    except Exception:
        return []


def get_system_load_summary() -> dict:
    """Return a dict with CPU %, RAM %, and load averages."""
    try:
        load_1, load_5, load_15 = os.getloadavg()
    except OSError:
        load_1 = load_5 = load_15 = 0.0
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "mem_percent": psutil.virtual_memory().percent,
        "load_1": load_1,
        "load_5": load_5,
        "load_15": load_15,
    }


# ──────────────────────────────────────────────
#  GPU probes
# ──────────────────────────────────────────────

def get_gpu_info() -> list[dict] | None:
    """Return list of GPU info dicts, or None if nvidia-smi unavailable."""
    output, ok = _run_cmd([
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ])
    if not ok:
        return None
    gpus = []
    for line in output.split("\n"):
        parts = [p.strip() for p in line.split(", ")]
        if len(parts) >= 4:
            gpus.append({
                "index": parts[0],
                "name": parts[1],
                "util_percent": parts[2],
                "mem_used_mb": parts[3],
                "mem_total_mb": parts[4],
                "temp_c": parts[5] if len(parts) > 5 else "N/A",
            })
    return gpus
