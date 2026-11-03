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

## Migration flow

The agent is involved only in **planning**. The **apply** phase is a generated script run as-is; no agent reasoning,
interpretation or improvisation happens while changes are made.

1. **Detect.** At session start, compare `manifest.core_version` to the plugin's core version and **report** if behind
   (no action). Equal → done. Repo ahead of plugin → tell the user to update the plugin.
2. **Plan.** On explicit command, list the chain `N-to-N+1 ... M-1-to-M`, show the summaries, and note any `breaking: true` steps.
3. **Preflight.** Require a clean git working tree in the brain repo; otherwise stop.
4. **Dry run (agent).** For one step at a time, the agent reads the migration doc, inspects the brain repo, resolves all
   judgement calls (asking the user), and **generates a migration script** plus a dry-run report (see below).
   Nothing in the brain repo is modified. The agent may test the script against a scratch copy of the repo.
5. **Review and confirm.** The user reads the summary, risk level and script, and approves.
6. **Apply (script, no agent).** The user (or the agent acting only as a launcher) runs the script exactly as saved.
   The script is deterministic, takes the repo path as an argument, performs the changes, runs its own verification,
   updates the manifest, and commits `migrate: core N -> N+1`. It never pushes.
7. **Failure.** If any check fails, the script restores the paths it touched to their pre-run state, aborts without
   committing, and exits non-zero with a message. It never attempts repair.

## Dry run and generated migration script

The dry run produces **code**, not just a description. Its outputs live in `.brain/migrations/dry-runs/<from>-to-<to>-<timestamp>/`:

| File | Purpose |
|---|---|
| `report.md` | Summary (top), risk level with justification, planned changes, decisions made, unhandled items. |
| `migrate.<ext>` | The script the apply phase runs as-is. |
| `plan.json` | Machine-readable list of files the script will touch and the brain repo HEAD commit it was generated against. |

- **Script requirements:**
  - Deterministic and self-contained; all judgement calls from the migration doc are **already resolved and baked in** by the dry run. The script asks no questions.
  - Refuses to run unless the working tree is clean and HEAD equals the commit recorded in `plan.json` (a stale script is discarded and regenerated).
  - Touches only the paths listed in `plan.json`; verifies that before and after.
  - Supports a `--check` mode that prints the changes it would make and modifies nothing, so the user can see the diff without the agent.
  - Includes the migration doc's Verify checks as assertions and fails the run if any fails.
  - Updates `manifest.yml` and creates the single migration commit; never pushes.
- **Report contents:**
  1. **Summary:** plain-language overview, counts (files touched, items changed, definitions changed), anything needing a user decision, and the **risk level**.
  2. **Risk level:** `low` | `medium` | `high` with a one-to-three-line justification.
  3. **Planned changes:** per file diff or description for large mechanical changes.
  4. **Decisions made:** each judgement call and the answer baked into the script.
  5. **Unhandled items:** things the script deliberately does not touch (e.g. script adapters, hooks), flagged for human attention.
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

## Implementation versioning

- `version` in an implementation's frontmatter is an integer the user (or agent on their behalf) bumps when changing its schema.
- A schema change to an implementation that affects existing items (rename/remove/retype a field) should be accompanied by a
  migration note at `.brain/impls/<type>/<name>.migrations/<from>-to-<to>.md` using the same doc shape, so an agent can
  update existing items. Purely additive changes need no note.

## Open questions

1. ~~Check timing~~ — resolved: the check runs at session start but only **reports** that the repo is behind; applying a migration requires an explicit command.
2. ~~Changelog~~ — resolved: **GitHub releases** are the changelog. Each release that bumps the core version should state the new core version and link the matching `migrations/<from>-to-<to>.md`. No separate CHANGELOG file.
3. ~~Dry run~~ — resolved: yes, see Dry run below.
4. Item-level `schema_version` in frontmatter, or rely solely on implementation `version` plus the manifest? (Leaning no: avoids touching every file.)

5. Script language for generated migrations. Leaning Python 3 standard library only, run with `python3 -I`: ubiquitous and good at structured frontmatter edits. Alternative: POSIX shell plus `git` (fewer deps, poor for frontmatter).
6. Keep dry-run folders in the repo as an audit trail, or `.gitignore` them? Leaning commit them with the migration.

## Next steps

1. Decide open questions above.
2. Fold the manifest and `defaults` into the install-flow spec.
3. Start the per-slot contract specs (storage first).
