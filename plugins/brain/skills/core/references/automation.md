# Automation

## Where rules live

- In an implementation's `automation:` list (`.brain/impls/<type>/<impl>.md`): event triggers and `manual`.
- Vault-level, in `.brain/automation.yml` (a mapping whose only key is the `automation:` list): **`manual` only** in the MVP, ids namespaced `vault/<id>`, and every rule must list the implementations it needs in `requires: [{type, impl, min_version?}]`. A rule that references an implementation not in `requires`, or one that is missing/too old, is blocked (reported, not run, not deleted).
- `schedule` triggers and non-interactive runs are **not supported yet**; reject a rule that uses `on: schedule`.

## Rule shape

`id` (unique in its implementation), `on`, optional `match` (structural: types, changed fields, new values, relation names, traits, `colleague.employer`-style fields), optional `when` (natural language, judged by you; treat as false and log if you cannot judge it), `do` (ordered actions, stops at the first failure unless `on_error: continue`), `enabled`.

## Triggers

`create`, `update` (before/after, `changed`), `capture` (item created in the Inbox; fires in addition to `create`), `archive`, `unarchive`, `relation` (added/removed), `before_delete` (veto-only, synchronous, fails closed), `manual` (`/brain:run <impl>/<rule-id>` or `/brain:run vault/<rule-id>`). There is no after-delete trigger.
Events carry `origin` (rule id chain, or `external/<type>/<impl-id>` for sync-detected changes) and `depth`. A rule never re-fires on an event whose origin chain contains it; cut the chain at depth 5 with a warning.

## Actions

Built-ins: `set_field`, `add_relation`/`remove_relation`, `set_relation` (replace one relation's targets), `create_item`, `archive`, `surface` (read-only result set from a named filter/sort; `as: name` binds it for later actions in the same rule; `show: false` hides the report), `write_body` (edit a markdown body; modes `replace_section` (default), `append`, `prepend`, `replace`), `notify`, `block` (before_delete only). `hook` runs an executable or `python:<name>` with the event JSON on stdin; confirm the command before the first run of a new or changed hook. Permanent `delete` is never available to automation.
**Creating once:** `create_item` accepts `unless_exists: { type, impl?, where: {field: value} }`; run `brainctl find --type <type> [--impl <impl>] --where field=value` (exit 0 means found) and, if an item exists, skip the action and log `skipped: exists` with its ref. Prefer it to a `when` condition for idempotence. In a vault rule the `impl` must be in `requires`. **Tags:** a tag map has one value per key, so a `claude` instruction that wants several tags must name distinct keys.
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

### Pending entry file

The main session writes the entry when it dispatches the event list that `brainctl sync` returned (`sync` itself only emits events; it never writes proposals). One JSON file per proposal:

```json
{
  "id": "20261106T034730Z-note-default-note-propose-topic-tag",
  "status": "pending",
  "created": "2026-11-06T03:47:30Z",
  "expires": "2026-11-20T03:47:30Z",
  "rule": { "type": "note", "impl": "default-note", "id": "propose-topic-tag" },
  "event": { "id": "<event id>", "trigger": "capture", "ref": "note:<id>", "origin": "external/note/default-note", "depth": 0 },
  "instruction": "<the rule's instruction text>",
  "revision": "<git blob hash of the triggering item when the proposal was made>",
  "rationale": "<why>",
  "operations": [ { "op": "set_field", "ref": "note:<id>", "field": "tags", "value": { "topic": "mobile" } } ]
}
```

`operations` use the same operation set as built-in actions. `/brain:pending` compares `revision` with the item's current hash before it applies anything, and drops the entry after `expires`.

## Template variables

**Resolve templates with the helper, never by hand:** `brainctl render "<template>" [--vars <json>]`, or `brainctl render --json '<value>'` to resolve every string inside an action. The helper knows `today`, `now` and the filters; `--vars` supplies bindings such as a `surface` result set (`{"todays_tasks": [{"ref", "fields"}, ...]}`). It exits 2 with a message on an unknown variable or filter. `validate` checks every template in a rule (`rule-template`).

Rule values may contain `{{ name }}` templates (`value`, `text`, `title`, and the string values of `where` and `unless_exists`). Built-in variables, resolved from the evaluation context (the user's time zone, doc 04):

- `{{ today }}`: the current date, `YYYY-MM-DD`.
- `{{ now }}`: the current instant, UTC `YYYY-MM-DDThh:mm:ssZ`.

The time zone is `timezone:` in `.brain/config.yml` (an IANA name such as `Europe/Berlin`; default UTC; `validate` rejects an unknown name).

Filters format a list of items (`{ref, fields}`): `checklist` (`- [ ] title`, `[x]` when the status is `done` or `dropped`), `bullets`, `refs` (comma-separated refs) and `table` (markdown; `title` plus each scalar field). A list or map without a filter is an error.

A `surface` binding added with `as: <name>` is available as `{{ <name> }}` to later actions of the same rule. An unknown variable stops the rule with an error.

Example: `unless_exists: { type: note, impl: journal, where: { title: "{{ today }}" } }` with `title: "{{ today }}"` on the `create_item`.

## Logging

Append one JSON line per rule run to `.brain/automation/log.jsonl` (rule id, trigger, event id, actions, outcome, duration). Record `(rule id, event id)` so a re-delivered event does not apply twice.
