# 01 — Core Data Model

Status: **Draft** · Branch: `claude/admiring-rubin-4sq9mk`

## Goal

Define a small set of **core model types** that the `brain` plugin understands, and let a user define their own
**implementations** of those types. An implementation owns its own rules for sorting, filtering, automation, and storage.
The core provides contracts; implementations provide behavior.

## Decisions so far

| Topic | Decision |
|---|---|
| Core types | `Note`, `Task`, `Project`, `Area`, `Person` (PARA-flavored) |
| Extension mechanism | **Hybrid**: declarative definition files by default, script/hook adapters as an escape hatch |
| Default storage | Markdown files with YAML frontmatter in the `second-brain` repo (git-versioned) |
| Sort/filter language | **Natural language, interpreted by Claude.** Sorts and filters are plain-English descriptions; a formal expression language can be added later as an optimization. |
| Default implementation | **Cascading overrides: Project → Area → Inbox.** The **Inbox is the default Area**: any item or Project with no explicit area belongs to it. The Inbox's defaults are the vault-wide defaults and are configured at plugin install. Areas and Projects may each override them. |
| Cross-implementation relations | References are `<type>:<id>` and resolve across implementations; no implementation-specific syntax is needed. |
| Ownership | **Core** types, contracts, built-in starters and migration instructions live in the plugin repo (`plugins/brain/`). **User-defined** implementations, config and data live in the user's brain repo (`second-brain`). |
| Extensibility | Five core types (`Note`, `Task`, `Project`, `Area`, `Person`) are extensible (a vault defines its own schema fields for them); `Person` has exactly one **active** implementation per vault (a second may exist only as a migration target, see Default implementation resolution), `markdown` in its own `people/` directory by default. **`Archive` is a sixth core type that is not extensible**: no user implementations, one built-in definition. |
| Archive | `Archive` is a container core type that can hold objects of **every other type** (the same objects as the vault, keeping their `ref`, `type` and `impl`). Archiving an item moves it into the Archive; it is the default way to remove an item (permanent delete is the exception). See Archive below and doc 03. |
| Versioning | Schema changes are handled by **migration instructions an agent follows**, driven by a **version manifest in the brain repo**. |
| Inheritance | An implementation `extends` a **core type only**; no implementation-to-implementation inheritance. Shared behavior is reused by copying or by referencing named sorts/filters/actions, not by extending. The one exception is **traits** (see Traits): optional, namespaced field bundles attached to individual people (`Person` only). |

## Concepts

- **Core type** — a contract shipped by the plugin: required fields, allowed relations, and the behavior slots it supports.
- **Implementation** — a user-defined realization of a core type (e.g. `Task` → `gtd-task`, `linear-task`). A vault may have several per core type, **except `Person`, which has exactly one active implementation per vault** (plus, temporarily, a migration target).
- **Item** — an instance of an implementation. Always carries `id`, `type` (core), `impl` (implementation name), `created`, `updated`.
- **Behavior slots** — the pluggable parts of an implementation:
  1. **Schema** — fields beyond the core required set, with types and validation.
  2. **Storage** — where/how items persist (path template, file format; or an adapter).
  3. **Sort** — named orderings (e.g. `due-then-priority`).
  4. **Filter** — named predicates/views (e.g. `actionable-today`).
  5. **Automation** — triggers (on-create, on-change, on-capture, manual; on-schedule is post-MVP, doc 05) and actions.
  6. **Relations** — typed links to other items (see below).

## Core types

Summary only; fields, relations, cardinality, status rules and reserved names are specified in [08 — Core Types](08-core-types.md).

| Type | Purpose | Required core fields | Core relations |
|---|---|---|---|
| `Note` | Knowledge / reference / captured thought | `title` | `about` → Project/Area/Person (at most one Project or Area), `links` → Note |
| `Task` | Actionable unit with a state | `title`, `status` (`open`/`done`/`dropped`, plus declared custom values) | `belongs_to` → Project/Area, `assigned_to` → Person, `blocked_by` → Task |
| `Project` | Outcome with an end state | `title`, `status` (`outcome` optional) | `area` → Area, `owner` → Person |
| `Area` | Ongoing responsibility, no end date | `title` | `parent` → Area |
| `Person` | Someone you interact with. **Top-level:** not placed in any Area or Project, and never in the Inbox | `name` (structured: `given`, `family`, ...) | Named relations to any item (names are chosen by the implementation or the user, e.g. `works_with`, `owner_of`); no required relation |
| `Archive` | Holds retired objects of any type | `title` | `contains` → any item except Archive |

All five extensible types also have an optional `tags` map (`Map<String, String>`, no hierarchy, doc 08), and Task and Project have a plugin-maintained `completed` timestamp. Core fields are deliberately minimal; implementations add the rest. **`Archive` is the exception: it cannot be extended.**

### Archive

- A container, like an Area, but for retired objects. It accepts items of all five extensible types, keeping their `ref`
  (`<type>:<id>`), `type`, `impl`, fields and relations unchanged, so existing references still resolve.
- **Not extensible:** no implementations, no custom schema, storage, sort, filter or automation slots, and no `defaults`.
  Its behavior is fixed by the plugin (browsing, restoring, listing), so every vault's Archive works the same way.
- An Archive cannot contain an Archive, and cannot itself be archived or deleted.
- The vault has exactly one system Archive, with id `archive` (ref `archive:archive`), created at install (like the Inbox area). No other Archives, no qualifiers.
- An archived item still follows its own implementation's **schema**, but is stored by the Archive's **single storage adapter**
  (one adapter for the whole vault, chosen at install, which must support all object types; see doc 03), not by its implementation's binding.
  Restoring writes it back to its implementation's binding (to its previous Area/Project when those still exist).

## Item shape (markdown + frontmatter)

```markdown
---
id: 01JABCDEF...          # stable, implementation-independent
type: task                # core type
impl: gtd-task            # implementation
title: Draft Q4 plan
status: open
belongs_to: [project:01J...]
due: 2026-11-15           # impl-specific field
---
Free-form body.
```

References use `<type>:<id>` so they survive file moves and storage changes.

## Implementation definition (declarative, hybrid)

Location (proposed): `second-brain/.brain/impls/<core-type>/<impl-name>.md` — YAML frontmatter for structure,
markdown body for guidance that Claude reads when working with items of that implementation.

```yaml
---
impl: gtd-task
extends: task
schema:
  fields:
    due:      { type: date }
    priority: { type: enum, values: [low, med, high], default: med }
storage:
  adapter: markdown            # built-in
  path: "tasks/{status}/{id}.md"
sorts:
  due-then-priority: "Soonest due date first; undated tasks last; ties broken by higher priority first."
filters:
  actionable-today: "Open tasks that are not blocked and are either undated or due today or earlier."
automation:
  - on: create
    do: [ { action: link-inbox-source } ]
  - on: manual
    do: [ { action: surface, filter: actionable-today } ]
  - on: change
    when: "status -> done"
    do: [ { action: hook, run: ".brain/hooks/log-completion.sh" } ]   # escape hatch
---
```

**Escape hatch:** any slot may specify `adapter: script` / `action: hook` pointing at an executable that
implements the slot's contract (stdin/stdout JSON). Declarative is the default; scripts cover storage backends
(Linear, Trello, etc.) and complex automation.

## Behavior-slot contracts (to specify next)

- **Storage**: specified in [03 — Storage Contract](03-storage-contract.md).
- **Sort/Filter**: natural-language descriptions evaluated by Claude, specified in [04 — Sorts and Filters](04-sort-filter.md).
- **Automation**: specified in [05 — Automation](05-automation.md). Rules in an implementation's `automation:` list can use the `manual` and event
  triggers (including `before_delete`, a veto-only safeguard on permanent delete) and the built-in actions, including `write_body` (edit an item's markdown
  body) and `surface` results bound with `as:` for use by later actions. Rules that span implementations are **vault-level**: they live in
  `second-brain/.brain/automation.yml`, may use only the `manual` trigger in the MVP, and must declare the implementations they `require`.

## Open questions

1. ~~Expression language~~ — resolved: natural language for now. Follow-ups: reproducibility across runs, cost at large vault sizes, and when to add a formal fallback.
2. ~~Inheritance~~ — resolved: core type only (see Decisions).
3. ~~Default implementation~~ — resolved: cascading Project → Area → Inbox (see Decisions and Default resolution). Project overrides are limited to types that live inside a Project (`task`, `note`); `person` is not considered to live inside a Project. Follow-up: install flow details.
4. ~~Cross-implementation relations~~ — resolved: `<type>:<id>` is enough.
5. ~~Code vs. user definitions~~ — resolved (see Ownership).
6. ~~Schema evolution~~ — resolved in principle (see Versioning). Specified in doc 02.
7. ~~Extensibility~~ — resolved: all five original types extensible; `Archive` is a non-extensible sixth type.

## Traits

A **trait** is a named, reusable bundle of schema fields (and optionally named sorts and filters) that can be attached to individual people. Traits give a person
kind-specific structure without a separate implementation. They exist because `Person` has a single active implementation (see Default implementation resolution):
a colleague, a client and a friend need different fields on the same implementation.

**Scope** *(Decided)*: traits apply to **`Person` only**. No other core type has traits; those types can have several implementations, so there is no need. Attaching
a trait to any other type is a validation error.

**Definition.** `second-brain/.brain/traits/<trait-name>.md`, YAML frontmatter plus a guidance body, like an implementation definition:

```yaml
---
trait: colleague
version: 1
schema:
  fields:
    employer: { type: string }
    team:     { type: string }
sorts:
  by-employer: "Alphabetical by employer, then by name."
filters:
  at-employer: "People whose employer matches the one named in the request."
---
Guidance for Claude when working with people who are colleagues.
```

**Fields are namespaced by trait** *(Decided)*. A trait's fields live under the trait's name, so two traits can both define `employer` without clashing: `colleague.employer`,
`client.employer`, `friend.employer`. In an item they are stored nested under the trait name, and the item lists its traits:

```markdown
---
id: 01JPERSON...
type: person
impl: default-person
name:
  given: Alex
  family: Rivera
traits: [colleague, client]
colleague:
  employer: Acme
  team: Platform
client:
  employer: Globex
---
```

- **References** to a trait field use the dotted form `colleague.employer` in sorts, filters, `match` and rule conditions (docs 04 and 05).
- **Named sorts and filters** from a trait are namespaced the same way (`colleague.by-employer`).
- A trait name must be lowercase (`[a-z][a-z0-9_-]*`) and must not equal any core field, implementation field or reserved key (`id`, `type`, `impl`, `traits`, ...). Setup and validation
  reject a clash, which is what keeps the namespaces separate.
- An item's trait fields are validated only for the traits it lists. A trait field present without its trait listed is a validation error. Removing a trait from an item removes
  its fields only after the user confirms (the data would otherwise be lost silently).
- **Required vs. optional:** fields a trait marks `required` are required only on items that carry that trait.

**Traits are composition, not inheritance.** Doc 01 rules out implementation-to-implementation inheritance. Traits are a deliberate, limited exception: they contribute namespaced fields,
sorts and filters only. They have **no storage, no automation and no relations of their own**; rules still live on the implementation (doc 05), and `match` can test whether an item has a trait.

**Storage and conversion.** Trait fields live in the item, so they use the item's implementation's binding. An adapter must be able to persist the `traits` list and nested trait
fields (a `supports_traits` capability, doc 03). Because trait fields are namespaced and travel with the item, conversion between implementations (doc 06) carries them over unchanged
provided the target adapter supports traits.

**Versioning.** Traits are versioned and migrated like implementations (doc 02): `version` in the definition, a manifest entry, and a migration note for breaking changes.

**Decided**
1. ~~Allow-list~~ — **no allow-list.** Any defined trait can be attached to a person. The vault controls availability by which traits it defines.
2. ~~Trait relations~~ — **fields only.** A trait does not declare expected relations; a person's relations stay free-form named relations to any item.
3. ~~Trait defaults~~ — **no defaults.** A new item starts with no traits. Traits are attached explicitly (for example `--trait colleague` on capture, or an approved Claude proposal).

## Default implementation resolution

When creating an item of core type `T` (capture, triage, or a skill asking for "a new task"), the implementation is chosen by
the first match in this chain:

1. The item's **Project** `defaults.T`, if the item belongs to a Project that sets one.
2. The item's **Area** `defaults.T`, if set (a Project inherits its Area; no area means the Inbox).
3. The **Inbox** area's `defaults.T` — the vault-wide default.
4. The plugin's built-in implementation for `T`.

`Person` does not use this chain: a vault has exactly one **active** person implementation (default `default-person`, `markdown` storage at `people/{id}.md`), and every new person uses it. Nothing can set a `person` default.

A second person implementation is allowed **only as a migration target** for moving persons in bulk to a different implementation (for example from `markdown` to a CRM backend):

- Its definition sets `migration_target: true`. Without that flag, a second `person` implementation is a validation error. At most one migration target may exist.
- While it exists, **new persons still go to the active implementation**. Both bindings are consulted by `resolve`, and ids stay unique across the vault (doc 03).
- Persons move one at a time with the same-id **conversion** (doc 06), keeping their refs and relations valid. A bulk command built on it is post-MVP (see `deferred.md`).
- When no persons remain in the old implementation, the target is **promoted** to active (`migration_target` removed) and the old definition is retired. The manifest (doc 02) reflects both states.

The same bulk migration applies to every other core type, where several implementations already coexist; for those the target is simply an additional implementation.

The **Inbox** is a system-created Area (`area:inbox`) that cannot be deleted. Items with no placement relation (Tasks, Notes,
Projects and Areas; see doc 06) belong to it. **Persons are top-level** and are never placed, so they are never in the Inbox. Because it is an Area, it is just a normal Area item whose `defaults` hold the vault-wide values.

```markdown
---
id: inbox
type: area
impl: default-area
title: Inbox
system: true
defaults:
  task: gtd-task
  note: zettel-note
  project: default-project
  area: default-area
---
```

Overrides use the same `defaults` field on any Area or Project:

```markdown
---
id: 01JPROJ...
type: project
area: area:01JAREA...
defaults:
  task: linear-task       # tasks in this project are stored/managed as Linear tasks
---
```

`defaults` is a core field on `Area` and `Project`, so every implementation of those types supports it. The **Inbox** may set a default for any core type except `person`; any other Area may too. `person` is never a valid `defaults` key, since new persons always use the vault's active person implementation. A **Project may set defaults only for the types that live inside it: `task` and `note`**. Other keys on a Project are a validation error.

## Install-time setup

The install flow (`/brain setup`) is specified in [06 — Install Flow and Triage](06-install-and-triage.md). In short, after one confirmation it:

1. Creates `second-brain/.brain/config.yml` (`version`, the vault `name`, the `archive` adapter choice, and the location of implementation definitions). Vault-level automation, if any, lives beside it in `.brain/automation.yml` (doc 05), created on first use.
2. Copies the built-in starter implementation definitions (`default-*`), including the single `person` implementation.
3. Creates the system Archive (`archive:archive`) and the Inbox area item with `defaults` pointing at the starters.
4. Adds `.gitignore` entries for derived state and writes `.brain/manifest.yml` last (doc 02).

**Triage** later moves an item out of the Inbox by assigning it an Area and/or Project and, if the resolved default implementation differs, **converting** it: the item
keeps its `id` and moves to the other implementation of the same core type, with a deterministic field mapping the user resolves where needed. Capture, triage and conversion are
specified in doc 06.

## Versioning and migrations

- The brain repo holds a **version manifest** (proposed: `.brain/manifest.yml`) recording the core model version it
  conforms to, and the version of each user implementation definition.
- The plugin repo ships **migration instructions** per core version step (proposed: `plugins/brain/migrations/<from>-to-<to>.md`),
  written for an agent to follow: what changed, how to update implementation definitions and existing items, and how to verify.
- On plugin update, a check compares the manifest to the plugin's core version. If behind, the agent walks the migration
  chain in order, updates the manifest after each step, and commits per step so it is reviewable and revertible.
- Formats, flow and conflict handling are specified in [02 — Versioning and Migrations](02-versioning-and-migrations.md).

## Next steps

1. Write the install flow and triage mechanics doc (setup steps, user-chosen vs. built-in defaults, converting an item between implementations). Docs 02 and 05 depend on it.
2. ~~Detail per-type core fields and relations~~ — drafted in [08 — Core Types](08-core-types.md).
3. Sketch the first built-in implementation of each core type as reference examples, used for install-time scaffolding.
4. Finalize the "proposed" paths (`.brain/manifest.yml`, `plugins/brain/migrations/`, `.brain/impls/...`) once the install flow is written.
5. Per-slot contracts are done: [03](03-storage-contract.md), [04](04-sort-filter.md), [05](05-automation.md). Deliberately postponed work is tracked in [Deferred and Out-of-Scope Items](deferred.md).
