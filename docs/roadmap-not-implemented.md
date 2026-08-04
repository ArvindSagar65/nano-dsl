# Roadmap — Not Yet Implemented

Everything in this document is a proposal only. Nothing here has been implemented — these are
future-direction ideas, ranked by priority, kept separate from
[quality-fixes-changelog.md](quality-fixes-changelog.md) (which lists what *was* actually built) on
purpose so the codebase's current, real behavior is never confused with what's proposed.

---

## Deferred from the original review (still open)

### `service.status`/`proc.kill` command allow-listing

**Priority: High · Complexity: Low–Medium**

`service_status` and `proc_kill` currently let any dashboard user query the status of *any* systemd
unit or terminate any process the OS user can signal, with no allow-list and no confirmation step.
See [architecture-and-review.md §2, finding #3](architecture-and-review.md#2-code-review--ranked-findings).

**Why it's not implemented:** restricting these commands is a genuine behavior change to the DSL
(some currently-valid commands would start being rejected), and needs a product decision most
engineers can't make unilaterally: what's on the allow-list? Is it configurable per-deployment? Does
`proc.kill` need a `--force`/confirmation flag instead of an outright ban? This is a design question
for the maintainer, not a mechanical fix.

**Sketch of an approach**, for whoever picks this up: an opt-in config file
(`~/.config/nano-dsl/allowed-services.txt` or similar) that `service.status` checks against, defaulting
to "no restriction" so existing single-user homelab usage isn't broken, with a loud warning in the
README about multi-user exposure. `proc.kill` could gain a same-user-only check (compare the target
process's UID to the current user) as a much lower-risk default than an allow-list.

---

### `RuleStore` — full encapsulation of rule state

**Priority: Medium · Complexity: Medium**

`ACTIVE_RULES` is still a bare module-level list (`nano_logic/engine.py`), mutated directly by
`dashboard.py`, `daemon.py`, and tests. Id assignment is now centralized (`engine.add_rule()`), which
closes the most concrete part of the original finding, but the list itself still isn't encapsulated —
there's no way to enforce other invariants (e.g. "no two rules with the same name"), and it can't be
swapped for a real datastore (SQLite, an embedded KV store) without touching every call site.

**Why it's not implemented:** a full class wrap (`RuleStore` with `.add()`/`.remove()`/`.all()`)
touches `dashboard.py`, `daemon.py`, and the entire test suite's direct-list-mutation pattern — a
large blast radius for an app that's currently single-threaded per process and has no actual
concurrency bug today. Doing this now would be premature abstraction; worth revisiting once/if
multi-host or plugin support (below) actually needs a real storage interface.

---

## DSL grammar additions

*(See [architecture-and-review.md §5](architecture-and-review.md#5-dsl-redesign-proposals) for the
original set. Complexity estimates assume implementing each in isolation; several share
infrastructure — see notes.)*

| Feature | Example | Priority | Complexity |
|---|---|---|---|
| Time windows | `alert cpu.util > 80 for 5m -> log` | High | Medium |
| Boolean composition | `alert cpu.util > 80 and mem.util > 90 -> log` | High | Medium |
| **Per-rule configurable alert cooldown** | `alert cpu.util > 3 -> log cooldown 10s` | **High** | **Low** |
| Multiple actions | `-> log, webhook, discord` | High | Low–Medium |
| Aggregation functions | `cpu.avg(5m)`, `disk.free.min(1h)` | Medium | High (shares time-series infra with time windows) |
| Scheduling | `every 5m check docker.ps -> notify` | Medium | Medium |
| Rule files / imports | `import "rules/disk.ndsl"` | Medium | Medium |
| Pipelines/filters | `proc.list \| filter cpu>20 \| sort -cpu` | Medium | High |
| Macros/templates | `template disk_low(path, pct) = alert disk.free(path) < pct -> log` | Low | Medium |

### Per-rule configurable alert cooldown *(added after live testing — see below)*

**Priority: High · Complexity: Low**

The engine now has a global 60-second cooldown (`DEFAULT_ALERT_COOLDOWN_SECONDS` in `engine.py`) to
stop a persistently-breached rule from flooding its log/bell every tick — see the
[`2eb74b8` changelog entry](quality-fixes-changelog.md#2eb74b8--fix-add-cooldown-to-alert-evaluation-to-stop-repeat-firing-floods).
Live testing surfaced a real tradeoff this creates: a rule with a low, easily-breached threshold
(e.g. `alert cpu.util > 3 -> log` on a machine that's essentially always above 3% CPU) almost never
sees its condition *clear*, so the cooldown almost never resets — the rule ends up firing exactly
once every 60 seconds like a metronome, which reads as "delayed" or "not real-time" even though
detection is genuinely happening every second. Full writeup:
[live-debugging-findings.md](live-debugging-findings.md#cooldown-vs-low-threshold-interaction).

There's currently no way to change this without editing `engine.py`'s constant, and it's global
across every rule regardless of how tight or loose that rule's own threshold is.

**Proposed syntax:**
```
alert cpu.util > 3 -> log cooldown 10s
alert disk.free < 5 -> log cooldown 5m
```
Falling back to the current 60s default when `cooldown` is omitted, preserving existing rule syntax
exactly.

**Implementation sketch:**
- Grammar: extend the `anon_rule`/`named_rule` productions in `DSL_GRAMMAR` (`dsl.py`) with an
  optional `"cooldown" NUMBER TIME_UNIT` clause after `ACTION`.
- `models.Rule`: add a `cooldown_seconds: float = DEFAULT_ALERT_COOLDOWN_SECONDS` field.
- `engine.evaluate_active_rules()`: read `rule.cooldown_seconds` per rule instead of taking a single
  `cooldown_seconds` parameter applied uniformly.
- `MetricsTransformer.anon_rule`/`named_rule`: parse the optional cooldown clause, converting
  `NUMBER` + unit (`s`/`m`/`h`) to seconds.

This is a small, self-contained, low-risk addition — no architecture change, no new files, and it
directly fixes a real usability issue found during this project's own live testing rather than a
speculative feature.

---

## Industry / production features

*(See [architecture-and-review.md §6](architecture-and-review.md#6-roadmap--industry-features-not-implemented-as-of-this-review)
for the original prioritized list. Reproduced here with status notes.)*

| Priority | Feature | Status |
|---|---|---|
| ~~High~~ | ~~Alert cooldown / deduplication~~ | ✅ Implemented (global; per-rule version proposed above) |
| ~~High~~ | ~~PID-file-based daemon singleton~~ | ✅ Implemented (`daemon_lock.py`) |
| High | `systemd` unit file for the daemon | Not implemented — natural follow-up to the PID-lock work; makes the daemon a real managed service instead of a dashboard-spawned subprocess |
| High | Webhook + Discord/Slack/Telegram actions | Not implemented |
| High | YAML rule-file support (declarative, alongside the DSL) | Not implemented |
| Medium | Prometheus exporter mode | Not implemented |
| Medium | Headless/CLI mode (no TUI) for cron and scripts | Not implemented |
| Medium | Plugin/custom-probe API | Not implemented |
| Medium | SMART / disk-health probes | Not implemented |
| Low | REST/WebSocket API | Not implemented |
| Low | OpenTelemetry export | Not implemented |
| Low | Docker image / packaging (deb, AUR, Homebrew) | Not implemented |

---

## Testing gaps still open

- **No CI** (`.github/workflows` still absent) — `pyproject.toml`'s ruff/mypy config exists but
  nothing runs it automatically on push/PR.
- **No fuzz/property tests on the parser** — the grammar is small and pure (no side effects during
  parsing), a natural fit for Hypothesis, but this wasn't added.
- **`mypy` is permissive** (`disallow_untyped_defs = false`) — tightening it incrementally, module by
  module, is a follow-up rather than a blocker for having the config exist.
