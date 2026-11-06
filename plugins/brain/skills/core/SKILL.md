---
name: core
description: Core rules for working in a second-brain vault (a git repo with a .brain/ directory). Covers the core types (note, task, project, area, person, archive), fields, relations, statuses, tags, traits, the Inbox, placement, archiving and deleting, and how items are stored. Load before reading, creating, changing, archiving, converting or deleting any vault item, or answering questions about what is in the vault.
---

# Second brain: core rules

A **vault** is a git repo that contains a `.brain/` directory (the repo root is the vault root). Find it by walking up from the working directory to the nearest `.brain/manifest.yml`.
If there is a `.brain/` with no manifest, setup did not finish: tell the user to run `/brain:setup`. If there is no `.brain/`, the directory is not a vault.

Detail lives in the reference files next to this skill. Read the one you need before acting:

- [references/core-types.md](references/core-types.md): fields, relations, statuses, tags, traits, field types, reserved names.
- [references/ids-and-slugs.md](references/ids-and-slugs.md): how ULIDs and slugs are made (the helper commands, slug rules).
- [references/storage.md](references/storage.md): item shape, storage operations, archive, delete, conversion, adapters.
- [references/automation.md](references/automation.md): rules, triggers, actions, approvals, the pending queue.

## What you must always do

1. **Identify items by ref** `<type>:<id>` (for example `task:01JABC...`). The `id` is a ULID the plugin assigns and never changes, and it is independent of the implementation and the file path.
2. **Respect the five core types** (`note`, `task`, `project`, `area`, `person`) plus the non-extensible `archive`. An item's `type` never changes; only its implementation (`impl`) can.
3. **Validate before you write.** Check required fields, field types and constraints from the item's implementation definition (`.brain/impls/<type>/<impl>.md`), relation targets and cardinality, and reserved names. Refuse and explain rather than writing an invalid item.
4. **Do not invent.** Leave optional fields empty rather than guessing (dates, priorities, family names, outcomes). Do not add tags, traits, relations or fields the user did not ask for.
5. **Placement and the Inbox.** An item with no placement relation (`task.belongs_to`, `note.about` Project/Area, `project.area`) is in the Inbox (`area:inbox`). Persons and Areas are top-level: never placed, never in the Inbox, never triaged (`area.parent` only nests areas).
6. **Archive instead of delete.** To remove an item, archive it. Permanent delete is an exception: confirm with the user first, and never from automation. The Inbox and the Archive cannot be archived or deleted.
7. **Show diffs, then apply.** For anything beyond a trivial edit, show the user what will change. Changes proposed by Claude actions need per-proposal approval (see the automation reference).
8. **Keep derived state out of git.** `.brain/index/`, `.brain/cache/`, `.brain/automation/seen|pending|log.jsonl`, `.brain/conversions/`, `.brain/python/.venv/` are ignored; never commit them.
9. **Do not commit unless the user asks** (setup and triage offer a commit at the end).
10. **Ids and slugs come from the helper, never from you.** Follow [references/ids-and-slugs.md](references/ids-and-slugs.md); a slug's source is in the Slug section of the implementation's definition (`.brain/impls/<type>/<impl>.md`).
11. **Keep derived state in step after every write** until `brainctl` has `create`/`update`: refresh `updated` (and `completed` when a task or project's status category changes), then run `brainctl sync --refresh` so the sync seen state accepts your own write. Forgetting it makes the next sync report your edit as an outside change.
12. **Check your work with `brainctl validate`** after changes that touch several items, and before offering a commit.

## Running `brainctl`

`brainctl` is the deterministic helper copied into the vault at `.brain/python/brainctl/` (spec: `docs/plans/11-brainctl-helper.md`). Run it from `.brain/python` through the workspace tool recorded in `python.tool` in `.brain/config.yml`, in the workspace virtualenv (`.brain/python/.venv`) only, using the locked environment without re-resolving: for `uv`, `uv run --frozen python -m brainctl <command>`; for `poetry`, `poetry run python -m brainctl <command>`; for `pdm`, `pdm run python -m brainctl <command>`. It finds the vault by walking up. Output is JSON on stdout (add `--text` for people); exit code 0 is success, 1 means findings or not found, 2 is a usage error.

| Command | Use |
|---|---|
| `validate [--ref R]` | Every mechanical check of the vault; exit 1 if any error. Read-only. |
| `sync [--no-adopt] [--dry-run]` | Detect outside changes, adopt hand-written files, update the seen state; returns `events` and a `report`. |
| `sync --refresh` | Accept the current state as seen (no events, no adoption), after your own writes. |
| `list`, `read <ref>` | Items across bindings and the Archive. |
| `id [-n N]`, `slug <title> [--dir D]` | New ULIDs and unique slugs (the latter as the implementation's Slug section directs). |
| `approve-hash <script>` | The workspace approval hash. |

Not available yet: `create`, `update`, `archive`, `unarchive`, `delete`, `convert`. Until they exist, write item files by hand following these rules, then `sync --refresh` and `validate`. Script-adapter bindings are not read yet; `sync` and `validate` report them as incomplete/skipped.

## Defaults for new items

A new item's implementation comes from, in order: the item's Project `defaults.<type>`, its Area `defaults.<type>`, the Inbox `defaults.<type>`, then the plugin's built-in `default-<type>`. A Project may set defaults only for `task` and `note`.
**Person is the exception:** the vault has exactly one active person implementation (plus at most one `migration_target: true` while migrating); every new person uses the active one, and `person` is never a valid `defaults` key.

## Where things are

| Path | Contents |
|---|---|
| `.brain/config.yml` | Vault name, Archive adapter, `python.tool`, `capture.type_by_source` |
| `.brain/manifest.yml` | Core version and implementation/trait versions (written last by setup) |
| `.brain/impls/<type>/<impl>.md` | Implementation definitions (storage binding, schema, sorts, filters, automation) |
| `.brain/traits/<name>.md` | Person trait definitions |
| `.brain/automation.yml` | Vault-level rules (created on first use) |
| `.brain/id-index/<type>/<impl>.json` | Native-id mapping for script adapters (committed) |
| `.brain/python/` | The managed Python workspace |
| `tasks/`, `notes/`, `projects/`, `areas/`, `people/`, `archive/` | Items stored by the default markdown adapter |

Implementations may bind to other adapters; read the definition, not the directory layout, to find where an item lives.
