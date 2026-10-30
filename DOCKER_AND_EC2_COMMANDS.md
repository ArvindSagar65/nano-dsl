# Nano-DSL: Docker & EC2 Commands Reference

This reference document catalogs all **Docker (Container)** and **EC2 (Cloud & Remote Nodes)** DSL commands, alert probes, argument formats, and practical usage examples across the TUI, Headless CLI REPL, and Web Dashboard.

---

## 📑 Table of Contents

1. [Docker Commands Reference](#1-docker-commands-reference)
   - [`docker.ps`](#dockerps)
   - [`docker.stats`](#dockerstats)
   - [`docker.info`](#dockerinfo)
   - [`docker.images`](#dockerimages)
   - [`docker.containers`](#dockercontainers)
   - [`docker.logs`](#dockerlogs)
   - [`docker.networks`](#dockernetworks)
   - [`docker.volumes`](#dockervolumes)
2. [Docker Alert Probes & Automation](#2-docker-alert-probes--automation)
3. [EC2 & Cloud Commands Reference](#3-ec2--cloud-commands-reference)
   - [`ec2.list`](#ec2list)
   - [`ec2.metrics`](#ec2metrics)
   - [`ec2.info`](#ec2info)
   - [`ec2.server`](#ec2server)
4. [EC2 Alert Probes & Automation](#4-ec2-alert-probes--automation)
5. [Quick Execution Cheatsheet](#5-quick-execution-cheatsheet)

---

## 1. Docker Commands Reference

The Docker plugin provides read-only introspection of containers, images, volumes, networks, and daemon health. It uses the Python Docker SDK if available and automatically falls back to the native `docker` CLI.

### `docker.ps`
* **Syntax**: `docker.ps`
* **Arguments**: None
* **Description**: Lists all currently running Docker containers with container ID, image, state, uptime, exposed ports, and name.
* **Example Usage**:
  ```bash
  nano» docker.ps
  ```
* **Sample Output**:
  ```text
  CONTAINER ID   IMAGE          COMMAND                  CREATED         STATUS         PORTS                    NAMES
  e9f2a7b1c3d4   nginx:alpine   "/docker-entrypoint.…"   2 hours ago     Up 2 hours     0.0.0.0:80->80/tcp       web-gateway
  4a8b1c2d3e4f   redis:7-alpine "docker-entrypoint.s…"   5 hours ago     Up 5 hours     0.0.0.0:6379->6379/tcp   cache-redis
  ```

---

### `docker.stats`
* **Syntax**: `docker.stats`
* **Arguments**: None
* **Description**: Provides a live resource consumption snapshot for running containers, including CPU %, memory usage, memory limit, memory %, and network I/O.
* **Example Usage**:
  ```bash
  nano» docker.stats
  ```
* **Sample Output**:
  ```text
  CONTAINER ID   NAME          CPU %     MEM USAGE / LIMIT     MEM %     NET I/O
  e9f2a7b1c3d4   web-gateway   0.15%     18.4MiB / 7.66GiB     0.23%     1.2MB / 850KB
  4a8b1c2d3e4f   cache-redis   0.08%     12.1MiB / 7.66GiB     0.15%     450KB / 320KB
  ```

---

### `docker.info`
* **Syntax**: `docker.info`
* **Arguments**: None
* **Description**: Displays Docker daemon system information: server version, OS/kernel details, storage driver, total containers (running, paused, stopped), and system resource limits.
* **Example Usage**:
  ```bash
  nano» docker.info
  ```
* **Sample Output**:
  ```text
  === Docker System Information ===
  Server Version:     24.0.7
  Containers Total:   4 (Running: 2, Paused: 0, Stopped: 2)
  Images:             12
  Storage Driver:     overlay2
  Logging Driver:     json-file
  Cgroup Version:     2
  Kernel Version:     6.8.0-generic
  Operating System:   Ubuntu 24.04 LTS
  ```

---

### `docker.images`
* **Syntax**: `docker.images`
* **Arguments**: None
* **Description**: Lists local container images stored on the host, with repository tags, image IDs, creation timestamps, and virtual disk size.
* **Example Usage**:
  ```bash
  nano» docker.images
  ```
* **Sample Output**:
  ```text
  REPOSITORY          TAG       IMAGE ID       CREATED        SIZE
  nginx               alpine    9a982c5f1234   3 weeks ago    42.6MB
  redis               7-alpine  1b8f4a2c5678   4 weeks ago    38.1MB
  python              3.12-slim e837482a9901   1 month ago    130MB
  ```

---

### `docker.containers`
* **Syntax**: `docker.containers`
* **Arguments**: None
* **Description**: Lists **all** containers on the system (both active running and exited/stopped containers) with their exit codes and status.
* **Example Usage**:
  ```bash
  nano» docker.containers
  ```
* **Sample Output**:
  ```text
  CONTAINER ID   IMAGE          STATUS                     NAMES
  e9f2a7b1c3d4   nginx:alpine   Up 2 hours                 web-gateway
  4a8b1c2d3e4f   redis:7-alpine Up 5 hours                 cache-redis
  b1c2d3e4f5a6   postgres:16    Exited (0) 12 hours ago    db-backup-job
  ```

---

### `docker.logs`
* **Syntax**: `docker.logs <container_name_or_id>`
* **Arguments**:
  - `container_name_or_id`: The container's name or container ID hash.
* **Description**: Fetches the most recent 20 log entries emitted to `stdout` and `stderr` by the specified container.
* **Example Usage**:
  ```bash
  nano» docker.logs web-gateway
  nano» docker.logs e9f2a7b1c3d4
  ```
* **Sample Output**:
  ```text
  === Logs: web-gateway (tail 20) ===
  [2026-09-16 01:14:02] [notice] 1#1: using the "epoll" event method
  [2026-09-16 01:14:02] [notice] 1#1: nginx/1.25.3
  [2026-09-16 01:14:02] [notice] 1#1: start worker processes
  172.17.0.1 - - [16/Sep/2026:01:15:10 +0000] "GET /health HTTP/1.1" 200 15
  ```

---

### `docker.networks`
* **Syntax**: `docker.networks`
* **Arguments**: None
* **Description**: Lists all Docker virtual network bridges, host networks, and overlay networks along with their driver and scope.
* **Example Usage**:
  ```bash
  nano» docker.networks
  ```
* **Sample Output**:
  ```text
  NETWORK ID     NAME      DRIVER    SCOPE
  0a1b2c3d4e5f   bridge    bridge    local
  1b2c3d4e5f6a   host      host      local
  2c3d4e5f6a7b   none      null      local
  3d4e5f6a7b8c   app-net   bridge    local
  ```

---

### `docker.volumes`
* **Syntax**: `docker.volumes`
* **Arguments**: None
* **Description**: Lists all local Docker persistent storage volumes.
* **Example Usage**:
  ```bash
  nano» docker.volumes
  ```
* **Sample Output**:
  ```text
  DRIVER    VOLUME NAME
  local     redis-cache-data
  local     postgres-data
  local     grafana-storage
  ```

---

## 2. Docker Alert Probes & Automation

Nano-DSL enables declarative alerts that monitor container health thresholds and dispatch actions (e.g., webhook, slack, log, desktop notifications).

| Metric Probe | Type | Description |
| :--- | :--- | :--- |
| `docker.containers.running` | Float (Scalar) | Number of containers currently in `running` state |

### Example Alert Rules:
```bash
# Alert if running containers fall below minimum replica threshold
nano» alert docker.containers.running < 2 -> webhook

# Name a rule and trigger desktop notification if all containers stop
nano» container_down: alert docker.containers.running == 0 -> notify
```

---

## 3. EC2 & Cloud Commands Reference

The EC2 plugin integrates with Nano-DSL's built-in HTTP telemetry receiver (`http://0.0.0.0:8080/metrics`). It receives metric push payloads from the lightweight `nano-agent` running on real AWS EC2 instances, virtual machines, or simulated cloud nodes.

### `ec2.list`
* **Syntax**: `ec2.list`
* **Arguments**: None
* **Description**: Renders a formatted tabular overview of all connected EC2 nodes, displaying their Node ID, type, public/private IP, live CPU%, memory%, disk%, health status (`[ONLINE]`, `[STALE]`, `[OFFLINE]`), and time since last heartbeat.
* **Example Usage**:
  ```bash
  nano» ec2.list
  ```
* **Sample Output**:
  ```text
  NODE ID                TYPE     IP ADDRESS       CPU%     MEM%     DISK%    STATUS     LAST SEEN
  -----------------------------------------------------------------------------------------------
  i-0deadbeef12345678    ec2      13.232.100.50    28.9%    89.9%    55.4%    [ONLINE]   0s ago
  i-09f8e7d6c5b4a3210    ec2      52.18.92.77      77.3%    81.9%    71.7%    [ONLINE]   0s ago
  i-0a1b2c3d4e5f67890    ec2      54.210.45.123    39.7%    63.1%    45.0%    [ONLINE]   0s ago

  Total: 3 node(s) | Online: 3
  ```

---

### `ec2.metrics`
* **Syntax**: `ec2.metrics` or `ec2.metrics <node_id>`
* **Arguments**:
  - `node_id` *(optional)*: The EC2 instance ID (e.g. `i-09f8e7d6c5b4a3210` or partial substring). If omitted, defaults to the most recently active online node.
* **Description**: Inspects detailed system telemetry for an instance: CPU utilization, 1m/5m/15m load averages, memory used/available/swap, disk free/used, and total network bytes transferred.
* **Example Usage**:
  ```bash
  nano» ec2.metrics
  nano» ec2.metrics i-09f8e7d6c5b4a3210
  ```
* **Sample Output**:
  ```text
  === Live Metrics: i-0deadbeef12345678 [ONLINE] ===
  Instance Type: r5.large  |  Region: ap-south-1
  Last Reported: 0s ago

  CPU:
    Utilization:   28.9%
    Load Average:  1m: 1.45 | 5m: 1.18 | 15m: 0.88

  Memory:
    Utilization:   89.9%
    Used:          7.17 GB
    Available:     0.83 GB
    Swap Util:     1.7%

  Disk & Network:
    Disk Usage:    55.4%
    Disk Free:     22.09 GB
    Bytes Sent:    1,516,699,835 bytes
    Bytes Recv:    1,446,394,520 bytes
  ```

---

### `ec2.info`
* **Syntax**: `ec2.info` or `ec2.info <node_id>`
* **Arguments**:
  - `node_id` *(optional)*: The EC2 instance ID or hostname. If omitted, defaults to the most recent node.
* **Description**: Displays cloud infrastructure metadata gathered from the AWS Instance Metadata Service (IMDSv2) or fallback discovery: AWS Region, Availability Zone, AMI/Instance Type, Hostname, Kernel version, vCPU core count, and system uptime.
* **Example Usage**:
  ```bash
  nano» ec2.info
  nano» ec2.info i-0a1b2c3d4e5f67890
  ```
* **Sample Output**:
  ```text
  === Instance Info: i-0a1b2c3d4e5f67890 ===
  Instance Type:     t3.medium
  Availability Zone: us-east-1a
  Region:            us-east-1
  Public IP:         54.210.45.123
  Private IP:        172.31.16.42
  Hostname:          ip-172-31-16-42.ec2.internal
  Platform:          Linux 6.1.0-aws (x86_64)
  vCPUs:             2
  Uptime:            28d 0h 4m
  Status:            ONLINE (last seen 0s ago)
  ```

---

### `ec2.server`
* **Syntax**: `ec2.server` or `ec2.server start` or `ec2.server stop`
* **Arguments**:
  - `start` *(optional)*: Manually initiates the HTTP metrics receiver thread on port 8080.
  - `stop` *(optional)*: Shuts down the background HTTP receiver thread.
  - Omitted: Reports the current operational status, host binding, port, and count of reporting nodes.
* **Example Usage**:
  ```bash
  nano» ec2.server
  ```
* **Sample Output**:
  ```text
  Receiver Server Status: ACTIVE
  Endpoint: http://0.0.0.0:8080/metrics
  Nodes Connected: 3 (3 online)
  ```

---

## 4. EC2 Alert Probes & Automation

All EC2 telemetry metrics are directly hooked into the Nano-Logic rule evaluation engine, allowing you to establish multi-cloud monitoring without Prometheus or CloudWatch:

| Metric Probe | Unit | Description |
| :--- | :--- | :--- |
| `ec2.cpu.util` | Percentage (`0.0 - 100.0`) | CPU utilization of the most active reporting node |
| `ec2.mem.util` | Percentage (`0.0 - 100.0`) | Memory utilization of the most active reporting node |
| `ec2.disk.usage` | Percentage (`0.0 - 100.0`) | Disk usage percentage of the reporting node |
| `ec2.nodes.online` | Integer count | Number of healthy nodes seen within the last 30 seconds |

### Example Alert Rules:
```bash
# Alert when an EC2 instance experiences CPU saturation
nano» alert ec2.cpu.util > 80.0 -> webhook

# Trigger a Slack notification when memory usage exceeds 90%
nano» ec2_mem_leak: alert ec2.mem.util > 90.0 -> slack

# Alert if fewer than 3 EC2 nodes are reporting online
nano» quorum_warning: alert ec2.nodes.online < 3 -> webhook

# Log to disk whenever disk space usage surpasses threshold
nano» alert ec2.disk.usage > 85.0 -> log
```

---

## 5. Quick Execution Cheatsheet

### Mode 1: Graphical TUI
Launch the interactive terminal interface:
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.dashboard
```
Type any command (`docker.ps`, `ec2.list`, `ec2.metrics`) in the bottom command input prompt.

---

### Mode 2: Headless CLI REPL
Launch the lightweight terminal REPL (ideal for SSH sessions, CI/CD, and scripts):
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.cli
```
Run commands directly:
```bash
nano» docker.ps
nano» ec2.list
nano» ec2.metrics
nano» status
```

---

### Mode 3: Web Observability Dashboard
Start the web dashboard alongside the metrics receiver:
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.web --port 5050
```
Open [http://localhost:5050](http://localhost:5050) in any browser to see live container tables and EC2 fleet cards.

---

### Testing EC2 Telemetry Locally
In a separate terminal, launch the built-in multi-instance simulator:
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python scripts/simulate_ec2.py
```
This pushes telemetry for 3 simulated AWS EC2 instances (`t3.medium`, `c5.xlarge`, and `r5.large`) across `us-east-1`, `eu-west-1`, and `ap-south-1`.
