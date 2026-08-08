# How to Add New Commands to Nano-DSL

This guide explains how to extend Nano-DSL with new commands that users can type in the dashboard.

## Overview

Commands in Nano-DSL follow a three-part structure:
- **Namespace**: `cpu`, `mem`, `disk`, `net`, `system`, etc.
- **Dot separator**: `.`
- **Metric name**: `util`, `load`, `stats`, etc.

Example: `cpu.util`, `disk.free`, `mem.stats`

## Architecture Checklist

Commands flow through these layers:

1. **Grammar Definition** (`dsl.py` - `DSL_GRAMMAR`) — defines allowed syntax
2. **Transformer Methods** (`dsl.py` - `MetricsTransformer` class) — executes the command logic
3. **Metrics Registry** (`engine.py` - `_METRIC_REGISTRY`) — for alert rule evaluation
4. **Monitoring Probes** (`monitoring/probes.py`) — collects raw system data

## Step-by-Step: Adding a New Command

### 1. Add to the Grammar (`dsl.py`)

In the `DSL_GRAMMAR` section, add your command rule. For example, to add `net.bandwidth`:

```python
net_cmd: "net" "." "interfaces"   -> net_interfaces
       | "net" "." "bandwidth"    -> net_bandwidth  # ← NEW
       | "net" "." "connections"  -> net_connections
```

**Rule**: Use the pattern `"namespace" "." "metric" -> handler_name`

The handler name (after `->`) should be descriptive and match the transformer method you'll write next.

### 2. Add a Transformer Method (`dsl.py` - inside `MetricsTransformer` class)

Each grammar rule needs a corresponding transformer method:

```python
def net_bandwidth(self, _children: list) -> str:
    """Return network bandwidth statistics."""
    try:
        # Call your monitoring probe to get raw data
        net_io = psutil.net_io_counters()
        bytes_sent = net_io.bytes_sent / (1024 ** 2)  # Convert to MB
        bytes_recv = net_io.bytes_recv / (1024 ** 2)
        return f"Network Bandwidth: Sent={bytes_sent:.1f}MB, Received={bytes_recv:.1f}MB"
    except Exception as e:
        return f"Error: {e}"
```

**Key points**:
- Method name must match the handler name from grammar (e.g., `net_bandwidth`)
- Accept `_children: list` parameter (Lark convention)
- Return a **string** (this goes to the dashboard display)
- Wrap logic in try-except to handle errors gracefully
- Use helper functions from `monitoring/probes.py` if complex logic is needed

### 3. Register a Metric for Alert Rules (Optional - if alerts should use this metric)

In `engine.py`, register your metric in the `_METRIC_REGISTRY` so alert rules can check it:

```python
def _get_net_bandwidth_mb() -> float:
    """Return current network bandwidth in MB/s."""
    net_io = psutil.net_io_counters()
    return (net_io.bytes_sent + net_io.bytes_recv) / (1024 ** 2)

_register_metric("net.bandwidth", _get_net_bandwidth_mb)
```

Then users can write rules like:
```
alert net.bandwidth > 100 -> log
```

### 4. Add Complex Logic to Probes (If needed - `monitoring/probes.py`)

For complex data gathering, create a dedicated function in `probes.py`:

```python
def get_network_stats():
    """Gather detailed network statistics."""
    net_io = psutil.net_io_counters()
    return {
        "sent_mb": net_io.bytes_sent / (1024 ** 2),
        "recv_mb": net_io.bytes_recv / (1024 ** 2),
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv,
    }
```

Then call it from your transformer:

```python
def net_bandwidth(self, _children: list) -> str:
    stats = get_network_stats()
    return f"Network: Sent={stats['sent_mb']:.1f}MB, Recv={stats['recv_mb']:.1f}MB"
```

## Example: Adding `disk.health`

Here's a complete example:

**1. Add to grammar:**
```python
disk_cmd: "disk" "." "free"    -> disk_free
        | "disk" "." "usage"   -> disk_usage
        | "disk" "." "health"  -> disk_health  # ← NEW
```

**2. Add transformer method:**
```python
def disk_health(self, _children: list) -> str:
    """Report disk health status."""
    try:
        usage = psutil.disk_usage("/")
        if usage.percent < 50:
            status = "✓ Good"
        elif usage.percent < 80:
            status = "⚠ Warning"
        else:
            status = "✗ Critical"
        return f"Disk Health: {status} ({usage.percent:.1f}% used)"
    except Exception as e:
        return f"Error: {e}"
```

**3. Register metric (optional):**
```python
_register_metric("disk.health", lambda: psutil.disk_usage("/").percent)
```

## Testing Your Command

1. Open the dashboard
2. Type your new command: `disk.health`
3. Press Enter and verify output appears
4. Write a test in `tests/test_dsl.py`:

```python
def test_disk_health_command():
    from nano_logic.dsl import parser, MetricsTransformer
    tree = parser.parse("disk.health")
    transformer = MetricsTransformer()
    result = transformer.transform(tree)
    assert isinstance(result, str)
    assert "Disk" in result or "Error" in result  # Either works or gracefully errors
```

## Namespace Conventions

Use these namespaces for organization:

- `cpu.*` — CPU and load metrics
- `mem.*` — Memory and swap usage
- `disk.*` — Disk space and I/O
- `proc.*` — Process management
- `net.*` — Network and connections
- `system.*` — System-wide info
- `sensor.*` — Temperature, battery, fans
- `docker.*` — Container stats
- `service.*` — Service status

## Common Patterns

**Return a single value:**
```python
def disk_free(self, _children: list) -> str:
    free_gb = psutil.disk_usage("/").free / (1024 ** 3)
    return f"Disk Free: {free_gb:.1f}GB"
```

**Return multiple stats:**
```python
def mem_stats(self, _children: list) -> str:
    mem = psutil.virtual_memory()
    return (
        f"Memory Stats:\n"
        f"  Used: {mem.used / (1024 ** 3):.1f}GB\n"
        f"  Available: {mem.available / (1024 ** 3):.1f}GB\n"
        f"  Percent: {mem.percent:.1f}%"
    )
```

**Return a sorted list:**
```python
def proc_top(self, _children: list) -> str:
    try:
        top5 = get_top_processes_by_cpu(limit=5)
        result = "Top 5 Processes by CPU:\n"
        for pid, name, cpu in top5:
            result += f"  {pid} | {name} | {cpu:.1f}%\n"
        return result.strip()
    except Exception as e:
        return f"Error: {e}"
```

## Checklist

- [ ] Added grammar rule to `DSL_GRAMMAR`
- [ ] Implemented transformer method in `MetricsTransformer`
- [ ] Method returns a string (for dashboard display)
- [ ] Wrapped logic in try-except
- [ ] (Optional) Registered metric in `_METRIC_REGISTRY` for alerts
- [ ] (Optional) Added helper to `monitoring/probes.py` if logic is complex
- [ ] Tested in dashboard
- [ ] Added test case to `tests/test_dsl.py`
