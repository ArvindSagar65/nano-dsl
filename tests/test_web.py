"""Tests for the nano-dsl Web Observability Dashboard and REST API."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import pytest

from nano_logic.engine import ACTIVE_RULES, add_rule
from nano_logic.models import Rule
from nano_logic.receiver import NodeStore
from nano_logic.web import (
    WebServer,
    get_docker_payload,
    get_nodes_payload,
    get_overview_payload,
    get_rules_payload,
    get_system_metrics_payload,
)


def _http_get(url: str) -> tuple[int, dict[str, str], bytes]:
    """Helper to perform HTTP GET using urllib standard library."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
            headers = dict(resp.headers)
            body = resp.read()
            return status, headers, body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class TestDataCollectors:
    """Test data collection functions behind the REST API."""

    def test_system_metrics_payload_structure(self):
        payload = get_system_metrics_payload()
        assert "timestamp" in payload
        assert "system" in payload
        assert "cpu" in payload
        assert "memory" in payload
        assert "disk" in payload
        assert "network" in payload
        assert "sensors" in payload
        assert "processes" in payload

        # Check cpu details
        cpu = payload["cpu"]
        assert isinstance(cpu["util_percent"], (int, float))
        assert isinstance(cpu["per_core_percent"], list)
        assert isinstance(cpu["load_1m"], (int, float))

        # Check memory details
        mem = payload["memory"]
        assert isinstance(mem["percent"], (int, float))
        assert mem["total_gb"] > 0
        assert mem["used_gb"] >= 0

        # Check disk details
        disk = payload["disk"]
        assert isinstance(disk["root_usage_percent"], (int, float))
        assert isinstance(disk["partitions"], list)

        # Check processes
        procs = payload["processes"]
        assert procs["total_count"] > 0
        assert isinstance(procs["top_cpu"], list)
        assert isinstance(procs["top_memory"], list)

    def test_rules_payload_structure(self):
        ACTIVE_RULES.clear()
        # Add sample rules: one normal, one firing
        add_rule(Rule(metric="cpu.util", operator=">", threshold=999.0, action="log", name="never_fire"))
        add_rule(Rule(metric="cpu.util", operator=">=", threshold=0.0, action="log", name="always_fire"))

        payload = get_rules_payload()
        assert payload["total_rules"] >= 2
        assert "firing_rules" in payload
        assert isinstance(payload["rules"], list)
        assert isinstance(payload["recent_alerts"], list)

        rule_names = [r["name"] for r in payload["rules"]]
        assert "never_fire" in rule_names
        assert "always_fire" in rule_names

        always_rule = next(r for r in payload["rules"] if r["name"] == "always_fire")
        assert always_rule["status"] == "alerting"

        never_rule = next(r for r in payload["rules"] if r["name"] == "never_fire")
        assert never_rule["status"] == "normal"

    def test_docker_payload_structure(self):
        payload = get_docker_payload()
        assert "docker_installed" in payload
        assert "daemon_reachable" in payload
        assert "containers" in payload
        assert "container_stats" in payload
        assert "images" in payload
        assert "system_info" in payload
        assert isinstance(payload["containers"], list)
        assert isinstance(payload["images"], list)

    def test_nodes_payload_empty_and_populated(self):
        store = NodeStore()
        payload_empty = get_nodes_payload(store)
        assert payload_empty["total_nodes"] == 0
        assert payload_empty["online_nodes"] == 0

        # Populate a node
        store.update_node({
            "node_id": "i-testnode123",
            "node_type": "ec2",
            "metrics": {"cpu.util": 42.5, "mem.util": 55.0},
            "metadata": {
                "instance_id": "i-testnode123",
                "instance_type": "t3.medium",
                "availability_zone": "us-east-1a",
                "public_ip": "54.12.34.56",
            },
        })

        payload = get_nodes_payload(store)
        assert payload["total_nodes"] == 1
        assert payload["online_nodes"] == 1
        node = payload["nodes"][0]
        assert node["node_id"] == "i-testnode123"
        assert node["status"] == "online"
        assert node["metrics"]["cpu.util"] == 42.5
        assert node["metadata"]["instance_type"] == "t3.medium"

    def test_overview_payload_structure(self):
        store = NodeStore()
        payload = get_overview_payload(store)
        assert "system" in payload
        assert "docker" in payload
        assert "nodes" in payload
        assert "rules" in payload
        assert "cpu_percent" in payload["system"]
        assert "memory_percent" in payload["system"]


class TestWebServerEndpoints:
    """Test HTTP server running in background and serving endpoints."""

    @pytest.fixture(scope="class")
    @classmethod
    def server(cls):
        store = NodeStore()
        store.update_node({
            "node_id": "i-webtest",
            "node_type": "ec2",
            "metrics": {"cpu.util": 12.0},
            "metadata": {"instance_id": "i-webtest", "instance_type": "t3.micro"},
        })
        # Port 5188 to avoid colliding with any running service
        srv = WebServer(host="127.0.0.1", port=5188, store=store)
        srv.start_background()
        time.sleep(0.3)
        yield srv
        srv.shutdown()

    def test_health_endpoint(self, server: WebServer):
        code, headers, body = _http_get(f"http://127.0.0.1:{server.port}/health")
        assert code == 200
        assert "application/json" in headers.get("Content-Type", "")
        data = json.loads(body.decode("utf-8"))
        assert data["status"] == "ok"
        assert data["service"] == "nano-web-dashboard"

    def test_index_html_serving(self, server: WebServer):
        code, headers, body = _http_get(f"http://127.0.0.1:{server.port}/")
        assert code == 200
        assert "text/html" in headers.get("Content-Type", "")
        html = body.decode("utf-8")
        assert "nano-dsl" in html
        assert "Overview" in html
        assert "Docker" in html
        assert "EC2" in html

    def test_static_assets_serving(self, server: WebServer):
        # CSS
        code_css, headers_css, body_css = _http_get(f"http://127.0.0.1:{server.port}/dashboard.css")
        assert code_css == 200
        assert "text/css" in headers_css.get("Content-Type", "")
        assert "--cyan" in body_css.decode("utf-8")

        # JS
        code_js, headers_js, body_js = _http_get(f"http://127.0.0.1:{server.port}/dashboard.js")
        assert code_js == 200
        assert "javascript" in headers_js.get("Content-Type", "")
        assert "fetchData" in body_js.decode("utf-8")

    def test_api_overview_endpoint(self, server: WebServer):
        code, headers, body = _http_get(f"http://127.0.0.1:{server.port}/api/v1/overview")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert "system" in data
        assert "docker" in data
        assert "nodes" in data
        assert data["nodes"]["total"] == 1

    def test_api_metrics_endpoint(self, server: WebServer):
        code, headers, body = _http_get(f"http://127.0.0.1:{server.port}/api/v1/metrics")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data

    def test_api_rules_endpoint(self, server: WebServer):
        code, headers, body = _http_get(f"http://127.0.0.1:{server.port}/api/v1/rules")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert "rules" in data
        assert "total_rules" in data

    def test_api_docker_endpoint(self, server: WebServer):
        code, headers, body = _http_get(f"http://127.0.0.1:{server.port}/api/v1/docker")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert "docker_installed" in data
        assert "daemon_reachable" in data

    def test_api_nodes_endpoint(self, server: WebServer):
        code, headers, body = _http_get(f"http://127.0.0.1:{server.port}/api/v1/nodes")
        assert code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["total_nodes"] == 1
        assert data["nodes"][0]["node_id"] == "i-webtest"

    def test_not_found_endpoint(self, server: WebServer):
        code, _, body = _http_get(f"http://127.0.0.1:{server.port}/nonexistent_route_123")
        assert code == 404
        data = json.loads(body.decode("utf-8"))
        assert "error" in data

    def test_directory_traversal_protection(self, server: WebServer):
        code, _, _ = _http_get(f"http://127.0.0.1:{server.port}/../../../../etc/passwd")
        assert code in (400, 404)
