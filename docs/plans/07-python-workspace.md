# 07 — Python Workspace

Status: **Draft** · Depends on: [03 — Storage Contract](03-storage-contract.md), [05 — Automation](05-automation.md), [06 — Install Flow and Triage](06-install-and-triage.md)

## Goal

Give the vault a managed Python project where deterministic, reusable code lives: scripts the user writes, and scripts the brain agents write for repetitive work. The same
workspace hosts the code behind hooks (doc 05) and `script` adapters (doc 03), including adapters that use any third-party SDK or remote API a user's chosen backend needs. The plugin has no built-in list of supported services; Todoist and Notion appear in this doc only as examples.
Anything an agent does repeatedly and deterministically should become a script here instead of being re-derived each session.

## Location and layout

`second-brain/.brain/python/`, committed to git except caches:

```
.brain/python/
  pyproject.toml          # the project: name, requires-python, dependencies
  <lockfile>              # uv.lock | poetry.lock | pdm.lock | requirements.lock (tool-dependent)
  registry.yml            # index of scripts (below); the source of truth for approval
  README.md               # guidance for agents (below)
  scripts/<name>.py       # runnable entry points, one per registered script
  lib/                    # importable shared helpers, written by users or agents
  tests/                  # optional tests for scripts and helpers
  outputs/                # git-ignored run outputs
  .venv/                  # git-ignored environment
```

`.venv/`, `outputs/` and `__pycache__/` are git-ignored; everything else is committed, so the workspace is shared across machines and its history is the audit trail.

## Dependency management: use the tool the user has *(Decided)*

The workspace is a real Python project with a **lock file**. The plugin does not pick a package manager for the user; it detects one:

1. `python.tool` in `.brain/config.yml`, if set.
2. Otherwise the tool the workspace already uses (an existing `uv.lock`, `poetry.lock` or `pdm.lock`).
3. Otherwise the first installed of: `uv`, `poetry`, `pdm`.
4. Otherwise a plain `venv` with `pip` and a pinned `requirements.lock`. This is the weakest option (no hash-checked resolution unless the user brings their own tooling); setup says so.

Setup shows the detected tool in its summary and the user may change it before confirming. The choice is recorded in `.brain/config.yml` (`python.tool`).

The plugin works through four abstract operations, mapped to the chosen tool: **init** (create the project), **add** (add a dependency and update the lock), **sync** (make the environment
match the lock, from the lock without re-resolving), and **run** (run a script in the environment, using the locked environment). Nothing else about the tool is assumed.

Rules:
- **Adding a dependency needs approval.** The agent shows the package, the version constraint and the resulting lock diff before anything is installed, since this runs third-party code and uses the network.
- **A fresh clone** has no `.venv`. The plugin runs **sync** on first use (or via `/brain python sync`), after confirmation because it installs packages.
- `requires-python` is set at init to the interpreter found. If no suitable Python or tool is found, setup skips the workspace and says so (it is optional; see Install step in doc 06).
- *Deferred:* running the workspace in a Docker container (`deferred.md`).

## Scripts

### Registry: `registry.yml`

```yaml
scripts:
  - name: log-completion
    path: scripts/log_completion.py
    description: Append a completed task to the weekly log note.
    requires_env: [ ]                 # environment variables the script is allowed to see
    timeout: 30                       # seconds
    created_by: agent                 # agent | user
    approved: { sha256: "ab12...", at: 2026-11-06, by: user }
  - name: example-tasks-backend      # illustrative: any remote service's adapter
    path: scripts/example_tasks_backend.py
    description: Script adapter backing an external task service.
    requires_env: [EXAMPLE_API_TOKEN]
    timeout: 60
    created_by: agent
    approved: { sha256: "cd34...", at: 2026-11-06, by: user }
```

A script not in the registry is not runnable by the plugin. The registry also lets agents find reusable scripts without reading every file.

### Invocation convention

The same conventions as script adapters (doc 03): **one process per call**, a JSON object on **stdin**, a JSON result on **stdout**, stderr surfaced on failure, a timeout, and an error code
on non-zero exit. A script gets only the environment variables listed in its `requires_env` (plus a minimal base environment), so credentials are not exposed to scripts that do not declare them.

### Referencing a script

Anywhere the plugin takes a command, the form `python:<name>` runs a registered workspace script through the project's tool:

- a `hook` action: `run: "python:log-completion"` (doc 05);
- a `script` adapter binding: `command: "python:example-tasks-backend"` (doc 03).

Both existing forms (a path to any executable) keep working; `python:` is the way to use the managed environment and its dependencies.

### Backends written as scripts

A `script` adapter implemented here may call **any** remote API, through whichever SDK or HTTP client the backend needs, which is how an external system becomes a storage backend for any
core type. The services are the user's choice (for example Todoist for tasks, or Notion for notes, purely as illustrations); nothing in the plugin is specific to them. The SDK goes in the project
dependencies and lock, and is added through the approved dependency flow above. The script follows the adapter contract (doc 03): `describe`, `create`, `read`, `update`, `list`, `resolve`, `archive` and the rest, with credentials from
`requires_env`.

### Access to vault data: unrestricted *(Decided)*

Scripts may read and write the vault however they need (files, git, the network, SDKs). The plugin does not sandbox them. Consequences, stated plainly:
- A script that edits vault files directly **bypasses core validation and revisions**. Its changes are treated like any other external edit: the next sync (doc 05) detects them, validates the items, and emits events marked `origin: external/...`.
- Scripts must not call Claude. They are for deterministic processes; anything needing judgment stays a `claude` action (doc 05).
- Network access is whatever the user's machine allows.

## Approval *(Decided)*

Agent-written (and user-written) scripts are code that runs with the user's privileges, so the same rule as hooks applies: **show and approve on first run, and again on any change**.

- The **approved hash** is the SHA-256 of the script file together with every `lib/` module in the workspace. Any change to either invalidates approval and shows a diff before the next run.
- A new or changed script is shown with its description, `requires_env`, timeout and the exact command, and runs only after confirmation. The hash and date are then written to the registry.
- Dependency changes are approved separately (above). A lock change alone does not invalidate script approvals.
- Unattended or non-interactive runs (post-MVP) may run only scripts whose current hash is approved; anything else is queued, as in doc 05.
- Each run is appended to the automation log (doc 05): script name, caller (rule or adapter operation), duration and outcome.

## How agents use the workspace

The workspace `README.md` (created at setup, owned by the vault) tells agents the rules; the plugin also loads it when an agent proposes repetitive work:

1. **Look first.** Read `registry.yml` for an existing script before writing one.
2. **Write for reuse.** A script does one deterministic job, takes its input as JSON, keeps helpers in `lib/`, and has a one-line `description`.
3. **Register it.** Add it to `registry.yml` with `requires_env` and a timeout; it is not runnable until approved.
4. **Prefer scripts to repetition.** If a task is deterministic and recurs (a report, a bulk edit, a sync with an external service), turn it into a script and call it from a rule or command, instead of redoing the work each time.
5. **Stay deterministic.** No model calls; seed randomness; avoid wall-clock dependence unless it is an input.
6. **Test when practical.** Put tests in `tests/` and run them with the project tool before asking for approval.

## Commands

- `/brain python init`: create the workspace (also done by setup).
- `/brain python sync`: make the environment match the lock.
- `/brain python list`: list registered scripts with approval state (approved, changed since approval, never approved).
- `/brain python run <name> [json]`: run a registered, approved script.
- `/brain python approve <name>`: show the script and approve its current hash.

## Interaction with other docs

- **Migrations (doc 02):** the generated `migrate.py` files remain standard-library-only, run with `python3 -I`, and are independent of this workspace. A core migration may need to adapt `registry.yml`; scripts and `lib/` are user code and are listed under *Unhandled items* in the migration report, like hooks.
- **Automation (doc 05):** `hook` actions may use `python:`; the existing first-run confirmation for hooks becomes this approval flow when the hook is a workspace script.
- **Storage (doc 03):** a `script` adapter `command` may use `python:`. Because each operation is a separate process, start-up cost matters; `run` uses the already-synced environment and never re-resolves dependencies at call time.

## Open questions

1. Windows and non-POSIX shells: which of the four tools and commands are supported in the MVP?
2. Does the approval hash need to include `pyproject.toml` (for example changed entry points), or is the lock-plus-dependency approval enough?
3. Should the workspace expose an optional helper library for common vault operations (read an item, apply an operation through the storage contract), or leave that entirely to each script?
4. Python version management: require the interpreter to already exist, or integrate with the tool's managed Pythons?

## Next steps

1. Resolve the open questions.
2. Define the shipped `README.md` for agents and the starter `pyproject.toml`.
3. Specify the `python:` command form in docs 03 and 05 precisely (parsing, errors for unknown or unapproved scripts).
