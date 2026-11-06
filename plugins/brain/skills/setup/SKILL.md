---
name: setup
description: Initialize a second-brain vault in the current git repo, or validate and repair an existing one. Use when the user runs /brain:setup or asks to set up their second brain.
disable-model-invocation: true
---

# /brain:setup

Read the `core` skill first. Setup asks **one** question: it shows a summary and asks for a single confirmation.

## Preconditions
- The working directory must be a git repository (the vault). If not, stop and say so; do not run `git init`.
- If `.brain/manifest.yml` exists, the vault is complete: do **not** reinitialize. Run the `validate` skill's checks and report. Never overwrite an existing file.

## Summary to show (with these defaults)
- Vault `name`: the repo directory name.
- Storage for every type: the built-in `markdown` adapter.
- Archive adapter: `markdown` at `archive/{type}/{impl}/{slug}.md`. It is fixed at install, so say so. A `script` adapter is allowed only if it reports `archive_adapter: true`.
- Inbox `defaults`: `default-task`, `default-note`, `default-project`, `default-area` (no `person` default).
- Person implementation: exactly one, `default-person`, at `people/{slug}.md`.
- Python workspace: the package manager detected (`uv`, `poetry`, `pdm`, else `venv` + `pip`), Python 3.12 or newer. Optional; skipped if no suitable Python is found and the user declines to fetch one.
- The list of files to be created.
Accept `go`, `change <choice>`, or `cancel`.

## Create, in this order (so an interrupted run is re-runnable)
1. `.brain/config.yml`: `version`, `name`, the `archive` adapter, the implementation definitions location, `python.tool` if the workspace is created.
2. Copy `../../starters/<type>/default-<type>.md` (relative to this skill's plugin) to `.brain/impls/<type>/default-<type>.md` for all five types. Copy, never link.
3. Register the Archive (`archive:archive`) with the chosen adapter.
4. Create the Inbox: `id: inbox`, `type: area`, `impl: default-area`, `title: Inbox`, `system: true`, `defaults` pointing at the four placed-type starters.
5. Python workspace (if applicable): follow the `python` skill's init.
6. `.gitignore` entries: `.brain/index/`, `.brain/cache/`, `.brain/automation/seen/`, `.brain/automation/pending/`, `.brain/automation/log.jsonl`, `.brain/conversions/`, `.brain/python/.venv/`, `.brain/python/outputs/`, `__pycache__/`. Keep existing lines; append only missing ones.
7. **`.brain/manifest.yml` last**: `core_version` of this plugin, empty `migrations`, the `implementations` index. A vault without a manifest is incomplete.

On a re-run, detect which of steps 1 to 6 exist, validate them against the same defaults, create only what is missing, then write the manifest. If an existing file conflicts with what setup would write, stop and ask.
Do not create `.brain/automation.yml`; it is created on first use. Install no third-party packages.

## Finish
After confirmation, make **one** git commit ("brain: initial setup") and report the vault summary. The first sync builds its baseline silently; it does not emit `create` events.
