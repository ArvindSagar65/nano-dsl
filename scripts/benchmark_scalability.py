#!/usr/bin/env python3
"""Automated Scalability & Concurrent Rule Benchmark for Nano-Logic.

Measures:
1. Parse Latency (Lark compilation into ASTs)
2. Evaluation Loop Latency (in-memory snapshot vs AST evaluation)
3. CPU Overhead (%) and Resident Memory (RSS in MB)
across N = 1, 10, 25, 50, 100 concurrent rules.

Leaves all existing rules and configurations untouched.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import psutil

# Ensure project root is in path
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nano_logic import engine
from nano_logic.dsl import execute_command, parse_command
from nano_logic.models import Rule


def run_benchmark():
    print("=" * 72)
    print("  🚀 Nano-Logic Concurrent Rule Scalability & Stress Benchmark")
    print("=" * 72)

    # Backup existing rules to guarantee zero side effects
    original_rules = list(engine.ACTIVE_RULES)
    original_rules_file = engine.RULES_FILE
    
    # Use temporary file for test runs
    temp_rules_file = Path(tempfile.gettempdir()) / f"nano_bench_rules_{os.getpid()}.json"
    engine.RULES_FILE = temp_rules_file

    process = psutil.Process(os.getpid())
    rule_tiers = [1, 5, 10, 25, 50, 100]

    results = []

    print(f"\nBenchmarking on Host: {sys.platform} | Python {sys.version.split()[0]} | PID: {process.pid}")
    print(f"{'Rules (N)':<10} | {'Parse Time (ms)':<16} | {'Per-Rule Parse (μs)':<20} | {'Eval Loop (ms)':<15} | {'CPU (%)':<10} | {'RSS (MB)':<10}")
    print("-" * 92)

    try:
        for n in rule_tiers:
            engine.ACTIVE_RULES.clear()

            # 1. Benchmark Parsing / AST compilation
            rule_texts = [
                f"rule_{i}: alert {'cpu.util' if i % 2 == 0 else 'mem.util'} > {30 + (i % 60)} -> log"
                for i in range(n)
            ]

            t_parse_start = time.perf_counter()
            for text in rule_texts:
                rule_obj = execute_command(text)
                if isinstance(rule_obj, Rule):
                    engine.add_rule(rule_obj)
            total_parse_ms = (time.perf_counter() - t_parse_start) * 1000
            per_rule_parse_us = (total_parse_ms / n) * 1000

            # 2. Benchmark Evaluation Loop (100 cycles to measure average per tick)
            # Run 5 warmup cycles first
            for _ in range(5):
                engine.evaluate_active_rules(cooldown_seconds=0.0)

            t_eval_start = time.perf_counter()
            cycles = 100
            for _ in range(cycles):
                engine.evaluate_active_rules(cooldown_seconds=0.0)
            avg_eval_ms = ((time.perf_counter() - t_eval_start) / cycles) * 1000

            # 3. Resource Utilization
            cpu_pct = process.cpu_percent(interval=0.05)
            mem_info = process.memory_info()
            rss_mb = mem_info.rss / (1024 * 1024)

            results.append({
                "n": n,
                "total_parse_ms": round(total_parse_ms, 2),
                "per_rule_parse_us": round(per_rule_parse_us, 1),
                "eval_loop_ms": round(avg_eval_ms, 3),
                "cpu_percent": round(cpu_pct, 1),
                "rss_mb": round(rss_mb, 1),
            })

            print(
                f"{n:<10} | {total_parse_ms:<16.2f} | {per_rule_parse_us:<20.1f} | "
                f"{avg_eval_ms:<15.3f} | {cpu_pct:<10.1f} | {rss_mb:<10.1f}"
            )

    finally:
        # Restore original state perfectly
        engine.ACTIVE_RULES.clear()
        engine.ACTIVE_RULES.extend(original_rules)
        engine.RULES_FILE = original_rules_file
        if temp_rules_file.exists():
            temp_rules_file.unlink(missing_ok=True)

    print("\n" + "=" * 72)
    print("  ✅ Benchmark Complete — Real empirical numbers measured successfully!")
    print("=" * 72)
    return results


if __name__ == "__main__":
    run_benchmark()
