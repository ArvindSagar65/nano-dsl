"""HTTP Receiver and NodeStore for ingesting telemetry from remote nodes.

Provides an HTTP ingestion endpoint for EC2 and other remote agent nodes
pushing live metric snapshots, and maintains a thread-safe registry
queryable by the DSL and alert engine.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from nano_logic.logging_config import configure_logging

logger = configure_logging(__name__)

# Node freshness thresholds (seconds)
ONLINE_THRESHOLD = 30.0
STALE_THRESHOLD = 120.0


class NodeStore:
    """Thread-safe storage of reported metrics and metadata for all connected nodes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, dict[str, Any]] = {}

    def update_node(self, payload: dict[str, Any]) -> str:
        """Ingest a metrics payload. Returns the resolved node_id."""
        metadata = payload.get("metadata", {})
        node_id = (
            str(payload.get("node_id") or metadata.get("instance_id") or metadata.get("hostname") or "unknown")
            .strip()
        )
        if not node_id:
            node_id = "unknown"

        metrics = payload.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}

        now = time.time()
        with self._lock:
            existing = self._nodes.get(node_id, {})
            first_seen = existing.get("first_seen", now)
            self._nodes[node_id] = {
                "node_id": node_id,
                "node_type": payload.get("node_type", "ec2"),
                "first_seen": first_seen,
                "last_seen": now,
                "client_timestamp": payload.get("timestamp", now),
                "metrics": {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))},
                "metadata": metadata if isinstance(metadata, dict) else {},
            }
        return node_id

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return a copy of a single node's data or None."""
        with self._lock:
            node = self._nodes.get(node_id)
            return dict(node) if node else None

    def list_nodes(self) -> list[dict[str, Any]]:
        """Return snapshot list of all registered nodes sorted by last_seen desc."""
        with self._lock:
            nodes = [dict(n) for n in self._nodes.values()]
        nodes.sort(key=lambda n: n.get("last_seen", 0.0), reverse=True)
        return nodes

    def get_node_status(self, node: dict[str, Any], now: float | None = None) -> str:
        """Classify node status as 'online', 'stale', or 'offline'."""
        if now is None:
            now = time.time()
        last_seen = float(node.get("last_seen", 0.0))
        delta = now - last_seen
        if delta <= ONLINE_THRESHOLD:
            return "online"
        if delta <= STALE_THRESHOLD:
            return "stale"
        return "offline"

    def get_metric(self, metric_name: str, node_id: str | None = None) -> float | None:
        """Fetch a metric value. If node_id is omitted, checks the most recently active online node."""
        with self._lock:
            if node_id:
                node = self._nodes.get(node_id)
                if node and metric_name in node.get("metrics", {}):
                    return float(node["metrics"][metric_name])
                return None

            # Find the most recently seen online node
            now = time.time()
            candidates = [
                n for n in self._nodes.values()
                if (now - float(n.get("last_seen", 0.0))) <= ONLINE_THRESHOLD
                and metric_name in n.get("metrics", {})
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda n: n.get("last_seen", 0.0), reverse=True)
            return float(candidates[0]["metrics"][metric_name])

    def count_online(self) -> int:
        """Count nodes seen within ONLINE_THRESHOLD."""
        now = time.time()
        with self._lock:
            return sum(
                1 for n in self._nodes.values()
                if (now - float(n.get("last_seen", 0.0))) <= ONLINE_THRESHOLD
            )

    def clear(self) -> None:
        """Empty the store (useful in tests)."""
        with self._lock:
            self._nodes.clear()


# Global default store
GLOBAL_NODE_STORE = NodeStore()


class MetricsHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for receiving pushed metrics."""

    store: NodeStore = GLOBAL_NODE_STORE
    expected_token: str | None = None

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress verbose standard access logs; route errors to logger
        if args and str(args[1]) >= "400":
            logger.warning(format, *args)

    def _verify_auth(self) -> bool:
        expected = self.expected_token or os.environ.get("NANO_AUTH_TOKEN", "").strip()
        if not expected:
            return True  # No token required

        auth_header = self.headers.get("Authorization", "").strip()
        custom_header = self.headers.get("X-Nano-Token", "").strip()
        if auth_header == f"Bearer {expected}" or custom_header == expected:
            return True
        return False

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/health":
            self._send_json(200, {
                "status": "ok",
                "nodes_total": len(self.store.list_nodes()),
                "nodes_online": self.store.count_online(),
            })
            return

        if path in ("/metrics", "/api/v1/metrics"):
            if not self._verify_auth():
                self._send_json(401, {"error": "Unauthorized"})
                return
            nodes = self.store.list_nodes()
            self._send_json(200, {"nodes": nodes})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path not in ("/metrics", "/api/v1/metrics", "/webhook"):
            self._send_json(404, {"error": "Not found"})
            return

        if not self._verify_auth():
            self._send_json(401, {"error": "Unauthorized"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 1_000_000:  # 1MB limit
                self._send_json(413, {"error": "Payload too large"})
                return

            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode("utf-8"))
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "Invalid JSON body: expected object"})
                return

            node_id = self.store.update_node(payload)
            self._send_json(200, {"status": "ok", "node_id": node_id})
        except (ValueError, json.JSONDecodeError) as e:
            self._send_json(400, {"error": f"Malformed JSON: {e}"})
        except Exception as e:
            logger.exception("Error processing metrics POST")
            self._send_json(500, {"error": f"Internal error: {e}"})


class ReceiverServer:
    """Convenience wrapper to manage the lifecycle of the Metrics HTTP server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        store: NodeStore | None = None,
        auth_token: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.store = store or GLOBAL_NODE_STORE
        self.auth_token = auth_token

        # Configure handler class
        class CustomHandler(MetricsHTTPHandler):
            pass

        CustomHandler.store = self.store
        CustomHandler.expected_token = self.auth_token

        self._server = ThreadingHTTPServer((self.host, self.port), CustomHandler)
        self._thread: threading.Thread | None = None
        self._is_running = False

    def start_background(self) -> None:
        """Start serving in a daemon background thread."""
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Metrics receiver listening on http://%s:%s", self.host, self.port)

    def shutdown(self) -> None:
        """Shut down the server."""
        if not self._is_running:
            return
        self._server.shutdown()
        self._server.server_close()
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Metrics receiver stopped")

    @property
    def is_running(self) -> bool:
        return self._is_running


_ACTIVE_SERVER: ReceiverServer | None = None


def get_or_start_receiver(
    host: str = "0.0.0.0",
    port: int = 8080,
    store: NodeStore | None = None,
) -> ReceiverServer:
    """Get the active receiver server or start one in the background."""
    global _ACTIVE_SERVER
    if _ACTIVE_SERVER is None or not _ACTIVE_SERVER.is_running:
        _ACTIVE_SERVER = ReceiverServer(host=host, port=port, store=store)
        _ACTIVE_SERVER.start_background()
    return _ACTIVE_SERVER


def get_active_server() -> ReceiverServer | None:
    return _ACTIVE_SERVER


def main() -> None:
    """CLI entrypoint to run the standalone receiver server."""
    import argparse

    parser = argparse.ArgumentParser(description="nano-dsl Metrics Receiver Server")
    parser.add_argument("--host", default=os.environ.get("NANO_RECEIVER_HOST", "0.0.0.0"), help="Bind host")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("NANO_RECEIVER_PORT", "8080")),
        help="Listen port",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("NANO_AUTH_TOKEN", None),
        help="Optional auth token for POST requests",
    )
    args = parser.parse_args()

    server = ReceiverServer(host=args.host, port=args.port, auth_token=args.token)
    print(f"📡 nano-dsl Metrics Receiver running on http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server._server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down receiver...")
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
