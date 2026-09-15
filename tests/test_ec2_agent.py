"""Tests for EC2 telemetry agent, metrics receiver, and DSL integration."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from nano_logic.agent import (
    build_payload,
    collect_ec2_metadata,
    collect_metrics,
    push_metrics,
)
from nano_logic.dsl import execute_command
from nano_logic.engine import ACTIVE_RULES, evaluate_active_rules
from nano_logic.models import Rule
from nano_logic.receiver import (
    GLOBAL_NODE_STORE,
    NodeStore,
    ReceiverServer,
)


@pytest.fixture(autouse=True)
def clean_node_store():
    """Ensure GLOBAL_NODE_STORE is clean before each test."""
    GLOBAL_NODE_STORE.clear()
    yield
    GLOBAL_NODE_STORE.clear()


# ──────────────────────────────────────────────
#  NodeStore Tests
# ──────────────────────────────────────────────

def test_node_store_update_and_get():
    store = NodeStore()
    payload = {
        "node_id": "i-0123456789abcdef0",
        "node_type": "ec2",
        "timestamp": time.time(),
        "metrics": {
            "cpu.util": 42.5,
            "mem.util": 68.0,
            "disk.usage": 55.2,
        },
        "metadata": {
            "instance_id": "i-0123456789abcdef0",
            "instance_type": "t3.medium",
            "region": "us-east-1",
            "public_ip": "54.210.10.20",
        },
    }

    node_id = store.update_node(payload)
    assert node_id == "i-0123456789abcdef0"

    node = store.get_node(node_id)
    assert node is not None
    assert node["node_type"] == "ec2"
    assert node["metrics"]["cpu.util"] == 42.5
    assert node["metadata"]["instance_type"] == "t3.medium"


def test_node_store_status_classification():
    store = NodeStore()
    payload = {
        "node_id": "test-node",
        "metrics": {"cpu.util": 10.0},
        "metadata": {},
    }
    store.update_node(payload)
    node = store.get_node("test-node")
    assert node is not None

    # Online: within 30s
    assert store.get_node_status(node, now=node["last_seen"] + 10) == "online"
    # Stale: 30-120s
    assert store.get_node_status(node, now=node["last_seen"] + 60) == "stale"
    # Offline: > 120s
    assert store.get_node_status(node, now=node["last_seen"] + 150) == "offline"


def test_node_store_get_metric():
    store = NodeStore()
    store.update_node({
        "node_id": "node-1",
        "metrics": {"cpu.util": 25.0, "mem.util": 50.0},
    })
    store.update_node({
        "node_id": "node-2",
        "metrics": {"cpu.util": 75.0, "mem.util": 80.0},
    })

    # Query specific node
    assert store.get_metric("cpu.util", "node-1") == 25.0
    assert store.get_metric("cpu.util", "node-2") == 75.0
    assert store.get_metric("nonexistent", "node-1") is None

    # Query without node_id returns most recent online node
    assert store.get_metric("cpu.util") == 75.0


def test_node_store_count_online():
    store = NodeStore()
    assert store.count_online() == 0
    store.update_node({"node_id": "n1", "metrics": {}})
    assert store.count_online() == 1


# ──────────────────────────────────────────────
#  ReceiverServer HTTP Tests
# ──────────────────────────────────────────────

def test_receiver_server_http_lifecycle():
    store = NodeStore()
    server = ReceiverServer(host="127.0.0.1", port=18088, store=store)
    server.start_background()
    time.sleep(0.2)
    assert server.is_running

    try:
        # Push a metric via agent helper
        payload = {
            "node_id": "i-test-instance",
            "node_type": "ec2",
            "metrics": {"cpu.util": 88.5},
            "metadata": {"instance_type": "c5.xlarge"},
        }
        ok = push_metrics("http://127.0.0.1:18088/metrics", payload)
        assert ok is True

        # Node should now exist in store
        node = store.get_node("i-test-instance")
        assert node is not None
        assert node["metrics"]["cpu.util"] == 88.5
    finally:
        server.shutdown()
        assert not server.is_running


def test_receiver_server_auth_token():
    store = NodeStore()
    server = ReceiverServer(host="127.0.0.1", port=18089, store=store, auth_token="secret123")
    server.start_background()
    time.sleep(0.2)

    try:
        payload = {"node_id": "i-secret", "metrics": {"cpu.util": 50.0}}
        # Attempt without token -> should fail (401)
        ok_no_token = push_metrics("http://127.0.0.1:18089/metrics", payload)
        assert ok_no_token is False

        # Attempt with valid token -> should succeed
        ok_with_token = push_metrics(
            "http://127.0.0.1:18089/metrics",
            payload,
            auth_token="secret123",
        )
        assert ok_with_token is True
    finally:
        server.shutdown()


# ──────────────────────────────────────────────
#  Agent Metadata & Metrics Tests
# ──────────────────────────────────────────────

def test_agent_collect_metrics():
    metrics = collect_metrics()
    assert "cpu.util" in metrics
    assert "mem.util" in metrics
    assert isinstance(metrics["cpu.util"], float)
    assert isinstance(metrics["mem.util"], float)


def test_agent_collect_ec2_metadata_fallback():
    # When IMDSv2 is unreachable, gracefully falls back to local machine info
    meta = collect_ec2_metadata()
    assert "hostname" in meta
    assert "platform" in meta
    assert "python_version" in meta
    assert "uptime_seconds" in meta


def test_agent_imds_mocking():
    token_resp = MagicMock()
    token_resp.status = 200
    token_resp.read.return_value = b"mock-token-xyz"
    token_resp.__enter__.return_value = token_resp

    item_resp = MagicMock()
    item_resp.status = 200
    item_resp.read.return_value = b"i-0123456789mock"
    item_resp.__enter__.return_value = item_resp

    def mock_urlopen(req, timeout=1.0):
        if req.full_url.endswith("/latest/api/token"):
            return token_resp
        return item_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        meta = collect_ec2_metadata()
        assert meta["is_ec2"] is True
        assert meta["instance_id"] == "i-0123456789mock"


def test_agent_build_payload():
    payload = build_payload(node_id="custom-node-42")
    assert payload["node_id"] == "custom-node-42"
    assert "metrics" in payload
    assert "metadata" in payload


def test_agent_push_graceful_failure():
    # Pointing to an unused port should return False without raising an exception
    ok = push_metrics("http://127.0.0.1:59999/metrics", {"dummy": 1}, timeout=0.5)
    assert ok is False


# ──────────────────────────────────────────────
#  DSL & Plugin Integration Tests
# ──────────────────────────────────────────────

def test_dsl_ec2_list_empty():
    GLOBAL_NODE_STORE.clear()
    out = execute_command("ec2.list")
    assert isinstance(out, str)
    assert "No remote nodes reporting" in out


def test_dsl_ec2_list_with_nodes():
    GLOBAL_NODE_STORE.update_node({
        "node_id": "i-0abcdef123456",
        "node_type": "ec2",
        "metrics": {"cpu.util": 23.4, "mem.util": 45.1, "disk.usage": 60.0},
        "metadata": {"public_ip": "1.2.3.4", "instance_type": "t3.micro"},
    })

    out = execute_command("ec2.list")
    assert "i-0abcdef123456" in out
    assert "23.4%" in out
    assert "45.1%" in out
    assert "ONLINE" in out


def test_dsl_ec2_metrics():
    GLOBAL_NODE_STORE.update_node({
        "node_id": "i-node-xyz",
        "metrics": {
            "cpu.util": 77.2,
            "cpu.load1": 1.5,
            "mem.util": 82.0,
            "mem.used": 3.2,
            "disk.usage": 40.0,
        },
        "metadata": {"instance_type": "t3.large", "region": "eu-west-1"},
    })

    out = execute_command("ec2.metrics")
    assert "i-node-xyz" in out
    assert "77.2%" in out
    assert "t3.large" in out

    out_specific = execute_command("ec2.metrics i-node-xyz")
    assert "i-node-xyz" in out_specific
    assert "77.2%" in out_specific


def test_dsl_ec2_info():
    GLOBAL_NODE_STORE.update_node({
        "node_id": "i-info-node",
        "metrics": {},
        "metadata": {
            "instance_id": "i-info-node",
            "instance_type": "m5.2xlarge",
            "region": "us-west-2",
            "public_ip": "54.100.200.1",
            "uptime_seconds": 3600,
        },
    })

    out = execute_command("ec2.info i-info-node")
    assert "m5.2xlarge" in out
    assert "us-west-2" in out
    assert "54.100.200.1" in out


def test_dsl_ec2_server():
    out = execute_command("ec2.server")
    assert "Receiver Server:" in out


# ──────────────────────────────────────────────
#  Alert Engine Integration Test
# ──────────────────────────────────────────────

def test_alert_rule_on_ec2_metric():
    # Register an alert rule on ec2.cpu.util
    rule_cmd = "ec2_alert: alert ec2.cpu.util > 80.0 -> log"
    parsed_rule = execute_command(rule_cmd)
    assert isinstance(parsed_rule, Rule)
    assert parsed_rule.metric == "ec2.cpu.util"
    assert parsed_rule.threshold == 80.0

    ACTIVE_RULES.clear()
    ACTIVE_RULES.append(parsed_rule)

    try:
        # Ingest metrics below threshold
        GLOBAL_NODE_STORE.update_node({
            "node_id": "i-alert-test",
            "metrics": {"cpu.util": 45.0},
        })
        triggered = evaluate_active_rules(cooldown_seconds=0)
        assert len(triggered) == 0

        # Ingest metrics exceeding threshold
        GLOBAL_NODE_STORE.update_node({
            "node_id": "i-alert-test",
            "metrics": {"cpu.util": 92.5},
        })
        triggered = evaluate_active_rules(cooldown_seconds=0)
        assert len(triggered) == 1
        rule, val = triggered[0]
        assert rule.metric == "ec2.cpu.util"
        assert val == 92.5
    finally:
        ACTIVE_RULES.clear()
