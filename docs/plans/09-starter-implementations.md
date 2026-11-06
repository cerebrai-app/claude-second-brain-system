# 09 — Built-in Starter Implementations

Status: **Draft** · Depends on: [01](01-core-data-model.md), [04](04-sort-filter.md), [05](05-automation.md), [06](06-install-and-triage.md), [08 — Core Types](08-core-types.md)

## Goal

Ship one working implementation per extensible core type, so a new vault works immediately and users have a reference to copy from. The files live in the plugin at
`plugins/brain/starters/<type>/default-<type>.md` and are **copied** into the vault's `.brain/impls/<type>/` by setup (doc 06), where the vault owns them (doc 01, Ownership).
They are definitions (doc 01 format), not code.

| Starter | Type | Storage path | Fields beyond the core | Notes |
|---|---|---|---|---|
| `default-task` | `task` | `tasks/{id}.md` | `due` (date), `priority` (`low`/`med`/`high`) | Sorts `due-then-priority` (pinned keys), `recent-first`; filters `actionable-today`, `overdue`; manual rule `today`. |
| `default-note` | `note` | `notes/{id}.md` | none | Sort `recent-first`; filter `untagged`. |
| `default-project` | `project` | `projects/{id}.md` | `target` (date) | Custom status `on_hold` (counts as `open`); sort `target-date`; filter `active`. |
| `default-area` | `area` | `areas/{id}.md` | none | Sort `by-title`. The Inbox is stored here as `areas/inbox.md`. |
| `default-person` | `person` | `people/{id}.md` | `email`, `phone` | The vault's single active person implementation (doc 01); sort `by-name`. |

## Conventions shared by every starter

- **Storage:** the built-in `markdown` adapter, one file per item, in its own top-level directory, named by `id` so renames and status changes never move files (doc 03 moves a file when its rendered path changes).
- **Version:** `version: 1`. Breaking changes ship as core migrations (doc 02) that rewrite the vault's copies.
- **No placement or status in the path:** keeps git history clean and paths stable.
- **Sorts** referenced by automation have **pinned `keys`** (doc 04) so unattended runs never depend on a model-proposed schema.
- **Filters** are plain English with a structural `scope` where one applies (doc 04). Pinned interpretations are omitted until the predicate grammar is decided (doc 04, open question).
- **Automation:** only a `manual` convenience rule on tasks. No event rules ship by default, so a new vault has no hidden behavior.
- **Guidance body:** each file ends with short instructions Claude reads when working with items of that implementation (what the fields mean, what not to guess).
- **No traits ship.** Traits are the user's to define (doc 01).
- **No tag or status customization** beyond what the core provides, except `default-project`'s `on_hold`.

## Using and changing the starters

- A user edits the vault copy freely; the plugin never overwrites it. A newer starter is applied only by a core migration that the dry run shows (doc 02).
- To make a variant, copy a starter to a new impl id, change it, bump its `version`, and point the relevant `defaults` at it (doc 01). The person implementation is the exception: it is replaced through a migration target (doc 01).
- Setup (doc 06) copies all five and sets the Inbox `defaults` for the four placed types to the starters.

## Gaps found while writing the starters

1. **Field type vocabulary is not specified anywhere.** The starters use `string`, `date`, `datetime` and `enum` (with `values` and `default`). The full set (and `number`, `bool`, `list`, validation constraints) needs a section, probably in doc 08.
2. **Sort `keys` for envelope properties.** `recent-first` keys on `updated`, an envelope property rather than a field. Doc 04 should say keys may name envelope properties (`created`, `updated`) and Person `name` parts.
3. **Pinned filter interpretations** are omitted pending the predicate grammar (doc 04).

## Next steps

1. Specify the field type vocabulary (gap 1) and the key-name rules (gap 2).
2. Add the starters to the plugin's install flow implementation, copying them in step 2 of setup.
3. Decide whether a few more starters are worth shipping (a GTD-style task variant, a journal note variant for the daily-journal example in doc 05).
