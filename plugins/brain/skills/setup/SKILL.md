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
- Python workspace (**required**): the package manager detected (`uv`, `poetry`, `pdm`, else `venv` + `pip`), Python 3.12 or newer, and the one locked dependency `ruamel.yaml` (needs network). **Preflight before anything is created:** find Python 3.12+ and a tool, or ask approval to fetch Python; if neither works, stop with instructions.
- The list of files to be created.
Accept `go`, `change <choice>`, or `cancel`.

## Create, in this order (so an interrupted run is re-runnable)
1. `.brain/config.yml`: `version`, `name`, `archive` (`adapter`, `path`), `impls`, `python.tool`, `capture.type_by_source` (see the `core` skill's storage reference for the shape).
2. Copy `../../starters/<type>/default-<type>.md` (relative to this skill's plugin) to `.brain/impls/<type>/default-<type>.md` for all five types. Copy, never link.
3. Register the Archive (`archive:archive`) with the chosen adapter.
4. Create the Inbox: `id: inbox`, `type: area`, `impl: default-area`, `title: Inbox`, `system: true`, `defaults` pointing at the four non-person starters.
5. Python workspace: follow the `python` skill's init, including copying `../../tools/brainctl/` to `.brain/python/brainctl/` (the helper's modules only; leave out `test_*.py` and `__pycache__`), adding `ruamel.yaml`, locking, and a `.gitkeep` in each empty directory (`scripts/`, `lib/`, `tests/`).
6. `.gitignore` entries: `.brain/index/`, `.brain/cache/`, `.brain/automation/seen/`, `.brain/automation/pending/`, `.brain/automation/log.jsonl`, `.brain/conversions/`, `.brain/python/.venv/`, `.brain/python/outputs/`, `__pycache__/`. Keep existing lines; append only missing ones.
7. **`.brain/manifest.yml` last**: `core_version` of this plugin, empty `migrations`, the `implementations` index. A vault without a manifest is incomplete.

On a re-run, detect which of steps 1 to 6 exist, validate them against the same defaults, create only what is missing, then write the manifest. If an existing file conflicts with what setup would write, stop and ask.
Do not create `.brain/automation.yml`; it is created on first use. The only third-party package setup installs is `ruamel.yaml`.
After writing `.gitignore`, run `git check-ignore -v` on `.brain/python/lib/x.py`, `.brain/id-index/x.json`, `.brain/impls/task/x.md` and an item path; if any is ignored (a Python `.gitignore` template ignores `lib/`), append a negation (for example `!.brain/python/lib/`). Skip appended lines whose effect already holds.

## Finish
Run `brainctl validate` (and `brainctl sync` to build the silent baseline). Fix any error before committing; do not commit a vault that does not validate. After confirmation, make **one** git commit ("brain: initial setup") and report the vault summary. The first sync builds its baseline silently; it does not emit `create` events.
