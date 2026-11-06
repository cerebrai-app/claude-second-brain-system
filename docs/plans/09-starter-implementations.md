# 09 — Built-in Starter Implementations

Status: **Draft** · Depends on: [01](01-core-data-model.md), [04](04-sort-filter.md), [05](05-automation.md), [06](06-install-and-triage.md), [08 — Core Types](08-core-types.md)

## Goal

Ship one working implementation per extensible core type, so a new vault works immediately and users have a reference to copy from. The files live in the plugin at
`plugins/brain/starters/<type>/default-<type>.md` and are **copied** into the vault's `.brain/impls/<type>/` by setup (doc 06), where the vault owns them (doc 01, Ownership).
They are definitions (doc 01 format), not code.

## What a starter contains *(Decided)*

A starter holds only what is specific to **this implementation and its backend**:

1. the **`storage` binding** (adapter and path template);
2. **schema fields the implementation adds** beyond the core (doc 08), and any **custom `status_values`**;
3. **sorts and filters that depend on those added fields or values**;
4. a **short body** only for guidance about those added fields.

It does **not** contain system rules. These belong to the plugin's system skills and instructions:
- the meaning of core fields, relations and statuses (the base `name` parts and rules for Person, what makes a task blocked, placement, the Inbox, how defaults resolve);
- automation rules (no `automation:` block ships in any starter);
- generic views that use only core fields (for example "most recently updated first" or "untagged");
- guidance on how to work with a core type.

| Starter | Type | Storage path | Fields beyond the core | Sorts and filters |
|---|---|---|---|---|
| `default-task` | `task` | `tasks/{id}.md` | `due` (date), `priority` (`low`/`med`/`high`) | Sort `due-then-priority` (pinned keys); filters `actionable-today`, `overdue` |
| `default-note` | `note` | `notes/{id}.md` | none | none |
| `default-project` | `project` | `projects/{id}.md` | `target` (date); custom status `on_hold` (counts as `open`) | Sort `target-date`; filter `active` |
| `default-area` | `area` | `areas/{id}.md` | none | none. The Inbox is stored here as `areas/inbox.md`. |
| `default-person` | `person` | `people/{id}.md` | `email`, `phone` | none. The base `name` structure and Person rules are core (doc 08), not repeated here. |

## Conventions shared by every starter

- **Storage:** the built-in `markdown` adapter, one file per item, in its own top-level directory, named by `id` so renames and status changes never move files (doc 03 moves a file when its rendered path changes).
- **Version:** `version: 1`. Breaking changes ship as core migrations (doc 02) that rewrite the vault's copies.
- **Sorts** referenced by automation have **pinned `keys`** (doc 04) so unattended runs never depend on a model-proposed schema.
- **Filters** are plain English with a structural `scope` where one applies (doc 04). Pinned interpretations are omitted until the predicate grammar is decided (doc 04, open question).
- **No traits ship.** Traits are the user's to define (doc 01).

## Using and changing the starters

- A user edits the vault copy freely; the plugin never overwrites it. A newer starter is applied only by a core migration that the dry run shows (doc 02).
- To make a variant, copy a starter to a new impl id, change it, bump its `version`, and point the relevant `defaults` at it (doc 01). The person implementation is the exception: it is replaced through a migration target (doc 01).
- Setup (doc 06) copies all five and sets the Inbox `defaults` for the four placed types to the starters.

## Gaps found while writing the starters

1. **Field type vocabulary is not specified anywhere.** The starters use `string`, `date` and `enum` (with `values` and `default`), and sorts use `datetime`. The full set (and `number`, `bool`, `list`, validation constraints) needs a section, probably in doc 08.
2. **Sort `keys` for envelope properties.** Doc 04 should say keys may name envelope properties (`created`, `updated`) and Person `name` parts.
3. **Pinned filter interpretations** are omitted pending the predicate grammar (doc 04).
4. **System-provided views and rules have no home yet.** With generic sorts, filters and automation removed from the starters (for example "recent first" or a daily "today" view), the plugin's system skills must provide them. Where they are defined, and how they are named so users and rules can reference them (doc 05 `surface`, doc 04), is not specified.

## Next steps

1. Specify the field type vocabulary (gap 1) and the key-name rules (gap 2).
2. Add the starters to the plugin's install flow implementation, copying them in step 2 of setup.
3. Specify system-provided views and rules (gap 4) in docs 04 and 05, and the system skills and instructions that carry the core semantics removed from the starters.
4. Decide whether a few more starters are worth shipping (a GTD-style task variant, a journal note variant for the daily-journal example in doc 05).
