# 🚀 Nano-DSL Execution & Usage Guide

This guide details all available execution modes, commands, required startup order, and DSL testing commands for the **Nano-DSL** observability platform.

---

## 🧹 Step 0: Port Cleanup (If Needed)

If ports `8080` (Receiver) or `5050` (Web Dashboard) are blocked by stuck processes from previous runs, run this cleanup command:

```bash
fuser -k 8080/tcp 5050/tcp 5000/tcp 2>/dev/null || true
```

---

## 🅰️ Mode A: Rich Terminal UI (TUI) Workflow

Run each command in a separate terminal tab in `~/Projects/Nano-DSL-plugin/nano-dsl`.

### **Terminal 1 — Start TUI (Starts Receiver on port 8080)**
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.dashboard
```
> 📌 **Note**: The receiver starts automatically inside the TUI. Keep this terminal running.

### **Terminal 2 — Start EC2 Simulator (Pushes Node Telemetry)**
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python scripts/simulate_ec2.py
```
> 📌 **Note**: Simulates 3 EC2 nodes (`i-0a1b2c3d4e5f67890`, `i-09f8e7d6c5b4a3210`, `i-0deadbeef12345678`) pushing live metrics every 3 seconds.

### **Terminal 3 — Start Web Dashboard (Browser UI)**
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.web --port 5050
```
> 📌 **Access in browser**: Go to [http://localhost:5050](http://localhost:5050) to view real-time node dashboards.

### **Terminal 4 (Optional) — Start Live Machine Agent**
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.web --port 5050
```
> 📌 **Note**: Pushes live metrics from your physical host machine alongside the simulated EC2 nodes.

---

## 🅱️ Mode B: Headless CLI REPL Workflow

If you prefer a plain terminal prompt instead of the full graphical TUI:

### **Terminal 1 — Start Headless CLI Prompt**
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.cli
```

### **Terminal 2 — Start EC2 Simulator**
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python scripts/simulate_ec2.py
```

### **Terminal 3 — Start Web Dashboard**
```bash
cd ~/Projects/Nano-DSL-plugin/nano-dsl
PYTHONPATH=. ./venv/bin/python -m nano_logic.web --port 5050
```

---

## 🧪 DSL Commands Cheat Sheet

Type these commands directly inside the **TUI** or **Headless CLI** prompt (`nano»`):

| Command | Description | Example |
| :--- | :--- | :--- |
| `ec2.list` | List all active EC2/remote nodes and CPU/Memory status | `ec2.list` |
| `ec2.metrics <node_id>` | View telemetry metrics (CPU, Memory, Disk) for a specific node | `ec2.metrics i-0a1b2c3d4e5f67890` |
| `ec2.info <node_id>` | Display system metadata (Instance Type, Region, IP Address) | `ec2.info i-09f8e7d6c5b4a3210` |
| `filter <field> <op> <val>` | Filter connected nodes by threshold | `filter cpu > 50%` |
| `alert <condition> emit ...` | Create an active alert rule | `alert cpu > 80% emit alert "High CPU on EC2 node!"` |
| `status` | Show receiver status, node count, and active rules | `status` |
| `rules` | List all active alert rules | `rules` |
| `help` | Show DSL syntax help guide | `help` |
| `exit` | Quit the CLI REPL | `exit` |

---

## 🏗️ Architecture & Component Summary

- **Receiver (`nano_logic/receiver.py`)**: Runs on port `8080`. Listens for HTTP POST telemetry payload on `/metrics`. Auto-started by TUI or CLI.
- **EC2 Simulator (`scripts/simulate_ec2.py`)**: Generates realistic telemetry streams for multiple EC2 instance types (`t3.medium`, `c5.xlarge`, `r5.large`).
- **Web Dashboard (`nano_logic/web.py`)**: Runs on port `5050`. Renders live visual charts and tables reading directly from the in-memory telemetry node store.
- **Agent (`nano_logic/agent.py`)**: Background daemon collecting real OS metrics via `psutil`.
