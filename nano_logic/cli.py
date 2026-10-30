"""Headless CLI REPL for nano-dsl — no TUI required.

A plain terminal read-eval-print loop that accepts DSL commands,
auto-starts the metrics receiver in the background, and optionally
launches the web dashboard.  Perfect for SSH sessions, CI pipelines,
or environments without curses/Textual support.

Usage:
    PYTHONPATH=. python -m nano_logic.cli
    PYTHONPATH=. python -m nano_logic.cli --web --web-port 5050
"""
from __future__ import annotations

import os
import readline  # noqa: F401 — enables arrow-key history in input()
import signal
import sys
from datetime import datetime

from lark.exceptions import LarkError

from nano_logic.dsl import execute_command
from nano_logic.engine import (
    ACTIVE_RULES,
    add_rule,
    evaluate_active_rules,
    load_rules,
    remove_rule,
)
from nano_logic.logging_config import configure_logging
from nano_logic.models import Rule, StopRule
from nano_logic.paths import get_logs_dir
from nano_logic.receiver import get_or_start_receiver

logger = configure_logging(__name__)

BANNER = r"""
 ╔══════════════════════════════════════════════════════════════╗
 ║              nano-dsl  ·  Headless CLI Mode                 ║
 ║                                                             ║
 ║  Type DSL commands directly.  Try: help                     ║
 ║  Type 'exit' or Ctrl+C to quit.                             ║
 ╚══════════════════════════════════════════════════════════════╝
"""

# ANSI colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _print_result(result: str | Rule | StopRule | None) -> None:
    """Format and print a DSL command result."""
    if isinstance(result, Rule):
        add_rule(result)
        print(
            f"{GREEN}✅ Rule '{result.name}' (ID: {result.id}) activated: "
            f"Monitor {result.metric} {result.operator} {result.threshold} -> {result.action}{RESET}"
        )
        # Create the log file
        try:
            log_path = get_logs_dir() / f"{result.name}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] --- Rule '{result.name}' Activated ---\n")
        except OSError:
            pass

    elif isinstance(result, StopRule):
        if remove_rule(result.identifier):
            print(f"{YELLOW}🛑 Rule '{result.identifier}' stopped.{RESET}")
        else:
            print(f"{YELLOW}⚠️  Rule '{result.identifier}' not found.{RESET}")

    elif result == "__CLEAR__":
        os.system("clear" if os.name != "nt" else "cls")

    elif result:
        print(str(result))

    else:
        print(f"{DIM}No output{RESET}")


def _probe_receiver(port: int = 8080) -> dict | None:
    """Probe a receiver's /health endpoint. Returns parsed JSON or None."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


def _print_status() -> None:
    """Print current receiver and rules status."""
    from nano_logic.receiver import get_active_server

    server = get_active_server()
    if server and server.is_running:
        node_count = server.store.count_online()
        total = len(server.store.list_nodes())
        print(f"{GREEN}📡 Receiver: ACTIVE on http://{server.host}:{server.port}{RESET}")
        print(f"   Nodes: {node_count} online / {total} total")
    else:
        # Try probing common ports for an external receiver
        for port in (8080, 8081):
            health = _probe_receiver(port)
            if health:
                print(f"{GREEN}📡 Receiver: ACTIVE (external) on http://localhost:{port}{RESET}")
                print(f"   Nodes: {health.get('nodes_online', '?')} online / {health.get('nodes_total', '?')} total")
                return
        print(f"{YELLOW}📡 Receiver: NOT RUNNING{RESET}")

    if ACTIVE_RULES:
        print(f"\n{CYAN}⚡ Active Rules ({len(ACTIVE_RULES)}):{RESET}")
        for r in ACTIVE_RULES:
            print(f"   [{r.id}] {r.name}: alert {r.metric} {r.operator} {r.threshold} -> {r.action}")
    else:
        print(f"\n{DIM}No active alert rules.{RESET}")


def repl_loop() -> None:
    """Main read-eval-print loop."""
    while True:
        try:
            command_text = input(f"{CYAN}nano» {RESET}").strip()
        except EOFError:
            print()
            break

        if not command_text:
            continue

        if command_text.lower() in {"exit", "quit", "q"}:
            break

        if command_text.lower() == "status":
            _print_status()
            continue

        if command_text.lower() == "rules":
            if ACTIVE_RULES:
                for r in ACTIVE_RULES:
                    print(f"  [{r.id}] {r.name}: alert {r.metric} {r.operator} {r.threshold} -> {r.action}")
            else:
                print(f"{DIM}No active alert rules.{RESET}")
            continue

        if command_text.lower() == "check":
            triggered = evaluate_active_rules(cooldown_seconds=0)
            if triggered:
                for rule, val in triggered:
                    print(f"{RED}🔔 ALERT: {rule.name} — {rule.metric} = {val} (threshold: {rule.operator} {rule.threshold}){RESET}")
            else:
                print(f"{GREEN}✅ All rules OK — no alerts triggered.{RESET}")
            continue

        try:
            result = execute_command(command_text)
            _print_result(result)
        except LarkError as exc:
            print(f"{RED}Parse error: {exc}{RESET}")
        except Exception as exc:
            print(f"{RED}Execution error: {exc}{RESET}")


def main() -> None:
    """CLI entrypoint for headless mode."""
    import argparse

    parser = argparse.ArgumentParser(description="nano-dsl Headless CLI (no TUI)")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Also launch the web dashboard in background",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=int(os.environ.get("NANO_WEB_PORT", "5000")),
        help="Port for the web dashboard (default: 5000)",
    )
    parser.add_argument(
        "--receiver-port",
        type=int,
        default=int(os.environ.get("NANO_RECEIVER_PORT", "8080")),
        help="Port for the metrics receiver (default: 8080)",
    )
    parser.add_argument(
        "--no-receiver",
        action="store_true",
        help="Don't auto-start the metrics receiver",
    )
    args = parser.parse_args()
    os.environ["NANO_RECEIVER_PORT"] = str(args.receiver_port)

    # Load persisted alert rules
    load_rules()

    # Auto-start receiver
    if not args.no_receiver:
        try:
            server = get_or_start_receiver(port=args.receiver_port)
            print(f"{GREEN}📡 Metrics receiver started on http://0.0.0.0:{args.receiver_port}{RESET}")
        except OSError:
            # Port is taken — check if it's already our receiver
            health = _probe_receiver(args.receiver_port)
            if health:
                print(f"{GREEN}📡 Receiver already active on port {args.receiver_port} "
                      f"({health.get('nodes_online', 0)} nodes online){RESET}")
            else:
                print(f"{YELLOW}⚠️  Port {args.receiver_port} is in use by another service."
                      f" Try: --receiver-port {args.receiver_port + 1}{RESET}")

    # Optionally start web dashboard
    if args.web:
        try:
            from nano_logic.web import get_or_start_web_server

            get_or_start_web_server(port=args.web_port)
            print(f"{GREEN}🌐 Web dashboard started on http://localhost:{args.web_port}{RESET}")
        except Exception:
            print(f"{YELLOW}⚠️  Could not start web dashboard on port {args.web_port}{RESET}")

    print(BANNER)
    _print_status()
    print()

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, lambda *_: (print(f"\n{DIM}Use 'exit' to quit or press Ctrl+C again.{RESET}"), None))

    try:
        repl_loop()
    except KeyboardInterrupt:
        pass

    print(f"\n{DIM}Goodbye! 👋{RESET}")
    sys.exit(0)


if __name__ == "__main__":
    main()
