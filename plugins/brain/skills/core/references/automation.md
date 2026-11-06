# Automation

## Where rules live

- In an implementation's `automation:` list (`.brain/impls/<type>/<impl>.md`): event triggers and `manual`.
- Vault-level, in `.brain/automation.yml`: **`manual` only** in the MVP, ids namespaced `vault/<id>`, and every rule must list the implementations it needs in `requires: [{type, impl, min_version?}]`. A rule that references an implementation not in `requires`, or one that is missing/too old, is blocked (reported, not run, not deleted).
- `schedule` triggers and non-interactive runs are **not supported yet**; reject a rule that uses `on: schedule`.

## Rule shape

`id` (unique in its implementation), `on`, optional `match` (structural: types, changed fields, new values, relation names, traits, `colleague.employer`-style fields), optional `when` (natural language, judged by you; treat as false and log if you cannot judge it), `do` (ordered actions, stops at the first failure unless `on_error: continue`), `enabled`.

## Triggers

`create`, `update` (before/after, `changed`), `capture` (item created in the Inbox; fires in addition to `create`), `archive`, `unarchive`, `relation` (added/removed), `before_delete` (veto-only, synchronous, fails closed), `manual` (`/brain:run <impl>/<rule-id>` or `/brain:run vault/<rule-id>`). There is no after-delete trigger.
Events carry `origin` (rule id chain, or `external/<type>/<impl-id>` for sync-detected changes) and `depth`. A rule never re-fires on an event whose origin chain contains it; cut the chain at depth 5 with a warning.

## Actions

Built-ins: `set_field`, `add_relation`/`remove_relation`, `set_relation` (replace one relation's targets), `create_item`, `archive`, `surface` (read-only result set from a named filter/sort; `as: name` binds it for later actions in the same rule; `show: false` hides the report), `write_body` (edit a markdown body; modes `replace_section` (default), `append`, `prepend`, `replace`), `notify`, `block` (before_delete only). `hook` runs an executable or `python:<name>` with the event JSON on stdin; confirm the command before the first run of a new or changed hook. Permanent `delete` is never available to automation.
**Placing created items:** `create_item` and a `write_body` target with `create_if_missing` accept `place:` (a ref, or `{ find: { type, where }, create_if_missing: true }`) to set the new item's placement relation. Without it the item lands in the Inbox and becomes a triage candidate; warn when a rule creates a `task`, `note` or `project` without `place`. A vault rule must list every implementation it finds or creates in `requires`.
`convert` is interactive only: it can appear in a `claude` proposal or in triage, never as a standalone rule action or from a hook.

## `claude` actions: propose, review, approve, apply

1. **Propose** (read-only): return an ordered operation list from the built-in operation set plus a short rationale. Do not write, run commands or call hooks while proposing.
2. **Review**: show the rule id, instruction, triggering event, exact operations as diffs, and the rationale.
3. **Approve / edit / reject**: approval applies the operations exactly as shown through normal validation; editing re-validates; rejection is logged.
4. **Apply deterministically**; if any operation fails validation, apply none where the adapter allows.
There is no always-allow mode and no pre-approved "shape". Approval is per proposal.

## Pending approvals

`claude` proposals triggered by sync-detected events (`origin` starts with `external/`) are written to `.brain/automation/pending/<timestamp>-<type>-<impl-id>-<rule-id>.json` instead of interrupting the user; deterministic rules and `when` conditions on those events run immediately. Proposals from the user's own in-session actions are shown right away. `before_delete` rules are never queued. Entries expire (default 14 days) and are re-evaluated against current state before approval.

## Logging

Append one JSON line per rule run to `.brain/automation/log.jsonl` (rule id, trigger, event id, actions, outcome, duration). Record `(rule id, event id)` so a re-delivered event does not apply twice.
