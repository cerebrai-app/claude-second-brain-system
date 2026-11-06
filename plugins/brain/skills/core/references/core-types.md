# Core types: fields and relations

## Common to note, task, project, area, person

- `title` (string, required; Person uses `name`), `tags` (`Map<String,String>`, default `{}`), optional `body` (markdown, envelope-level).
- Envelope: `id`, `type`, `impl`, `created` (never changes), `updated` (set on every write), `revision`, `archive`, `archived_at`. Timestamps are UTC ISO 8601.
- **Tags**: name → string value; no hierarchy. Names are trimmed, lowercased, no whitespace or control characters, unique per item; `.` and `/` are ordinary characters. A bare tag has the empty string as its value. A list of names is accepted on input and becomes empty-string values. A list or map as a value is an error.

## Types

| Type | Required | Relations (stored forward, always as lists of refs) |
|---|---|---|
| `note` | `title` | `about` → Project/Area/Person (at most one Project-or-Area; any number of Persons), `links` → Note |
| `task` | `title`, `status` (default `open`) | `belongs_to` → Project/Area (0..1, placement), `assigned_to` → Person (any), `blocked_by` → Task (any) |
| `project` | `title`, `status` (default `open`); `outcome` optional | `area` → Area (0..1, placement), `owner` → Person (0..1); `defaults` (only `task`, `note` keys) |
| `area` | `title` | `parent` → Area (0..1, placement; cycles are an error); `defaults` (any core type except `person`); `system` (true only for the Inbox) |
| `person` | `name` (structured map) | Named relations to any item; names `[a-z][a-z0-9_]*`, not reserved, not a trait or field name. Undeclared names are allowed. |
| `archive` | `title` | `contains` (plugin-maintained). Not extensible; one only: `archive:archive`. |

Inverses are never stored (a project's tasks come from querying tasks whose `belongs_to` includes it).

## Status (task, project)

Core values: `open`, `done`, `dropped`. An implementation may add custom values, each mapped to one core value in its `status_values`. Cross-implementation features use the **category** (the core value). A task is **blocked** when any task in `blocked_by` has category `open`; a `blocked_by` cycle is a warning.
`completed` (datetime) is maintained by the plugin only: set when the category moves from `open` to `done`/`dropped`, cleared when it returns to `open`, never edited directly.

## Person name

`name` is a map of optional strings: `given`, `middle`, `family`, `nickname`, `display`; at least one non-empty. Display name: `display`, else given + middle + family, else nickname. Default sort: family, given, display. Do not guess a family name from one name.

## Traits (person only)

`traits: [colleague]` lists trait names; each trait's fields live under the trait name (`colleague.employer`). Trait fields are validated only for the traits listed; removing a trait deletes its fields only after the user confirms. Attach traits only when asked.

## Field types (implementation schema)

`string` (single line), `text` (multi-line), `integer` (±(2^53−1)), `number` (finite), `boolean`, `date` (`YYYY-MM-DD`), `datetime` (UTC `...Z`; no-offset input is read in the user's time zone), `enum` (`values`), `list` (`of` one scalar type; no nested lists or maps).
Constraints: `required`, `default` (on create only), `min`/`max` (integer, number, date, datetime), `min_length`/`max_length` (string, text, list), `pattern` (whole-string, portable regex subset), `values` (enum only). Null means absent; clear a field by removing it. Field names `[a-z][a-z0-9_]*`, no dots.

## Reserved names (cannot be fields, relations or traits)

`id type impl created updated revision archive archived_at body title name tags status completed outcome defaults system traits contains about links belongs_to assigned_to blocked_by area owner parent`
