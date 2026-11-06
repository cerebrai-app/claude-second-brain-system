---
name: sync
description: Detect changes made to vault items outside the plugin (hand edits, a backend's own UI) and dispatch them as automation events. Runs at session start and on demand. Use when the user runs /brain:sync, or at the start of a session in a vault.
---

# /brain:sync

Read the `core` skill and the automation reference first.

## Detect (run as a background sub-agent so the session stays usable; detect only)
The sub-agent reads through the storage operations, compares against the seen state, updates the seen state, and returns a **sync report** and an ordered **event list**. It does **not** run rules, apply operations, call hooks, or propose `claude` actions.

- **Seen state:** `.brain/automation/seen/<type>/<impl-id>.json` (git-ignored, rebuildable): per `ref`, the last `revision` and a compact snapshot of `fields` and `relations` (no body), plus a checkpoint (`cursor`, high-water `updated_since`). Update it after the plugin's own writes too.
- **Per binding:** page through `list` (use `updated_since` if the adapter honors it) and compare:
  - ref not in seen state: `create` (and `capture` if in the Inbox);
  - `revision` differs: `update` with `before` from the snapshot and `changed` from the diff;
  - `archive` newly set/cleared: `archive` / `unarchive`; relation added/removed: also `relation`;
  - ref in seen state but resolvable nowhere (including the Archive): **not** an event; list it as a *missing item* in the report.
- **First run:** with no seen state, build the baseline silently. No `create` storm.
- **Validate first:** an externally created or changed item is validated against its implementation schema. If invalid, run no rules on it and report it.
- **Mark events:** `origin: external/<type>/<impl-id>`, `detected_at`, `depth: 0`; `before` is a snapshot (fields and relations only).
- **Adapters** are scanned in parallel with each other, each one serially. No pacing or throttling. On `rate_limited`, wait **one minute** and retry that call once; a second `rate_limited` in a row fails the binding. Other errors (including `unavailable`) fail the binding immediately. A failed binding is *incomplete* in the report and resumes from its checkpoint next time. No run budget.
- Advance the seen state only for items whose events were handed to the main session; events are keyed by `(ref, revision)` so they dispatch once.

## Dispatch (main session)
For each event run the matching rules in definition order (loop protection, logging and idempotency per the automation reference). **Deterministic rules and `when` conditions run immediately. `claude` proposals from `external/...` events go to `.brain/automation/pending/` instead of prompting.** At the end report: bindings synced, incomplete bindings and why, missing items, invalid items, and the pending count.
