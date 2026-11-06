---
name: run
description: List automation rules and their last run, or run a rule manually by id (for example /brain:run task/default-task/today, or vault/daily-journal-tasks). Use when the user runs /brain:run or /brain:run list, or asks what rules exist.
argument-hint: "list | <impl>/<rule-id> | vault/<rule-id>"
disable-model-invocation: true
---

# /brain:run

Read the `core` skill and the automation reference first.

## `list`
Show every rule (from `.brain/impls/**` and `.brain/automation.yml`): id, trigger, enabled, last run and outcome (from `.brain/automation/log.jsonl`), and any rule that is **blocked** (a vault rule whose required implementation is missing or below `min_version`), plus the pending approval count.

## Run a rule
- Resolve `<impl>/<rule-id>` or `vault/<rule-id>`. Only rules with `on: manual` can be run this way. Optionally accept selected items as the event payload.
- Vault rules: check every entry of `requires` first; if any is missing, refuse and say which.
- Run the rule's actions in order, validating each operation like any change. Resolve every `{{ ... }}` template with `brainctl render --json '<action as JSON>' --vars '<bound results>'` before you use the action; do not fill in dates or format lists yourself, and stop the rule if `render` exits 2. Pass a `create_item` action whole to `brainctl op`: it checks `unless_exists` itself (result `skipped: exists`; log that as `skipped` with reason `exists`) and resolves `place` (finding or creating the area); do not judge either yourself. Stop at the first failing action unless it has `on_error: continue`.
- `surface` produces a report; with `as:` the result set is bound for later actions in this rule only. `write_body` defaults to `replace_section`, which is idempotent.
- `claude` actions: propose, review, approve, apply (never skip approval). `convert` is not allowed here.
- Apply each built-in operation with `brainctl op` (never edit item files). Append the run with `brainctl log --json '{"rule": ..., "trigger": "manual", "event": ..., "actions": [...], "outcome": ...}'`; the outcome vocabulary is checked.
