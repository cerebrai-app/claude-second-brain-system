---
name: python
description: Use and manage the vault's Python workspace (.brain/python/) for deterministic, reusable code, such as scripts for repetitive tasks, hooks, and adapters for remote backends. Use when the user runs /brain:python, or when you would otherwise repeat the same deterministic work (a report, a bulk edit, a sync with an external service).
argument-hint: "init | sync | list | run <name> [json] | approve <name>|--all"
---

# /brain:python

Read the `core` skill first. The workspace is a Python project with a **lock file** at `.brain/python/`: `pyproject.toml`, the lock, `registry.yml`, `README.md`, `scripts/`, `lib/`, `tests/`; `.venv/`, `outputs/` and `__pycache__/` are git-ignored. POSIX only (Linux, macOS). Python 3.12 or newer.

## Prefer a script to repetition
If a task is deterministic and recurs, make it a script instead of redoing the work: **look first** in `registry.yml`; if none fits, write one that does one job, takes JSON on stdin and writes JSON on stdout, keeps helpers in `lib/`, and has a one-line `description`; register it; get approval; call it from a rule, hook or adapter. Scripts never call Claude and stay deterministic (seed randomness; avoid wall-clock dependence unless it is an input). Add tests in `tests/` and run them before asking for approval.

## Tool and interpreter
Use the user's package manager: `python.tool` in `.brain/config.yml`, else the tool the workspace already uses (`uv.lock`, `poetry.lock`, `pdm.lock`), else the first installed of `uv`, `poetry`, `pdm`, else `venv` + `pip` with a pinned `requirements.lock` (weakest; say so). Map the four operations: **init**, **add** (dependency + lock), **sync** (environment from the lock, no re-resolve), **run** (in the locked environment).
Use an existing Python 3.12+; otherwise ask approval to fetch one with the user's tool (`uv`, `pyenv`, `conda`/`mamba`, `pdm`), naming the tool, version and download. If none is available or the user declines, stop and say what to install: the workspace is required, because `brainctl` (the deterministic helper) runs in it.

## Registry and approval
`registry.yml` lists each script: `name`, `path`, `description`, `requires_env`, `timeout`, `created_by`, `approved: {sha256, at, by}`. A script not in the registry cannot run. The scrubbed environment passed to a script contains only the variables in `requires_env` plus a minimal base.
**Show and approve on first run and on any change.** The approved hash is the SHA-256 of the script, every `lib/` module and `pyproject.toml`. Show the script, description, `requires_env`, timeout and exact command, then record the hash after the user confirms. **Adding a dependency needs separate approval** (package, version constraint, lock diff) before anything is installed; it changes `pyproject.toml`, so every script needs re-approval: `approve --all` shows that diff once and re-approves scripts whose own file and `lib/` are unchanged. A lock-only change does not invalidate approvals. A fresh clone has no `.venv`: **sync** (after confirmation, since it installs packages).

## Invocation
Same protocol as script adapters: one process per call, JSON on stdin, JSON on stdout, stderr shown on failure, timeout, non-zero exit is an error. A command of the form `python:<name>` runs a registered script through the project's tool (hooks: `run: "python:<name>"`; adapters: `command: "python:<name>"`). Unknown or unapproved names are errors. Append each run to `.brain/automation/log.jsonl`.

## Adapters written as scripts
A backend adapter is its own workflow: use the `backend` skill (`/brain:backend`) to specify, build, test and bind one. In short, subclass `brainctl.adapter.BrainAdapter` (shipped in the vault's `brainctl` package), implement the operations the backend supports, call `YourAdapter.run()`, and prove it with `brainctl.conformance`. Scripts may touch the vault freely, but edits that bypass the plugin are detected by sync as external changes.

## Commands
`init` (create the workspace; also done by setup), `sync`, `list` (scripts with approval state), `run <name> [json]` (registered and approved scripts only), `approve <name>` / `approve --all`.
