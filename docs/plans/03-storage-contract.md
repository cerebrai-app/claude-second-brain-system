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
  "fields": { "title": "Draft Q4 plan", "status": "open", "due": "2026-11-15", "tags": { "q4": "" } },
  "relations": { "belongs_to": ["project:01J..."], "blocked_by": [] },
  "body": "Free-form markdown.",
  "created": "2026-11-03T10:00:00Z",
  "updated": "2026-11-03T10:00:00Z",
  "archive": null,
  "archived_at": null,
  "revision": "opaque-string"
}
```

- `ref` is `<type>:<id>`; `id` is stable and implementation-independent (a ULID by default) and is **assigned by the plugin**, not the backend.
  Backends with their own native ids store the native id privately (see `native_id`) and map it to the `id`.
- `relations` always hold refs (`<type>:<id>`), never native ids or paths.
- `revision` is opaque, backend-defined (git blob hash, `updated` timestamp, ETag) and used for optimistic concurrency.
- `archive` is `null` for live items, or the ref of the Archive that holds the item (`archive:archive`); `archived_at` is the timestamp. Both are set only by `archive`/`unarchive`, never by `update`. Archived items are stored by the **Archive adapter** (see below), not by their implementation's binding.
- Unknown `fields` are preserved on round trip.

## Operations

Every adapter implements these. All take and return envelopes; all are scoped to the binding they are called for.

| Operation | Input | Output | Notes |
|---|---|---|---|
| `create` | envelope without `ref`/`revision`/timestamps (plus a plugin-assigned `id`) | envelope | Fails with `conflict` if `id` exists. |
| `read` | `ref` | envelope | `not_found` if missing. |
| `update` | envelope with the `revision` it was read at | envelope | `conflict` if the stored revision differs. Full replace of `fields`/`relations`/`body`. |
| `archive` | `ref`, `revision` | envelope | **The default way to remove an item.** Reads the item from its implementation's binding, writes it to the **Archive adapter** (type, impl, id, fields, relations, body unchanged), then removes it from the source binding. See Archive adapter for ordering and failure handling. Idempotent. Not valid for `archive` items. |
| `unarchive` | `ref`, `revision` | envelope | Reverse of `archive`: writes the item back to the binding of its `impl` and removes it from the Archive adapter. |
| `delete` | `ref`, `revision`, `confirm: "permanent"` | `{ok: true}` | **Exception case:** permanent removal. Requires the explicit `confirm` literal; `unsupported` if the adapter has no hard delete. The plugin calls it for a user-requested permanent delete only after its own confirmation prompt **and** after any `before_delete` automation rules (doc 05) have run without blocking; a blocked delete never reaches the adapter. |
| `list` | `query` (below), `limit`, `cursor` | `{items: [envelope], cursor}` | Always paged: callers pass `limit` and follow `cursor`; adapters cap at `max_page`. Full envelopes only (no reduced or projected items). Returns envelopes, not just refs. Excludes archived items unless the query sets `include_archived` (or `archived_only`, optionally narrowed with `archive: "archive:archive"`). |
| `resolve` | `ref` | `{binding, found: bool}` | Cheap existence check, used for cross-adapter reference validation. |
| `describe` | none | capabilities and settings schema | Static; used at install/setup and by the dry-run sampler. |

### `query` (structural pre-filter only)

Sort/filter *rules* are natural language handled by Claude (doc 01). Storage supports only a **coarse structural filter** so
Claude reads less:

```json
{ "types": ["task"], "impls": ["gtd-task"], "fields_eq": { "status": "open" },
  "relations_include": { "belongs_to": "project:01J..." }, "updated_since": "2026-11-01T00:00:00Z",
  "include_archived": false }
```

All keys optional, all combined with AND. Adapters apply as much as they can natively and **declare which keys they honor**
(`capabilities.query`); the caller filters the remainder client-side. Adapters must never return fewer items than match.

## Capabilities (`describe`)

```json
{
  "adapter": "markdown",
  "capabilities": {
    "query": ["types", "impls", "fields_eq", "relations_include", "updated_since", "include_archived"],
    "archive_adapter": true,
    "hard_delete": true,
    "native_ids": false,
    "transactions": false,
    "supports_body": true,
    "preserves_unknown_fields": true,
    "supports_traits": true,
    "tags": "map",
    "max_page": 200
  },
  "settings_schema": { "path": { "type": "string", "required": true } }
}
```

The plugin adapts to capabilities (e.g. refuses to bind an implementation with `body` content to an adapter with
`supports_body: false`, or warns when `preserves_unknown_fields` is false and the implementation defines extra fields). Field values are exchanged in their canonical encodings (doc 08, Field types); a backend with no native type for a field stores the canonical string, so no schema is refused for its types. `tags` reports how the backend stores the core `tags` map (doc 08): `"map"` for native key/value tags, or `"labels"` for names only, in which case the implementation must name a side field for the values (`storage.tag_values_field`) or it is refused at binding. An implementation whose items can carry traits (doc 01) is refused on an adapter with `supports_traits: false`: the adapter must persist the `traits` list and the nested `<trait>.<field>` values.

## Built-in `markdown` adapter

- Storage in the brain repo as one markdown file per item, YAML frontmatter + body (format in doc 01).
- **Path template** from the binding, e.g. `tasks/{slug}.md` or `tasks/{status}/{slug}.md`. Placeholders:
  - `{slug}`: the item's human-readable `slug` (doc 08), the default file name. Fixed at creation, unique within the directory the path renders to.
  - `{id}`, `{type}`, `{impl}`, or any scalar field of the item.
  - `{field:FORMAT}` for a `date` or `datetime` field (or `created` / `updated`), using these `strftime` codes: `%Y %m %d %H %M %S`. For example `journal/{date}.md` for a `date` field (a `date` renders as `YYYY-MM-DD` by default) or `journal/{created:%Y-%m-%d}.md`.
  - A rendered path segment is sanitized: `/`, NUL and control characters become `-`, and an empty result is an error. A path that renders to an existing file of a **different item** is a collision: for `{slug}` the plugin picks the next free suffix at creation (`-02`, `-03`, zero-padded); any other template fails with `conflict`.
  Because changing a field can change the path, `update` **moves** the file when the rendered path changes. `{slug}` never changes after creation, so files named by slug do not move when the title changes.
- **Id → path index:** `resolve`/`read` by ref must work without knowing the template inputs. The adapter maintains a derived
  index (`.brain/index/refs.json`, git-ignored, rebuildable by scanning frontmatter `id`s) and falls back to a scan on miss.
- **Revision:** git blob hash of the file's content as read (or content hash if not in a git repo).
- **Atomic writes:** write temp file in the same directory, then rename. No partial files on crash.
- **As Archive adapter:** may be chosen as the vault's Archive adapter (it satisfies the requirements below). Archived items are stored at `archive/{type}/{impl}/{slug}.md` (configurable via the Archive binding's `path`), with the same frontmatter format, plus `archive`/`archived_at`.
- **Delete:** permanently removes the file. Only on explicit `confirm: "permanent"`; git history still holds prior content, but the adapter does not rely on that.
- Preserves unknown frontmatter keys and key order on round trip.
- Git commits are **not** made by the adapter. Committing is the caller's concern (e.g. a skill or automation).

## `script` adapter (external systems)

For Linear, Trello, or anything else. The binding points at an executable, or `python:<name>`, a registered script in the vault's Python workspace (doc 07), which can use third-party SDKs and follows that doc's approval flow; the plugin invokes it **once per operation**
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
- **As Archive adapter:** a script adapter may be the Archive adapter only if its `describe` reports the Archive requirements below. It does not need a native "archive" concept; archived items are ordinary records it stores with `archive`/`archived_at` set. Backends with fixed schemas typically cannot meet the requirements and should not be chosen for the Archive.
- **Id mapping:** since the plugin assigns `id`, a script for a backend with native ids must store the plugin `id` in the
  backend (a custom field, label, or description marker) or, if the backend cannot hold it, in the **id index** (below, kept in the brain repo), and
  return `ref` consistently. `describe` reports `native_ids: true` and how it maps.
- **Timeouts and output limits** are enforced by the plugin; stderr is surfaced to the user on failure.
- **Trust:** scripts execute on the user's machine with their privileges. They live in the user's brain repo and are the
  user's responsibility; the plugin shows the command before the first run of a new or changed script and does not run it
  without that confirmation.
- **Testing:** `list` and `read` are used by the migration sampler (doc 02), and an adapter must also be usable through a
  **fixture adapter** that serves a `sample.json` of envelopes, so a script's logic can be tested without the real system.

## Id index (in the brain repo)

For backends that cannot store the plugin `id`, the plugin keeps a JSON **id index** mapping `ref` to native id. It is
**source-of-truth data, not a cache**.

- **Location:** the brain repo working directory, one file per implementation, in a folder for its core type and named by the implementation id:
  `.brain/id-index/<type>/<impl-id>.json` (e.g. `.brain/id-index/task/linear-task.json`). **Committed to git** like any other data.
- **Shape:** `{ "impl": "linear-task", "entries": { "task:01J...": { "native_id": "ENG-123" } } }`.
- **Implementation ids must be unique within a core type** (the same id may be reused under different types). This matches the
  definition layout `.brain/impls/<type>/<impl>.md` (doc 01). Setup and validation reject a duplicate impl id within a type.
- **Written by the plugin**, never by the script adapter: the script returns the native id from `create`; the plugin records it
  after a successful call and passes it back to the script in later requests (`args.native_id`).
- **Recovery:** because it is in git, history is the backup. If an entry is lost, an adapter that can search by a stable key may
  support `rebuild` (reported in `describe` as `rebuild: "by_native_key"`); otherwise `rebuild: "none"` and the git history is the only source.
- **Migrations (doc 02):** the files are ordinary repo paths, so the migration script can list them in `plan.json`, transform
  them, and git restores them on failure, with no special handling.
- Adapters that can store the plugin `id` inside the backend need no index and have no file.

## Fixture adapter (test-only)

Serves envelopes from a JSON file and writes updates to a copy. Implements the same operations and the same errors,
including `conflict` on stale `revision`. Used by migration test runs (doc 02) and by authors of script adapters. Never
selectable in a real binding.

## Archive adapter

The `Archive` core type (doc 01) has **exactly one storage adapter for the whole vault**, chosen at install and recorded in
`.brain/config.yml`:

```yaml
archive:
  adapter: markdown        # or: script
  path: "archive/{type}/{impl}/{slug}.md"
```

Because the Archive holds objects of **every** type and implementation, the Archive adapter must satisfy all of:

- **All types:** stores items of any core type (`note`, `task`, `project`, `area`, `person`) and any `impl`, including
  implementations whose definitions have since changed or been removed.
- **`preserves_unknown_fields: true`:** round-trips arbitrary implementation-specific fields exactly.
- **`supports_body: true`** and arbitrary-size markdown bodies.
- **Full relations:** stores `relations` as refs (`<type>:<id>`) without requiring the targets to exist in the same system.
- **Stable id:** stores the plugin-assigned `id` and `ref` unchanged; `resolve`/`read` by ref work.
- **`list` with `types`, `impls` and `updated_since`** query keys honored natively or cheaply filterable.
- **`create` / `read` / `list` / `resolve` / `delete`** (the last used only by `unarchive`).

The adapter's `describe` reports `archive_adapter: true` only when it meets these; setup refuses an adapter that does not.
`markdown` is the default and always qualifies. Archive is non-extensible: there is one adapter, no per-type or per-impl Archive bindings.

**Archive ordering (create-then-remove, so a failure never loses data):**
1. `read` the item from its source binding.
2. `create` it in the Archive adapter (with `archive`/`archived_at` set).
3. Remove it from the source binding (a permanent `delete` there is correct because the item now lives in the Archive).
4. If step 3 fails, the item exists in both places; `resolve` prefers the source binding and the plugin reports the pending cleanup. Re-running `archive` is idempotent and finishes it.

`unarchive` is the mirror: create in the impl's binding, then delete from the Archive adapter. If the item's `impl` no longer exists,
unarchive requires the user to pick a target implementation of the same type (the plugin converts the item per doc 01 triage rules).

## Cross-adapter references

- A ref `<type>:<id>` does not encode its backend. To follow a ref the plugin asks the bindings that can hold that `type`
  (in resolution order: the default implementations from doc 01, then the rest) to `resolve` it, and caches the winning
  binding for the session.
- An `id` is unique across the whole vault, not per adapter. `create` checks `resolve` on all bindings of that type first
  when `capabilities` do not guarantee uniqueness (ULIDs make collision practically impossible, so this is a safety net).
- `resolve` also asks the Archive adapter, and reports the item's `archive` (non-null when archived); a relation to an archived item is **not** dangling, but validation surfaces it as a warning.
- If a ref resolves nowhere, it is a **dangling reference**: reported by a validation pass, never silently dropped.
- Moving an item between implementations (triage, doc 01) is `create` in the target binding with the **same id**, then `delete`
  in the source (a permanent delete is correct here: the item lives on under the same id, so archiving would leave a duplicate
  id), so existing refs stay valid. This is one of the few sanctioned uses of `delete`. It is not atomic across adapters; the plugin
  does create-then-delete and reports if the delete fails (the item then exists twice, and `resolve` order picks the one in the default binding).

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

1. ~~Large lists~~ — resolved: **pagination** (always paged, cursor-based, `max_page` cap); no refs-only or projected items.
2. ~~Local cache~~ — resolved: **deferred**, possibly adapter-specific. Before implementing, add a way to measure adapter latency (see Next steps).
3. ~~Delete semantics~~ (Archive is now a core type, see doc 01) — resolved and decided: **archive is the default**, permanent `delete` is the exception (explicit `confirm`). The plugin **always asks for confirmation before a permanent delete** (then runs any `before_delete` automation rules, which can veto it, doc 05), except the delete that completes an `archive` or a triage move. Archived items are **never purged automatically**.
4. ~~Id mapping files~~ — resolved: a committed JSON **id index in the brain repo**, one file per implementation, `.brain/id-index/<type>/<impl-id>.json` (see Id index). Impl ids must be unique within a core type.
5. ~~Batch reads~~ — resolved: **no `read_many`**; individual reads for now. Revisit with latency data.
6. ~~Attachments~~ — resolved: **out of scope** for now.

7. ~~Multiple Archives~~ — resolved: exactly one Archive, id `archive` (ref `archive:archive`), no qualifiers.
8. ~~Cascade on archive~~ — resolved: when an Area or Project is archived the plugin **asks** whether to also archive its contained items, and **recommends yes** (cascade) as the default choice. Contained items are archived with the standard `archive` operation, one at a time.

9. ~~Migrations over archived items~~ — resolved: yes, migration scripts also transform archived items (via the Archive adapter, including external ones, tested per doc 02).
10. ~~Changing the Archive adapter~~ — resolved: **out of scope for the MVP**; the adapter is fixed at install.

## Next steps

1. Add latency measurement for adapters: the plugin records per-operation timings (op, adapter, duration, item count) to a local log, with a `describe`-level summary command, so the cache and batch-read decisions (questions 2 and 5) can be made with data.
2. Validate the markdown adapter and a script adapter end to end against the contract, including the Archive adapter requirements and `rebuild`.
3. Deferred items (local cache, `read_many`, changing the Archive adapter) are tracked in [Deferred and Out-of-Scope Items](deferred.md).
