# 05 — Automation

Status: **Draft** · Depends on: [01 — Core Data Model](01-core-data-model.md), [03 — Storage Contract](03-storage-contract.md)

## Goal

Let each implementation declare automation: reactions to things that happen to its items (and to time), made of built-in
actions, user scripts, and Claude instructions. Anything that can change data without a person looking must be predictable;
anything that relies on Claude's judgment must be approved first.

## Where automation lives

In the `automation:` list of an implementation definition (doc 01), so it follows the implementation's lifecycle, versioning
and migrations (doc 02). The `Archive` core type is not extensible and has no automation; *archive/unarchive events on items*
are triggers for those items' own implementations.

Rules that span several implementations live at the **vault level** instead (next section).

## Vault-level automation

Some rules belong to no single implementation: a daily review that reads `task` items and writes into a `journal` note, a weekly roll-up per
project. These live in `.brain/automation.yml`, a versioned vault config file with its own `automation:` list, migrated with the vault (doc 02).

**Restrictions** *(Decided)*:
- Only the **`schedule`** and **`manual`** triggers. Event triggers (`create`, `update`, `capture`, `archive`, `unarchive`, `relation`,
  `before_delete`) are per-implementation only, so event chains stay attributable to one implementation and loop protection stays simple.
- Same action set, validation, approval (`claude` per proposal), logging, unattended queue and permission rules as implementation rules.
- Rule ids are namespaced `vault/<id>` in logs, approvals and `/brain run vault/<id>`, so they cannot collide with `<impl>/<rule-id>`.

### `requires`: declared implementations

Every vault rule **must** list the implementations it depends on. A rule with no `requires` is invalid.

```yaml
automation:
  - id: daily-journal-tasks
    requires:
      - { type: task, impl: task }
      - { type: note, impl: journal, min_version: 2 }   # min_version optional (implementation version, doc 02)
    on: { schedule: "0 8 * * *" }
    do:
      - action: surface
        impl: task                       # explicit: which implementation's named filter/sort
        filter: actionable-today
        sort: due-then-priority
        as: todays_tasks
        show: false
      - action: write_body
        target: { find: { type: note, impl: journal, where: { title: "{{ today }}" } }, create_if_missing: true }
        section: "## Today's tasks"
        mode: replace_section
        text: "{{ todays_tasks | checklist }}"
```

| Key | Meaning |
|---|---|
| `type` | The core type (doc 01). |
| `impl` | The implementation id. Must be bound in the vault. |
| `min_version` | Optional minimum implementation `version` (doc 01/02). |

- **Closed world:** every implementation a vault rule touches (an `impl:` on `surface`, `find`, `create_item`, a hook's declared reads, etc.) must
  appear in its `requires`. Load-time validation rejects a rule that references an implementation it did not declare.
- **Availability check:** a rule whose required implementations are missing, unbound, below `min_version`, or whose adapter is unreachable is **not run**.
  It is reported (session start and `/brain rules`) as *blocked: missing `<type>/<impl>`*. It is neither deleted nor silently skipped.
- **Named filters and sorts** are resolved in the implementation given by `impl:`; where a rule uses exactly one required implementation of that
  type, `impl:` may be omitted.
- **Used by tooling:** `requires` feeds the migration dry run (doc 02), which flags rules affected when a required implementation is renamed,
  removed, retyped, or has a referenced field or filter changed.

```yaml
automation:
  - id: link-inbox-source            # unique within the implementation; used in logs and approvals
    on: create
    do:
      - action: set_field
        field: source
        value: inbox
  - id: morning-surface
    on: { schedule: "0 8 * * *" }
    do:
      - action: surface
        filter: actionable-today     # a named filter from this implementation (natural language, doc 01)
        sort: due-then-priority
  - id: log-completion
    on: update
    match: { changed: [status], to: { status: done } }
    do:
      - action: hook
        run: ".brain/hooks/log-completion"
  - id: triage-suggest
    on: capture
    when: "The captured text mentions a deadline or a person's name."
    do:
      - action: claude                  # requires approval every time
        instruction: "Suggest an Area and Project for this item and a due date if one is implied."
```

## Rule shape

| Key | Meaning |
|---|---|
| `id` | Unique within the implementation. |
| `on` | The trigger (below). |
| `match` | Optional **structural** condition over the event (types, changed fields, new values, relation names). Deterministic. |
| `when` | Optional **natural-language** condition, judged by Claude (same interpretation model as sorts/filters, doc 01). Evaluated only after `match` passes. A `when` that cannot be judged confidently is treated as **false** and logged. *(Decided: acceptable.)* |
| `do` | Ordered list of actions. Stops at the first failing action unless it has `on_error: continue`. |
| `enabled` | Defaults to true. A rule can be disabled without being removed. |

Because `when` involves Claude, a rule with `when` **cannot run unattended** (no Claude available) and is queued as pending
(see Unattended runs). *(Decided.)* Rules with only `match` are fully deterministic.

## Triggers

| Trigger | Fires when | Event payload |
|---|---|---|
| `create` | An item of this implementation is created. | the new envelope |
| `update` | An item is updated. | before and after envelopes, `changed` field names |
| `capture` | An item is created in the Inbox area (doc 01), including by triage-by-capture flows. Fires in addition to `create`. | the new envelope |
| `archive` / `unarchive` | An item moves into or out of the Archive. | envelope |
| `relation` | A relation is added to or removed from an item: `on: { relation: blocked_by, added: true }`. | envelope, relation name, ref, added/removed |
| `schedule` | A cron time elapses (see Scheduling). | `{ scheduled_for, fired_at }` |
| `before_delete` | Just before a **user-requested permanent delete** of an item (doc 03). Synchronous; can veto. See below. | the envelope being deleted, `requested_by` |
| `manual` | The user invokes the rule by id (`/brain run <impl>/<rule-id>`), optionally on selected items. | selection, or none |

There is no after-the-fact `delete` trigger: the item is gone. The `before_delete` trigger is the only hook into permanent delete.

### `before_delete`

A safeguard that runs **before** a permanent `delete` (doc 03) and can stop it.

- **Fires only** for user-requested permanent deletes, after the plugin's own confirmation prompt and before the `delete` call. It does **not** fire
  for the internal deletes that complete an `archive` or a triage move (doc 03), since the item lives on. Deletes made outside the plugin cannot be
  intercepted and are only seen as a *missing item* by reconciliation.
- **Allowed actions:** `notify`, `surface`, `hook`, `claude`, and `block`. Actions that mutate the item are rejected at load time.
- **`block`:** `- action: block` with a `reason`; the delete is cancelled and the reason shown to the user. A failing action, or a `hook` that returns
  `{"ok":false}` or `{"block":true,"reason":"..."}`, also blocks.
- **Fail closed:** if a matching rule cannot complete (it needs Claude or approval and none is available, a hook errors or times out), the delete does
  **not** proceed. A `before_delete` rule is never queued as pending; permanent delete is only ever interactive.
- **Example:**
  ```yaml
  - id: keep-linked-projects
    on: before_delete
    match: { relation_present: linked_from }   # structural
    do:
      - action: block
        reason: "Still referenced; archive it instead."
  ```
- Rules run in definition order; the first `block` wins. Permanent delete remains **unavailable as an automation action**; this trigger can only prevent it.

## Actions

All actions work only through the storage contract (doc 03) and core validation, never by touching files directly, so they behave the
same on every adapter.

### Built-in actions

| Action | Effect |
|---|---|
| `set_field` | Set a field on the triggering item (validated against the schema). |
| `add_relation` / `remove_relation` | Edit a relation on the triggering item. |
| `create_item` | Create an item of any type, using the resolved default implementation (doc 01) unless `impl` is given. |
| `archive` | Archive the triggering item (or a referenced one). |
| `surface` | Produce a **result set** of items matching a named filter/sort. By default it is shown to the user in the session as a report; with `as:` it is also (or instead, with `show: false`) bound as **input to later actions in the same rule** (below). Read-only. Evaluation is specified in doc 04; a sort used here must have pinned `keys`, and a filter with a pinned interpretation can run unattended; because it needs Claude, a rule using `surface` cannot run unattended unless the needed results are cached and still valid, and is otherwise queued as pending. |
| `notify` | Emit a message to the user via the session (or a configured notifier hook). |

Built-ins are deterministic and idempotent where possible (`set_field` to the same value is a no-op).

### Using `surface` results as input to later actions

`surface` can collect items for another operation. `as: <name>` binds the result set (ordered `ref`s plus the `fields` and `relations` of each item,
no bodies unless `include: [body]`) to a rule-scoped variable, available to the **following actions** of that rule:

- in `value:` / `text:` templates as `{{ <name> }}` (rendered via `format:`, e.g. `checklist`, `bullets`, `table`, `refs`, or a template string);
- as the `items:` input of `write_body`, `create_item`, `add_relation`, `notify`;
- as an extra field `surface_results` on the stdin JSON of a `hook`, and as read-only context for a `claude` proposal.

The binding exists only for the current rule run; nothing is stored beyond the run (and the log's counts). Evaluation, caching and the unattended
limits of `surface` are unchanged (see above and doc 04); a failure to evaluate stops the rule.

Example: write today's actionable tasks into the daily journal note.

```yaml
- id: daily-journal-tasks
  on: { schedule: "0 8 * * *" }
  do:
    - action: surface
      filter: actionable-today
      sort: due-then-priority
      as: todays_tasks
      show: false
    - action: write_body
      target: { find: { type: note, impl: journal, where: { title: "{{ today }}" } }, create_if_missing: true }
      section: "## Today's tasks"          # replaced in place; created at the end if absent
      mode: replace_section
      text: "{{ todays_tasks | checklist }}"
```

| Action | Effect |
|---|---|
| `write_body` | Edit the markdown `body` of the triggering item or a `target` (a `ref`, or `find` over structural fields with optional `create_if_missing`). `mode`: `replace_section` (default; idempotent, replaces the content under a heading), `append`, `prepend`, `replace`. Requires `supports_body` (doc 03); validated and written through `update` with the read `revision`. `find` matching more than one item is an error. |

### `hook` (script)

Runs a user executable from the brain repo with the event as JSON on stdin and a JSON result on stdout, using the same conventions as
script adapters (doc 03): one process per call, timeout, error codes, credentials from environment, stderr surfaced on failure.
A hook may return **operations** (the same operation set as the built-ins, e.g. `{"op":"set_field",...}`), which the plugin validates and applies
itself, or just `{"ok":true}` if it acts on the outside world. The plugin shows the command and requires confirmation before the first
run of a new or changed hook.

### `claude` (natural-language instruction)

A natural-language instruction carried out by Claude. **Every execution requires user approval before anything is applied.**

1. **Propose.** Claude receives the instruction, the event payload and read-only access to the items it needs, and returns a **proposal**:
   an ordered list of operations from the same operation set as built-ins (`set_field`, `create_item`, `add_relation`, `archive`, `notify`, ...),
   plus a short rationale. It cannot write, run commands, or call hooks while proposing.
2. **Review.** The user sees the rule id, the instruction, the triggering event, the exact operations (as diffs) and the rationale.
3. **Approve / edit / reject.** Approval applies the operations **exactly as shown** through the normal storage and validation path.
   Editing re-validates. Rejection discards the proposal and is logged.
4. **Apply deterministically.** After approval, no further Claude judgment is involved: the plugin applies the approved operation list, as the
   migration script does in doc 02. If any operation fails validation, none are applied (all-or-nothing where the adapter allows; otherwise
   ordered with the partial-failure rules in doc 03).

There is no "always allow" mode, and no way to pre-approve a rule's shape or "safe" operations. **Approval is always per proposal.** *(Decided.)*

## Execution model

- **Events** are emitted by the plugin's own storage layer after a successful `create`/`update`/`archive`/... through it, and by
  **reconciliation** for changes made outside the plugin (next subsection).
- **Matching:** all enabled rules of the item's implementation whose trigger and `match` fit the event are collected, then ordered by their
  position in the definition. Rules run **sequentially**.
- **Loop protection:** every event carries `origin` (rule id chain) and a `depth`. Operations performed by a rule emit events with
  `depth + 1`; a rule never re-fires on an event whose origin chain contains it, and the chain is cut at depth 5 with a logged warning.
- **Idempotency:** rules should be safe to re-run; the plugin records `(rule id, event id)` for scheduled and recovered runs so a re-delivered
  event does not apply twice.
- **Failure:** a failed action logs an error, stops that rule, and does not roll back already-applied earlier actions of the same rule
  (they are individually valid operations). The user sees failures in the session and in the log.
- **Logging:** each rule run appends a JSON line to `.brain/automation/log.jsonl` (git-ignored): rule id, trigger, event id, actions,
  outcome, duration. This also feeds the latency measurement in doc 03.

### Detecting changes made outside the plugin

Items are also edited by hand (markdown files) or in a backend's own UI. The plugin detects these and emits the same events.

- **When:** at session start and on demand (`/brain sync`), run by a **sync sub-agent** (next subsection) so it does not block the session. Not continuous; there is no daemon.
- **Seen state:** `.brain/automation/seen/<type>/<impl-id>.json` (git-ignored, rebuildable) holds, per `ref`, the last-seen `revision`
  and a compact snapshot of `fields` and `relations` (no body). Entries are updated after the plugin's own writes too, so its
  own changes are not seen as external.
- **Algorithm per binding:** page through `list` (using `updated_since` where the adapter honors it, otherwise a full paged scan) and compare:
  - ref not in seen state → a **new object**: emit `create` (and `capture` if it is in the Inbox area).
  - `revision` differs → emit `update`, with `before` taken from the snapshot and `changed` computed from the field/relation diff.
  - item now has `archive` set (moved by hand) → emit `archive`; cleared → `unarchive`.
  - relation added/removed → also emit `relation` events.
  - ref in seen state but not found by `read`/`resolve` anywhere (including the Archive) → **not** an event; recorded as a *missing item* in the
    sync report (permanent delete is not a trigger, and validation reports dangling references per doc 03).
- **Event marking:** reconciled events carry `origin: external` and `detected_at`; they have `depth: 0`, so rules triggered by them run
  normally. The body of the payload says `before` is a snapshot (fields/relations only).
- **Validation:** an externally created or changed item is validated against its implementation schema first. If invalid, no rules run on it; it is
  reported to the user as invalid.
- **First run:** with no seen state, the plugin builds the baseline silently (no `create` storm). Only changes after the baseline emit events.
- **External backends** are bound by adapter rate limits and latency; the sync sub-agent throttles itself (below) and the cost is logged.
- Automation does not run for an item whose adapter could not be reached; the failure is reported and the sync resumes next time.

### Sync sub-agent

Reconciliation runs in a dedicated **sub-agent** started at session start, in the background, so the main session is usable immediately.

- **Role (detect only):** it reads through the storage contract (`list`, `read`, `resolve`), compares against the seen state, updates the
  seen state, and returns a **sync report** and an ordered **event list** to the main session. It does **not** run rules, apply operations,
  call hooks, or propose or apply `claude` actions. The main session dispatches the events afterward, so approvals, loop protection and
  logging behave as in the Execution model.
- **Self rate limiting:** the sub-agent paces its own requests per adapter.
  - Limits come from the adapter's `describe` (`rate_limit`: requests per second/minute, `max_concurrency`, `max_page`), overridable in
    `.brain/config.yml` under `sync.rate_limits.<type>/<impl-id>`. Defaults are conservative (e.g. 2 requests/second, concurrency 1) for
    `script` adapters; the local `markdown` adapter is not rate limited (it only reads local files).
  - Implemented as a token bucket per adapter. On `rate_limited` or `unavailable` errors it honors any `retry_after` and otherwise backs off
    exponentially with jitter, up to a bounded number of retries, then gives up on that binding for this run and records it as incomplete.
  - Adapters are scanned **in parallel with each other** but each adapter serially, so one slow backend does not block the rest.
- **Budget and resumability:** each run has a budget (wall-clock and request count, set in `sync.budget`). Each binding keeps a checkpoint (`cursor`
  and the high-water `updated_since` mark) in the seen state, so a run that hits its budget or is interrupted resumes from the checkpoint next
  time instead of rescanning. Bindings are visited **least recently synced first** so none starve.
- **Reporting:** the sub-agent streams progress ("synced 4 of 6 bindings; linear-task incomplete: rate limited") and ends with the report. The
  main session may start dispatching events for completed bindings before the whole sync finishes.
- **Consistency:** the seen state is only advanced for items whose events have been **handed to** the main session; if the session ends before
  dispatch, those items are re-detected next time (events are keyed by `(ref, revision)` so they dispatch once).
- Logged timings (per binding: duration, requests, retries, pages) feed the latency measurement in doc 03.

## Scheduling

Claude Code plugins have no always-on process, so schedules cannot fire on their own.

- **Catch-up at session start (MVP):** at the start of a session the plugin evaluates each `schedule` rule against its last-run time
  (stored in `.brain/automation/state.json`, git-ignored) and runs the ones that are due, at most once per missed window (missed runs
  are not replayed).
- **External trigger (optional):** the user may run the plugin non-interactively from cron, a CI job or a scheduled Claude Code task
  (`claude -p "/brain run-due"`). Deterministic rules run; rules that need Claude or approval are queued.

## Unattended runs and pending approvals

Rules that need a person (`claude` actions, or `when` conditions) cannot complete when nobody is present. They are written to a queue:
`.brain/automation/pending/<timestamp>-<rule-id>.json`, containing the event and, if already computed, the proposal. The next interactive
session reports the pending count and lets the user review each. Pending entries expire after a configurable period (default 14 days) and
are re-evaluated against current state before approval, since the item may have changed.

## Permissions and safety

- Automation can only perform operations the core model permits, validated like any user change. It cannot change implementation definitions
  or the automation list itself.
- `hook` and `claude` actions are the only paths to external effects. Hooks are user code (trusted by explicit confirmation); `claude`
  actions never act without per-proposal approval.
- The Archive's permanent `delete` is **not available** to automation actions in the MVP.
- Rules can be inspected with a command that lists them, their last run and outcome, and any pending approvals.

## Migrations (doc 02)

`automation:` blocks are part of implementation definitions, so a core-version migration may rewrite them. Vault-level rules
(`.brain/automation.yml`) are migrated the same way, and the dry run uses each rule's `requires` to list every vault rule touched by a change to a
required implementation (rename, removal, version bump, changed field or filter). A rule whose required implementation no longer exists after
migration is reported as *blocked*, not removed. The dry run's report lists
rules whose action names, trigger names or payloads change. Hooks are always listed under *Unhandled items* since they are user code.
Pending approval files reference rule ids and are discarded (with a note) if their rule no longer exists after migration.

## Open questions

1. ~~Rule scope~~ — resolved: **per implementation only**. (Was: should rules also be definable at **Area or Project level** (e.g. "tasks in this project notify me on completion"), mirroring `defaults` overrides (doc 01), or only per implementation? )
2. ~~External changes~~ — resolved: **detected and emitted as events**, including new objects (see Detecting changes made outside the plugin). (Was: events for changes made **outside** the plugin (editing markdown by hand, a backend UI): reconcile at session start or ignore?)
3. ~~Approving a `claude` rule's shape~~ — resolved: **no auto-approve**; approval is per proposal, always.
4. ~~`before_delete` safeguard~~ — resolved: **added** as a trigger (see `before_delete`), veto-only, fail closed.
5. ~~Condition language~~ — resolved: **`match` (structural) and `when` (natural language) are sufficient.**
6. ~~`surface` destinations~~ — resolved: results can be **bound with `as:` and used as input to later actions**, e.g. writing a task list into a daily journal note via `write_body`. (Was: where reports go beyond the session.)
7. ~~Cross-item and cross-implementation rules~~ — resolved: **event rules stay per-implementation** (a rule on `task` cannot react to a `project` change; model it as a rule on the project that edits its tasks). **Cross-implementation `schedule`/`manual` rules are allowed at the vault level** with a mandatory `requires` list (see Vault-level automation).
8. ~~Session-start cost~~ — resolved for sync: a **self-rate-limiting sync sub-agent** (see Sync sub-agent). Remaining: the rule that decides which `schedule` rules are "due" when many exist, and defaults for `sync.budget`.

## Next steps

1. Resolve the open questions above.
2. Write `04-sort-filter.md` (how Claude is invoked for sorts/filters, reproducibility), which `when` and `surface` rely on.
3. Specify the install flow and triage mechanics.
