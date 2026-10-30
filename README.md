# nano-dsl

A lightweight system-monitoring toolkit with a custom DSL, a Textual TUI, a background alert daemon, optional Docker/EC2 plugins, and a companion web observability dashboard.

Commands that change the machine (kill a process, create a rule, start the receiver) run in the **TUI**. The **web UI** is read-only telemetry.

- **Custom DSL** — Query CPU, memory, disk, GPU, processes, network, sensors, systemd, Docker, and remote EC2 nodes with short dotted commands (`cpu.util`, `docker.ps`, `ec2.list`).
- **45+ Commands** across 11 namespaces, parsed with Lark (LALR).
- **Web Observability Dashboard** (`nano-web`) — Overview KPIs, per-core CPU, Docker tables, EC2 fleet cards, live alert status with zero external Python dependencies.
- **Headless CLI REPL Mode** (`nano-cli`) — Lightweight terminal prompt for remote servers without TUI/graphical dependencies.
- **Alert Rules & Actions** — `name: alert <metric> <op> <threshold> -> <action>` with operators `>`, `<`, `==`, `>=`, `<=`. Actions include `log`, `webhook`, `slack`, and `discord`.
- **Background Daemon & Rule Persistence** — Rules persist in `rules.json` (XDG state directory) and evaluate in the background even after you close the TUI.
- **EC2 & Remote Node Monitoring** — `nano-agent` pushes metrics to `nano-receiver`; query with `ec2.list`, `ec2.metrics`, `ec2.info`.
- **Interactive Textual TUI** — Live disks/network/system panels, in-app guide, command history, active-rules panel, and clipboard copy.
- **Plugin Registry** — Drop-in `PluginBase` modules for custom commands, numeric probes, and alert actions.
- **Comprehensive Test Suite** — 304+ automated unit and integration tests passing at 100%.

## Getting Started

### Installation

```bash
git clone https://github.com/ArvindSagar65/nano-dsl.git
cd nano-dsl
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

On Windows, PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

### Run the TUI

```bash
nano-dsl
# or
python -m nano_logic.dashboard
```

**TUI navigation**

- Type DSL commands in the input at the bottom; results go to the command console.
- **Up / Down** cycle command history.
- `help`, `guide`, `status`, `rules`, `clear`, `history`.
- `q`, `exit`, or `quit` closes the TUI. **The daemon keeps running** so alerts still fire.
- `Ctrl+Shift+C` (or `F6`) copies the console to the clipboard.

Launch TUI and web together:

```bash
nano-dsl --web
nano-dsl --web --web-port 5000
```

Then open [http://localhost:5000](http://localhost:5000).

### Run the web dashboard alone

```bash
nano-web --port 5000
python -m nano_logic.web --port 5000 --with-receiver
```

| Endpoint | Description |
|----------|-------------|
| `/` | Web UI |
| `/health` | Service health |
| `/api/v1/overview` | Lightweight KPI snapshot |
| `/api/v1/metrics` | Host metrics, per-core CPU, partitions, sensors, top processes |
| `/api/v1/rules` | Alert rules + recent log lines |
| `/api/v1/docker` | Containers, stats, images (TTL-cached) |
| `/api/v1/nodes` | Remote EC2 / agent nodes |

Web UI shortcuts: keys **1–6** switch tabs; **Space** pauses polling.

---

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

The suite covers the DSL, rule engine, plugins, Docker probes, webhook actions, EC2 agent/receiver, and web API.

---

## Alert Rules

| Syntax | Example |
|--------|---------|
| Anonymous | `alert cpu.util > 80 -> log` |
| Named | `high_cpu: alert cpu.util > 80 -> log` |
| Stop by id | `stop rule 1` |
| Stop by name | `stop rule high_cpu` |

**Actions**

| Action | Behavior |
|--------|----------|
| `log` | Append to `$XDG_STATE_HOME/nano-dsl/logs/<rule>.log` (default `~/.local/state/nano-dsl/logs/`) and beep |
| `webhook` | POST JSON to `NANO_DSL_WEBHOOK_URL` |
| `slack` | Slack incoming webhook via `NANO_DSL_SLACK_WEBHOOK_URL` |
| `discord` | Discord webhook via `NANO_DSL_DISCORD_WEBHOOK_URL` |

Repeated fires are suppressed for 60 seconds while a condition stays true, then re-arm when it clears.

**Alertable metrics (built-in + plugins):** `cpu.util`, `cpu.load1/5/15`, `mem.util`, `mem.used`, `mem.avail`, `swap.util`, `disk.free`, `disk.usage`, `sensor.temp`, `sensor.battery`, `proc.count`, `net.connections`, `docker.containers.running`, `ec2.cpu.util`, `ec2.mem.util`, `ec2.disk.usage`, `ec2.nodes.online`.

---

## TUI command cheat sheet

**Queries:** `cpu.util` · `mem.stats` · `disk.inode` · `proc.search python` · `net.dns google.com` · `sensor.temp` · `status`

**Docker:** `docker.ps` · `docker.stats` · `docker.info` · `docker.images` · `docker.containers` · `docker.logs <name>` · `docker.networks` · `docker.volumes`

**EC2:** `ec2.list` · `ec2.metrics [id]` · `ec2.info [id]` · `ec2.server [start\|stop]`

<<<<<<< HEAD
| Command | Description |
|---------|-------------|
| `mem.util` | Current memory utilization percentage |
| `mem.stats` | Memory details (used, available, total, swap %) |
| `mem.swap` | Detailed swap memory statistics |
| `mem.top` | Top 5 processes by memory usage |
| `mem.cached` | Cached and buffers memory in GiB |

### Disk Commands

| Command | Description |
|---------|-------------|
| `disk.free` | Free and total disk space for root filesystem (/) |
| `disk.usage` | Disk usage percentage for all mounted partitions |
| `disk.io` | Disk I/O statistics (read/write counts and bytes) |
| `disk.top` | Top directories by storage usage |
| `disk.inode` | Inode usage on root filesystem |

### GPU Commands

| Command | Description |
|---------|-------------|
|`gpu.util` | GPU utilization and memory (NVIDIA) |

### Process Commands

| Command | Description |
|---------|-------------|
| `proc.list` | List all running processes with PIDs |
| `proc.kill <pid>` | Terminate a process by PID (e.g., `proc.kill 1234`) |
| `proc.search <name>`	| Find processes by name substring |
| `proc.tree` |	Process tree view (via ps auxf) |
| `proc.info <pid>`	| Detailed info (CPU, memory, threads, cmdline) for a PID |

### Network Commands

| Command | Description |
|---------|-------------|
| `net.interfaces` | List all network interfaces and their status |
| `net.bandwidth` | Total network bandwidth (sent/received bytes and packets) |
| `net.connections` | Active network connections (total, established, listening) |
| `net.ports`	| List all listening TCP ports |
| `net.dns <host>`	| DNS lookup for a hostname |

### System Commands

| Command | Description |
|---------|-------------|
| `system.uptime` | System uptime in days, hours, and minutes |
| `system.info` | OS, hostname, kernel, and processor information |
| `system.processes` | Total process and thread count |
| `system.users` | Currently logged-in users |
| `system.load` | Quick CPU + RAM + load snapshot |

### Sensor Commands

| Command | Description |
|---------|-------------|
|`sensor.temp` | CPU and device temperatures with thresholds |
|`sensor.fans` | Fan speeds in RPM |
|`sensor.battery` | Battery percentage and charging status\

### Docker Commands

| Command | Description |
|---------|-------------|
|`docker.ps` | List running Docker containers |
|`docker.stats` | Live CPU/memory stats for containers |

### Service Commands

| Command | Description |
|---------|-------------|
|`service.list` | List running systemd services |
|`service.status <name>` | Status and logs for a specific service |

### EC2 & Remote Node Commands

| Command | Description |
|---------|-------------|
|`ec2.list` | List all connected remote nodes with live metrics and status |
|`ec2.metrics [id]` | Detailed metric breakdown for a node (CPU, Memory, Disk, Network) |
|`ec2.info [id]` | AWS metadata and node configuration (Instance Type, AZ, IPs, Uptime) |
|`ec2.server [start\|stop]` | Check or manage the metrics receiver server |

**Alertable EC2 metrics:** `ec2.cpu.util`, `ec2.mem.util`, `ec2.disk.usage`, `ec2.nodes.online`

### Utility Commands

| Command | Description |
|---------|-------------|
|`help` | Show all available commands with descriptions |
|`rules` | List all active alert rules |
|`status` | System overview (CPU, RAM, disk, uptime, rules) |
|`clear` | Clear the command console |
|`history` | Show command history (use up/down arrows) |
|`guide` | Show the in-app command guide |
=======
**Rules:** `disk_alert: alert disk.free < 5 -> log` · `alert ec2.cpu.util > 80 -> webhook` · `stop rule disk_alert`
>>>>>>> upstream/main

---

## DSL command reference

### CPU

| Command | Description |
|---------|-------------|
| `cpu.util` | CPU utilization % |
| `cpu.load` | 1/5/15 minute load average |
| `cpu.cores` | Physical and logical cores |
| `cpu.top` | Top 5 processes by CPU |
| `cpu.avg` | Load average normalised by core count |

### Memory

| Command | Description |
|---------|-------------|
| `mem.util` | Memory utilization % |
| `mem.stats` | Used / available / total / swap |
| `mem.swap` | Swap details |
| `mem.top` | Top 5 processes by memory |
| `mem.cached` | Cached and buffers |

### Disk

| Command | Description |
|---------|-------------|
| `disk.free` | Free space on `/` |
| `disk.usage` | All mounted partitions |
| `disk.io` | Read/write counters |
| `disk.top` | Directory sizes (`du`) |
| `disk.inode` | Inode usage (Unix) |

### GPU / process / network / system / sensors

| Command | Description |
|---------|-------------|
| `gpu.util` | NVIDIA GPU util & memory (`nvidia-smi`) |
| `proc.list` | Running processes |
| `proc.kill <pid>` | Terminate a process |
| `proc.search <name>` | Find by name |
| `proc.tree` | Process tree (`ps auxf`) |
| `proc.info <pid>` | Details for one PID |
| `net.interfaces` | Interfaces and IPv4 |
| `net.bandwidth` | Bytes/packets sent and received |
| `net.connections` | Totals by state |
| `net.ports` | Listening TCP ports |
| `net.dns <host>` | DNS lookup |
| `system.uptime` | Uptime |
| `system.info` | OS / hostname / arch |
| `system.processes` | Process and thread counts |
| `system.users` | Logged-in users |
| `system.load` | Load + CPU + RAM snapshot |
| `sensor.temp` | Temperatures |
| `sensor.fans` | Fan RPM |
| `sensor.battery` | Battery % |

### Docker

| Command | Description |
|---------|-------------|
| `docker.ps` | Running containers |
| `docker.stats` | CPU/memory stats |
| `docker.info` | Daemon info |
| `docker.images` | Images |
| `docker.containers` | All containers |
| `docker.logs <name>` | Container logs |
| `docker.networks` | Networks |
| `docker.volumes` | Volumes |

### Services

| Command | Description |
|---------|-------------|
| `service.list` | Running systemd units |
| `service.status <name>` | Status and recent logs |

### EC2 & remote nodes

| Command | Description |
|---------|-------------|
| `ec2.list` | Connected nodes and live CPU/mem/disk |
| `ec2.metrics [id]` | Full metric dump for a node |
| `ec2.info [id]` | IMDSv2 metadata (type, AZ, IPs) |
| `ec2.server [start\|stop]` | Receiver status / control |

### Utility

| Command | Description |
|---------|-------------|
| `help` | Command list |
| `rules` | Active alerts |
| `status` | Host overview |
| `clear` | Clear TUI console |
| `history` | History hint |
| `guide` | In-app TUI guide |

---

## TUI dashboard panels

The Textual app uses a dark layout with a left-hand **guide**, three live metric cards, an **active rules** panel, and the **command console**:

1. **Disk** — root usage % and a progress bar  
2. **Network** — sent / received MiB  
3. **System** — CPU %, process count, uptime  
4. **Active rules** — id, name, condition, action  
5. **Console** — query output and alert tails from the daemon logs  

Panels refresh about once per second. The daemon is spawned on TUI start (single-instance lock). Closing the TUI does **not** stop rules.

---

## EC2 remote monitoring

**1. Receiver** (auto-started when the EC2 plugin loads, or run by hand):

```bash
python -m nano_logic.receiver --port 8080
# or
nano-receiver
```

**2. Agent on the remote host:**

```bash
nano-agent --receiver-url http://<YOUR_IP>:8080/metrics --interval 5
```

| Variable | Default | Meaning |
|----------|---------|---------|
| `NANO_RECEIVER_URL` | `http://localhost:8080/metrics` | Push URL |
| `NANO_PUSH_INTERVAL` | `5` | Seconds |
| `NANO_NODE_ID` | IMDSv2 instance id or hostname | Node id |
| `NANO_AUTH_TOKEN` | unset | Optional shared token |

On EC2 the agent reads IMDSv2 (instance id, type, AZ, public/private IP). Elsewhere it uses hostname and local platform info.

---

## Project structure

```
nano-dsl/
├── README.md
├── requirements.txt
├── pyproject.toml          # entry points: nano-dsl, nano-web, nano-agent, nano-receiver
├── nano_logic/
<<<<<<< HEAD
│   ├── __init__.py
│   ├── agent.py             # EC2 telemetry agent (deploy on remote nodes)
│   ├── receiver.py          # HTTP metrics receiver & NodeStore
│   ├── web.py               # Web Observability server & REST API
│   ├── dashboard.py         # Main Textual TUI application (Frontend)
│   ├── daemon.py            # Independent background monitoring process
│   ├── dsl.py              # DSL parser and executor (Lark-based)
│   ├── engine.py           # Background rule evaluation engine
│   ├── models.py           # Core data structures (Rules, etc.)
│   ├── monitoring/
│   │   ├── __init__.py
│   │   └── probes.py       # System metric collection functions
│   ├── plugins/
│   │   ├── __init__.py      # Plugin registry & discovery
│   │   ├── base.py          # Plugin base class
│   │   ├── ec2_plugin.py    # EC2/remote node DSL commands & probes
│   │   ├── docker_plugin.py # Docker container introspection
│   │   ├── webhook_plugin.py # Generic webhook alert action
│   │   ├── discord_plugin.py # Discord webhook action
│   │   └── slack_plugin.py  # Slack webhook action
│   └── ui/
│       ├── __init__.py
│       ├── guide.py        # In-app command guide
│       └── web/            # Web Dashboard frontend (HTML/CSS/JS)
│           ├── index.html
│           ├── dashboard.css
│           └── dashboard.js
└── tests/
    ├── test_dsl.py          # DSL & engine test suite
    ├── test_ec2_agent.py    # EC2 agent, receiver & integration tests
    ├── test_web.py          # Web dashboard & REST API tests
    ├── test_docker.py       # Docker probe tests
    ├── test_plugins.py      # Plugin discovery & routing tests
    └── test_actions.py      # Webhook action tests

=======
│   ├── dashboard.py        # Textual TUI (`nano-dsl`, optional --web)
│   ├── web.py              # Web UI + REST (`nano-web`)
│   ├── daemon.py           # Background rule evaluator
│   ├── dsl.py              # Lark grammar + command executor
│   ├── engine.py           # Metric registry, persistence, cooldowns, plugin actions
│   ├── agent.py            # Remote telemetry pusher
│   ├── receiver.py         # HTTP ingest + NodeStore
│   ├── plugins/            # Docker, EC2, webhook / Slack / Discord
│   ├── monitoring/probes.py
│   └── ui/
│       ├── guide.py        # TUI sidebar guide
│       └── web/            # index.html, dashboard.css, dashboard.js
└── tests/
>>>>>>> upstream/main
```

### Adding a command

1. Grammar + transformer in `nano_logic/dsl.py`  
2. Optional numeric probe in `engine.py` or a plugin `probe_registry`  
3. Optional collector in `monitoring/probes.py`  
4. Guide text in `ui/guide.py`  
5. Tests in `tests/`  

**Adding a plugin:** subclass `PluginBase` in `nano_logic/plugins/`, expose `Plugin = YourClass`. Discovery registers `command_handlers`, `probe_registry`, and `action_registry` on import.

---

## Web Observability Dashboard (Portainer & Grafana Style)

nano-dsl includes a modern, high-performance web dashboard inspired by Portainer and Grafana for visual, real-time observability across your host system, Docker daemon, EC2 fleet, and alert rules.

### Key Capabilities

- 📊 **Overview Dashboard**: High-level KPI summary cards (CPU %, RAM %, Disk %, Docker containers count, EC2 nodes count, firing alert rules) paired with real-time history charts.
- ⚡ **System Metrics Explorer**: Real-time per-core CPU utilization cards, load averages (1m, 5m, 15m), memory & swap breakdown, disk partition storage progress bars, network traffic throughput & active sockets, hardware sensors (temperatures, battery), and top processes by CPU and Memory.
- 🐳 **Docker Engine View (Portainer-Style)**: Live container cards and interactive searchable data table (State badges, container names, image tags, IDs, port mappings, status), Docker images explorer, and daemon metadata.
- ☁️ **EC2 & Remote Fleet Grid**: Multi-node telemetry cards displaying IMDSv2 metadata (Instance ID, Type, AZ, Public/Private IPs), online/stale/offline status pills, and pushed metrics.
- 🚨 **Alert Rules Console**: Real-time evaluation matrix showing each rule's current target metric value against thresholds (Normal vs Alerting), action targets (`log`, `slack`, `discord`, `webhook`), and a live streaming alert history log.
- 💻 **TUI Execution Isolation**: Command and script execution remains strictly inside the terminal TUI (`nano-dsl`) for local safety and process isolation, with an interactive syntax guide built into the web UI.
- ⚡ **Zero External Dependencies**: Built entirely with Python's standard library `http.server.ThreadingHTTPServer` and modern vanilla HTML5/CSS/JS.

### Launching the Web Dashboard

**Option A — Standalone CLI:**
```bash
nano-web --port 5000
# or
python -m nano_logic.web --port 5000
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

**Option B — Together with the TUI:**
```bash
nano-dsl --web
# Launches the TUI in your terminal and starts the web dashboard in the background!
```

### REST API Endpoints

The web server exposes clean REST endpoints queryable by any HTTP client:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | `GET` | Portainer / Grafana style Web UI |
| `/health` | `GET` | Service health status |
| `/api/v1/overview` | `GET` | Consolidated high-speed telemetry snapshot |
| `/api/v1/metrics` | `GET` | Host system metrics, per-core CPU, disk partitions, sensors |
| `/api/v1/rules` | `GET` | Active alert rules, evaluation status, and recent alert logs |
| `/api/v1/docker` | `GET` | Docker daemon state, container list, stats, and images |
| `/api/v1/nodes` | `GET` | Remote EC2 / agent nodes from `NodeStore` |

---

## EC2 & Remote Node Monitoring

nano-dsl can monitor remote EC2 instances (or any Linux server) in real-time using a lightweight push-based agent architecture.

### Quick Start

**1. Start the receiver** (on your local/central machine — auto-started when DSL loads):
```bash
# Standalone mode (optional, the dashboard auto-starts it):
python -m nano_logic.receiver --port 8080
```

**2. Deploy the agent on your EC2 instance:**
```bash
# On the EC2 instance:
pip install nano-dsl   # or clone the repo

# Start pushing metrics:
nano-agent --receiver-url http://<YOUR_IP>:8080/metrics --interval 5

# Or use environment variables:
export NANO_RECEIVER_URL=http://<YOUR_IP>:8080/metrics
export NANO_PUSH_INTERVAL=5
nano-agent
```

**3. Query from the dashboard:**
```
ec2.list               # See all connected nodes
ec2.metrics            # Detailed metrics for the latest node
ec2.metrics i-abc123   # Metrics for a specific instance
ec2.info               # AWS metadata (Instance Type, AZ, IPs)
```

**4. Set alerts on remote metrics:**
```
alert ec2.cpu.util > 80 -> webhook
alert ec2.mem.util > 90 -> discord
alert ec2.disk.usage > 85 -> log
```

### Agent Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NANO_RECEIVER_URL` | `http://localhost:8080/metrics` | Receiver endpoint URL |
| `NANO_PUSH_INTERVAL` | `5` | Push interval in seconds |
| `NANO_NODE_ID` | Auto (IMDSv2 or hostname) | Override node identifier |
| `NANO_AUTH_TOKEN` | None | Optional auth token for push/pull |

### AWS EC2 Auto-Detection

When running on EC2, the agent automatically probes [IMDSv2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html) for:
- Instance ID, Instance Type, Availability Zone, Region
- Public and Private IPv4 addresses

If not on EC2, it gracefully falls back to local hostname and platform info.

---

## Requirements

- Python 3.8+  
- `textual` ≥ 0.58.0  
- `psutil` ≥ 5.9.0  
- `lark` ≥ 1.2.2  
- `pytest` for tests  

See `requirements.txt`. Optional: Docker CLI or SDK for container views; `nvidia-smi` for GPU; systemd for service commands (Linux).

---

## License

MIT
