# nano-dsl

A lightweight system-monitoring toolkit with a custom DSL, a Textual TUI, a background alert daemon, optional Docker/EC2 plugins, and a companion web observability dashboard.

Commands that change the machine (kill a process, create a rule, start the receiver) run in the **TUI**. The **web UI** is read-only telemetry.

## Features

- **Custom DSL** — Query CPU, memory, disk, GPU, processes, network, sensors, systemd, Docker, and remote EC2 nodes with short dotted commands (`cpu.util`, `docker.ps`, `ec2.list`).
- **45+ commands** across 11 namespaces, parsed with Lark (LALR).
- **Alert rules** — `name: alert <metric> <op> <threshold> -> <action>` with operators `>`, `<`, `==`, `>=`, `<=`.
- **Alert actions** — Built-in `log` (per-rule log file + terminal bell). Plugin actions: `webhook`, `slack`, `discord` (URLs from environment variables).
- **Background daemon** — Rules persist in `rules.json` (XDG state dir) and keep evaluating after you close the TUI.
- **Textual TUI** — Live disks/network/system panels, in-app guide, command history, active-rules panel, clipboard copy.
- **Web dashboard** (`nano-web`) — Overview KPIs, per-core CPU, Docker tables, EC2 fleet cards, live alert status. Standard-library HTTP server; Chart.js loaded from CDN.
- **EC2 / remote nodes** — `nano-agent` pushes metrics to `nano-receiver`; query with `ec2.list` / `ec2.metrics` / `ec2.info`.
- **Plugin registry** — Drop-in `PluginBase` modules for commands, numeric probes, and alert actions.

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

**Rules:** `disk_alert: alert disk.free < 5 -> log` · `alert ec2.cpu.util > 80 -> webhook` · `stop rule disk_alert`

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
```

### Adding a command

1. Grammar + transformer in `nano_logic/dsl.py`  
2. Optional numeric probe in `engine.py` or a plugin `probe_registry`  
3. Optional collector in `monitoring/probes.py`  
4. Guide text in `ui/guide.py`  
5. Tests in `tests/`  

**Adding a plugin:** subclass `PluginBase` in `nano_logic/plugins/`, expose `Plugin = YourClass`. Discovery registers `command_handlers`, `probe_registry`, and `action_registry` on import.

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
