"""EC2 and Remote Node Plugin for nano-dsl.

Integrates with the Metrics Receiver to provide:
- DSL commands: ec2.list, ec2.metrics, ec2.info, ec2.server
- Probes for the alert engine: ec2.cpu.util, ec2.mem.util, ec2.disk.usage, ec2.nodes.online
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from nano_logic.plugins.base import PluginBase
from nano_logic.receiver import (
    GLOBAL_NODE_STORE,
    NodeStore,
    get_active_server,
    get_or_start_receiver,
)


def _format_ago(timestamp: float, now: float | None = None) -> str:
    if now is None:
        now = time.time()
    diff = max(0.0, now - timestamp)
    if diff < 60:
        return f"{int(diff)}s ago"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    return f"{int(diff // 3600)}h ago"


def _format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


class EC2Plugin(PluginBase):
    name = "ec2"
    description = "Monitor live metrics from remote EC2 instances and nodes"

    def __init__(self, store: NodeStore | None = None) -> None:
        self.store = store or GLOBAL_NODE_STORE

        self.command_handlers = {
            "ec2.list": self.handle_list,
            "ec2.metrics": self.handle_metrics,
            "ec2.info": self.handle_info,
            "ec2.server": self.handle_server,
        }

        self.probe_registry = {
            "ec2.cpu.util": lambda: self.store.get_metric("cpu.util"),
            "ec2.mem.util": lambda: self.store.get_metric("mem.util"),
            "ec2.disk.usage": lambda: self.store.get_metric("disk.usage"),
            "ec2.nodes.online": lambda: float(self.store.count_online()),
        }

        self.commands = []
        self.transformer_hooks = {}

    def register(self, app=None) -> None:
        """Start the background receiver when plugin is registered if not already running."""
        try:
            # Auto-start receiver in background thread on default port (8080)
            get_or_start_receiver(store=self.store)
        except Exception:
            pass

    def handle_list(self, *args) -> str:
        """Render a table of all reporting EC2 nodes."""
        if hasattr(self.store, "sync_from_receiver"):
            self.store.sync_from_receiver(force=True)
        nodes = self.store.list_nodes()
        if not nodes:
            server = get_active_server()
            port = server.port if server else int(os.environ.get("NANO_RECEIVER_PORT", "8080"))
            return (
                "No remote nodes reporting yet.\n"
                f"Receiver endpoint is active on http://0.0.0.0:{port}/metrics\n\n"
                "To report from an EC2 instance, run:\n"
                f"  nano-agent --receiver-url http://<YOUR_IP>:{port}/metrics"
            )

        lines = [
            f"{'NODE ID':<22} {'TYPE':<8} {'IP ADDRESS':<16} {'CPU%':<8} {'MEM%':<8} {'DISK%':<8} {'STATUS':<10} {'LAST SEEN'}",
            "-" * 95,
        ]

        now = time.time()
        for n in nodes:
            meta = n.get("metadata", {})
            metrics = n.get("metrics", {})
            status = self.store.get_node_status(n, now=now).upper()
            status_badge = "[ONLINE]" if status == "ONLINE" else f"[{status}]"

            ip = meta.get("public_ip") or meta.get("local_ip") or "-"
            cpu = f"{metrics.get('cpu.util', 0.0):.1f}%" if "cpu.util" in metrics else "-"
            mem = f"{metrics.get('mem.util', 0.0):.1f}%" if "mem.util" in metrics else "-"
            disk = f"{metrics.get('disk.usage', 0.0):.1f}%" if "disk.usage" in metrics else "-"
            last_seen_str = _format_ago(float(n.get("last_seen", now)), now=now)

            lines.append(
                f"{n['node_id']:<22} {n.get('node_type', 'ec2'):<8} {ip:<16} {cpu:<8} {mem:<8} {disk:<8} {status_badge:<10} {last_seen_str}"
            )

        online_count = self.store.count_online()
        lines.append("")
        lines.append(f"Total: {len(nodes)} node(s) | Online: {online_count}")
        return "\n".join(lines)

    def _resolve_target_node(self, children: tuple) -> dict[str, Any] | None:
        if hasattr(self.store, "sync_from_receiver"):
            self.store.sync_from_receiver(force=True)
        nodes = self.store.list_nodes()
        if not nodes:
            return None

        # If an explicit node_id was provided
        if children and str(children[0]).strip():
            target_id = str(children[0]).strip()
            node = self.store.get_node(target_id)
            if node:
                return node
            # Substring match if exact match fails
            for n in nodes:
                if target_id in n["node_id"]:
                    return n
            return None

        # Default to the most recently seen node
        return nodes[0]

    def handle_metrics(self, *children) -> str:
        """Render detailed live metrics for a node."""
        node = self._resolve_target_node(children)
        if not node:
            if children:
                return f"Error: Node '{children[0]}' not found. Run 'ec2.list' to see active nodes."
            return "No nodes reporting. Run 'ec2.list' or start 'nano-agent' on an EC2 instance."

        metrics = node.get("metrics", {})
        meta = node.get("metadata", {})
        now = time.time()
        status = self.store.get_node_status(node, now=now).upper()

        lines = [
            f"=== Live Metrics: {node['node_id']} [{status}] ===",
            f"Instance Type: {meta.get('instance_type', 'N/A')}  |  Region: {meta.get('region', meta.get('availability_zone', 'N/A'))}",
            f"Last Reported: {_format_ago(float(node.get('last_seen', now)), now=now)}",
            "",
            "CPU:",
            f"  Utilization:   {metrics.get('cpu.util', 0.0):.1f}%",
            f"  Load Average:  1m: {metrics.get('cpu.load1', 0.0):.2f} | 5m: {metrics.get('cpu.load5', 0.0):.2f} | 15m: {metrics.get('cpu.load15', 0.0):.2f}",
            "",
            "Memory:",
            f"  Utilization:   {metrics.get('mem.util', 0.0):.1f}%",
            f"  Used:          {metrics.get('mem.used', 0.0):.2f} GB",
            f"  Available:     {metrics.get('mem.avail', 0.0):.2f} GB",
            f"  Swap Util:     {metrics.get('swap.util', 0.0):.1f}%",
            "",
            "Disk & Network:",
            f"  Disk Usage:    {metrics.get('disk.usage', 0.0):.1f}%",
            f"  Disk Free:     {metrics.get('disk.free', 0.0):.2f} GB",
            f"  Bytes Sent:    {int(metrics.get('net.bytes_sent', 0)):,} bytes",
            f"  Bytes Recv:    {int(metrics.get('net.bytes_recv', 0)):,} bytes",
        ]
        return "\n".join(lines)

    def handle_info(self, *children) -> str:
        """Render metadata and configuration info for a node."""
        node = self._resolve_target_node(children)
        if not node:
            if children:
                return f"Error: Node '{children[0]}' not found. Run 'ec2.list' to see active nodes."
            return "No nodes reporting. Run 'ec2.list' or start 'nano-agent' on an EC2 instance."

        meta = node.get("metadata", {})
        now = time.time()
        status = self.store.get_node_status(node, now=now).upper()

        uptime_val = meta.get("uptime_seconds", 0.0)
        uptime_str = _format_uptime(float(uptime_val)) if uptime_val else "Unknown"
        first_seen_str = datetime.fromtimestamp(float(node.get("first_seen", now))).strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            f"=== Node Info: {node['node_id']} ===",
            f"Status:            {status}",
            f"Node Type:         {node.get('node_type', 'ec2')}",
            f"AWS Instance ID:   {meta.get('instance_id', 'N/A')}",
            f"AWS Instance Type: {meta.get('instance_type', 'N/A')}",
            f"Availability Zone: {meta.get('availability_zone', 'N/A')}",
            f"Region:            {meta.get('region', 'N/A')}",
            f"Public IPv4:       {meta.get('public_ip', 'None')}",
            f"Local IPv4:        {meta.get('local_ip', 'None')}",
            f"Hostname:          {meta.get('hostname', 'N/A')}",
            f"Platform:          {meta.get('platform', 'N/A')} {meta.get('platform_release', '')}",
            f"CPU Cores:         {meta.get('cpu_count', 'N/A')}",
            f"Uptime:            {uptime_str}",
            f"Connected Since:   {first_seen_str}",
        ]
        return "\n".join(lines)

    def handle_server(self, *children) -> str:
        """Inspect or manage the receiver server."""
        subcmd = str(children[0]).strip().lower() if children else "status"
        server = get_active_server()

        if subcmd == "start":
            if server and server.is_running:
                return f"Receiver is already running on http://{server.host}:{server.port}"
            server = get_or_start_receiver(store=self.store)
            return f"Started receiver on http://{server.host}:{server.port}"

        if subcmd == "stop":
            if server and server.is_running:
                server.shutdown()
                return "Receiver server stopped."
            return "Receiver server is not currently running."

        # Default: status
        if server and server.is_running:
            return (
                f"Receiver Server: RUNNING\n"
                f"Endpoint:        http://{server.host}:{server.port}/metrics\n"
                f"Nodes Online:    {self.store.count_online()} / {len(self.store.list_nodes())} total"
            )
        return "Receiver Server: STOPPED. Use 'ec2.server start' to activate."


# Discovery convention: expose the plugin class as Plugin
Plugin = EC2Plugin
