# nano-dsl: Engineering & Product Review

*Full-repo review — architecture, ranked code findings, product positioning, market gap analysis,
DSL redesign proposals, and a roadmap. Written as a review only; none of it was implemented at the
time it was written (see [quality-fixes-changelog.md](quality-fixes-changelog.md) for what was
actually implemented afterward, and [roadmap-not-implemented.md](roadmap-not-implemented.md) for
what deliberately wasn't).*

**Scope at review time:** ~2,540 LOC, 8 modules, 1 test file. Stack: Python 3.8+, Lark, Textual, psutil.

---

## 1. Architecture & data flow

Four cooperating pieces, no framework glue holding them together beyond shared module state:

```
dashboard.py (Textual TUI)          daemon.py (detached process)
       │  execute_command()                │  evaluate_active_rules()
       ▼                                    ▼
   dsl.py  ──── Lark LALR grammar ────  MetricsTransformer
       │  parses "cpu.util" / "alert x > y -> log" / "stop rule 1"
       ▼
   engine.py ── ACTIVE_RULES (module-level list, process-local)
       │              │
       │       fetch_metric_value() via _METRIC_REGISTRY
       ▼              ▼
  rules.json     monitoring/probes.py ── psutil / subprocess (docker, systemctl, du)
  (file-based IPC between dashboard and daemon)
```

The dashboard, on mount, checks (by scanning `psutil.process_iter` for a matching cmdline) whether
`daemon.py` is already running, and if not, forks it as a detached subprocess. From then on the
dashboard and the daemon are two independent processes that never talk directly — they synchronize
*only* through `rules.json`, polled once a second by mtime comparison. This is a deliberate,
low-tech IPC choice and it mostly works, but it's also the seam most of the correctness findings
below live in.

The DSL itself is two things wearing one grammar: a **query language** (`cpu.util`, `disk.free` —
read-only, string-formatted for humans) and a **rule-definition language**
(`alert metric op threshold -> action`). `engine.py` keeps a second, parallel registry
(`_METRIC_REGISTRY`) of the same metrics but as raw numeric getters, because the transformer's job
is to produce formatted strings, not numbers. That split is the right call — it's why alerts can
evaluate `cpu.util` without re-parsing a formatted string — but it means every metric that should be
alertable has to be defined twice, in two files, in two shapes.

---

## 2. Code review — ranked findings

Findings below are things worth actually raising in review, not style nits. Ranked High → Low.
*(Status column added after the fact — see the changelog for what happened to each.)*

| # | Severity | Finding | Location | Status |
|---|----------|---------|----------|--------|
| 1 | **High** | Daemon proliferation race — multiple daemons can spawn and double-fire every alert | `dashboard.py:154-169` | ✅ Fixed |
| 2 | **High** | No alert deduplication — a breached rule fires every second forever | `daemon.py:22-33`, `engine.py:151-169` | ✅ Fixed |
| 3 | **High** | Unbounded, unauthenticated command execution surface via `service.status`/`proc.kill` | `dsl.py:595-600` | ⏳ Not implemented (policy decision required — see roadmap) |
| 4 | Medium | Global mutable state makes the engine untestable in isolation and unsafe under future concurrency | `engine.py:10`, `dashboard.py`, `daemon.py`, `test_dsl.py:257` | 🟡 Partially addressed |
| 5 | Medium | Silent failure by design — nearly every I/O path swallows exceptions with bare `except: pass` | `engine.py:22-23,36-37`; `daemon.py:32-33,39-40,42-44`; `dashboard.py:168-169` | ✅ Fixed |
| 6 | Medium | Rules are keyed on a mutable in-memory counter that resets per-process | `dashboard.py:172-173,293-294` | ✅ Fixed |
| 7 | Medium | Working directory dependence — `rules.json` and `logs/` are relative paths | `engine.py:11`, `dashboard.py:307`, `daemon.py:28-29` | ✅ Fixed |
| 8 | Low | Duplicated process-iteration and formatting logic between `dsl.py` and `monitoring/probes.py` | `dsl.py:176-191,232-247` vs `probes.py:117-131` | ✅ Fixed |
| 9 | Low | Docker grammar is inconsistent with every other namespace | `dsl.py:81-82` | ✅ Fixed |
| 10 | Low | `mem_cached`'s conditional expression is fragile | `dsl.py:249-255` | ✅ Fixed |
| 11 | Low | Tests exercise real system state, not fixtures — flaky on minimal/CI hosts | `test_dsl.py:240-245,166-169` | ✅ Fixed |
| 12 | Low | No type checking configured; type hints present but unenforced | repo-wide | ✅ Fixed (config added; hints not yet strict) |

### Detail

**1. Daemon proliferation race (High).** The "is the daemon already running" check greps
`psutil.process_iter` for a cmdline containing `daemon.py`, with no lock file, no PID file, and no
atomicity between the check and the `Popen`. Launch two dashboard instances within the same second
(two terminal tabs, a crashed-and-restarted session, tmux panes), and both will observe "not
running" and both will spawn a daemon. Two live daemons then both tail `rules.json`, both evaluate
the same rules every second, and every alert gets logged and beeped twice — silently, with no error
anywhere. There's also nothing that ever kills a stray daemon; `pgrep`-and-orphan is the only way a
user finds out.

**2. No alert deduplication (High).** `evaluate_active_rules()` has no concept of "already alerted"
or "still breached, don't repeat." If `disk.free < 10` is true, the daemon appends to
`logs/<rule>.log` and rings the terminal bell once per second, indefinitely, until the condition
clears or the rule is stopped. On a genuinely full disk that's 86,400 log lines and bell characters
a day from one rule. This isn't a nice-to-have cooldown — it's the difference between an alerting
tool and a very slow log-flooding tool.

**3. Unbounded, unauthenticated command execution surface (High).** `service_status` takes a
free-form `CMD` token (regex `[a-zA-Z0-9_.\-\/]+`) and passes it straight into
`systemctl status <service>.service` via `subprocess.run` with a list argv (no shell, so no classic
injection) — that part is done correctly. But there is zero allow-listing: any user of the dashboard
can query the status of *any* unit on the box, including ones they have no business seeing (other
users' user-services, security-relevant daemons), and `proc.kill <pid>` similarly lets the DSL
terminate any process the OS user has permission to signal, with no confirmation step. In a
single-user homelab context this is fine; the moment this tool is exposed to any second user (a
shared NAS, a team Pi), it's an unguarded privilege surface. **Left unimplemented deliberately** —
restricting these commands changes DSL behavior and needs a product decision on what an acceptable
allow-list looks like.

**4. Global mutable state (Medium).** `ACTIVE_RULES` is a bare module-level list, mutated from the
dashboard's input handler, the daemon's poll loop, and directly from tests
(`ACTIVE_RULES.clear()` in `setup_method`). It works today because each process is single-threaded
and cooperative, but it means the rule list can't be wrapped in a class, can't have invariants
enforced (e.g. "IDs are unique"), and can't be swapped for a real datastore without touching every
call site. **Partially addressed**: id assignment/uniqueness is now centralized in
`engine.add_rule()`, but `ACTIVE_RULES` itself is still a bare module-level list — a full `RuleStore`
class wrap was judged premature abstraction for the app's current single-process-per-role scale.

**5. Silent failure by design (Medium).** `save_rules()`, `load_rules()`, log-file writes, the
terminal bell, and the daemon's outer loop all caught broad `Exception` and discarded it. The
comment on `save_rules` — "don't corrupt TUI" — showed the intent (keep the UI alive), but the cost
was that a disk-full, a permissions error, or a JSON corruption bug produced *zero* signal to the
user. There was no logging module anywhere in the codebase.

**6. Rules keyed on a per-process counter (Medium).** `rule_counter` lived on the dashboard instance
and was seeded from `max(r.id for r in ACTIVE_RULES)` at startup. If the dashboard restarted while
the daemon was still alive and later created a new rule, nothing enforced that ids stayed unique
across the two processes' views. `remove_rule` also did a linear scan matching by string equality on
both id and name, so a rule named `"3"` and rule ID `3` were ambiguous to `stop rule 3`.

**7. Working directory dependence (Medium).** `RULES_FILE = "rules.json"` and `logs/` were both
relative to whatever CWD the process was launched from. The daemon was launched via
`subprocess.Popen([sys.executable, "-m", "nano_logic.daemon"], ...)` without an explicit `cwd=`, so
it inherited the dashboard's CWD at spawn time — worked by accident, not by design, and would have
broken the moment this became a systemd service or was invoked from a different directory.

**8. Duplicated process-iteration logic (Low).** `probes.py`'s own docstring says probes "should be
pure data gatherers... no formatting or display logic" — a rule `dsl.py` didn't actually follow.
`cpu_top`, `mem_top`, `proc_list`, and `proc_search` in the transformer each re-implemented their own
`psutil.process_iter` loop, with the same `NoSuchProcess`/`AccessDenied` handling copy-pasted four
times.

**9. Docker grammar inconsistency (Low).** Every other namespace used dotted `ns.command`
(`cpu.util`, `sensor.temp`), but Docker used `docker ps` / `docker stats` with a space, mirroring
the real CLI instead of the DSL's own grammar. README and `guide.py`'s help text (`docker.ps`) both
disagreed with the actual grammar (`docker ps` — no dot), so the documented command didn't parse — a
real bug a new user would hit on the very first Docker command tried from the README.

**10. `mem_cached` fragile ternary (Low).**
`f"buffers={_format_gib(mem.buffers) if hasattr(mem, 'buffers') else 0:.2f}GiB"` — the format spec
`:.2f` applied to the whole conditional expression; fragile and easy to misread.

**11. Tests exercise real system state (Low).** `test_net_dns_returns_string` did a live DNS lookup
to `google.com` — fails or hangs offline, airgapped, or behind restrictive firewall policy, all
realistic conditions for this project's own target audience (Raspberry Pis, NAS boxes, VPSes with no
outbound DNS by policy). Zero mocking anywhere in the suite.

**12. No type checking configured (Low).** Type hints were used fairly consistently
(`from __future__ import annotations`, return-type annotations throughout `probes.py` and
`engine.py`), but nothing enforced them — no `mypy`/`pyright` config, no `pyproject.toml` at all.

---

## 3. Product review — who is this for, actually?

The honest pitch at review time was: *"htop plus a query language, plus alerts that beep and write
a log file."* Held up against the incumbents, that's a hard sell:

- **vs. htop / btop** — They're faster to glance at and need zero syntax. Typing `cpu.top` to get
  what a keypress gives you in htop is strictly slower.
- **vs. Prometheus + Grafana** — Real time-series storage, real dashboards, real alerting
  (Alertmanager has dedup, silencing, routing). nano-dsl's alerting was a `for`-loop with a bell.
- **vs. Netdata** — Auto-discovers everything, ships hundreds of collectors, has a web UI out of the
  box, zero-config. nano-dsl requires knowing the DSL up front.
- **vs. Cockpit** — Cockpit is the "manage my one Linux box" story already, with a web UI, systemd
  integration, and no syntax to learn.

The project's *only* asset none of those five have is the DSL itself — a typed, composable,
scriptable query-and-rule language you can paste into a terminal, chain in scripts, or eventually
run headless. Every other feature (panels, sparklines, a TUI) is a weaker copy of something that
already exists and is better at it.

**The redesign, then, isn't "add more probes" — it's "stop competing as a dashboard and start
competing as a programmable monitoring shell."**

---

## 4. Market gap analysis

Where a DSL genuinely beats a dashboard is anywhere the *action* matters more than the *view* —
homelab and edge contexts where you want one CLI-native tool that can express "when X, do Y" without
standing up Prometheus + Alertmanager + Grafana + node_exporter for a single Raspberry Pi.

| Gap | Why dashboards lose here |
|-----|---------------------------|
| Docker/container health watchdogs on a home server | Netdata/Grafana show you a red graph after the container's already been down 5 minutes; a DSL rule can restart it inline. |
| Backup verification (rsync/restic/borg jobs) | No dashboard tool treats "did last night's backup actually complete and was the size sane" as a first-class metric — it's always a bolt-on script. |
| SSD/disk health (SMART) on a NAS | Full observability stacks are overkill for "email me before the drive dies," and Grafana/Prometheus need a SMART exporter installed separately. |
| Single-board / Pi cluster fleets | Full Prometheus stack is heavy for a 512MB-RAM Pi Zero; a single lightweight daemon with a script-like rule file fits the resource envelope. |
| "Programmable" runbooks (if X and Y for 5m then Z) | Alertmanager can route, but composing conditions and remediation actions in one readable line is the DSL's actual differentiator. |

The common thread: **action-oriented, low-resource, single-host automation** — not visualization.
That's a real, underserved niche between "grep a log by hand" and "stand up the Prometheus stack."

---

## 5. DSL redesign proposals

Grammar review of `DSL_GRAMMAR` (`dsl.py:15-99`): it's a clean LALR grammar, one token type per
concept, sensible use of Lark's alias syntax (`->` rule names) to route straight to transformer
methods. Its ceiling, though, is that it only expresses instants — there's no way to say "for 5
minutes," no boolean composition of conditions, no pipelines, no aggregation.

| Feature | Example | Value | Complexity |
|---------|---------|-------|------------|
| Time windows | `alert cpu.util > 80 for 5m -> log` | Kills false positives from momentary spikes — the single highest-value addition | Medium |
| Boolean composition | `alert cpu.util > 80 and mem.util > 90 -> log` | Real incidents are conjunctions, not single thresholds | Medium |
| Aggregation functions | `cpu.avg(5m)`, `disk.free.min(1h)` | Needs a ring-buffer metric history (doesn't exist today — everything is instantaneous) | High |
| Pipelines/filters | `proc.list \| filter cpu>20 \| sort -cpu` | Turns static commands into a query language, not just a lookup table | High |
| Scheduling | `every 5m check docker.ps -> notify` | Cron-like triggers decoupled from "always-on threshold," useful for periodic checks (backup verification, SMART scans) | Medium |
| Multiple actions | `-> log, webhook, discord` | Today only `log` exists; this is the DSL's stated "more coming" from `guide.py:80` | Low–Medium |
| Rule files / imports | `import "rules/disk.ndsl"` | Declarative rule sets checked into dotfiles/ansible instead of typed interactively | Medium |
| Macros/templates | `template disk_low(path, pct) = alert disk.free(path) < pct -> log` | Reusable rule shapes across many disks/hosts | Medium |
| **Per-rule alert cooldown** *(added post-review — see below)* | `alert cpu.util > 3 -> log cooldown 10s` | The engine now has a global 60s cooldown to stop flood-firing (see changelog); a low, easily-breached threshold makes that cooldown feel like "delay." Making it per-rule and DSL-configurable resolves the tradeoff without picking one global value for every use case. | Low |

Keep the existing three-token dotted namespace (`ns.command`) — it's the DSL's best trait,
consistent and guessable.

---

## 6. Roadmap — industry features (not implemented as of this review)

Ranked by leverage against the "programmable monitoring shell" identity above, not by novelty.
*(See [roadmap-not-implemented.md](roadmap-not-implemented.md) for the up-to-date version of this
list, including items identified after this review was written.)*

| Priority | Feature | Why | Complexity |
|----------|---------|-----|------------|
| High | Alert cooldown / deduplication | Fixes the log-flooding correctness bug found above; table stakes for any alerting tool | Low |
| High | PID-file-based daemon singleton + `systemd` unit | Fixes the double-daemon race; makes the daemon a real service instead of a fork-and-hope subprocess | Low–Medium |
| High | Webhook + Discord/Slack/Telegram actions | The single most-requested feature type for any homelab tool; "beeps and writes a file" isn't alerting you'll trust | Medium |
| High | YAML rule-file support (declarative, alongside the DSL) | Lets rules live in dotfiles/ansible/git, not just typed into a TUI that has to be open | Medium |
| Medium | Prometheus exporter mode (`nano-dsl export --port 9100`) | Interop, not competition — lets existing Grafana users pull nano-dsl's custom/DSL-derived metrics without abandoning their stack | Medium |
| Medium | Headless/CLI mode (no TUI) for cron and scripts | The DSL's real advantage only shows up if it runs without a terminal open — `nano-dsl run "cpu.util"` as a one-shot | Low–Medium |
| Medium | Plugin/custom-probe API | Backup verification, SMART health, GPU-workstation metrics all belong as plugins, not core — keeps the core small | High |
| Medium | SMART / disk-health probes | Directly serves the NAS/homelab niche identified above | Medium |
| Low | REST/WebSocket API | Nice for a future web companion, but the CLI-native/no-daemon-overhead story is the differentiator — a heavy API surface cuts against "lightweight" | High |
| Low | OpenTelemetry export | Real value only once there's more than one host to correlate — premature before multi-host support exists at all | High |
| Low | Docker image / packaging (deb, AUR, Homebrew) | Matters a lot for adoption, but only after the daemon/PID-file story above is solid — packaging a race condition just ships it faster | Low–Medium |

Note: "Alert cooldown / deduplication" and "PID-file-based daemon singleton" were subsequently
implemented — see the changelog.

---

## 7. Performance & security notes

- **Repeated psutil calls, no caching.** `cpu_percent(interval=0.5)` and similar blocking calls
  appeared directly in transformer methods — each DSL query paid its own ~0.2–0.5s psutil sampling
  window. Fine for one-shot queries, but pipelines composing multiple metrics in one command would
  add up.
- **1s poll loop, no backoff.** Both the dashboard's `_metrics_loop` and the daemon's evaluation loop
  are a flat `time.sleep(1)` — reasonable defaults, but not configurable. *(Note: the "every rule
  re-runs its own `fetch_metric_value` call" half of this finding was later found to be a real
  correctness bug, not just an efficiency one — see
  [live-debugging-findings.md](live-debugging-findings.md).)*
- **`subprocess.run` usage is consistently safe.** Every shell-out (docker, systemctl, du,
  nvidia-smi, ps) uses list-form argv, no `shell=True` anywhere in the codebase — correctly defended
  against injection throughout.
- **No secrets/config surface yet.** Nothing in the codebase touches credentials today, so there's
  no secrets-management gap — but it becomes one the moment webhook/Discord/Telegram actions land.

---

## 8. Developer experience & testing

`working.md` and the README's "Adding a New Command" section were genuinely good signs — a project
that already documented its own extension points, which most projects this size don't bother with.
What was missing to make it feel production-grade:

- No CI (`.github/workflows` absent) — the test suite never actually ran anywhere but a
  contributor's machine.
- No `pyproject.toml` — dependencies lived only in `requirements.txt`, no packaging metadata, no
  console-script entry point.
- No lint/format config (ruff/black), no pre-commit.
- Test suite had zero mocking — an integration suite dressed as a unit suite; genuinely valuable but
  mislabeled, and needed a fixture layer before it could safely run in CI on minimal/offline hosts.
- No fuzz/property tests on the parser despite it being hand-fed regex tokens (`CMD`, `RULE_NAME`) —
  a natural fit for Hypothesis given the grammar is already small and pure. *(Still not implemented
  — see roadmap.)*

---

## 9. Verdict

The code was better than the pitch. Grammar design, module boundaries, and the
metric-registry/transformer split all showed real engineering judgment for a young project — the
problems found were the ones you'd expect at this stage (races around the daemon, no dedup, silent
failure), not fundamental design rot. The product problem was the one worth solving first: as a
dashboard, this loses to five mature tools on every axis; as a programmable, low-resource automation
shell for homelabs and edge boxes, it has no direct competitor. Recommendation was to fix the
High-severity correctness issues (daemon race, alert dedup, unguarded process/service commands)
before anything else, then build the roadmap around `for`-windows, boolean rules, and notification
actions rather than more read-only probes.
