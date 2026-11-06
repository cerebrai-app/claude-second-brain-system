# 10 — Plugin Skills

Status: **Draft** · Depends on: all of [01](01-core-data-model.md) to [09](09-starter-implementations.md)

## Goal

The plugin has no application code. Its behavior is carried by **skills**: instructions Claude loads and follows, plus the deterministic scripts and adapters in the vault. This doc lists the system skills, what each owns, and how
they relate to the design docs. The skills are self-contained (the installed plugin does not include `docs/plans/`), so the rules the docs describe are restated in each skill's `references/`.

## The skill set

All live in `plugins/brain/skills/<name>/SKILL.md`. A plugin skill is invoked as `/brain:<name>`; the design docs write the same commands as `/brain <name>` for brevity.

| Skill | Command | Model-invocable | Owns |
|---|---|---|---|
| `core` | none (background knowledge) | yes | Core types, fields, relations, statuses, tags, traits, field types, placement and the Inbox, archive and delete rules, defaults, storage and automation references (`references/core-types.md`, `storage.md`, `automation.md`). Replaces the core semantics removed from the starters (doc 09). |
| `setup` | `/brain:setup` | no | Install flow and repair (doc 06). |
| `capture` | `/brain:capture` | yes | Creating items in the Inbox and persons (doc 06). |
| `triage` | `/brain:triage` | no | Placement and conversion (doc 06). |
| `sync` | `/brain:sync` | yes | Detecting external changes, events, and deferred dispatch (doc 05). |
| `pending` | `/brain:pending` | no | Reviewing deferred `claude` proposals (doc 05). |
| `run` | `/brain:run` | no | Listing rules and running `manual` rules (doc 05). |
| `validate` | `/brain:validate` | yes | Vault health checks and repair proposals (docs 06, 07, 08). |
| `python` | `/brain:python` | yes | The managed Python workspace and the "prefer a script to repetition" rule (doc 07). |

"Not model-invocable" skills change data or apply approvals, so only the user starts them. `capture`, `sync`, `validate` and `python` may also be started by Claude when the user's request calls for them.
Every command skill begins by reading `core`.

## Principles

- **One home for each rule.** A rule lives in `core` (or its references) when it is a system semantic, in a command skill when it is about that command's flow, and in a vault definition only when it is implementation-specific (doc 09).
- **The skills restate the docs; the docs remain the design record.** When a doc changes, update the matching skill or reference in the same change.
- **Approvals are never skipped.** Every skill that applies a `claude` proposal, a script, a hook or a conversion shows it and waits for approval, and records the result.

## Not yet written

1. **Migration command.** Doc 02's flow (check on session start, dry run, generated `migrate.py`, apply per step) has no skill yet.
2. **Session-start behavior.** The design says sync, the migration check and the pending count run at session start; the plugin needs a `SessionStart` hook for that.
3. **`lib/brain_adapter.py`.** Setup and the `python` skill copy it into the workspace, but the module is not yet in the plugin.
4. **System-provided views and rules** (doc 09, gap 2): generic named sorts, filters and rules, and how they are referenced.
5. **Shipped `README.md` and starter `pyproject.toml`** for the Python workspace (doc 07).

## Next steps

1. Write the migration skill (and the session-start hook).
2. Write `brain_adapter.py` and the workspace starter files.
3. Specify system-provided views and rules.
4. Try the skills end to end against a scratch vault and fix what the rehearsal exposes.
