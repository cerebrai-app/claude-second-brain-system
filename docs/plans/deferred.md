# Deferred and Out-of-Scope Items

Status: **Living index** · Collects items from [01](01-core-data-model.md) · [02](02-versioning-and-migrations.md) · [03](03-storage-contract.md) · [04](04-sort-filter.md) · [05](05-automation.md)

This is a summary, not a spec. Each item names the doc that owns its design; update the owning doc first, then this list. Items leave this
list when they are specified and built, or when the decision is reversed.

## 1. Deferred past the MVP (decided)

Designed or reserved in the specs, deliberately not built in the first release.

| Item | What the MVP does instead | Owner | Notes |
|---|---|---|---|
| Bulk migration of objects between implementations (a command that converts many items, for example all persons to a new implementation) | Per-item conversion (doc 06) works for any type; a `person` migration-target implementation can coexist with the active one. No bulk command, so users convert items individually. | 06, 01 | Needs selection, a combined conversion report and resumability. Promotion of the target to active is also manual in the MVP. |
| Traits on core types other than `Person` | Traits are enabled for `Person` only. | 01 | The mechanism is general; the other types already allow several implementations. |
| `schedule` triggers and session-start catch-up | `on: schedule` is rejected at load time; time-based work runs via `manual` rules (`/brain run ...`). | 05 | Rule shape is reserved so it can be added without changes. Includes the open question of how "due" is decided when many schedule rules exist. |
| Non-interactive runs (cron, CI, `claude -p "/brain run-due"`) | Every run happens inside an interactive session. | 05 | Would reuse the pending-approval queue for rules needing Claude or approval, and the `when` condition could then not be judged. |
| Sync self rate limiting (token bucket, `describe`-supplied limits, `.brain/config.yml` overrides, backoff with jitter, honoring `retry_after`) | No pacing. One retry after a minute on `rate_limited`; a second one in a row fails the binding for the run. `unavailable` gets no retry. | 05 | Can be added without changing the sync report or checkpoints. |
| Sync run budget (`sync.budget`, wall-clock and request count) | A run continues until every binding is scanned or fails. | 05 | Checkpoints stay, so interrupted or failed bindings resume. |
| Automation using permanent `delete` | Not available to automation actions. `before_delete` can only veto. | 05 | |
| Local cache for adapter reads | None. | 03 | Possibly adapter-specific. Needs latency data first (see section 3). |
| `read_many` (batch reads) | Individual reads. | 03 | Revisit with latency data. |
| `follow` depth greater than 1 in sorts and filters | Depth 1. | 04 | |
| Changing the Archive adapter after install | The adapter is fixed at install. | 03 | |

## 2. Out of scope or decided against

Not planned. Listed so they are not re-litigated by accident.

| Item | Decision | Owner |
|---|---|---|
| Auto-approving `claude` actions, or approving a rule's "shape" | No. Approval is always per proposal. | 05 |
| Event triggers at the vault level (cross-implementation reactions) | No. Event rules stay per-implementation; vault rules are `manual` only in the MVP. Model a reaction as a rule on the item that changes. | 05 |
| A condition language beyond `match` and `when` | Not needed. | 05 |
| Attachments | Out of scope for now. | 03 |
| Multiple Archives | Exactly one, `archive:archive`. | 03 |
| Automatic purging of archived items | Never. | 03 |
| Item-level `schema_version` | No. Migration state is repo-level only. | 02 |
| A separate CHANGELOG file | No. GitHub releases are the changelog. | 02 |
| Per-run cache sharing across machines | Local only, git-ignored. | 04 |

## 3. To revisit once there is data

| Item | Trigger to revisit | Owner |
|---|---|---|
| Per-operation adapter latency measurement and a summary command | Prerequisite for the cache and batch-read decisions above. | 03 |
| Sort and filter batch defaults (`max_items_per_call` 20, `direct_sort_max` 10) | After measurements. | 04 |
| Rule quality check sample size (3 runs, 50 items; 80% agreement threshold) | Whether the sample is right. | 04 |
| A formal expression language as a fallback for natural-language sorts and filters | If reproducibility or cost at large vault sizes proves a problem. | 01, 04 |
| Pinned-interpretation predicate grammar, and whether it ships in the first release or the one after | Before implementing pinned filters. | 04 |

## 4. Not yet specified (work to do, not deferral)

These are gaps in the plan rather than deliberate deferrals, kept here so nothing is lost.

| Item | Needed by | Owner |
|---|---|---|
| Install flow (setup steps, defaults chosen by the user vs. built-in starters) | Pending approvals, `capture`, Inbox triage | 01 (to be a new doc) |
| Triage mechanics, including how an item is converted between implementations ("conversion mechanics TBD") | `capture` trigger and the Inbox | 01 (to be a new doc) |
| Per-type core fields and relations (doc 01's strawman table) | All implementations | 01 |
| Reference built-in implementations for each core type | Starter scaffolding at install | 01 |
| Manifest and migration doc paths are marked "proposed" | Migration implementation | 01, 02 |
| Doc 05 status: Draft vs. reviewed | | 05 |

## Housekeeping

- The next-steps lists in docs 01 to 05 were refreshed together and each links back here for deferred work.
