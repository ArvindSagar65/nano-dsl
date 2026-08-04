# nano-dsl Documentation

Documentation produced from a full-repo engineering review and the subsequent implementation work,
kept separate from the top-level [`README.md`](../README.md) (user-facing usage docs) and
[`working.md`](../working.md) (architecture walkthrough).

| Document | What's in it |
|---|---|
| [architecture-and-review.md](architecture-and-review.md) | The original full review: architecture & data flow, ranked code findings, product positioning vs. htop/Prometheus/Netdata/Cockpit, market gap analysis, DSL redesign proposals, roadmap, performance & security notes, dev experience gaps, and a verdict. |
| [quality-fixes-changelog.md](quality-fixes-changelog.md) | Every code-quality fix actually implemented, one entry per commit, each linked back to the review finding it addresses. Includes the fixes found only through live testing (not in the original static review). |
| [live-debugging-findings.md](live-debugging-findings.md) | Issues found by actually running the dashboard and daemon against a real system — the CPU phantom-readings bug, the alert-visibility gap, a test-suite process leak, and the cooldown/low-threshold interaction — each with the investigation that found it and its resolution (or roadmap link, if unresolved). |
| [roadmap-not-implemented.md](roadmap-not-implemented.md) | Everything proposed but not built: the deferred `service.status`/`proc.kill` allow-listing decision, the `RuleStore` encapsulation, DSL grammar additions (time windows, boolean composition, per-rule cooldown, etc.), and the industry-feature backlog (webhooks, YAML rules, Prometheus export, plugin API, ...). Nothing in this file reflects the codebase's current real behavior. |

## Reading order

If you're new to this: [architecture-and-review.md](architecture-and-review.md) first for context
on why things are the way they are, then [quality-fixes-changelog.md](quality-fixes-changelog.md) to
see what changed since. [live-debugging-findings.md](live-debugging-findings.md) and
[roadmap-not-implemented.md](roadmap-not-implemented.md) are reference material — dip into them for
a specific bug's backstory or before picking up a roadmap item.
