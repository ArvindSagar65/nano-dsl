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

    def __init__(self, auto_sync: bool = False) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, dict[str, Any]] = {}
        self.auto_sync = auto_sync
        self._last_sync_time: float = 0.0

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
            first_seen = float(payload.get("first_seen") or existing.get("first_seen", now))
            last_seen = float(payload.get("last_seen") or now)
            self._nodes[node_id] = {
                "node_id": node_id,
                "node_type": payload.get("node_type", "ec2"),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "client_timestamp": float(payload.get("client_timestamp") or payload.get("timestamp", now)),
                "metrics": {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))},
                "metadata": metadata if isinstance(metadata, dict) else {},
            }
        return node_id

    def sync_from_receiver(
        self,
        port: int | None = None,
        timeout: float = 0.5,
        force: bool = False,
    ) -> bool:
        """If an external receiver is running, sync live nodes from its /metrics endpoint."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return False
        if not self.auto_sync and not force:
            return False

        server = get_active_server()
        if server is not None and server.is_running:
            return True

        now = time.time()
        last_sync = getattr(self, "_last_sync_time", 0.0)
        if not force and (now - last_sync) < 1.0:
            return False

        self._last_sync_time = now

        if port is None:
            port = int(os.environ.get("NANO_RECEIVER_PORT", "8080"))

        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://localhost:{port}/metrics",
                headers={"User-Agent": "nano-nodestore-sync"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    remote_nodes = data.get("nodes", [])
                    if isinstance(remote_nodes, list):
                        with self._lock:
                            for n in remote_nodes:
                                if isinstance(n, dict):
                                    nid = str(n.get("node_id") or "").strip()
                                    if nid:
                                        self._nodes[nid] = {
                                            "node_id": nid,
                                            "node_type": n.get("node_type", "ec2"),
                                            "first_seen": float(n.get("first_seen", now)),
                                            "last_seen": float(n.get("last_seen", now)),
                                            "client_timestamp": float(n.get("client_timestamp", now)),
                                            "metrics": {
                                                k: float(v)
                                                for k, v in n.get("metrics", {}).items()
                                                if isinstance(v, (int, float))
                                            },
                                            "metadata": n.get("metadata", {}) if isinstance(n.get("metadata"), dict) else {},
                                        }
                        return True
        except Exception:
            pass
        return False

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return a copy of a single node's data or None."""
        self.sync_from_receiver()
        with self._lock:
            node = self._nodes.get(node_id)
            return dict(node) if node else None

    def list_nodes(self) -> list[dict[str, Any]]:
        """Return snapshot list of all registered nodes sorted by last_seen desc."""
        self.sync_from_receiver()
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
        self.sync_from_receiver()
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
        self.sync_from_receiver()
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
GLOBAL_NODE_STORE = NodeStore(auto_sync=True)


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

        class ReusableThreadingServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = ReusableThreadingServer((self.host, self.port), CustomHandler)
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
    import urllib.request

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

    try:
        server = ReceiverServer(host=args.host, port=args.port, auth_token=args.token)
    except OSError as err:
        if getattr(err, "errno", None) == 98 or "already in use" in str(err).lower():
            # Check if an existing receiver is answering
            check_host = "localhost" if args.host == "0.0.0.0" else args.host
            is_our_receiver = False
            try:
                with urllib.request.urlopen(f"http://{check_host}:{args.port}/health", timeout=2) as resp:
                    if resp.status == 200:
                        is_our_receiver = True
            except Exception:
                pass

            if is_our_receiver:
                print(f"📡 nano-dsl Metrics Receiver is ALREADY ACTIVE and running on http://{args.host}:{args.port}")
                print("ℹ️  Note: When 'nano-web' or 'nano-dsl' is running, the receiver automatically starts in the background.")
                print("👉 You don't need to run this command — you can push metrics directly:")
                print(f"   PYTHONPATH=. ./venv/bin/python -m nano_logic.agent --receiver-url http://localhost:{args.port}/metrics\n")
                sys.exit(0)
            else:
                print(f"❌ Error: Port {args.port} is already in use by another service on your system.", file=sys.stderr)
                print(f"👉 Try specifying a different port: python -m nano_logic.receiver --port {args.port + 1}\n", file=sys.stderr)
                sys.exit(1)
        raise

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
