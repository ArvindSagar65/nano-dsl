#!/usr/bin/env python3
"""Simulate multiple EC2 instances pushing telemetry to the receiver.

Creates 3 fake EC2 nodes with realistic AWS metadata and fluctuating
metrics so you can test ec2.list, ec2.metrics, ec2.info, and alerts.
"""
import json
import math
import random
import time
import urllib.request

RECEIVER_URL = "http://localhost:8080/metrics"

# Fake EC2 instances
FAKE_NODES = [
    {
        "node_id": "i-0a1b2c3d4e5f67890",
        "node_type": "ec2",
        "metadata": {
            "instance_id": "i-0a1b2c3d4e5f67890",
            "instance_type": "t3.medium",
            "availability_zone": "us-east-1a",
            "region": "us-east-1",
            "public_ip": "54.210.45.123",
            "local_ip": "172.31.16.42",
            "hostname": "ip-172-31-16-42.ec2.internal",
            "platform": "Linux",
            "platform_release": "6.1.0-aws",
            "cpu_count": 2,
            "is_ec2": True,
        },
        "base_cpu": 35.0,
        "base_mem": 62.0,
        "base_disk": 45.0,
    },
    {
        "node_id": "i-09f8e7d6c5b4a3210",
        "node_type": "ec2",
        "metadata": {
            "instance_id": "i-09f8e7d6c5b4a3210",
            "instance_type": "c5.xlarge",
            "availability_zone": "eu-west-1b",
            "region": "eu-west-1",
            "public_ip": "52.18.92.77",
            "local_ip": "10.0.1.55",
            "hostname": "prod-api-server-01",
            "platform": "Linux",
            "platform_release": "5.15.0-aws",
            "cpu_count": 4,
            "is_ec2": True,
        },
        "base_cpu": 72.0,  # Runs hot — good for alert testing
        "base_mem": 78.0,
        "base_disk": 71.0,
    },
    {
        "node_id": "i-0deadbeef12345678",
        "node_type": "ec2",
        "metadata": {
            "instance_id": "i-0deadbeef12345678",
            "instance_type": "r5.large",
            "availability_zone": "ap-south-1a",
            "region": "ap-south-1",
            "public_ip": "13.232.100.50",
            "local_ip": "10.0.2.10",
            "hostname": "db-replica-mumbai",
            "platform": "Linux",
            "platform_release": "6.2.0-aws",
            "cpu_count": 2,
            "is_ec2": True,
        },
        "base_cpu": 18.0,  # DB replica — low CPU, high memory
        "base_mem": 88.0,
        "base_disk": 55.0,
    },
]


def fluctuate(base, amplitude=10.0, t=0):
    """Add realistic sine-wave + random jitter to a base value."""
    wave = amplitude * math.sin(t * 0.3) * 0.5
    jitter = random.uniform(-amplitude * 0.3, amplitude * 0.3)
    return max(0.0, min(100.0, base + wave + jitter))


def build_payload(node_cfg, tick):
    t = tick * 0.5
    cpu = fluctuate(node_cfg["base_cpu"], amplitude=15.0, t=t)
    mem = fluctuate(node_cfg["base_mem"], amplitude=8.0, t=t + 1)
    disk = fluctuate(node_cfg["base_disk"], amplitude=2.0, t=t + 2)

    uptime_base = 86400 * random.randint(3, 30)

    return {
        "node_id": node_cfg["node_id"],
        "node_type": node_cfg["node_type"],
        "timestamp": time.time(),
        "metrics": {
            "cpu.util": round(cpu, 1),
            "cpu.load1": round(cpu / 25.0 + random.uniform(0, 0.5), 2),
            "cpu.load5": round(cpu / 30.0 + random.uniform(0, 0.3), 2),
            "cpu.load15": round(cpu / 35.0 + random.uniform(0, 0.2), 2),
            "mem.util": round(mem, 1),
            "mem.used": round(mem * 0.08, 2),
            "mem.avail": round((100 - mem) * 0.08, 2),
            "swap.util": round(random.uniform(0, 5), 1),
            "disk.usage": round(disk, 1),
            "disk.free": round((100 - disk) * 0.5, 2),
            "net.bytes_sent": int(random.uniform(5e8, 2e9)),
            "net.bytes_recv": int(random.uniform(1e9, 5e9)),
        },
        "metadata": {
            **node_cfg["metadata"],
            "uptime_seconds": uptime_base + tick * 3,
        },
    }


def push(payload):
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            RECEIVER_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  ❌ Push failed: {e}")
        return False


def main():
    print("🧪 EC2 Simulator — pushing fake telemetry to receiver")
    print(f"   Target: {RECEIVER_URL}")
    print(f"   Simulating {len(FAKE_NODES)} nodes:")
    for n in FAKE_NODES:
        m = n["metadata"]
        print(f"     • {n['node_id']} ({m['instance_type']}, {m['region']}, {m['public_ip']})")
    print()
    print("   Push interval: 3 seconds")
    print("   Press Ctrl+C to stop.\n")

    tick = 0
    while True:
        for node_cfg in FAKE_NODES:
            payload = build_payload(node_cfg, tick)
            ok = push(payload)
            status = "✅" if ok else "❌"
            cpu = payload["metrics"]["cpu.util"]
            mem = payload["metrics"]["mem.util"]
            print(f"  {status} {node_cfg['node_id'][:20]}  CPU={cpu:5.1f}%  MEM={mem:5.1f}%")

        tick += 1
        print(f"  ── tick {tick} ──")
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Simulator stopped.")
