# nano-dsl

A lightweight terminal-based system monitoring dashboard with a custom DSL for querying system metrics.

## Getting Started

### Installation

1. Clone the repository:
```bash
git clone https://github.com/ArvindSagar65/nano-dsl.git
cd nano-dsl
```

2. Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

### Running the Dashboard

Start the interactive TUI dashboard:
```bash
.venv/bin/python -m nano_logic.dashboard
```

Or with full path:
```bash
cd ~/Documents/Projects/Tui/Nano-logic && .venv/bin/python -m nano_logic.dashboard
```

**Navigation:**
- Press `q` to quit
- Type commands in the input box at the bottom
- View results in the command console panel
- Real-time metrics update automatically in the 6 dashboard panels

---

## DSL Commands

### CPU Commands

| Command | Description |
|---------|-------------|
| `cpu.util` | Current CPU utilization percentage |
| `cpu.load` | 1/5/15 minute load average (system load) |
| `cpu.cores` | Number of physical and logical CPU cores |
| `cpu.top` | Top 5 processes by CPU usage |

### Memory Commands

| Command | Description |
|---------|-------------|
| `mem.util` | Current memory utilization percentage |
| `mem.stats` | Memory details (used, available, total, swap %) |
| `mem.swap` | Detailed swap memory statistics |
| `mem.top` | Top 5 processes by memory usage |

### Disk Commands

| Command | Description |
|---------|-------------|
| `disk.free` | Free and total disk space for root filesystem (/) |
| `disk.usage` | Disk usage percentage for all mounted partitions |
| `disk.io` | Disk I/O statistics (read/write counts and bytes) |
| `disk.top` | Top directories by storage usage |

### Process Commands

| Command | Description |
|---------|-------------|
| `proc.list` | List all running processes with PIDs |
| `proc.kill <pid>` | Terminate a process by PID (e.g., `proc.kill 1234`) |

### Network Commands

| Command | Description |
|---------|-------------|
| `net.interfaces` | List all network interfaces and their status |
| `net.bandwidth` | Total network bandwidth (sent/received bytes and packets) |
| `net.connections` | Active network connections (total, established, listening) |

### System Commands

| Command | Description |
|---------|-------------|
| `system.uptime` | System uptime in days, hours, and minutes |
| `system.info` | OS, hostname, kernel, and processor information |
| `system.processes` | Total process and thread count |

---

## Dashboard Panels

The main dashboard displays 6 real-time metric panels with **ASCII sparkline graphs** showing trends:

1. **CPU Usage** - Current CPU %, load average, and historical trend
2. **RAM Usage** - Current RAM %, used/total GB, swap %, and trend
3. **GPU Usage** - GPU utilization (if nvidia-smi available)
4. **Disk Usage** - Root filesystem percentage and trend
5. **Network** - Sent/received data totals
6. **System** - Process count and system uptime

All panels are equally sized and updated every second.

---

## Planned Features

Commands to be implemented in future releases:

- 

---

## Project Structure

```
nano-logic/
├── README.md                 # Documentation
├── requirements.txt         # Python dependencies
├── nano_logic/
│   ├── __init__.py
│   ├── dashboard.py         # Main Textual TUI application
│   ├── dsl.py              # DSL parser and executor (Lark-based)
│   ├── monitoring/
│   │   ├── __init__.py
│   │   ├── probes.py       # System metric collection functions
│   │   └── __pycache__/
│   └── ui/
│       ├── __init__.py
│       ├── guide.py        # In-app command guide
│       └── __pycache__/
└── __pycache__/
```

---

## Requirements

- Python 3.8+
- `textual` >= 0.58.0 - Terminal user interface framework
- `psutil` >= 5.9.0 - System and process utilities
- `lark` >= 1.2.2 - DSL parsing library

See `requirements.txt` for full dependency list.

---

## License

MIT