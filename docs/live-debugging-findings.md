# Live Debugging Findings

The static review in [architecture-and-review.md](architecture-and-review.md) was a read of the
code. It missed things that only became visible by actually running the dashboard and daemon against
a real system and watching real output — this document is that record. Each entry includes the
question that surfaced it, the investigation, the root cause, and what happened as a result.

---

## Alerts were invisible from the dashboard

**Question asked:** "If an alert gets triggered, how will the user know from the DSL dashboard?"

**Investigation:** Traced the dashboard's `_metrics_loop` (`dashboard.py`) and found it only calls
`refresh_metrics()` every second — never `evaluate_active_rules()`, which is exclusively called by
the separate daemon process. The Active Rules panel (`update_rules_panel`) only renders each rule's
static definition (id, name, condition) and is only re-rendered on add/remove, never on a refresh
loop, so it had no "last fired" state to show even if it did refresh. The daemon's only two signals
when a rule fires were writing to `logs/<rule>.log` and a terminal bell
(`sys.stdout.write('\a')`) — but the dashboard spawns the daemon with
`stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`, so that bell went straight into the void.

**Root cause:** No code path existed connecting "the daemon fired a rule" to anything the dashboard
process could observe, beyond a file on disk the dashboard never read.

**Resolution:** Implemented in `c2d4a7c` — the dashboard now tails each active rule's log file every
tick and surfaces new `[ALERT]` lines via the Command Console + Textual's `App.bell()`. See
[quality-fixes-changelog.md](quality-fixes-changelog.md#c2d4a7c--feat-surface-daemon-fired-alerts-in-the-dashboard-console--bell).

---

## The 100% CPU phantom readings

**Question asked:** "My CPU is not reaching 100%, yet it shows 100 and triggers `> 3` — where is the
number 100 coming from?" (Backed by a screenshot showing the real system monitor at 9.2% CPU while
the dashboard logged `cpu.util reached 100.0`.)

**Investigation:** Reproduced directly:

```python
import psutil, time
psutil.cpu_percent(interval=None)   # warm up baseline
time.sleep(1)
psutil.cpu_percent(interval=None)   # call 1 (after ~1s): 12.2  — sane
psutil.cpu_percent(interval=None)   # call 2 (immediately after): 0.0  — garbage
psutil.cpu_percent(interval=None)   # call 3 (immediately after): 0.0  — garbage
```

`psutil.cpu_percent(interval=None)` measures usage *since the last time it was called*, using
process-global state. `evaluate_active_rules()` looped over every active rule and called
`fetch_metric_value(rule.metric)` independently — with three rules all watching `cpu.util`, that's
three back-to-back calls within the same tick. The first call (whichever rule happens to be evaluated
first) measures a real ~1s window and returns a sane value; the second and third calls, microseconds
later, measure a near-zero elapsed slice. Linux's CPU accounting only updates at clock-tick
granularity (~10ms); when the elapsed time between two `cpu_percent()` calls is smaller than that,
the "busy fraction" gets quantized into extreme, round artifacts (0%, 50%, 100%) depending on whether
a tick happened to land in that sub-millisecond window — not a reflection of real load at all.

This exactly explained the observed pattern: the rule evaluated first each tick (`rule_1`) showed
realistic values (10–20%); the rules evaluated after it (`rule_2`, `rule_3`) showed almost
exclusively `0.0`, `50.0`, or `100.0` — quantization artifacts, not real CPU load.

**Root cause:** `engine.py`'s `evaluate_active_rules()` fetched each metric once per *rule* instead
of once per *tick*, so any metric shared by 2+ rules got measured multiple times per second with
each measurement after the first being effectively meaningless for "since last call"-style metrics.

**Resolution:** Implemented in `f8e4b5b` — metrics are now cached once per evaluation tick and shared
across every rule referencing them. Verified post-fix: three rules all watching `cpu.util` in the
same tick now all report the identical, real value. See
[quality-fixes-changelog.md](quality-fixes-changelog.md#f8e4b5b--fix-fetch-each-metric-only-once-per-evaluation-tick-not-once-per-rule).

---

## Tests were leaking real daemon processes

**Context:** Not something the user asked about directly — caught while investigating the CPU
phantom-readings report above, when `ps aux | grep nano_logic.daemon` turned up four running daemon
processes instead of the expected one.

**Investigation:** Cross-referenced each process's environment (`/proc/<pid>/environ`) against its
`NANO_DSL_STATE_DIR`. One process had no override (the real, legitimately-running daemon backing the
user's actual dashboard session). The other three each had a distinct `/tmp/nano-dsl-test-*` state
dir — matching the `tempfile.mkdtemp(prefix="nano-dsl-test-")` pattern from `tests/conftest.py`.

`SystemDashboardApp.on_mount()` unconditionally spawns `python -m nano_logic.daemon` via
`subprocess.Popen`. The dashboard alert-notification tests added in `c2d4a7c` instantiate the app
through Textual's `App.run_test()`, which calls `on_mount()` for real — meaning every test run spawned
an actual, real daemon subprocess pointed at that pytest invocation's throwaway state dir. Because
each one successfully acquires its own `flock()`'d PID-file lock (no conflict — different state
dirs), none of them ever exit on their own. Running the test suite repeatedly silently leaked one
permanently-running background process per run.

**Root cause:** A test exercising real app-mounting behavior (correctly, for what it was testing)
had an un-mocked side effect — spawning a real subprocess — that had no corresponding cleanup.

**Resolution:** Implemented in `81024b9` — `nano_logic.dashboard.subprocess.Popen` is patched to a
no-op for the two tests that mount the full app. Killed the three leaked processes and their tmp
state dirs as part of the same investigation; verified with a full suite run afterward that no new
daemon processes remained. See
[quality-fixes-changelog.md](quality-fixes-changelog.md#81024b9--fix-stop-dashboard-tests-from-leaking-real-daemon-subprocesses).

---

## Cooldown vs. low-threshold interaction

**Question asked:** "I added `alert cpu.util > 3 -> log`, and it works, but after so long — my CPU
hit above 3 multiple times but it only records occasionally, and the trigger feels delayed, not
real-time — why?"

**Investigation:** Real log excerpt showed the rule firing at `23:36:22`, `23:37:22`, `23:38:22` —
each exactly 60 seconds apart, regardless of how many times the underlying condition was actually
breached in between. Traced to the cooldown logic added in `2eb74b8`:

```python
if not op_fn(current_val, rule.threshold):
    _last_triggered_at.pop(rule.id, None)   # cooldown only resets here
    continue
...
if now - last_fired < cooldown_seconds:      # otherwise suppressed for 60s
    continue
```

The cooldown only resets when the rule's condition *clears* (metric drops back below threshold).
`cpu.util > 3` is such a low bar that CPU essentially never drops below it on an active machine — the
condition never clears, so the cooldown never resets, and the rule fires once then stays suppressed
for the full 60 seconds every time, like a metronome.

**Root cause:** Not a bug — the cooldown (added specifically to fix the flood-firing issue in
finding #2 of the original review) is working exactly as designed. But its interaction with a low,
easily-breached threshold produces behavior indistinguishable from "broken/delayed alerting" from a
user's perspective, because detection is genuinely happening every second (the daemon's poll loop
latency is real-time) while *reporting* is throttled to once per cooldown window regardless of
severity or repeat-breach frequency.

**Resolution:** Not yet implemented — proposed as a per-rule, DSL-configurable cooldown rather than a
single global constant. See
[roadmap-not-implemented.md](roadmap-not-implemented.md#per-rule-configurable-alert-cooldown).

---

## Log/rule-state location confusion after the XDG state-dir change

**Question asked:** "Why are no logs being created for `alert cpu.util > 10 -> log`? Are the rules
even working?"

**Investigation:** Checked the daemon process and the new state directory
(`~/.local/state/nano-dsl/`) directly — `rules.json`, `logs/rule_1.log` etc. all existed and were
being actively written to, with alerts firing correctly. The rules were working; the user was
checking a `logs/` folder inside the project directory, which is where logs lived *before* the
`367e9ad` XDG state-dir fix.

**Root cause:** Not a bug — a legitimate behavior change (fixing CWD-dependence, see
[architecture-and-review.md, finding #7](architecture-and-review.md#2-code-review--ranked-findings))
relocated where state lives, and that wasn't obvious from the dashboard's own UI (nothing in the
dashboard tells the user where its state directory is).

**Resolution:** README already documents the new location
(`$XDG_STATE_HOME/nano-dsl/logs/`, defaulting to `~/.local/state/nano-dsl/logs/`). No code change —
flagged here mainly because it's a real point of confusion worth being aware of for anyone
upgrading from a pre-XDG-fix checkout, and because a `status`/`guide` command surfacing the resolved
state directory path would be a small, cheap discoverability improvement worth considering (not
currently on the roadmap as a distinct item — low-effort enough to fold into whatever touches
`cmd_status`/`cmd_guide` next).
