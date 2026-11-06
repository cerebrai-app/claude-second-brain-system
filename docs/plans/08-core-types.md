# 08 — Core Types: Fields and Relations

Status: **Draft** · Depends on: [01 — Core Data Model](01-core-data-model.md), [03 — Storage Contract](03-storage-contract.md) · Used by: [04](04-sort-filter.md), [05](05-automation.md), [06](06-install-and-triage.md)

## Goal

Pin down exactly what every core type requires: fields, relations, cardinality, validation and reserved names. This replaces the strawman table in doc 01. The core is deliberately
minimal: it defines only what cross-implementation features (triage, archive, sync, filters, automation) rely on. Everything else is an implementation field (doc 01).

## Item envelope vs. fields

Per the storage contract (doc 03), an item has envelope-level properties and `fields`:

| Where | Name | Notes |
|---|---|---|
| Envelope | `id`, `type`, `impl`, `created`, `updated`, `revision`, `archive`, `archived_at`, `body` | `id` is a ULID assigned by the plugin; `created` never changes; `updated` is set on every write (timestamps are UTC ISO 8601). `archive`/`archived_at` are set only by `archive`/`unarchive` (doc 03). |
| `fields` | `title` (or `name` for Person), `tags`, plus the type's other core fields and all implementation fields | In markdown they appear flat in the frontmatter (doc 01). |
| `relations` | Core relations and implementation relations | Stored as lists of refs (`<type>:<id>`), always lists even when the cardinality is one. |

## Fields common to the five extensible types

| Field | Type | Required | Notes |
|---|---|---|---|
| `title` | string | yes (not Person) | Non-empty after trimming. Person uses `name` instead. |
| `slug` | string | maintained by the plugin | Human-readable file name *(Decided)*. See Slug. |
| `tags` | `Map<String, String>` | no (default `{}`) | Free-form labels with optional string values *(Decided: on all five extensible types; not on `Archive`)*. See Tags. |
| `body` | markdown string | no (Note: present, may be empty) | Envelope-level. Adapters may not support it (`supports_body`, doc 03). |

**Slug** *(Decided)*. Every item of the five extensible types has a `slug`, the human-readable stem of its file name in the default path templates (`tasks/{slug}.md`). The `id` stays the stable identity; the slug is only a name.

- **Made from** the `title` (Person: the display name) when the item is **created**: lowercased, Unicode letters and digits kept, every other run of characters replaced by one `-`, leading and trailing `-` trimmed, cut to 60 characters (at a `-` where possible). An empty result becomes `untitled`. A title that is already a date (`2026-11-06`) yields itself, which is how journal notes get date file names.
- **Unique** within the directory its path renders to. A collision takes the next free suffix: `draft-q4-plan`, `draft-q4-plan-2`, `draft-q4-plan-3`.
- **Fixed at creation.** It is stored in the item and never changes when the title changes, so a rename does not move the file or break anything. An explicit rename command may change it (the plugin moves the file and keeps refs, which use `id`).
- **Not user-editable** like `completed`: set by the plugin. Hand-created files get one when they are adopted (doc 05, sync), taken from the file name.
- The `slug` is plain data, so it travels when an item is archived or converted. On conversion the target's template decides the file name; the slug is kept, with a new suffix if it collides there.
- Backends that have no file names store it as an ordinary field.

**Tags** *(Decided)*. `tags` is a **`Map<String, String>`**: tag name → string value. There is no hierarchy.

```yaml
tags:
  urgent: ""                  # a bare tag: empty-string value
  work/acme: proposal         # "/" and "." are ordinary characters in a name
  review.due: "2026-12-01"
```

- **Names** are non-empty strings, trimmed and lowercased on write, with no whitespace or control characters. `.` and `/` are allowed like any other character; they have **no meaning to the plugin** (no parent/child
  relationship, no prefix matching). Names are unique per item (case-insensitive) and keep their order.
- **Values** are strings, not normalized. A bare tag has the empty string as its value.
- **Shorthand on input:** a list of names (`tags: [urgent, work/acme]`) is accepted and normalized to the map with empty-string values. Scalar YAML values (numbers, booleans, dates) are converted to their string
  form; a list or map as a value is an error.
- **External backends** *(Decided)*. Where a backend can store tags only as names (labels), the implementation keeps the tag **values** in an **implementation-specific side field**: a field of the backend (a custom property, a
  description block, a metadata column) that the implementation names in its definition as `storage.tag_values_field`. Names go to the native labels, values go to the side field, and the adapter recombines them on read, so
  the `Map<String, String>` round-trips. A backend that stores key/value tags natively needs no side field. An implementation whose adapter reports `tags: "labels"` (doc 03) without declaring `tag_values_field` is refused at
  binding rather than silently dropping values.
- Tags are unvalidated labels with no schema. They are not traits (doc 01, Person only; traits add namespaced, validated fields) and not relations (links to other items). Filters, sorts and rule `match` can test a tag's presence, name and value.

## Field types (implementation schema) *(Decided)*

An implementation adds fields in `schema.fields` (doc 01). Each field has a `type` from this vocabulary and optional constraints:

```yaml
schema:
  fields:
    due:        { type: date }
    priority:   { type: enum, values: [low, med, high], default: med }
    estimate:   { type: integer, min: 0, max: 100 }
    summary:    { type: text, max_length: 2000 }
    reference:  { type: string, pattern: "^[A-Z]{2,5}-[0-9]+$" }
    reviewed:   { type: boolean, default: false }
    watchers:   { type: list, of: string, max_length: 10 }
    stages:     { type: list, of: { type: enum, values: [draft, review, done] } }
```

### Types

| Type | Meaning | Canonical encoding (JSON / frontmatter) |
|---|---|---|
| `string` | Single-line text. Line breaks are rejected. | JSON string |
| `text` | Multi-line text (markdown allowed). Distinct from the item `body`, which is envelope-level. | JSON string |
| `integer` | Whole number in the range ±(2^53 − 1), so it survives JSON. | JSON number |
| `number` | Finite floating-point number (no NaN or infinity). | JSON number |
| `boolean` | `true` or `false`. | JSON boolean |
| `date` | Calendar date with no time or zone. | `"YYYY-MM-DD"` |
| `datetime` | An instant. Stored in UTC; input with an offset is converted, and input with **no offset** is read in the user's configured time zone (doc 04's evaluation context). | `"YYYY-MM-DDThh:mm:ssZ"` |
| `enum` | One of the field's declared `values` (a non-empty list of unique strings). Declaration order is the natural order. | JSON string |
| `list` | Ordered list whose elements are all of one **scalar** type, given by `of` (a type name, or an inline spec with its own constraints). Lists of lists and lists of maps are not allowed. | JSON array of the element encoding |

There are **no nested maps** and no other collection types. Structured data uses several fields, a relation, or a trait (doc 01); the core `tags` map (above) is the only map-valued field.
Format types such as `url`, `email` and `duration` are not built in; use `string` with a `pattern` (see `deferred.md`).

### Constraints

| Constraint | Applies to | Meaning |
|---|---|---|
| `required` | all | The field must be present (not absent or null). For `string` and `text` it must also be non-empty after trimming. Default `false`. |
| `default` | all | A literal of the field's type, applied when an item is **created** and the field is absent. Never applied on update, and never overwrites a value. For `list`, a list literal. |
| `min`, `max` | `integer`, `number`, `date`, `datetime` | Inclusive bounds. |
| `min_length`, `max_length` | `string`, `text` (characters), `list` (element count) | Inclusive bounds. |
| `pattern` | `string` | A regular expression that must match the **whole** value. Limited to a portable subset (no lookbehind or backreferences) so every backend and the plugin agree. |
| `values` | `enum` | Required for `enum`, invalid for any other type. |

An unknown constraint, or one that does not apply to the type, is an error when the definition loads.

### Rules

- **Absent and null.** A field is either present with a value of its type or absent. `null` is treated as absent. To clear a field, remove it. An empty string is a value, not absence.
- **Names.** `[a-z][a-z0-9_]*`. A field name must not be a reserved key, a relation name, or a trait name (below), and must not contain `.` (dotted names are how trait fields are referenced, doc 01).
- **Validation.** Done by the plugin on every write, against the implementation's schema, whatever the backend enforces natively. Values changed outside the plugin are validated when sync sees them; an invalid item runs no rules and is reported (doc 05).
- **Markdown representation.** The `markdown` adapter writes each value in its canonical form. A `string` that would otherwise parse as another YAML type (`yes`, `010`, `2026-12-01`) is written quoted. When a field declared `string` is read as a non-string scalar (a hand edit), the adapter converts it back to its original text and the plugin reports a warning. YAML 1.2 core-schema semantics apply.
- **Other backends.** Values are exchanged with adapters in the canonical encodings above. A backend with no native type for a field stores the canonical string; the plugin decodes it, so every type round-trips on every backend (doc 03). The plugin does not rely on a backend to sort or compare typed values.
- **Sort keys and filters** (doc 04) use these type names; `missing` handling and `order` for enums are specified there.
- **Evolution.** Adding an optional field, or adding an `enum` value, is additive and needs no migration. Renaming or removing a field, changing its `type`, tightening a constraint on existing data, or removing or renaming an `enum` value that items use is a schema change and needs a migration note (doc 02, Implementation versioning).

### Core field types

| Field | Type |
|---|---|
| `title` | `string`, required |
| `name` (Person) | structured map, see Person name |
| `status` | `enum`: `open`, `done`, `dropped`, plus declared custom values |
| `completed` | `datetime`, maintained by the plugin |
| `outcome` | `string` (single line); an implementation may redefine its constraints, not its type |
| `tags` | `Map<String, String>` |
| `defaults` | map of core type → implementation id (system-defined shape) |
| `system` | `boolean` |

## Status values and categories *(Decided)*

`Task` and `Project` have a `status` with three **core values**: `open`, `done`, `dropped`. An implementation may define **additional values**, each declared as a kind of one core value:

```yaml
# in the implementation definition
status_values:
  in_progress: open
  waiting: open
  blocked_external: open
  shipped: done
```

- The **category** of an item is its status if it is a core value, otherwise the core value it maps to. Cross-implementation features (core filters, "not done", triage, automation `match`) use the **category**.
- A custom value must map to exactly one core value, and must not equal a core value or another custom value. Setup and validation reject the definition otherwise.
- Changing a value's mapping, or removing a value that items use, is a schema change that needs a migration note (doc 02).
- *Not covered by this decision, my call:* `Project` uses the same three core values and the same mapping rule, so an `on_hold` project is just a custom value that maps to `open`.

## Completion timestamp *(Decided)*

`Task` and `Project` have a core `completed` timestamp (UTC ISO 8601), maintained by the plugin and never set directly by users or rules:

- Set to the time of the write when the **category** of `status` changes from `open` to `done` or `dropped`.
- Cleared when the category returns to `open`.
- Not changed by edits that keep the category (for example `done` to `dropped`), or by status changes within `open`.
- **External changes:** the plugin sets it only on its own writes. If a backend reports a completion time, the adapter maps it to `completed`; otherwise an item completed outside the plugin has no
  `completed` until the next plugin write to it (sync, doc 05, does not write to items). Filters should treat a missing `completed` on a `done` item as unknown.

## Core types

### `Note`

Knowledge, reference, or a captured thought.

| Name | Kind | Cardinality | Targets | Notes |
|---|---|---|---|---|
| `title` | field | required | | |
| `about` | relation | any number | Project, Area, Person | **At most one** Project-or-Area target (this is the placement, doc 06); any number of Person targets. |
| `links` | relation | any number | Note | |

### `Task`

Actionable unit with a state.

| Name | Kind | Cardinality | Targets | Notes |
|---|---|---|---|---|
| `title` | field | required | | |
| `status` | field | required | `open` \| `done` \| `dropped` (+ custom, mapped) | Default `open`. |
| `completed` | field | set by the plugin | timestamp | See Completion timestamp. |
| `belongs_to` | relation | 0 or 1 | Project or Area | The placement relation (doc 06). |
| `assigned_to` | relation | any number | Person | |
| `blocked_by` | relation | any number | Task | A task is **blocked** when at least one blocker's category is `open`. A cycle in `blocked_by` is a validation warning, not an error. |

### `Project`

Outcome with an end state.

| Name | Kind | Cardinality | Targets | Notes |
|---|---|---|---|---|
| `title` | field | required | | |
| `status` | field | required | `open` \| `done` \| `dropped` (+ custom, mapped) | Default `open`. |
| `completed` | field | set by the plugin | timestamp | See Completion timestamp. |
| `outcome` | field | **optional** *(Decided)* | string | An implementation may make it required for itself. |
| `area` | relation | 0 or 1 | Area | The placement relation (doc 06). |
| `owner` | relation | 0 or 1 | Person | |
| `defaults` | field | optional | map | Only `task` and `note` keys are valid (doc 01). |

### `Area`

Ongoing responsibility with no end date. Retired by archiving, so it has no `status`.

| Name | Kind | Cardinality | Targets | Notes |
|---|---|---|---|---|
| `title` | field | required | | |
| `parent` | relation | 0 or 1 | Area | The placement relation (doc 06). No cycles (an error), and an Area cannot be its own parent. |
| `defaults` | field | optional | map | Any core type except `person` (doc 01). |
| `system` | field | optional, boolean | | `true` only for the Inbox. System areas cannot be deleted or archived. Not settable by users or rules. |

### `Person`

Someone you interact with. **Top-level** (not placed, never in the Inbox, doc 01). One active implementation per vault.

| Name | Kind | Cardinality | Targets | Notes |
|---|---|---|---|---|
| `name` | field (structured) | required | map | See Person name. At least one part must be non-empty. |
| *named relations* | relation | any number each | any item | Relation names are chosen by the implementation or the user, for example `works_with`, `owner_of`. See Named relations. |
| `traits` and trait fields | field | optional | | Doc 01. |

**Person name** *(Decided: structured)*. `name` is a map of parts, all optional strings, at least one non-empty after trimming:

```yaml
name:
  given: Alex
  middle: J.
  family: Rivera
  nickname: Lex
  display: Alex Rivera        # optional explicit display name
```

- **Display name** (used wherever the plugin needs one): `display` if set, otherwise `given`, `middle` and `family` joined by spaces, otherwise `nickname`.
- **Sorting** by default: `family`, then `given`, then the display name. Mononyms are fine (only `given`, or only `display`).
- An implementation may add further parts (for example `suffix`); unknown parts are preserved. Parts are not reordered or reformatted by the plugin.

### `Archive` (not extensible)

| Name | Kind | Cardinality | Targets | Notes |
|---|---|---|---|---|
| `title` | field | required | | |
| `contains` | relation | any number | any item except Archive | Maintained by the plugin; not edited directly. |

## Relations

- **Stored forward only.** Each relation is stored on the item that owns it; the inverse (a project's tasks) is computed by querying `relations_include` (doc 03), never stored.
- **Validation.** On write, each target ref must resolve (a dangling ref is reported, not silently dropped, doc 03) and be of an allowed target type; cardinality limits are enforced; a relation to an archived item is a warning, not an error (doc 03).
- **Implementation relations.** An implementation may add relations to any of the five types beyond the core ones. Each declares a name, a cardinality and its allowed target types (default: any item). Core relation names cannot be redefined.
- **Triage placement** (doc 06): `Task.belongs_to`, `Note.about` (its single Project/Area target), `Project.area`, `Area.parent`. Persons have none.

### Named relations (Person)

A person's relation names are not fixed by the core. Rules for a name:
- lowercase, `[a-z][a-z0-9_]*`;
- must not equal a reserved key (below), a trait name (doc 01), or a field of the implementation;
- targets are any item (including other persons and archived items, with the archived-target warning);
- the implementation may *declare* names with cardinality or target restrictions; **undeclared names are allowed** and stored with no restrictions (any number, any target type).

## Reserved keys

These names cannot be used as an implementation field, a relation name, or a trait name:

`id`, `type`, `impl`, `slug`, `created`, `updated`, `revision`, `archive`, `archived_at`, `body`, `title`, `name`, `tags`, `status`, `completed`, `outcome`, `defaults`, `system`, `traits`, `contains`, `about`, `links`,
`belongs_to`, `assigned_to`, `blocked_by`, `area`, `owner`, `parent`.

Where a name is a core name for one type (for example `owner` on Project) it is reserved across all types to keep names uniform in cross-type filters and rules.

## Validation summary

| Rule | Severity |
|---|---|
| Required field missing or empty | error |
| `status` not a core or declared custom value | error |
| Relation target of a disallowed type, or cardinality exceeded | error |
| `Area.parent` cycle | error |
| `Task.blocked_by` cycle | warning |
| Dangling relation target | reported by the validation pass (doc 03), not by the write |
| Relation to an archived item | warning |
| `tags` names not normalized (case, whitespace), a list shorthand, or a scalar non-string value | fixed silently on write |
| `tags` value that is a list or map | error |
| `completed` set or changed directly | error (maintained by the plugin) |
| Person `name` not a map, or all parts empty | error |
| Reserved key used as an implementation name | error at definition load |

## Open questions

1. ~~Tag syntax~~ — resolved: tags are a **`Map<String, String>`**; names may contain `.` and `/` as ordinary characters; there is **no hierarchy**; list shorthand accepted.
2. ~~Person `name`~~ — resolved: **structured** (`given`, `middle`, `family`, `nickname`, `display`, at least one non-empty).
3. ~~Dates~~ — resolved: add a core **`completed`** timestamp to Task and Project, maintained by the plugin; `due` and `start` stay implementation fields.
4. ~~Maximum `Area.parent` depth~~ — resolved: **no maximum** (cycles are still an error).
5. ~~Tag values on external backends~~ — resolved: label-only backends keep the values in an **implementation-specific side field** (`storage.tag_values_field`), recombined on read; a missing declaration is refused at binding.

## Next steps

1. ~~Resolve the open questions~~ — done. Field types are specified above; remaining refinements: the regex subset for `pattern`, a `unique` constraint, and units for numbers (none for now).
2. ~~Replace doc 01's strawman table with a summary that links here~~ — done. Update the doc 03 envelope example to show `tags` as a map and `completed` for tasks.
3. ~~Write the built-in `default-*` starter implementations~~ — done: [09 — Built-in Starter Implementations](09-starter-implementations.md).
4. Cross-check the rules in docs 04 and 05 that name fields and relations (for example the `blocked` computation and `source`/`due` examples).
