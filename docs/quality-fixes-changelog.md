# Quality Fixes Changelog

Every code-quality fix implemented on top of the review in
[architecture-and-review.md](architecture-and-review.md), in the order committed. All commits
preserve existing public API and DSL behavior except where fixing an actual bug. Each entry links
back to the review finding it addresses where applicable.

Run `git log --oneline` for the exact commit range; hashes below are for reference.

---

## `c714128` — fix: correct docker.\* grammar and mem_cached formatting bug

Addresses review findings **#9** (Docker grammar inconsistency) and **#10** (`mem_cached` fragile
ternary).

The `docker_cmd` grammar rule required `"docker ps"` (space) while every other namespace uses dotted
syntax, and the README/guide/tests all already documented `"docker.ps"`/`"docker.stats"` — those
commands never actually parsed. Aligned the grammar with the documented syntax.

Also fixed `mem_cached`'s ternary-inside-format-spec, which silently depended on operator precedence
working out; replaced with a plain `getattr` default so the GiB conversion always applies uniformly.

**Files:** `nano_logic/dsl.py`

---

## `367e9ad` — fix: resolve rules.json and logs/ via XDG state dir, not CWD

Addresses review finding **#7** (working directory dependence).

`rules.json` and `logs/` were hardcoded as relative paths, so their location silently depended on
whatever directory each process happened to be launched from. The dashboard spawns the daemon
without an explicit `cwd`, so this worked by accident (inherited cwd) rather than by design, and
would break as soon as either process was launched from elsewhere (a symlinked binary, a systemd
unit, a different terminal).

Added `nano_logic/paths.py` to resolve a proper state directory (`$XDG_STATE_HOME/nano-dsl`,
defaulting to `~/.local/state/nano-dsl`), and routed `engine.py`/`daemon.py`/`dashboard.py` through
it. `$NANO_DSL_STATE_DIR` overrides it for tests/sandboxing.

**Files:** `nano_logic/paths.py` (new), `nano_logic/engine.py`, `nano_logic/daemon.py`,
`nano_logic/dashboard.py`, `tests/test_dsl.py`, `README.md`

---

## `5f09bc4` — fix: replace racy process-scan daemon check with an flock() singleton

Addresses review finding **#1** (daemon proliferation race).

The dashboard decided whether to spawn the daemon by scanning `psutil.process_iter()` for a matching
cmdline, then spawning if none was found. That check-then-spawn is not atomic: two dashboard
instances (two terminals, a crashed-and-restarted session) launched close together can both observe
"not running" and both spawn a daemon, after which every alert rule fires and logs twice.

Added `daemon_lock.py`, which wraps the daemon's run loop in an `flock()`'d PID file — a
kernel-arbitrated mutex, so only one daemon can ever hold it. The dashboard now always attempts to
spawn the daemon; a redundant spawn just fails to acquire the lock and exits immediately instead of
racing.

**Files:** `nano_logic/daemon_lock.py` (new), `nano_logic/daemon.py`, `nano_logic/dashboard.py`

---

## `2eb74b8` — fix: add cooldown to alert evaluation to stop repeat-firing floods

Addresses review finding **#2** (no alert deduplication).

`evaluate_active_rules()` had no concept of "already alerted" or "still breached, don't repeat." If
`disk.free < 10` was true, the daemon appended to `logs/<rule>.log` and rang the terminal bell once
per second, indefinitely, until the condition cleared or the rule was stopped.

Added a per-rule last-fired timestamp and suppress re-firing within a cooldown window (default 60s),
resetting it as soon as the condition clears so a rule re-arms promptly rather than staying
suppressed by a stale cooldown. `remove_rule()` also clears the tracked state so it doesn't
accumulate entries for deleted rules.

> **Follow-up caveat found via live testing:** a 60s *global* cooldown combined with an easily
> breached, low threshold (e.g. `cpu.util > 3`) makes real-time alerting feel throttled/delayed —
> see [live-debugging-findings.md](live-debugging-findings.md#cooldown-vs-low-threshold-interaction)
> and the per-rule cooldown proposal in
> [roadmap-not-implemented.md](roadmap-not-implemented.md#per-rule-configurable-alert-cooldown).

**Files:** `nano_logic/engine.py`, `tests/test_dsl.py`

---

## `7d389f1` — fix: log instead of silently discarding background-process failures

Addresses review finding **#5** (silent failure by design).

`save_rules()`, `load_rules()`, the daemon's log-write/bell/monitor-loop paths, and the dashboard's
daemon-spawn all caught broad exceptions and discarded them with a bare `pass`. There is no terminal
attached to the daemon and nothing in the codebase used the logging module, so a disk-full, a
permissions error, or a corrupted `rules.json` produced zero observable signal — rules could
silently fail to persist while the UI still reported success.

Added `logging_config.py` (a shared file handler under the state directory, `nano-dsl.log`) and
wired it into `engine.py`/`daemon.py`/`dashboard.py`. Narrowed a couple of bare `except Exception` to
the specific exception types actually expected (`OSError`, `JSONDecodeError`) so genuinely
unexpected errors aren't swallowed by accident.

**Files:** `nano_logic/logging_config.py` (new), `nano_logic/paths.py`, `nano_logic/engine.py`,
`nano_logic/daemon.py`, `nano_logic/dashboard.py`

---

## `fcfdea2` — fix: centralize rule-id assignment, fix id/name removal ambiguity

Addresses review finding **#6** (rules keyed on per-process counter).

Rule id assignment lived in the dashboard's `on_input_submitted` as a UI-instance counter
(`self.rule_counter`), entirely separate from `engine.py`'s rule storage — so nothing actually
enforced that ids stay unique, it just happened not to collide in the common single-dashboard case.
Moved it into `engine.add_rule()`, which derives the next id from `ACTIVE_RULES` itself, so the
invariant holds regardless of caller.

Also fixed `remove_rule()`: matching on `str(rule.id) == identifier or rule.name == identifier` in
one pass meant a rule named `"3"` could shadow removal of the rule whose actual id is 3, depending on
list order. Id matches are now checked first, deterministically.

**Files:** `nano_logic/engine.py`, `nano_logic/dashboard.py`, `tests/test_dsl.py`

---

## `26a5118` — refactor: delegate process-iteration commands to monitoring/probes.py

Addresses review finding **#8** (duplicated process-iteration logic).

`probes.py`'s own docstring states probes should be "pure data gatherers... no formatting or display
logic," but `cpu_top`, `mem_top`, `proc_list`, and `proc_search` in `dsl.py` each re-implemented
their own `psutil.process_iter` loop (with the same `NoSuchProcess`/`AccessDenied` handling
copy-pasted four times) instead of calling into it.

Added `get_all_processes`/`get_top_processes_by_cpu`/`get_top_processes_by_memory` to `probes.py`
alongside the existing `get_process_by_name`, and had the transformer methods format their output
instead of re-fetching it. Output format is unchanged.

**Files:** `nano_logic/dsl.py`, `nano_logic/monitoring/probes.py`

---

## `825ef8a` — test: isolate test state dir and remove live-DNS dependency

Addresses review finding **#11** (tests exercise real system state).

The suite had two real-environment dependencies masquerading as unit tests: it wrote
`rules.json`/`logs/`/`nano-dsl.log` wherever pytest happened to run from (the real
`~/.local/state/nano-dsl` after the XDG change above), and `test_net_dns_returns_string` performed an
actual DNS lookup against `google.com` — which fails or hangs offline, airgapped, or behind
restrictive DNS policy, all realistic conditions for this project's own target environments (homelab,
NAS, isolated VPS).

Added `conftest.py` to point `$NANO_DSL_STATE_DIR` at a throwaway tempdir for the whole suite (set at
module scope so it's in place before `nano_logic.engine` is first imported), and mocked
`socket.gethostbyname_ex` for the DNS test instead of hitting the network. Added a companion test for
the lookup-failure path, which wasn't covered before.

**Files:** `tests/conftest.py` (new), `tests/test_dsl.py`

---

## `81c6e65` — build: add pyproject.toml with packaging metadata and lint/type config

Addresses review finding **#12** (no type checking configured) and part of §8 (dev experience).

The project had no packaging metadata at all — dependencies lived only in `requirements.txt`, with
no console-script entry point, and no lint or type-check configuration existed anywhere, so the type
hints already used throughout the codebase were never actually enforced.

Added project metadata (mirroring `requirements.txt`), a `nano-dsl` console script pointing at the
existing `dashboard.main()`, and ruff/mypy config. mypy starts permissive
(`disallow_untyped_defs = false`) given nothing has enforced hints before now — tightening it is a
follow-up, not a prerequisite for having the config exist at all.

**Files:** `pyproject.toml` (new)

---

## `0bd96d7` — chore: remove dead code surfaced by ruff

Small cleanup pass using the ruff config just added: an unused `deque` import and an unused
`command_log` local in `dashboard.py`, an unused `time` import in `probes.py`, unused
`DSL_GRAMMAR`/`parser` imports in `test_dsl.py`, a redundant explicit `"r"` mode on an already
read-only `open()` in `engine.py`, and one stray trailing whitespace in the grammar string. No
behavior change.

**Files:** `nano_logic/dashboard.py`, `nano_logic/monitoring/probes.py`, `nano_logic/engine.py`,
`nano_logic/dsl.py`, `tests/test_dsl.py`

---

## `c2d4a7c` — feat: surface daemon-fired alerts in the dashboard console + bell

New feature, not a code-quality fix — implemented on explicit request after discovering the
dashboard gave no in-app signal when an alert fired (see
[live-debugging-findings.md](live-debugging-findings.md#alerts-were-invisible-from-the-dashboard)).

The dashboard's Active Rules panel only ever rendered a rule's static definition and its metrics loop
never called `evaluate_active_rules()` — only the separate daemon process does that — so a rule
firing was completely invisible from the dashboard. The daemon's own terminal bell was also silently
discarded, since the dashboard spawns it with `stdout`/`stderr` redirected to `DEVNULL`.

The only thing shared between the two processes is the filesystem, so the dashboard's existing 1s
metrics loop now tails each active rule's own log file (byte-offset tracked per rule id) and, for any
new `"[ALERT]"` line the daemon wrote since the last tick, prints it to the Command Console and rings
the terminal bell via Textual's own `App.bell()` — which the dashboard, unlike the backgrounded
daemon, actually owns a terminal for. A newly-added or newly-loaded rule starts tracking from the
current end of its log file, so pre-existing alerts aren't replayed when the dashboard starts.

**Files:** `nano_logic/dashboard.py`, `tests/test_dsl.py`

---

## `f8e4b5b` — fix: fetch each metric only once per evaluation tick, not once per rule

A correctness bug found via live testing, not present in the original static review — see
[live-debugging-findings.md](live-debugging-findings.md#the-100-cpu-phantom-readings).

`evaluate_active_rules()` called `fetch_metric_value(rule.metric)` independently for every active
rule, so N rules watching the same metric meant N calls per tick. For "since last call" metrics —
`cpu.util` is `psutil.cpu_percent(interval=None)` — the first call in a tick measures a real ~1s
window, but the second/third call microseconds later measures a near-zero elapsed slice. Linux's
clock-tick CPU accounting (~10ms resolution) quantizes that into garbage readings like exactly 0%,
50%, or 100%, regardless of actual load — confirmed against a live run where two rules alerted at
100.0% while the real system was at 9.2% CPU.

Cached each distinct metric's value once per `evaluate_active_rules()` call so every rule referencing
it in that tick sees the same, correctly-measured reading.

**Files:** `nano_logic/engine.py`, `tests/test_dsl.py`

---

## `81024b9` — fix: stop dashboard tests from leaking real daemon subprocesses

A bug introduced by the `c2d4a7c` test additions, caught immediately via live process inspection —
see [live-debugging-findings.md](live-debugging-findings.md#tests-were-leaking-real-daemon-processes).

`SystemDashboardApp.on_mount()` unconditionally spawns a real `python -m nano_logic.daemon`
subprocess. The dashboard alert-notification tests instantiate the app via Textual's
`App.run_test()`, which calls `on_mount()` for real — so every test run spawned an actual daemon
process pointed at that run's throwaway tmp state dir. Since each one successfully acquires its own
PID-file lock, it never exits on its own: running the suite repeatedly silently leaked one
permanently-running background process per run.

Patched `nano_logic.dashboard.subprocess.Popen` to a no-op for these two tests so mounting the app no
longer spawns anything real.

**Files:** `tests/test_dsl.py`

---

## Summary

| Metric | Value |
|---|---|
| Commits | 12 |
| Files touched | 13 (`paths.py`, `daemon_lock.py`, `logging_config.py`, `conftest.py` new) |
| Tests at start | 155 |
| Tests at end | 164 |
| Review findings closed | 10 of 12 fully closed, 1 partially addressed (#4), 1 deliberately deferred (#3 — see roadmap) |
| Bugs found only via live testing (not in original static review) | 3 (metric-per-tick caching, alert visibility gap, test daemon leak) |
