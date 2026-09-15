"""Isolated Docker integration layer.

All Docker-specific logic lives here so it can later be promoted into a
full plugin (nano_logic/plugins/docker_plugin.py) with minimal refactoring:
the DSL transformer only calls the report functions at the bottom.

Strategy:
  1. Prefer the Python Docker SDK (`docker` package) when installed.
  2. Fall back to the `docker` CLI via subprocess otherwise.
  3. Never raise: every public entry point returns a user-facing string,
     with graceful fallbacks like "Docker: not available".

Read-only command families: ps, stats, info, images, containers (all),
logs, networks, volumes.
"""
from __future__ import annotations

import shutil
import subprocess

DOCKER_BIN = "docker"
_CMD_TIMEOUT = 10  # seconds; docker stats --no-stream can be slow on busy hosts

NOT_AVAILABLE = "Docker: not available"
DAEMON_UNREACHABLE = "Docker: daemon not reachable"

# Substrings in the CLI's stderr that indicate a daemon/socket problem
# rather than a genuine command failure.
_DAEMON_ERROR_MARKERS = (
    "cannot connect",
    "is the docker daemon",
    "permission denied while trying to connect",
    "no such file or directory",  # missing /var/run/docker.sock
)


# ──────────────────────────────────────────────
#  Availability checks
# ──────────────────────────────────────────────

def is_docker_installed() -> bool:
    """True if the docker CLI binary exists on PATH (or SDK is importable)."""
    if shutil.which(DOCKER_BIN):
        return True
    try:
        import docker  # noqa: F401 — SDK-only installs are still usable
        return True
    except ImportError:
        return False


def _sdk_client():
    """Return a Docker SDK client, or None if the SDK is missing/unusable."""
    try:
        import docker
        return docker.from_env(timeout=_CMD_TIMEOUT)
    except Exception:
        return None


def is_daemon_reachable() -> bool:
    """True if the Docker daemon answers a cheap round-trip."""
    client = _sdk_client()
    if client is not None:
        try:
            return bool(client.ping())
        except Exception:
            return False
    _, returncode, _ = _run_cli(["info", "--format", "{{.ServerVersion}}"])
    return returncode == 0


# ──────────────────────────────────────────────
#  Data gatherers — list[dict] | str
#  A string return is a friendly failure message, never an exception.
# ──────────────────────────────────────────────

def get_containers(include_all: bool = False) -> list[dict] | str:
    """Containers (running only by default, all if include_all)."""
    client = _sdk_client()
    if client is not None:
        try:
            return [_sdk_container_row(c)
                    for c in client.containers.list(all=include_all)]
        except Exception:
            pass  # fall through to the CLI before giving up
    ps_args = ["ps", "-a"] if include_all else ["ps"]
    output, returncode, stderr = _run_cli([
        *ps_args, "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}",
    ])
    failure = _classify_cli_failure(returncode, stderr)
    if failure is not None:
        return failure
    rows = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) >= 4:
            rows.append({
                "id": parts[0],
                "name": parts[1],
                "image": parts[2],
                "status": parts[3],
                "ports": parts[4] if len(parts) > 4 else "",
            })
    return rows


def get_container_stats() -> list[dict] | str:
    """Per-container stats, a friendly error string on failure."""
    client = _sdk_client()
    if client is not None:
        try:
            return [_sdk_stat_row(c) for c in client.containers.list()]
        except Exception:
            pass  # fall through to the CLI before giving up
    output, returncode, stderr = _run_cli([
        "stats", "--no-stream", "--format",
        "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}",
    ])
    failure = _classify_cli_failure(returncode, stderr)
    if failure is not None:
        return failure
    rows = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) >= 4:
            rows.append({
                "name": parts[0],
                "cpu_perc": parts[1],
                "mem_perc": parts[2],
                "mem_usage": parts[3],
            })
    return rows


def get_system_info() -> dict | str:
    """Daemon/system info as a flat dict, a friendly error string on failure."""
    client = _sdk_client()
    if client is not None:
        try:
            version = client.version()
            info = client.info()
            return {
                "server_version": version.get("Version", "?"),
                "api_version": version.get("ApiVersion", "?"),
                "os": info.get("OperatingSystem") or info.get("Name", "?"),
                "cpus": info.get("NCPU", 0),
                "mem_total": int(info.get("MemTotal", 0)),
                "driver": info.get("Driver", "?"),
                "images": info.get("Images", 0),
                "running": info.get("ContainersRunning", 0),
                "paused": info.get("ContainersPaused", 0),
                "stopped": info.get("ContainersStopped", 0),
            }
        except Exception:
            pass  # fall through to the CLI before giving up
    output, returncode, stderr = _run_cli([
        "info", "--format",
        "{{.ServerVersion}}|{{.OperatingSystem}}|{{.NCPU}}|{{.MemTotal}}"
        "|{{.Driver}}|{{.Images}}|{{.ContainersRunning}}"
        "|{{.ContainersPaused}}|{{.ContainersStopped}}",
    ])
    failure = _classify_cli_failure(returncode, stderr)
    if failure is not None:
        return failure
    parts = output.split("|")
    if len(parts) < 9:
        return f"Docker Info: unexpected CLI output: {output[:80]!r}"
    try:
        return {
            "server_version": parts[0],
            "api_version": "",
            "os": parts[1],
            "cpus": int(float(parts[2])),
            "mem_total": int(parts[3]),
            "driver": parts[4],
            "images": int(parts[5]),
            "running": int(parts[6]),
            "paused": int(parts[7]),
            "stopped": int(parts[8]),
        }
    except ValueError:
        return f"Docker Info: could not parse CLI output: {output[:80]!r}"


def get_images() -> list[dict] | str:
    """Stored images, a friendly error string on failure."""
    client = _sdk_client()
    if client is not None:
        try:
            rows = []
            for img in client.images.list():
                tags = getattr(img, "tags", None) or ["<none>:<none>"]
                repo, _, tag = tags[0].partition(":")
                rows.append({
                    "repository": repo or "<none>",
                    "tag": tag or "<none>",
                    "id": getattr(img, "short_id", "").replace("sha256:", ""),
                    "size": _fmt_bytes(int(img.attrs.get("Size", 0))),
                })
            return rows
        except Exception:
            pass  # fall through to the CLI before giving up
    output, returncode, stderr = _run_cli([
        "images", "--format", "{{.Repository}}|{{.Tag}}|{{.ID}}|{{.Size}}",
    ])
    failure = _classify_cli_failure(returncode, stderr)
    if failure is not None:
        return failure
    return [
        {"repository": p[0], "tag": p[1], "id": p[2],
         "size": p[3] if len(p) > 3 else ""}
        for line in output.splitlines()
        if len(p := line.split("|")) >= 3
    ]


def get_networks() -> list[dict] | str:
    """Docker networks, a friendly error string on failure."""
    client = _sdk_client()
    if client is not None:
        try:
            return [{
                "name": n.name,
                "driver": n.attrs.get("Driver", "?"),
                "scope": n.attrs.get("Scope", "?"),
            } for n in client.networks.list()]
        except Exception:
            pass  # fall through to the CLI before giving up
    output, returncode, stderr = _run_cli([
        "network", "ls", "--format", "{{.Name}}|{{.Driver}}|{{.Scope}}",
    ])
    failure = _classify_cli_failure(returncode, stderr)
    if failure is not None:
        return failure
    return [
        {"name": p[0], "driver": p[1], "scope": p[2] if len(p) > 2 else ""}
        for line in output.splitlines()
        if len(p := line.split("|")) >= 2
    ]


def get_volumes() -> list[dict] | str:
    """Docker volumes, a friendly error string on failure."""
    client = _sdk_client()
    if client is not None:
        try:
            return [{
                "name": v.name,
                "driver": v.attrs.get("Driver", "?"),
            } for v in client.volumes.list()]
        except Exception:
            pass  # fall through to the CLI before giving up
    output, returncode, stderr = _run_cli([
        "volume", "ls", "--format", "{{.Name}}|{{.Driver}}",
    ])
    failure = _classify_cli_failure(returncode, stderr)
    if failure is not None:
        return failure
    return [
        {"name": p[0], "driver": p[1] if len(p) > 1 else ""}
        for line in output.splitlines()
        if line and (p := line.split("|"))
    ]


def get_container_logs(name: str, tail: int = 50) -> str:
    """Last `tail` lines of a container's logs, or a friendly error string.

    Note: `docker logs` writes the container's own stderr stream to the
    CLI's stderr even on success, so streams are combined when rc == 0.
    """
    client = _sdk_client()
    if client is not None:
        try:
            container = client.containers.get(name)
            text = container.logs(tail=tail).decode("utf-8", errors="replace")
            return text.strip() or f"Docker Logs '{name}': no log output"
        except Exception:
            pass  # fall through to the CLI for precise error classification
    output, returncode, stderr = _run_cli(["logs", "--tail", str(tail), name])
    lowered = stderr.lower()
    if any(marker in lowered for marker in ("no such object", "no such container")):
        return f"Docker Logs: no such container '{name}'"
    failure = _classify_cli_failure(returncode, stderr)
    if failure is not None:
        return failure
    combined = "\n".join(s for s in (output, stderr) if s)
    return combined or f"Docker Logs '{name}': no log output"


def _sdk_container_row(container) -> dict:
    ports_attr = container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
    bindings = []
    for container_port, hosts in ports_attr.items():
        if hosts:
            for h in hosts:
                bindings.append(f"{h.get('HostIp', '')}:{h.get('HostPort', '')}->{container_port}")
        else:
            bindings.append(container_port)
    return {
        "id": getattr(container, "short_id", "") or "",
        "name": container.name,
        "image": getattr(getattr(container, "image", None), "tags", [""])[0]
        if getattr(getattr(container, "image", None), "tags", None) else "",
        "status": getattr(container, "status", "") or "",
        "ports": ", ".join(bindings),
    }


def _sdk_stat_row(container) -> dict:
    raw = container.stats(stream=False)
    cpu = _cpu_percent(raw)
    used, limit = _mem_usage(raw)
    mem_pct = (used / limit * 100) if limit else 0.0
    return {
        "name": container.name,
        "cpu_perc": f"{cpu:.2f}%",
        "mem_perc": f"{mem_pct:.2f}%",
        "mem_usage": f"{_fmt_bytes(used)} / {_fmt_bytes(limit)}",
    }


def _cpu_percent(stats: dict) -> float:
    """CPU % using the same formula as `docker stats`."""
    try:
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"].get("system_cpu_usage", 0)
            - stats["precpu_stats"].get("system_cpu_usage", 0)
        )
        online_cpus = stats["cpu_stats"].get("online_cpus") or len(
            stats["cpu_stats"]["cpu_usage"].get("percpu_usage") or []
        ) or 1
        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * online_cpus * 100
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return 0.0


def _mem_usage(stats: dict) -> tuple[int, int]:
    try:
        mem = stats.get("memory_stats", {}) or {}
        cache = mem.get("stats", {}).get("cache") or mem.get("stats", {}).get("inactive_file") or 0
        return max(0, int(mem.get("usage", 0)) - int(cache)), int(mem.get("limit", 0))
    except (TypeError, ValueError):
        return 0, 0


def _fmt_bytes(num_bytes: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TiB"


# ──────────────────────────────────────────────
#  CLI plumbing
# ──────────────────────────────────────────────

def _run_cli(args: list[str], timeout: int = _CMD_TIMEOUT) -> tuple[str, int, str]:
    """Run `docker <args>`, returning (stdout, returncode, stderr). Never raises."""
    cmd = [DOCKER_BIN, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.stdout.strip(), proc.returncode, proc.stderr.strip()
    except FileNotFoundError:
        return "", 127, f"{DOCKER_BIN}: binary not found"
    except subprocess.TimeoutExpired:
        return "", 124, f"{DOCKER_BIN}: timed out after {timeout}s"
    except OSError as e:
        return "", 126, str(e)


def _classify_cli_failure(returncode: int, stderr: str) -> str | None:
    """Map a CLI failure to NOT_AVAILABLE / DAEMON_UNREACHABLE / None(=success)."""
    if returncode == 0:
        return None
    lowered = stderr.lower()
    if returncode == 127 or "binary not found" in lowered:
        return NOT_AVAILABLE
    if any(marker in lowered for marker in _DAEMON_ERROR_MARKERS):
        return DAEMON_UNREACHABLE
    return f"Docker: error - {stderr[:120]}" if stderr else f"Docker: error (exit {returncode})"


# ──────────────────────────────────────────────
#  Formatting helpers (pure — easy to unit-test)
# ──────────────────────────────────────────────

def format_containers(rows: list[dict], title: str = "Docker Containers",
                      empty: str = "Docker Containers: none running") -> str:
    if not rows:
        return empty
    header = f"  {'NAME':22s} | {'IMAGE':28s} | {'STATUS':22s} | PORTS"
    lines = [f"{title} ({len(rows)}):", header, "  " + "-" * len(header.strip())]
    for r in rows:
        lines.append(
            f"  {r['name'][:22]:22s} | {r['image'][:28]:28s} | "
            f"{r['status'][:22]:22s} | {r['ports']}"
        )
    return "\n".join(lines)


def format_stats(rows: list[dict]) -> str:
    if not rows:
        return "Docker Stats: no running containers"
    header = f"  {'NAME':22s} | {'CPU %':>8s} | {'MEM %':>8s} | MEM USAGE"
    lines = [f"Docker Stats ({len(rows)}):", header, "  " + "-" * len(header.strip())]
    for r in rows:
        lines.append(
            f"  {r['name'][:22]:22s} | {r['cpu_perc']:>8s} | "
            f"{r['mem_perc']:>8s} | {r['mem_usage']}"
        )
    return "\n".join(lines)


def _table(title: str, headers: list[str], rows: list[list[str]], caps: list[int] | None = None) -> str:
    """Render an aligned `title (N):` table. caps[i] limits column i's width."""
    if not rows:
        return f"{title}: none found"
    widths = []
    for i, h in enumerate(headers):
        cap = caps[i] if caps and i < len(caps) else 40
        cell_max = max((len(r[i]) for r in rows if i < len(r)), default=0)
        widths.append(min(max(len(h), cell_max), max(len(h), cap)))
    lines = [f"{title} ({len(rows)}):",
             "  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)),
             "  " + "-" * (sum(widths) + 2 * (len(headers) - 1))]
    for r in rows:
        lines.append("  " + "  ".join(
            (r[i][:widths[i]] if i < len(r) else "").ljust(widths[i])
            for i in range(len(headers))
        ))
    return "\n".join(lines)


def format_info(info: dict) -> str:
    containers_bit = (
        f"{info.get('running', 0)} running"
        + (f", {info['paused']} paused" if info.get("paused") else "")
        + (f", {info['stopped']} stopped" if info.get("stopped") else "")
    )
    api = f"\n  API version:   {info['api_version']}" if info.get("api_version") else ""
    return (
        "Docker Info:\n"
        f"  Server version: {info.get('server_version', '?')}{api}\n"
        f"  OS:            {info.get('os', '?')}\n"
        f"  CPUs:          {info.get('cpus', '?')}\n"
        f"  Total memory:  {_fmt_bytes(int(info.get('mem_total', 0)))}\n"
        f"  Storage driver: {info.get('driver', '?')}\n"
        f"  Images:        {info.get('images', 0)}\n"
        f"  Containers:    {containers_bit}"
    )


# ──────────────────────────────────────────────
#  Public API — the only surface the DSL touches
# ──────────────────────────────────────────────

def docker_ps_report() -> str:
    """User-facing result of `docker.ps`."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    result = get_containers()
    return result if isinstance(result, str) else format_containers(result)


def docker_stats_report() -> str:
    """User-facing result of `docker.stats`."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    result = get_container_stats()
    return result if isinstance(result, str) else format_stats(result)


def docker_info_report() -> str:
    """User-facing result of `docker.info`."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    result = get_system_info()
    return result if isinstance(result, str) else format_info(result)


def docker_images_report() -> str:
    """User-facing result of `docker.images`."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    result = get_images()
    if isinstance(result, str):
        return result
    return _table("Docker Images",
                  ["REPOSITORY", "TAG", "ID", "SIZE"],
                  [[r["repository"], r["tag"], r["id"], r["size"]] for r in result])


def docker_containers_report() -> str:
    """User-facing result of `docker.containers` — every container, stopped too."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    result = get_containers(include_all=True)
    return (result if isinstance(result, str)
            else format_containers(result, title="Docker Containers (all)",
                                   empty="Docker Containers (all): none found"))


def docker_logs_report(name: str) -> str:
    """User-facing result of `docker.logs <name>`."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    logs = get_container_logs(name)
    if logs.startswith(("Docker Logs", "Docker:", "Docker ")):
        return logs
    return f"Docker Logs '{name}' (last 50 lines):\n{logs}"


def docker_networks_report() -> str:
    """User-facing result of `docker.networks`."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    result = get_networks()
    if isinstance(result, str):
        return result
    return _table("Docker Networks",
                  ["NAME", "DRIVER", "SCOPE"],
                  [[r["name"], r["driver"], r["scope"]] for r in result])


def docker_volumes_report() -> str:
    """User-facing result of `docker.volumes`."""
    if not is_docker_installed():
        return NOT_AVAILABLE
    result = get_volumes()
    if isinstance(result, str):
        return result
    return _table("Docker Volumes",
                  ["NAME", "DRIVER"],
                  [[r["name"], r["driver"]] for r in result],
                  caps=[40, 20])
