# How Nano-DSL Works

Nano-DSL is a lightweight, custom Domain-Specific Language (DSL) built for system monitoring and alert management. It allows users to write intuitive commands to query system metrics (like CPU, RAM, and Disk) and define background alert rules.

## Core Architecture

The system is composed of several key components working together:

### 1. The DSL Parser (`dsl.py`)
At the core of the project is the grammar defined using **Lark** (a modern parsing library for Python). 
- When a user types a command like `alert cpu.util > 80 -> log`, Lark parses this syntax against the `DSL_GRAMMAR` rules.
- The `MetricsTransformer` then processes the generated syntax tree, converting raw tokens into actionable Python objects (like the `Rule` dataclass).

### 2. The Interactive Dashboard (`dashboard.py`)
The frontend is built using **Textual**, a Python framework for creating beautiful Terminal User Interfaces (TUIs). 
- It features an event loop (`_metrics_loop`) that updates ASCII sparklines and metric panels every second by pulling data from the `monitoring/probes.py`.
- It handles user input natively via the `on_input_submitted` event, dynamically passing commands to the `dsl.py` executor and rendering the output in the Command Console.

### 3. The Monitoring Engine (`engine.py`)
The engine acts as the logic bridge between the parser, the probes, and the daemon.
- It provides `evaluate_active_rules()`, which iterates over the `ACTIVE_RULES` list, fetches live metrics, and checks if thresholds are breached.
- It handles Rule Persistence via `save_rules()` and `load_rules()`, converting `Rule` dataclasses to dictionaries and saving them in `rules.json`.

### 4. The Background Daemon (`daemon.py`)
To ensure that alert rules run continuously even when the dashboard UI is closed, the project utilizes an independent daemon process.
- When the dashboard starts, it checks if `daemon.py` is running and spawns it as a detached subprocess if it isn't.
- The daemon continuously polls `rules.json` to stay synced with any rules the user creates or stops in the dashboard.
- Every second, it evaluates the active rules using the engine. If an alert is triggered, it writes the event to a dedicated log file inside the `logs/` directory (e.g., `logs/rule_1.log`) and emits a terminal bell.

## Data Flow Example: Creating a Rule

1. **Input:** The user types `my_rule : alert disk.free < 10 -> log` in the dashboard.
2. **Parsing:** The dashboard passes the string to `execute_command()` in `dsl.py`. The Lark parser matches this to the `named_rule` syntax and returns a `Rule` object.
3. **Activation:** The dashboard adds the `Rule` to `ACTIVE_RULES` and calls `save_rules()`, which writes it to `rules.json`.
4. **Daemon Sync:** The detached `daemon.py` detects a change in `rules.json`, calls `load_rules()`, and updates its own `ACTIVE_RULES` list.
5. **Execution:** The daemon continuously fetches `disk.free` data. If the free space drops below 10GB, it logs the alert to `logs/my_rule.log`.

## Summary
By decoupling the heavy monitoring logic into a background daemon and using Lark for robust DSL parsing, Nano-DSL provides a seamless, Unix-like experience that balances an interactive frontend with reliable background automation.
