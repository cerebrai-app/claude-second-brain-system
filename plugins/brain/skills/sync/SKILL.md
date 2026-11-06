---
name: sync
description: Detect changes made to vault items outside the plugin (hand edits, a backend's own UI) and dispatch them as automation events. Runs at session start and on demand. Use when the user runs /brain:sync, or at the start of a session in a vault.
---

# /brain:sync

Read the `core` skill and the automation reference first.

## Detect and adopt (the helper does this; run it as a background sub-agent so the session stays usable)
Run `<tool> run python -m brainctl sync` from `.brain/python` (see "Running `brainctl`" in the `core` skill). It scans every markdown binding and the Archive, matches items **by ref across bindings** (so a conversion is one `update` with `impl` in `changed`), diffs against the seen state (`.brain/automation/seen/`), **adopts hand-written files**, writes the new seen state, and returns JSON `{events, report}`. Use `--no-adopt` to report without editing files and `--dry-run` to write nothing.

- **Events** have `trigger` (`create`, `capture`, `update`, `archive`, `unarchive`, `relation`), `ref`, `origin` (`external/<type>/<impl-id>`), `depth: 0`, `changed`, and `before`/`after` snapshots (fields and relations, no body). `capture` is only for tasks, notes and projects in the Inbox; areas and persons are top-level.
- **Report** has `baseline` (true on the first run: no events, no `create` storm), `adopted`, `completed`, `incomplete_identity`, `unadopted`, `invalid` (externally created or changed items that fail their schema: run no rules on them; they are reported again until fixed), `missing` (not events), `incomplete` (bindings the helper cannot read yet, for example script adapters), and `problems` (unparseable files, wrong-directory items, ambiguous directories).
- **Adoption** adds only the missing identity fields (`id`, `type`, `impl`, `slug` from the file name (only if the implementation declares a `slug` field), `created`, `updated`, `title`, `status`, schema defaults) at the top of the front matter and never renames the file or touches the body or existing keys. The same applies to an item that already has an id but lacks identity fields (a slug, title, status, `created` or `updated`): sync adds only those and lists them under `completed` (with `--no-adopt` or `--dry-run` they appear under `incomplete_identity` instead); schema defaults are not filled and a wrong value is left for `validate`. A file that would still be invalid, or whose directory matches more than one binding, is left alone and reported. List every adopted file for the user; git can undo it.
- There is no pacing, retry or run budget in the helper. If a script-adapter binding is reported incomplete, say so; reading it is not supported yet.

## Dispatch (main session)
For each event run the matching rules in definition order (loop protection, logging and idempotency per the automation reference). **Deterministic rules and `when` conditions run immediately. `claude` proposals from `external/...` events go to `.brain/automation/pending/` instead of prompting.** At the end report: bindings synced, files adopted, incomplete bindings and why, missing items, invalid items, and the pending count.
