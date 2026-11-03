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
2. **Plan.** List the chain `N-to-N+1 ... M-1-to-M`, show the user the summaries, and note any `breaking: true` steps.
3. **Preflight.** Require a clean git working tree in the brain repo; otherwise stop.
4. **Apply per step.** Follow the doc's Steps, resolve Judgement calls (asking the user where specified), run Verify.
5. **Record.** Update `core_version` and append to `migrations` in the manifest.
6. **Commit per step** (`migrate: core 1 -> 2`) so each is reviewable and revertible. Do not push without the user's say-so.
7. **Failure.** If Verify fails, stop, leave the working tree uncommitted for that step, and report. The user can discard with git.

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

1. Should the migration check run automatically at every session start, or only on an explicit command / plugin update?
2. Do we keep a `plugins/brain/CHANGELOG`-style index of core versions, or is the `migrations/` directory listing enough?
3. Dry-run mode: should the agent be able to produce a diff plan before touching files? (Leaning yes.)
4. Item-level `schema_version` in frontmatter, or rely solely on implementation `version` plus the manifest? (Leaning no: avoids touching every file.)

## Next steps

1. Decide open questions above.
2. Fold the manifest and `defaults` into the install-flow spec.
3. Start the per-slot contract specs (storage first).
