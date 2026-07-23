# nano-dsl

A lightweight terminal-based system monitoring dashboard with a custom DSL for querying system metrics and managing alert rules.

## Features

- **Custom DSL**: Query various system metrics (CPU, Memory, Disk, Network) with simple, intuitive commands.
- **Alert Rules Management**: Set up custom rules to monitor system metrics dynamically. Name your rules, assign thresholds, and easily stop them when no longer needed.
- **Rule Persistence & Background Daemon**: Alert rules are automatically saved (`rules.json`) and monitored by an independent, invisible background daemon. Your alerts keep running and logging even after you close the dashboard!
- **Dedicated Rule Logs**: Every alert rule gets its own dedicated `<rule_name>.log` file.
- **Real-Time Interactive Dashboard**: A minimalist, beautifully designed TUI (Terminal User Interface) showing live metrics using Textual.
- **Command History**: Cycle through previously used commands using the Up and Down arrow keys.
- **Active Rules Panel**: Dedicated UI component to monitor all running alerts at a glance.

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

**Navigation:**
- Type `exit` or `quit` (or press `q`) to cleanly shut down the dashboard (background rules will keep running!)
- Type commands in the input box at the bottom
- Use the **Up** and **Down** arrow keys to navigate command history
- View results in the command console panel
- Real-time metrics update automatically in the dashboard panels
- Active rules are displayed in a dedicated panel

---

## Alert Rules Management

You can set up background alert rules that monitor specific metrics and trigger an action (e.g., logging) when a threshold is breached.

| Syntax | Description | Example |
|--------|-------------|---------|
| `alert <metric> <operator> <threshold> -> <action>` | Creates an anonymous alert rule | `alert cpu.util > 80 -> log` |
| `<name> : alert <metric> ...` | Creates a named alert rule | `my_mem_rule : alert mem.util > 50 -> log` |
| `stop rule <id>` | Stops an active rule by its auto-assigned ID | `stop rule 1` |
| `stop rule <name>` | Stops an active rule by its custom name | `stop rule my_mem_rule` |

*Note: The only action currently supported is `log` (writes to a dedicated `<rule_name>.log` file in the project directory, and triggers a terminal beep).*

---

## Test DSL Commands (Try these out!)

Here are some test commands you can paste into the dashboard's command input to see the DSL in action:

**1. Basic Queries:**
- `cpu.util`
- `mem.stats`
- `disk.top`
- `proc.list`

**2. Alert Rules (Anonymous):**
- `alert cpu.util > 10 -> log` *(Will trigger quickly if your CPU is over 10%)*
- `alert mem.util > 90 -> log`

**3. Alert Rules (Named):**
- `disk_alert : alert disk.free < 5 -> log`
- `test_rule : alert cpu.util > 5 -> log`

**4. Stopping Rules:**
- `stop rule 1` *(Stops the first rule you created)*
- `stop rule test_rule` *(Stops the rule named 'test_rule')*

**5. Exiting:**
- `exit` *(Closes the dashboard, but leaves background rules running)*

---

## DSL Commands Reference

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

The main dashboard displays real-time metric panels with **ASCII sparkline graphs** showing trends, plus specialized console panels. It uses a minimalist, distraction-free aesthetic:

1. **Disk Usage** - Root filesystem percentage and trend
2. **Network** - Sent/received data totals
3. **System** - Process count and system uptime
4. **Active Rules** - Displays all currently running alert rules (ID, Name, Condition)
5. **Command Console** - Output logs and command history

All metric panels are updated every second.

---

## Project Structure

```
nano-logic/
├── README.md                 # Documentation
├── requirements.txt         # Python dependencies
├── nano_logic/
│   ├── __init__.py
│   ├── dashboard.py         # Main Textual TUI application (Frontend)
│   ├── daemon.py            # Independent background monitoring process
│   ├── dsl.py              # DSL parser and executor (Lark-based)
│   ├── engine.py           # Background rule evaluation engine
│   ├── models.py           # Core data structures (Rules, etc.)
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