# 09 — Built-in Starter Implementations

Status: **Draft** · Depends on: [01](01-core-data-model.md), [04](04-sort-filter.md), [05](05-automation.md), [06](06-install-and-triage.md), [08 — Core Types](08-core-types.md)

## Goal

Ship one working implementation per extensible core type, so a new vault works immediately and users have a reference to copy from. The files live in the plugin at
`plugins/brain/starters/<type>/default-<type>.md` and are **copied** into the vault's `.brain/impls/<type>/` by setup (doc 06), where the vault owns them (doc 01, Ownership).
They are definitions (doc 01 format), not code.

## What a starter contains *(Decided)*

A starter contains **only the file storage semantics**: the `markdown` adapter binding and the path template, plus the identity keys every definition needs (`impl`, `extends`, `version`).

```yaml
---
impl: default-task
extends: task
version: 1
storage:
  adapter: markdown
  path: "tasks/{id}.md"
---
```

Everything else is defined somewhere else:
- **At the top level (core and system):** the core fields, relations, statuses and their rules (doc 08), the semantics of the Inbox, placement and defaults (docs 01 and 06), automation, and guidance on how to work with each core type. These belong to the plugin's system skills and instructions, not to a vault's definitions.
- **By the user:** added schema fields, custom status values, sorts, filters, automation and traits are added to the vault's copy of the implementation when the user wants them (docs 01, 04, 05). A fresh vault has none.

| Starter | Type | Storage path |
|---|---|---|
| `default-task` | `task` | `tasks/{id}.md` |
| `default-note` | `note` | `notes/{id}.md` |
| `default-project` | `project` | `projects/{id}.md` |
| `default-area` | `area` | `areas/{id}.md` (the Inbox is stored here as `areas/inbox.md`) |
| `default-person` | `person` | `people/{id}.md` (the vault's single active person implementation, doc 01) |

## Conventions shared by every starter

- **One file per item, in its own top-level directory, named by `id`**, so renames and status changes never move files (doc 03 moves a file when its rendered path changes).
- **Version:** `version: 1`. Breaking changes ship as core migrations (doc 02) that rewrite the vault's copies.
- **No schema, status values, sorts, filters, automation, traits or guidance body.**

## Using and changing the starters

- A user edits the vault copy freely; the plugin never overwrites it. A newer starter is applied only by a core migration that the dry run shows (doc 02).
- To make a variant, copy a starter to a new impl id, change it, bump its `version`, and point the relevant `defaults` at it (doc 01). The person implementation is the exception: it is replaced through a migration target (doc 01).
- Setup (doc 06) copies all five and sets the Inbox `defaults` for the four placed types to the starters.

## Gaps found while writing the starters

1. ~~Field type vocabulary~~ — resolved: specified in [08 — Core Types](08-core-types.md) (Field types). Starters need none of it; it applies to fields users add.
2. **System-provided views and rules have no home yet.** With no sorts, filters or automation in the starters, anything a vault should have out of the box (a generic "recently updated" view, a "today" view) must come from the plugin's system skills. Where they are defined and how they are named so users and rules can reference them (doc 05 `surface`, doc 04) is not specified.
3. ~~System skills and instructions~~ — written: see [10 — Plugin Skills](10-plugin-skills.md). The `core` skill carries the semantics removed from the starters.

## Next steps

1. ~~Specify the field type vocabulary~~ — done (doc 08).
2. Specify system-provided views and rules (gap 2) in docs 04 and 05.
3. ~~Write the system skills and instructions~~ — done (doc 10).
4. Add the starters to the plugin's install flow implementation, copying them in step 2 of setup.
