"""Lightweight telemetry agent running on EC2 or remote nodes.

Collects local system metrics and AWS EC2 IMDSv2 metadata, and pushes
telemetry payloads periodically to a configured nano-dsl receiver.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import psutil

from nano_logic.logging_config import configure_logging

logger = configure_logging(__name__)

IMDS_TOKEN_URL = "http://169.254.169.254/latest/api/token"
IMDS_METADATA_BASE = "http://169.254.169.254/latest/meta-data"
IMDS_TIMEOUT = 1.0  # seconds


def _fetch_imds_token() -> str | None:
    """Acquire an IMDSv2 session token from AWS metadata service."""
    try:
        req = urllib.request.Request(
            IMDS_TOKEN_URL,
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=IMDS_TIMEOUT) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8").strip()
    except Exception:
        pass
    return None


def _fetch_imds_item(item_path: str, token: str) -> str | None:
    """Fetch an item from IMDSv2 using the session token."""
    try:
        url = f"{IMDS_METADATA_BASE}/{item_path}"
        req = urllib.request.Request(
            url,
            headers={"X-aws-ec2-metadata-token": token},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=IMDS_TIMEOUT) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8").strip()
    except Exception:
        pass
    return None


def collect_ec2_metadata() -> dict[str, Any]:
    """Probe AWS EC2 IMDSv2; fall back to local machine metadata if unreachable."""
    token = _fetch_imds_token()
    is_ec2 = token is not None

    hostname = socket.gethostname()
    boot_time = psutil.boot_time()
    uptime = time.time() - boot_time

    meta: dict[str, Any] = {
        "hostname": hostname,
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python_version": platform.python_version(),
        "cpu_count": psutil.cpu_count(logical=True),
        "uptime_seconds": round(uptime, 1),
        "is_ec2": is_ec2,
    }

    if is_ec2 and token:
        instance_id = _fetch_imds_item("instance-id", token)
        instance_type = _fetch_imds_item("instance-type", token)
        az = _fetch_imds_item("placement/availability-zone", token)
        public_ip = _fetch_imds_item("public-ipv4", token)
        local_ip = _fetch_imds_item("local-ipv4", token)

        if instance_id:
            meta["instance_id"] = instance_id
        if instance_type:
            meta["instance_type"] = instance_type
        if az:
            meta["availability_zone"] = az
            # Region is AZ minus the trailing letter (e.g. us-east-1a -> us-east-1)
            meta["region"] = az[:-1] if az and az[-1].isalpha() else az
        if public_ip:
            meta["public_ip"] = public_ip
        if local_ip:
            meta["local_ip"] = local_ip

    return meta


def collect_metrics() -> dict[str, float]:
    """Collect current system metrics snapshot via psutil."""
    metrics: dict[str, float] = {}

    # CPU
    metrics["cpu.util"] = float(psutil.cpu_percent(interval=None))
    if hasattr(os, "getloadavg"):
        loads = os.getloadavg()
        metrics["cpu.load1"] = float(loads[0])
        metrics["cpu.load5"] = float(loads[1])
        metrics["cpu.load15"] = float(loads[2])

    # Memory
    mem = psutil.virtual_memory()
    metrics["mem.util"] = float(mem.percent)
    metrics["mem.used"] = float(round(mem.used / (1024 ** 3), 2))
    metrics["mem.avail"] = float(round(mem.available / (1024 ** 3), 2))

    # Swap
    swap = psutil.swap_memory()
    metrics["swap.util"] = float(swap.percent)

    # Disk
    try:
        disk = psutil.disk_usage("/")
        metrics["disk.usage"] = float(disk.percent)
        metrics["disk.free"] = float(round(disk.free / (1024 ** 3), 2))
    except Exception:
        pass

    # Network IO
    try:
        net = psutil.net_io_counters()
        metrics["net.bytes_sent"] = float(net.bytes_sent)
        metrics["net.bytes_recv"] = float(net.bytes_recv)
    except Exception:
        pass

    return metrics


def build_payload(node_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Construct the full JSON telemetry payload."""
    if metadata is None:
        metadata = collect_ec2_metadata()

    resolved_id = node_id or metadata.get("instance_id") or metadata.get("hostname") or "unknown_node"
    node_type = "ec2" if metadata.get("is_ec2") else "agent"

    return {
        "node_id": resolved_id,
        "node_type": node_type,
        "timestamp": time.time(),
        "metrics": collect_metrics(),
        "metadata": metadata,
    }


def push_metrics(
    receiver_url: str,
    payload: dict[str, Any],
    auth_token: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """POST payload to receiver endpoint. Returns True on success, False on failure."""
    try:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "nano-dsl-agent/0.1.0",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
            headers["X-Nano-Token"] = auth_token

        req = urllib.request.Request(
            receiver_url,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        logger.warning("Failed to push metrics to %s: %s", receiver_url, e)
        return False
    except Exception as e:
        logger.exception("Unexpected error pushing metrics to %s: %s", receiver_url, e)
        return False


def run_agent(
    receiver_url: str,
    interval: float = 5.0,
    node_id: str | None = None,
    auth_token: str | None = None,
    oneshot: bool = False,
) -> None:
    """Main agent execution loop."""
    logger.info("Initializing nano-dsl agent (target: %s, interval: %.1fs)...", receiver_url, interval)
    metadata = collect_ec2_metadata()
    resolved_id = node_id or metadata.get("instance_id") or metadata.get("hostname") or "unknown_node"
    logger.info("Agent identified as '%s' (is_ec2=%s)", resolved_id, metadata.get("is_ec2", False))

    # Primer sample for psutil cpu_percent
    psutil.cpu_percent(interval=None)

    while True:
        payload = build_payload(node_id=resolved_id, metadata=metadata)
        ok = push_metrics(receiver_url, payload, auth_token=auth_token)
        if ok:
            logger.debug("Successfully pushed metrics for %s", resolved_id)
        else:
            logger.warning("Push failed for %s, will retry in %.1fs", resolved_id, interval)

        if oneshot:
            break

        time.sleep(interval)


def main() -> None:
    """CLI entrypoint for nano-agent."""
    import argparse

    parser = argparse.ArgumentParser(description="nano-dsl Telemetry Agent for EC2 and remote nodes")
    parser.add_argument(
        "--receiver-url",
        default=os.environ.get("NANO_RECEIVER_URL", "http://localhost:8080/metrics"),
        help="Target receiver endpoint URL (default: http://localhost:8080/metrics or $NANO_RECEIVER_URL)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("NANO_PUSH_INTERVAL", "5.0")),
        help="Push interval in seconds (default: 5.0 or $NANO_PUSH_INTERVAL)",
    )
    parser.add_argument(
        "--node-id",
        default=os.environ.get("NANO_NODE_ID", None),
        help="Explicit node/instance ID override (default: auto from IMDSv2 or hostname)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("NANO_AUTH_TOKEN", None),
        help="Optional auth bearer token (default: $NANO_AUTH_TOKEN)",
    )
    parser.add_argument(
        "--oneshot",
        action="store_true",
        help="Send a single metrics payload and exit",
    )
    args = parser.parse_args()

    print(f"🚀 Starting nano-agent -> {args.receiver_url} (interval={args.interval}s)")
    try:
        run_agent(
            receiver_url=args.receiver_url,
            interval=args.interval,
            node_id=args.node_id,
            auth_token=args.token,
            oneshot=args.oneshot,
        )
    except KeyboardInterrupt:
        print("\nAgent stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
