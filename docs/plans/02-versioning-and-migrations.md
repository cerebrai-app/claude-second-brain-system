# 02 — Versioning and Migrations

Status: **Draft** · Depends on: [01 — Core Data Model](01-core-data-model.md)

## Goal

Let the plugin's core model evolve without breaking a user's brain repo. Core changes ship with instructions an agent
follows to bring the user's implementations and items up to date.

## Versions in play

| Version | Lives in | Meaning |
|---|---|---|
| **Core version** | `plugins/brain/` (plugin manifest + `core-version` file) | Version of the core model contracts (types, required fields, slot contracts, resolution rules). |
| **Brain repo core version** | `second-brain/.brain/manifest.yml` | The core version the brain repo currently conforms to. |
| **Implementation version** | Each implementation definition's frontmatter (`version`) | The user's own revision of that implementation; the plugin never changes it except during a migration. |

Core version is a plain integer (`1`, `2`, ...). It is separate from the plugin's semver: many plugin releases may share
a core version. A bump of the core version is required whenever a change could invalidate existing definitions or items
(field renamed/removed, new required field, changed relation semantics, changed resolution rules). Additive, optional
changes do not bump it.

## Manifest: `second-brain/.brain/manifest.yml`

```yaml
core_version: 1                 # core version this repo conforms to
plugin_version_last_run: 0.0.1  # informational; plugin that last touched the repo
migrations:                     # applied history, append-only
  - from: 0
    to: 1
    applied: 2026-11-03
    commit: abc1234
implementations:
  task/gtd-task:   { version: 3 }
  note/zettel-note: { version: 1 }
```

- Written by the install flow (`core_version` = the plugin's current core version, empty `migrations`).
- `implementations` is a derived index for quick checks; the definition file's own `version` is authoritative.
- Only the migration flow changes `core_version`.

## Migration docs: `plugins/brain/migrations/<from>-to-<to>.md`

One file per single-step core version bump (`1-to-2.md`), never skipping versions. Each is written for an agent and has a fixed shape:

```markdown
---
from: 1
to: 2
summary: Rename Task.state to Task.status
breaking: true
---
## What changed
Plain-language description and rationale.

## Steps
Ordered, concrete instructions. Each step says what to find, what to change, and how.
1. In every implementation definition under `.brain/impls/task/`, rename schema field `state` to `status` ...
2. In every item with `type: task`, rename frontmatter key `state` to `status` ...

## Judgement calls
Where the agent must decide or ask the user (e.g. custom values that do not map cleanly), and how to decide.

## Verify
Checks proving the step worked (grep for old key returns nothing, sample items parse, etc.).

## Rollback
How to revert (normally `git revert` of the step's commit).
```

## Partial migrations and recovery

There is **no per-object version marker**: not every storage backend can persist one, so state is tracked at the repo level.

- Before changing anything, the script writes `migration_in_progress: { from: N, to: N+1, script: <dry-run folder> }` to
  `manifest.yml`. It removes the marker and sets `core_version` only after all changes and checks succeed, in the same commit.
- **Idempotent transforms:** every transformation in the script first tests whether it has already been applied
  (e.g. the old key is absent / the new key is present) and skips if so. Re-running `migrate.py` on a half-migrated tree
  therefore finishes the job and never double-applies.
- **Normal failure:** the script restores the paths it touched and removes the marker (flow step 7).
- **Crash or kill:** the marker and uncommitted changes remain. The session-start check reports a partial migration. The user
  either re-runs the same `migrate.py` (resume) or discards everything with git (`git restore`/`git clean` on the paths in
  `plan.json`) and removes the marker.
- **Archived items** are part of every migration: the script also transforms objects held by the Archive adapter (doc 03).
- **Non-file storage** (external adapters): the script can only act on them through their adapter's script protocol (doc 03).
  Writes there are not covered by git rollback, so such steps must be idempotent too. They are tested against a sample
  snapshot (see Required test run), and the risk level is at least `medium` (`high` if the step is not safely re-runnable).

## Migration flow

The agent is involved only in **planning**. The **apply** phase is a generated script run as-is; no agent reasoning,
interpretation or improvisation happens while changes are made.

1. **Detect.** At session start, compare `manifest.core_version` to the plugin's core version and **report** if behind
   (no action). Equal → done. Repo ahead of plugin → tell the user to update the plugin.
2. **Plan.** On explicit command, list the chain `N-to-N+1 ... M-1-to-M`, show the summaries, and note any `breaking: true` steps.
3. **Preflight.** Require a clean git working tree in the brain repo; otherwise stop.
4. **Dry run (agent).** For one step at a time, the agent reads the migration doc, inspects the brain repo, resolves all
   judgement calls (asking the user), and **generates a migration script** plus a dry-run report (see below).
   Nothing in the brain repo is modified. The agent **must** test the script (see Required test run) before presenting it.
5. **Review and confirm.** The user reads the summary, risk level and script, and approves.
6. **Apply (script, no agent).** The user (or the agent acting only as a launcher) runs the script exactly as saved.
   The script is deterministic, takes the repo path as an argument, performs the changes, runs its own verification,
   updates the manifest, and commits `migrate: core N -> N+1`. It never pushes.
7. **Failure.** If any check fails, the script restores the paths it touched to their pre-run state, removes the in-progress marker, aborts without
   committing, and exits non-zero with a message. It never attempts repair. If the process dies before it can restore
   (crash, kill), see Partial migrations and recovery.

## Dry run and generated migration script

The dry run produces **code**, not just a description. Its outputs live in `.brain/migrations/dry-runs/<from>-to-<to>-<timestamp>/`:

| File | Purpose |
|---|---|
| `report.md` | Summary (top), risk level with justification, planned changes, decisions made, unhandled items. |
| `migrate.py` | The script the apply phase runs as-is. |
| `plan.json` | Machine-readable list of files the script will touch and the brain repo HEAD commit it was generated against. |

- **Script requirements:**
  - Deterministic and self-contained; all judgement calls from the migration doc are **already resolved and baked in** by the dry run. The script asks no questions.
  - Refuses to run unless HEAD equals the commit recorded in `plan.json` (a stale script is discarded and regenerated) and the working tree is clean, **except** when resuming a partial run of this same script (detected by `migration_in_progress` in the manifest naming this script, and uncommitted changes only in paths listed in `plan.json`).
  - Idempotent: each transform checks whether it is already applied and skips if so.
  - Touches only the paths listed in `plan.json`; verifies that before and after.
  - Supports a `--check` mode that prints the changes it would make and modifies nothing, so the user can see the diff without the agent.
  - Includes the migration doc's Verify checks as assertions and fails the run if any fails.
  - Sets `migration_in_progress` in `manifest.yml` first, clears it and sets `core_version` last, then creates the single migration commit (which includes the dry-run folder); never pushes.
  - Python 3 standard library only; no third-party imports. Run as `python3 -I migrate.py <repo-path>`.
- **Required test run:** before the user is asked to approve, the agent runs `migrate.py` for real (not `--check`) against an
  isolated copy of the brain repo and records the outcome in `report.md`.
  - If the brain repo is a git repo: use a **git worktree** at the planned HEAD commit (`git worktree add <tmp> <commit>`), removed afterward.
  - Otherwise: a **scratch copy** of the directory in a temporary location, deleted afterward.
  - The test must show: the script exits 0, all verify assertions pass, the resulting diff matches `plan.json`'s file list,
    and **a second run is a no-op** (proves idempotency, which resume depends on).
  - Additionally, to exercise resume, the agent interrupts a run partway where practical (e.g. a test-only `--stop-after N`
    flag) and confirms a re-run completes to the same final tree as an uninterrupted run.
  - **External storage** is tested against a **sample snapshot** (next subsection) instead of the live system.
  - A failed test run blocks approval; the agent fixes the script and re-tests, and the report records the final passing run only.
- **External storage sample testing:** git and scratch copies cannot cover objects held by an external adapter, so:
  1. **Sample.** The agent asks the adapter (doc 03 script protocol, `list` + `read`) for a sample of its objects and saves it to
     `sample.json` in the dry-run folder. JSON, because the scripts are standard-library Python (no YAML parser); the
     sample holds each object's core fields, impl fields and ref (`<type>:<id>`), with secrets and large bodies redacted or truncated.
  2. **Sampling rule.** Stratified: for each type and implementation the migration touches, take up to K objects (default 10),
     always including edge cases the migration doc names (missing optional fields, unusual values, empty relations) and the
     objects with the most unusual field sets. Record sample size versus total count per type.
  3. **Patch.** In the test run, `migrate.py` runs with a **fixture adapter** that serves `sample.json` instead of the real
     adapter and writes its updates back into a copy of the sample (`sample.migrated.json`). The real system is never contacted or written.
  4. **Check.** The script's verify assertions run against the patched sample, and a second run over `sample.migrated.json` must be a no-op.
  5. **Report.** The report includes the before/after of every sampled object (or a diff for large ones) and the coverage numbers.
  - A sample cannot prove the full data set migrates cleanly. External-storage steps therefore keep a risk floor of `medium`; the
    risk is `high` if coverage is low (e.g. under ~10% of a type with irregular data), a step is not safely re-runnable, or the
    adapter's write path cannot be exercised by the fixture.
  - When applying for real, the script writes to the real adapter through the same protocol it used in the fixture.
- **Report contents:**
  1. **Summary:** plain-language overview, counts (files touched, items changed, definitions changed), anything needing a user decision, and the **risk level**.
  2. **Risk level:** `low` | `medium` | `high` with a one-to-three-line justification.
  3. **Planned changes:** per file diff or description for large mechanical changes.
  4. **Test run:** result of the required test run (pass/fail, files changed, idempotency and resume results, external-storage sample coverage per type, anything not covered).
  5. **Decisions made:** each judgement call and the answer baked into the script.
  6. **Unhandled items:** things the script deliberately does not touch (e.g. script adapters, hooks), flagged for human attention.
- **Risk rubric** (highest level any single factor reaches):
  - `low`: purely mechanical, fully reversible via git, no judgement calls, no unhandled items.
  - `medium`: judgement calls with clear defaults, many items changed, or the doc is marked `breaking: true`.
  - `high`: data could be lost or become ambiguous (dropped fields, lossy type changes), unhandled script adapters/hooks, external storage adapters affected, or a verify step that cannot be fully automated.
- **Gate:** a step cannot be applied without a dry run for that exact step. `high` requires an explicit confirmation naming the risk.
- **Rollback:** `git revert` of the migration commit; the script also backs out its own changes on failure (flow step 7).

## User implementations that conflict with a core change

The migration doc is the first line: it should say how to adapt user definitions. For definitions it cannot cover (custom
hooks, script adapters), the agent flags them in a **migration report** (`.brain/migration-report.md`, committed with the step)
listing what needs human attention rather than guessing.

## Vault-level automation (doc 05)

`.brain/automation.yml` is migrated like other vault config. Each rule declares its `requires` (implementations, optional `min_version`); the dry run
uses them to list every vault rule affected by a change to a required implementation (rename, removal, version bump, changed field or filter) in the
migration report. Rules whose required implementation disappears are marked *blocked*, not deleted. Rules containing hooks are listed under
*Unhandled items*.

## Implementation versioning

- `version` in an implementation's frontmatter is an integer the user (or agent on their behalf) bumps when changing its schema.
- A schema change to an implementation that affects existing items (rename/remove/retype a field) should be accompanied by a
  migration note at `.brain/impls/<type>/<name>.migrations/<from>-to-<to>.md` using the same doc shape, so an agent can
  update existing items. Purely additive changes need no note.

## Open questions

1. ~~Check timing~~ — resolved: the check runs at session start but only **reports** that the repo is behind; applying a migration requires an explicit command.
2. ~~Changelog~~ — resolved: **GitHub releases** are the changelog. Each release that bumps the core version should state the new core version and link the matching `migrations/<from>-to-<to>.md`. No separate CHANGELOG file.
3. ~~Dry run~~ — resolved: yes, see Dry run below.
4. ~~Item-level `schema_version`~~ — resolved: **no**. Not every storage backend can persist per-object fields, so migration state is tracked at the repo level only (manifest) and recovery relies on idempotent scripts and git. Items do not record an implementation `version` either.

5. ~~Script language~~ — resolved: **Python 3, standard library only**, run with `python3 -I`. Generated script is `migrate.py`.
6. ~~Dry-run retention~~ — resolved: dry-run folders are **kept and committed** with the migration as an audit trail.

## Next steps

1. Fold the manifest and `defaults` into the install-flow spec (doc 01, to be written), including the initial manifest created at setup.
2. Add vault-level automation (`.brain/automation.yml`, doc 05) to the worked migration examples once the first real migration exists.
3. Build and exercise the dry-run sampler against a real vault to validate the generated `migrate.py` flow.
4. Deferred items are tracked in [Deferred and Out-of-Scope Items](deferred.md).
