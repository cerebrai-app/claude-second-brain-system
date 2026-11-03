# 03 — Storage Contract

Status: **Draft** · Depends on: [01 — Core Data Model](01-core-data-model.md), [02 — Versioning and Migrations](02-versioning-and-migrations.md)

## Goal

Define how items are persisted and retrieved so that an implementation can store its items anywhere (markdown files,
Linear, Trello, ...) without the rest of the system caring. The contract is the same for built-in and user-supplied adapters.

## Terms

- **Adapter** — code that implements the storage operations for one backend. Built-in: `markdown`. User-supplied: `script`.
- **Storage binding** — the `storage:` block of an implementation definition (doc 01) naming an adapter and its settings.
  Many implementations may share one adapter; each binding may have its own settings (path template, project key, ...).
- **Item envelope** — the adapter-neutral representation of an item passed across the contract.

## Item envelope

```json
{
  "ref": "task:01JABC...",
  "type": "task",
  "impl": "gtd-task",
  "fields": { "title": "Draft Q4 plan", "status": "open", "due": "2026-11-15" },
  "relations": { "belongs_to": ["project:01J..."], "blocked_by": [] },
  "body": "Free-form markdown.",
  "created": "2026-11-03T10:00:00Z",
  "updated": "2026-11-03T10:00:00Z",
  "revision": "opaque-string"
}
```

- `ref` is `<type>:<id>`; `id` is stable and implementation-independent (a ULID by default) and is **assigned by the plugin**, not the backend.
  Backends with their own native ids store the native id privately (see `native_id`) and map it to the `id`.
- `relations` always hold refs (`<type>:<id>`), never native ids or paths.
- `revision` is opaque, backend-defined (git blob hash, `updated` timestamp, ETag) and used for optimistic concurrency.
- Unknown `fields` are preserved on round trip.

## Operations

Every adapter implements these. All take and return envelopes; all are scoped to the binding they are called for.

| Operation | Input | Output | Notes |
|---|---|---|---|
| `create` | envelope without `ref`/`revision`/timestamps (plus a plugin-assigned `id`) | envelope | Fails with `conflict` if `id` exists. |
| `read` | `ref` | envelope | `not_found` if missing. |
| `update` | envelope with the `revision` it was read at | envelope | `conflict` if the stored revision differs. Full replace of `fields`/`relations`/`body`. |
| `delete` | `ref`, `revision` | `{ok: true}` | Default semantics are adapter-defined (hard delete, or archive); see `capabilities.delete`. |
| `list` | `query` (below), `limit`, `cursor` | `{items: [envelope], cursor}` | Paged. Returns envelopes, not just refs. |
| `resolve` | `ref` | `{binding, found: bool}` | Cheap existence check, used for cross-adapter reference validation. |
| `describe` | none | capabilities and settings schema | Static; used at install/setup and by the dry-run sampler. |

### `query` (structural pre-filter only)

Sort/filter *rules* are natural language handled by Claude (doc 01). Storage supports only a **coarse structural filter** so
Claude reads less:

```json
{ "types": ["task"], "impls": ["gtd-task"], "fields_eq": { "status": "open" },
  "relations_include": { "belongs_to": "project:01J..." }, "updated_since": "2026-11-01T00:00:00Z" }
```

All keys optional, all combined with AND. Adapters apply as much as they can natively and **declare which keys they honor**
(`capabilities.query`); the caller filters the remainder client-side. Adapters must never return fewer items than match.

## Capabilities (`describe`)

```json
{
  "adapter": "markdown",
  "capabilities": {
    "query": ["types", "impls", "fields_eq", "relations_include", "updated_since"],
    "delete": "hard",
    "native_ids": false,
    "transactions": false,
    "supports_body": true,
    "preserves_unknown_fields": true,
    "max_page": 200
  },
  "settings_schema": { "path": { "type": "string", "required": true } }
}
```

The plugin adapts to capabilities (e.g. refuses to bind an implementation with `body` content to an adapter with
`supports_body: false`, or warns when `preserves_unknown_fields` is false and the implementation defines extra fields).

## Built-in `markdown` adapter

- Storage in the brain repo as one markdown file per item, YAML frontmatter + body (format in doc 01).
- **Path template** from the binding, e.g. `tasks/{status}/{id}.md`. Placeholders are `{id}`, `{type}`, `{impl}`, or any scalar field.
  Because changing a field can change the path, `update` **moves** the file when the rendered path changes.
- **Id → path index:** `resolve`/`read` by ref must work without knowing the template inputs. The adapter maintains a derived
  index (`.brain/index/refs.json`, git-ignored, rebuildable by scanning frontmatter `id`s) and falls back to a scan on miss.
- **Revision:** git blob hash of the file's content as read (or content hash if not in a git repo).
- **Atomic writes:** write temp file in the same directory, then rename. No partial files on crash.
- **Delete:** `hard` by default; an optional binding setting `archive_path` moves instead.
- Preserves unknown frontmatter keys and key order on round trip.
- Git commits are **not** made by the adapter. Committing is the caller's concern (e.g. a skill or automation).

## `script` adapter (external systems)

For Linear, Trello, or anything else. The binding points at an executable; the plugin invokes it **once per operation**
(no long-lived process), with the operation and arguments as JSON on stdin and the result as JSON on stdout.

```yaml
storage:
  adapter: script
  run: ".brain/adapters/linear-task"        # executable, relative to the brain repo
  settings: { team: ENG, project: Q4 }      # passed through to the script
  timeout_seconds: 30
```

Request:

```json
{ "protocol": 1, "op": "read", "settings": { "team": "ENG" }, "args": { "ref": "task:01J..." } }
```

Response (exit code 0):

```json
{ "ok": true, "result": { "...": "operation output" } }
```

Error (exit code non-zero **or** `ok: false`):

```json
{ "ok": false, "error": { "code": "not_found", "message": "No such task", "retryable": false } }
```

- **Error codes:** `not_found`, `conflict`, `invalid`, `unauthorized`, `rate_limited`, `unavailable`, `unsupported`, `internal`.
  `retryable: true` is advisory; the caller retries at most with bounded backoff.
- **Credentials:** never in request JSON or the repo. The script reads them from environment variables or the user's secret
  store, and `describe` lists the variable names it needs (`requires_env`) so setup can check they exist.
- **Id mapping:** since the plugin assigns `id`, a script for a backend with native ids must store the plugin `id` in the
  backend (a custom field, label, or description marker) or in a mapping file under `.brain/adapters/<name>.map.json`, and
  return `ref` consistently. `describe` reports `native_ids: true` and how it maps.
- **Timeouts and output limits** are enforced by the plugin; stderr is surfaced to the user on failure.
- **Trust:** scripts execute on the user's machine with their privileges. They live in the user's brain repo and are the
  user's responsibility; the plugin shows the command before the first run of a new or changed script and does not run it
  without that confirmation.
- **Testing:** `list` and `read` are used by the migration sampler (doc 02), and an adapter must also be usable through a
  **fixture adapter** that serves a `sample.json` of envelopes, so a script's logic can be tested without the real system.

## Fixture adapter (test-only)

Serves envelopes from a JSON file and writes updates to a copy. Implements the same operations and the same errors,
including `conflict` on stale `revision`. Used by migration test runs (doc 02) and by authors of script adapters. Never
selectable in a real binding.

## Cross-adapter references

- A ref `<type>:<id>` does not encode its backend. To follow a ref the plugin asks the bindings that can hold that `type`
  (in resolution order: the default implementations from doc 01, then the rest) to `resolve` it, and caches the winning
  binding for the session.
- An `id` is unique across the whole vault, not per adapter. `create` checks `resolve` on all bindings of that type first
  when `capabilities` do not guarantee uniqueness (ULIDs make collision practically impossible, so this is a safety net).
- If a ref resolves nowhere, it is a **dangling reference**: reported by a validation pass, never silently dropped.
- Moving an item between implementations (triage, doc 01) is `create` in the target binding with the **same id**, then `delete`
  in the source, so existing refs stay valid. It is not atomic across adapters; the plugin does create-then-delete and reports
  if the delete fails (the item then exists twice, and `resolve` order picks the one in the default binding).

## Concurrency and consistency

- Optimistic concurrency only: `update`/`delete` carry the `revision`; `conflict` means re-read and retry or ask the user.
- No cross-item or cross-adapter transactions (`transactions: false` is the norm). Operations that touch several items
  (e.g. triage) must be ordered so a failure midway leaves a recoverable state, and be re-runnable.
- The `markdown` adapter assumes a single writer at a time; concurrent edits by other tools surface as `conflict`
  via the revision check.

## Validation

On every `create`/`update` the plugin validates the envelope against the core type contract and the implementation's schema
(doc 01) **before** calling the adapter. Adapters are not responsible for schema validation, only for faithful storage and the
errors above.

## Open questions

1. `list` returns full envelopes; for very large external systems should there be a refs-only mode? (Leaning: add `fields_only: [..]` projection later, not now.)
2. Should the plugin keep a local cache/index of external items for fast sort/filter, with a sync operation? (Leaning: defer until we measure cost.)
3. Does `delete` need a required `soft`/`hard` semantics flag exposed to callers, or stay adapter-defined?
4. Where do script adapters' id mapping files live if the backend cannot store the plugin `id`, and how are they migrated (doc 02)?
5. Is one process per operation too slow for large lists? A batch op (`read_many`) may be needed.
6. Binary attachments: out of scope for v1, or `attachments` capability?

## Next steps

1. Resolve open questions above.
2. Write `04-sort-filter.md` (natural-language rules: how Claude is invoked, inputs, outputs, reproducibility).
3. Write `05-automation.md` (triggers, actions, hooks).
