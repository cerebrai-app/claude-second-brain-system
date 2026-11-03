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

1. **Detect.** At session start (or via an explicit command), compare `manifest.core_version` to the plugin's core version.
   Equal → done. Repo ahead of plugin → stop and tell the user to update the plugin. Behind → continue.
2. **Plan and dry run.** List the chain `N-to-N+1 ... M-1-to-M`, show the user the summaries, and note any `breaking: true` steps.
3. **Preflight.** Require a clean git working tree in the brain repo; otherwise stop.
4. **Confirm, then apply per step.** After the dry run summary is approved, follow the doc's Steps, resolve Judgement calls (asking the user where specified), run Verify.
5. **Record.** Update `core_version` and append to `migrations` in the manifest.
6. **Commit per step** (`migrate: core 1 -> 2`) so each is reviewable and revertible. Do not push without the user's say-so.
7. **Failure.** If Verify fails, stop, leave the working tree uncommitted for that step, and report. The user can discard with git.

## Dry run

Before applying a migration, the agent produces a dry run: it follows the migration doc's Steps **without modifying any
item or definition**, and records what it would do.

- **Output file:** `.brain/migrations/dry-runs/<from>-to-<to>-<timestamp>.md` in the brain repo. It is written only
  into that directory and is not part of the migration commit unless the user chooses to keep it.
- **Contents:**
  1. **Summary** (top of file): plain-language overview of what will change, counts (files touched, items changed,
     definitions changed), anything that needs a user decision, and the **risk level**.
  2. **Risk level:** `low` | `medium` | `high`, with a one-to-three-line justification.
  3. **Planned changes:** per file, the proposed diff (or a description for large mechanical changes).
  4. **Judgement calls:** each decision the agent would need, with its proposed answer.
  5. **Unhandled items:** things flagged for human attention (e.g. script adapters, hooks).
- **Risk rubric:**
  - `low`: purely mechanical, fully reversible via git, no judgement calls, no unhandled items.
  - `medium`: judgement calls with clear defaults, or changes to many items, or the doc is marked `breaking: true`.
  - `high`: data could be lost or become ambiguous (dropped fields, lossy type changes), unhandled script
    adapters/hooks, external storage adapters affected, or any verify step that cannot be fully automated.
  The agent takes the highest level any single factor reaches.
- **Gate:** after the dry run the agent shows the summary and risk level and asks the user to proceed. `high` requires an
  explicit confirmation naming the risk. Applying a migration without a prior dry run for that exact step is not allowed.
- **Staleness:** a dry run records the brain repo's HEAD commit; if HEAD differs when applying, the dry run is
  discarded and regenerated.

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

## Next steps

1. Decide open questions above.
2. Fold the manifest and `defaults` into the install-flow spec.
3. Start the per-slot contract specs (storage first).
