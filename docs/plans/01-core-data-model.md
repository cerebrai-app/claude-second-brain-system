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
| Inheritance | An implementation `extends` a **core type only**; no implementation-to-implementation inheritance. Shared behavior is reused by copying or by referencing named sorts/filters/actions, not by extending. |

## Concepts

- **Core type** — a contract shipped by the plugin: required fields, allowed relations, and the behavior slots it supports.
- **Implementation** — a user-defined realization of a core type (e.g. `Task` → `gtd-task`, `linear-task`). A vault may have several per core type.
- **Item** — an instance of an implementation. Always carries `id`, `type` (core), `impl` (implementation name), `created`, `updated`.
- **Behavior slots** — the pluggable parts of an implementation:
  1. **Schema** — fields beyond the core required set, with types and validation.
  2. **Storage** — where/how items persist (path template, file format; or an adapter).
  3. **Sort** — named orderings (e.g. `due-then-priority`).
  4. **Filter** — named predicates/views (e.g. `actionable-today`).
  5. **Automation** — triggers (on-create, on-change, on-schedule, on-capture) and actions.
  6. **Relations** — typed links to other items (see below).

## Core types (strawman)

| Type | Purpose | Required core fields | Core relations |
|---|---|---|---|
| `Note` | Knowledge / reference / captured thought | `title`, `body` | `about` → Project/Area/Person, `links` → Note |
| `Task` | Actionable unit with a state | `title`, `status` (`open`/`done`/`dropped`) | `belongs_to` → Project/Area, `assigned_to` → Person, `blocked_by` → Task |
| `Project` | Outcome with an end state | `title`, `status`, `outcome` | `area` → Area, `owner` → Person |
| `Area` | Ongoing responsibility, no end date | `title` | `parent` → Area |
| `Person` | Someone you interact with | `name` | `related_to` → Person |

Core fields are deliberately minimal; implementations add the rest.

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
  - on: schedule
    cron: "0 8 * * *"
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

- **Storage**: `create`, `read`, `update`, `delete`, `list(query)`, `resolve(ref)`.
- **Sort/Filter**: natural-language descriptions. Claude applies them to a list of items (frontmatter field maps) and returns an ordered or filtered list of item ids. Must be read-only; deterministic wording is encouraged, and ambiguous cases should be resolved by asking or by noting the assumption in the result. Cheap structural filtering (by `type`, `impl`, `status`) may be done by the storage adapter first to limit what Claude reads.
- **Automation**: trigger event payload → ordered action list; actions are built-in or hooks.

## Open questions

1. ~~Expression language~~ — resolved: natural language for now. Follow-ups: reproducibility across runs, cost at large vault sizes, and when to add a formal fallback.
2. ~~Inheritance~~ — resolved: core type only (see Decisions).
3. Multiple implementations per core type in one vault: which one does "new task" default to? (per-area default? config?)
4. Cross-implementation relations (a `linear-task` blocked by a `gtd-task`): is resolution via `<type>:<id>` enough?
5. Where does the plugin's own code live vs. user definitions? Proposed: core contracts in `plugins/brain/`, user definitions in the `second-brain` repo.
6. Schema evolution / migrations when an implementation changes fields.
7. Should `Person`/`Area` be extensible at all, or fixed? (Proposed: all five extensible.)

## Next steps

1. Resolve open questions 1–3.
2. Write per-slot contract specs (`02-storage-contract.md`, `03-sort-filter.md`, `04-automation.md`).
3. Sketch the first built-in implementation of each core type as reference examples.
