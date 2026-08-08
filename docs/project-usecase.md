# Nano-DSL Project Use Case

Nano-DSL is a lightweight terminal-based monitoring and alerting tool for a single machine.
It combines a dashboard, a custom DSL, and a background daemon so you can inspect system state and keep rules running continuously.

## What problem it solves

The project is useful when you want to:

- check system health from a terminal,
- monitor CPU, memory, disk, network, and process activity,
- define alert rules in a simple text format,
- and keep those alert rules active in the background.

It is designed for environments like:

- personal Linux machines,
- Raspberry Pi setups,
- home servers,
- lab systems,
- and other low-resource single-host monitoring setups.

## Typical use cases

### 1. Live system monitoring

Use the dashboard to see current CPU, memory, disk, and network information in one place.

### 2. Lightweight alerting

Create rules that watch a threshold and write an alert when it is crossed.

Example:

`alert disk.free < 10 -> log`

### 3. Background monitoring

Keep rules active even after closing the dashboard. The daemon continues evaluating alerts in the background.

### 4. Process and service inspection

Query running processes, system services, and other operational details without leaving the terminal.

### 5. System administration support

Use it as a quick monitoring shell for checking whether a machine is healthy before you run heavier tools.

## Who should use it

Nano-DSL fits users who want a terminal-first workflow and prefer a simple local monitoring tool over a full observability stack.

It is a better fit than large dashboards when the goal is:

- quick inspection,
- simple threshold alerts,
- and a compact, scriptable interface.

It is not trying to replace enterprise monitoring platforms. Its goal is to stay lightweight and easy to run locally.

## Common workflow

1. Start the dashboard.
2. Check the current system state.
3. Add one or more alert rules.
4. Leave the daemon running in the background.
5. Return later to inspect the dashboard or the alert logs.

## Example scenarios

### Scenario 1: Disk space warning

You want to know when disk space gets low.

Rule:

`low_disk : alert disk.free < 5 -> log`

### Scenario 2: High memory usage

You want to watch memory usage while testing a program.

Rule:

`alert mem.util > 90 -> log`

### Scenario 3: CPU load tracking

You want to monitor a system during a heavy workload.

Query:

`cpu.util`

Alert:

`alert cpu.util > 80 -> log`

### Scenario 4: Process awareness

You want to inspect active processes and search for a specific program name.

Query:

`proc.search python`

## Why the project is useful

The main value is not just showing metrics. The value is that the same terminal language can:

- query live metrics,
- define rules,
- keep rules active,
- and save their state for later.

That makes it practical for small, self-managed systems where you want a simple always-on monitor without deploying a full observability stack.

## What you can demonstrate in a project review

If you are presenting this as a major project, you can demonstrate:

- live system monitoring in the dashboard,
- rule creation and persistence,
- background alert evaluation,
- log generation when a threshold is crossed,
- and command-based interaction through the DSL.

## Short conclusion

Nano-DSL is best described as a terminal-native monitoring shell with alerting. It is useful for quick local checks, continuous threshold monitoring, and lightweight automation on single machines.
