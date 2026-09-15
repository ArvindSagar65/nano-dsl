"""Lightweight HTTP server and REST API for the nano-dsl Web Dashboard.

Provides:
- Static file serving for the Portainer/Grafana-style Web UI.
- REST API endpoints for live metrics, active alert rules, Docker containers/images,
  and EC2/remote node telemetry.
- Zero external Python dependencies (built on standard library http.server).
"""
from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import psutil

from nano_logic.engine import ACTIVE_RULES, RULES_FILE, fetch_metric_value, load_rules
from nano_logic.logging_config import configure_logging
from nano_logic.monitoring.probes import (
    get_top_processes_by_cpu,
    get_top_processes_by_memory,
)
from nano_logic.paths import get_logs_dir
from nano_logic.plugins import docker_probe
from nano_logic.receiver import GLOBAL_NODE_STORE, NodeStore, get_or_start_receiver

logger = configure_logging(__name__)

WEB_DIR = Path(__file__).resolve().parent / "ui" / "web"

_BOOT_TIME = psutil.boot_time() if hasattr(psutil, "boot_time") else time.time()

# Warm the non-blocking CPU sampler so the first dashboard poll is not 0.0%.
psutil.cpu_percent(interval=None)
psutil.cpu_percent(interval=None, percpu=True)


class _TtlCache:
    """Tiny in-process TTL cache for expensive collectors (Docker CLI, sockets)."""

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = ttl_seconds
        self._value: Any = None
        self._expires_at = 0.0

    def get(self, factory):
        now = time.time()
        if self._value is not None and now < self._expires_at:
            return self._value
        self._value = factory()
        self._expires_at = now + self.ttl_seconds
        return self._value


_docker_cache = _TtlCache(4.0)
_conn_cache = _TtlCache(5.0)
_alert_log_cache = _TtlCache(3.0)
_rules_file_mtime = 0.0


def _reload_rules_if_changed() -> None:
    """Reload rules.json only when it actually changed on disk."""
    global _rules_file_mtime
    if not RULES_FILE.exists():
        return
    mtime = RULES_FILE.stat().st_mtime
    if mtime != _rules_file_mtime:
        load_rules()
        _rules_file_mtime = mtime


# ──────────────────────────────────────────────
#  Data Collector Functions
# ──────────────────────────────────────────────

def get_system_metrics_payload() -> dict[str, Any]:
    """Collect comprehensive local host metrics."""
    # CPU
    cpu_util = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    load_avg = list(os.getloadavg()) if hasattr(os, "getloadavg") else [0.0, 0.0, 0.0]

    # Memory
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Disk
    disk_usage = psutil.disk_usage("/")
    partitions: list[dict[str, Any]] = []
    try:
        for p in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(p.mountpoint)
                partitions.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "percent": usage.percent,
                })
            except (PermissionError, OSError):
                continue
    except Exception:
        pass

    # Disk IO
    disk_io = {}
    try:
        dio = psutil.disk_io_counters()
        if dio:
            disk_io = {
                "read_bytes": dio.read_bytes,
                "write_bytes": dio.write_bytes,
                "read_count": dio.read_count,
                "write_count": dio.write_count,
            }
    except Exception:
        pass

    # Network
    net_io = {}
    try:
        nio = psutil.net_io_counters()
        if nio:
            net_io = {
                "bytes_sent": nio.bytes_sent,
                "bytes_recv": nio.bytes_recv,
                "packets_sent": nio.packets_sent,
                "packets_recv": nio.packets_recv,
                "mib_sent": round(nio.bytes_sent / (1024 ** 2), 2),
                "mib_recv": round(nio.bytes_recv / (1024 ** 2), 2),
            }
    except Exception:
        pass

    def _count_connections() -> int:
        try:
            return len(psutil.net_connections())
        except Exception:
            return 0

    conns_count = _conn_cache.get(_count_connections)

    # Sensors (Temperature, Battery)
    temperatures: dict[str, list[dict[str, Any]]] = {}
    try:
        temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        if temps:
            for name, entries in temps.items():
                temperatures[name] = [
                    {"label": s.label or name, "current": s.current, "high": s.high, "critical": s.critical}
                    for s in entries
                ]
    except Exception:
        pass

    battery = None
    try:
        if hasattr(psutil, "sensors_battery"):
            batt = psutil.sensors_battery()
            if batt:
                battery = {
                    "percent": batt.percent,
                    "power_plugged": batt.power_plugged,
                    "secsleft": batt.secsleft if batt.secsleft != psutil.POWER_TIME_UNLIMITED else None,
                }
    except Exception:
        pass

    # Top processes
    top_cpu = []
    top_mem = []
    try:
        top_cpu = [
            {"pid": p[0], "name": p[1], "cpu_percent": round(p[2], 1)}
            for p in get_top_processes_by_cpu(limit=6)
        ]
        top_mem = [
            {"pid": p[0], "name": p[1], "mem_percent": round(p[2], 1)}
            for p in get_top_processes_by_memory(limit=6)
        ]
    except Exception:
        pass

    uptime_secs = max(0.0, time.time() - _BOOT_TIME)

    return {
        "timestamp": time.time(),
        "system": {
            "hostname": platform.node(),
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "cpu_count_logical": psutil.cpu_count(logical=True) or 1,
            "cpu_count_physical": psutil.cpu_count(logical=False) or 1,
            "uptime_seconds": round(uptime_secs, 1),
            "boot_time": _BOOT_TIME,
        },
        "cpu": {
            "util_percent": cpu_util,
            "per_core_percent": cpu_per_core,
            "load_1m": load_avg[0],
            "load_5m": load_avg[1],
            "load_15m": load_avg[2],
        },
        "memory": {
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "used_gb": round(vm.used / (1024 ** 3), 2),
            "available_gb": round(vm.available / (1024 ** 3), 2),
            "percent": vm.percent,
            "swap_total_gb": round(swap.total / (1024 ** 3), 2),
            "swap_used_gb": round(swap.used / (1024 ** 3), 2),
            "swap_percent": swap.percent,
        },
        "disk": {
            "root_usage_percent": disk_usage.percent,
            "root_total_gb": round(disk_usage.total / (1024 ** 3), 2),
            "root_free_gb": round(disk_usage.free / (1024 ** 3), 2),
            "partitions": partitions,
            "io": disk_io,
        },
        "network": {
            "io": net_io,
            "active_connections": conns_count,
        },
        "sensors": {
            "temperatures": temperatures,
            "battery": battery,
        },
        "processes": {
            "total_count": len(psutil.pids()),
            "top_cpu": top_cpu,
            "top_memory": top_mem,
        },
    }


def get_rules_payload() -> dict[str, Any]:
    """Collect active alert rules, their current evaluation status, and alert history."""
    _reload_rules_if_changed()
    rules_data = []
    ops = {
        ">": lambda v, t: v > t,
        "<": lambda v, t: v < t,
        "==": lambda v, t: v == t,
        ">=": lambda v, t: v >= t,
        "<=": lambda v, t: v <= t,
    }

    firing_count = 0
    for r in ACTIVE_RULES:
        val = fetch_metric_value(r.metric)
        op_fn = ops.get(r.operator)
        is_firing = False
        if val is not None and op_fn:
            try:
                is_firing = bool(op_fn(val, r.threshold))
            except Exception:
                is_firing = False

        if is_firing:
            firing_count += 1

        rules_data.append({
            "id": r.id,
            "name": r.name,
            "metric": r.metric,
            "operator": r.operator,
            "threshold": r.threshold,
            "action": r.action,
            "current_value": round(val, 2) if val is not None else None,
            "status": "alerting" if is_firing else "normal",
        })

    def _read_recent_alerts() -> list[dict[str, Any]]:
        logs: list[dict[str, Any]] = []
        logs_dir = get_logs_dir()
        if not logs_dir.exists():
            return logs
        for log_file in logs_dir.glob("*.log"):
            try:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            except OSError:
                continue
            for line in lines:
                if "[ALERT]" not in line:
                    continue
                logs.append({
                    "rule": log_file.stem,
                    "raw": line,
                    "timestamp": line[1:20] if line.startswith("[") and len(line) >= 20 else "",
                    "message": line.split("] ", 1)[-1] if "] " in line else line,
                })
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[:30]

    logs = _alert_log_cache.get(_read_recent_alerts)

    return {
        "rules": rules_data,
        "total_rules": len(rules_data),
        "firing_rules": firing_count,
        "recent_alerts": logs,
    }


def _collect_docker_payload() -> dict[str, Any]:
    """Uncached Docker collector — CLI/SDK round-trips are relatively slow."""
    installed = docker_probe.is_docker_installed()
    reachable = docker_probe.is_daemon_reachable() if installed else False

    containers_list = []
    stats_list = []
    images_list = []
    info_data = {}

    if reachable:
        containers_res = docker_probe.get_containers(include_all=True)
        if isinstance(containers_res, list):
            containers_list = containers_res

        stats_res = docker_probe.get_container_stats()
        if isinstance(stats_res, list):
            stats_list = stats_res

        images_res = docker_probe.get_images()
        if isinstance(images_res, list):
            images_list = images_res

        info_res = docker_probe.get_system_info()
        if isinstance(info_res, dict):
            info_data = info_res

    return {
        "docker_installed": installed,
        "daemon_reachable": reachable,
        "containers": containers_list,
        "containers_count": len(containers_list),
        "running_count": sum(1 for c in containers_list if c.get("state") == "running" or "Up" in c.get("status", "")),
        "container_stats": stats_list,
        "images": images_list,
        "images_count": len(images_list),
        "system_info": info_data,
    }


def get_docker_payload() -> dict[str, Any]:
    """Collect Docker daemon state, with a short TTL so the UI can poll often."""
    return _docker_cache.get(_collect_docker_payload)


def get_nodes_payload(store: NodeStore | None = None) -> dict[str, Any]:
    """Collect EC2 and remote node telemetry from the NodeStore."""
    ns = store or GLOBAL_NODE_STORE
    nodes = ns.list_nodes()
    now = time.time()

    enriched_nodes = []
    online_count = 0
    stale_count = 0
    offline_count = 0

    for n in nodes:
        status = ns.get_node_status(n, now=now)
        if status == "online":
            online_count += 1
        elif status == "stale":
            stale_count += 1
        else:
            offline_count += 1

        last_seen = float(n.get("last_seen", 0.0))
        enriched_nodes.append({
            "node_id": n.get("node_id"),
            "node_type": n.get("node_type", "ec2"),
            "status": status,
            "last_seen_seconds_ago": round(max(0.0, now - last_seen), 1),
            "last_seen": last_seen,
            "first_seen": n.get("first_seen"),
            "metadata": n.get("metadata", {}),
            "metrics": n.get("metrics", {}),
        })

    return {
        "nodes": enriched_nodes,
        "total_nodes": len(enriched_nodes),
        "online_nodes": online_count,
        "stale_nodes": stale_count,
        "offline_nodes": offline_count,
    }


def get_overview_payload(store: NodeStore | None = None) -> dict[str, Any]:
    """Cheap KPI snapshot. Avoids process/top scans used by the full metrics API."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    rules_info = get_rules_payload()
    docker_info = get_docker_payload()
    nodes_info = get_nodes_payload(store)

    return {
        "timestamp": time.time(),
        "system": {
            "hostname": platform.node(),
            "uptime_seconds": round(max(0.0, time.time() - _BOOT_TIME), 1),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": vm.percent,
            "disk_percent": disk.percent,
            "process_count": len(psutil.pids()),
        },
        "docker": {
            "reachable": docker_info["daemon_reachable"],
            "containers_total": docker_info["containers_count"],
            "containers_running": docker_info["running_count"],
            "images_total": docker_info["images_count"],
        },
        "nodes": {
            "total": nodes_info["total_nodes"],
            "online": nodes_info["online_nodes"],
        },
        "rules": {
            "total": rules_info["total_rules"],
            "firing": rules_info["firing_rules"],
        },
    }


# ──────────────────────────────────────────────
#  HTTP Request Handler
# ──────────────────────────────────────────────

class WebDashboardHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler serving REST API endpoints and dashboard static files."""

    node_store: NodeStore = GLOBAL_NODE_STORE

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[1]) >= "400":
            logger.warning(format, *args)

    def _send_json(self, status_code: int, data: Any) -> None:
        body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._send_json(404, {"error": f"File not found: {file_path.name}"})
            return

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except OSError as e:
            self._send_json(500, {"error": f"Could not read file: {e}"})

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:
        clean_path = self.path.split("?")[0]

        # Health
        if clean_path in ("/health", "/api/health"):
            self._send_json(200, {"status": "ok", "service": "nano-web-dashboard", "timestamp": time.time()})
            return

        # API Endpoints
        if clean_path in ("/api/v1/overview", "/api/overview"):
            self._send_json(200, get_overview_payload(self.node_store))
            return

        if clean_path in ("/api/v1/metrics", "/api/metrics"):
            self._send_json(200, get_system_metrics_payload())
            return

        if clean_path in ("/api/v1/rules", "/api/rules"):
            self._send_json(200, get_rules_payload())
            return

        if clean_path in ("/api/v1/docker", "/api/docker"):
            self._send_json(200, get_docker_payload())
            return

        if clean_path in ("/api/v1/nodes", "/api/nodes", "/api/v1/ec2", "/api/ec2"):
            self._send_json(200, get_nodes_payload(self.node_store))
            return

        # Static Assets & Web UI
        if clean_path in ("/", "/index.html"):
            index_path = WEB_DIR / "index.html"
            self._send_file(index_path, "text/html; charset=utf-8")
            return

        if clean_path in ("/dashboard.css", "/static/dashboard.css"):
            self._send_file(WEB_DIR / "dashboard.css", "text/css; charset=utf-8")
            return

        if clean_path in ("/dashboard.js", "/static/dashboard.js"):
            self._send_file(WEB_DIR / "dashboard.js", "application/javascript; charset=utf-8")
            return

        # Try relative file inside WEB_DIR
        relative_path = clean_path.lstrip("/")
        if relative_path.startswith("static/"):
            relative_path = relative_path[len("static/"):]

        candidate = (WEB_DIR / relative_path).resolve()
        # Security: protect against directory traversal
        if WEB_DIR.resolve() in candidate.parents and candidate.is_file():
            ext = candidate.suffix.lower()
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json",
                ".png": "image/png",
                ".svg": "image/svg+xml",
                ".ico": "image/x-icon",
            }.get(ext, "application/octet-stream")
            self._send_file(candidate, content_type)
            return

        self._send_json(404, {"error": f"Endpoint or static asset '{clean_path}' not found"})


# ──────────────────────────────────────────────
#  Server Lifecycle Management
# ──────────────────────────────────────────────

class WebServer:
    """Manages the background execution and lifecycle of the nano-dsl Web Dashboard."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        store: NodeStore | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.store = store or GLOBAL_NODE_STORE

        class ConfiguredHandler(WebDashboardHTTPHandler):
            pass

        ConfiguredHandler.node_store = self.store

        class ReusableThreadingServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = ReusableThreadingServer((self.host, self.port), ConfiguredHandler)
        self._thread: threading.Thread | None = None
        self._is_running = False

    def start_background(self) -> None:
        """Start the web server in a daemon background thread."""
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Web Dashboard listening on http://%s:%s", self.host, self.port)

    def shutdown(self) -> None:
        """Stop and terminate the web server."""
        if not self._is_running:
            return
        self._server.shutdown()
        self._server.server_close()
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Web Dashboard stopped")

    @property
    def is_running(self) -> bool:
        return self._is_running


_ACTIVE_WEB_SERVER: WebServer | None = None


def get_or_start_web_server(
    host: str = "0.0.0.0",
    port: int = 5000,
    store: NodeStore | None = None,
) -> WebServer:
    """Get the running web server instance or start one in the background."""
    global _ACTIVE_WEB_SERVER
    if _ACTIVE_WEB_SERVER is None or not _ACTIVE_WEB_SERVER.is_running:
        _ACTIVE_WEB_SERVER = WebServer(host=host, port=port, store=store)
        _ACTIVE_WEB_SERVER.start_background()
    return _ACTIVE_WEB_SERVER


def get_active_web_server() -> WebServer | None:
    return _ACTIVE_WEB_SERVER


def main() -> None:
    """CLI entrypoint to launch the nano-dsl Web Dashboard server."""
    import argparse

    parser = argparse.ArgumentParser(description="nano-dsl Web Observability Dashboard")
    parser.add_argument("--host", default=os.environ.get("NANO_WEB_HOST", "0.0.0.0"), help="Bind host (default: 0.0.0.0)")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("NANO_WEB_PORT", "5000")),
        help="Listen port (default: 5000)",
    )
    parser.add_argument(
        "--with-receiver",
        action="store_true",
        help="Also auto-start the metrics telemetry receiver on port 8080 if not running",
    )
    args = parser.parse_args()

    if args.with_receiver:
        get_or_start_receiver()
        print("Telemetry receiver active on http://0.0.0.0:8080/metrics")

    try:
        server = WebServer(host=args.host, port=args.port)
    except OSError as err:
        if getattr(err, "errno", None) in (98, 10048) or "address already in use" in str(err).lower():
            print(f"Error: Port {args.port} is already in use.", file=sys.stderr)
            print(f"Try: python -m nano_logic.web --port {args.port + 50}", file=sys.stderr)
            sys.exit(1)
        raise

    url_host = "localhost" if args.host == "0.0.0.0" else args.host
    print("=" * 64)
    print("  nano-dsl Web Observability Dashboard")
    print(f"  URL: http://{url_host}:{args.port}")
    print("  TUI commands still run via 'nano-dsl'")
    print("=" * 64)
    print("Press Ctrl+C to stop.")

    try:
        server._server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web dashboard...")
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
