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
- Run the rule's actions in order, validating each operation like any change. Before a `create_item` with `unless_exists`, run `brainctl find` (see the automation reference) and skip the action when an item exists; do not judge that yourself. Stop at the first failing action unless it has `on_error: continue`.
- `surface` produces a report; with `as:` the result set is bound for later actions in this rule only. `write_body` defaults to `replace_section`, which is idempotent.
- `claude` actions: propose, review, approve, apply (never skip approval). `convert` is not allowed here.
- Append the run to `.brain/automation/log.jsonl`.
