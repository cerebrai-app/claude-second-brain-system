# Script adapter protocol and `brainctl.adapter`

## The process boundary

The plugin runs the script **once per operation**: a JSON request on stdin, a JSON response on stdout, stderr shown to the user on failure, a timeout (`timeout_seconds` on the binding), and exit code 0 for `ok` and 1 otherwise. `BrainAdapter.main()` does all of this; a script ends with:

```python
if __name__ == "__main__":
    MyAdapter.run()
```

Request: `{"protocol": 1, "op": "<op>", "settings": {...}, "args": {...}}`
Response: `{"ok": true, "result": {...}}` or `{"ok": false, "error": {"code": "...", "message": "...", "retryable": false}}`

## Operations

| `op` | `args` | `result` |
|---|---|---|
| `describe` | none | `{protocol, adapter, capabilities, settings_schema, requires_env}` |
| `create` | `envelope`: `id`, `type`, `impl`, `fields`, `relations`, `body` (no `ref`, `revision` or timestamps) | the full envelope (add `native_id` if the backend has its own ids). `conflict` if the id exists |
| `read` | `ref`, optional `native_id` | the envelope. `not_found` if missing |
| `update` | `envelope` with the `revision` it was read at | the new envelope. **Full replace** of `fields`, `relations`, `body`. `conflict` if the stored revision differs, `not_found` if gone |
| `delete` | `ref`, `revision`, `confirm: "permanent"` | `{"ok": true}`. `invalid` without the confirm literal, `conflict` on a stale revision, `unsupported` if the backend has no hard delete |
| `list` | `query`, `limit`, `cursor` | `{"items": [envelope], "cursor": next or null}` — full envelopes, at most `limit` and at most `max_page`; **never fewer than match** (the caller filters what you do not) |
| `resolve` | `ref` | `{"binding": "<name>", "found": true/false}` (default: built on `read`) |
| `archive`, `unarchive` | `ref`, `revision` | optional; the plugin archives through the Archive adapter and does not need them |

Unknown arguments are ignored; a missing required argument is `invalid`.

## Envelope

`{ref, type, impl, fields, relations, body, created, updated, archive, archived_at, revision}`. `ref` is `<type>:<id>`; `fields` holds `title`, `status`, `tags` (`Map<String,String>`) and every implementation field in the canonical encodings (dates as `YYYY-MM-DD`, datetimes as UTC `...Z`); `relations` maps relation names to lists of refs; `revision` is an opaque string. Build one with `brainctl.adapter.envelope(...)`.

## Query keys (all optional, ANDed)

`types`, `impls`, `fields_eq`, `relations_include`, `updated_since`, `include_archived` (and `archived_only`). Declare in `query` only the ones you filter natively; `matches_query(item, query)` filters locally.

## Errors (raise these)

| Raise | Code | Use for | Service signal |
|---|---|---|---|
| `NotFound` | `not_found` | no such item | 404 |
| `Conflict` | `conflict` | id exists; revision mismatch | 409, 412 |
| `Invalid` | `invalid` | bad request, missing setting, bad cursor | 400, 422 |
| `Unauthorized` | `unauthorized` | missing or rejected credentials | 401, 403 |
| `RateLimited(retry_after=seconds)` | `rate_limited` | throttled | 429 |
| `Unavailable` | `unavailable` | service down, network error, timeout | 5xx, timeouts |
| `Unsupported` | `unsupported` | operation not supported | — |

Anything else becomes `internal` and prints a traceback to stderr. `retryable` is advisory (true for `rate_limited` and `unavailable`).

## `BrainAdapter` class attributes (what `describe` reports)

`name`, `requires_env`, `settings_schema`, `query`, `max_page`, `supports_body`, `preserves_unknown_fields`, `supports_traits`, `tags` (`"map"` or `"labels"`), `native_ids`, `hard_delete`, `archive_adapter`, `transactions`. Defaults are conservative (everything false, `tags="labels"`). Declare only what you honor.

Helpers: `self.env(NAME)` (raises `Unauthorized` if unset, never echoes the value), `self.setting(name, default, required)`, `split_ref`, `make_ref`, `envelope`, `paginate(items, limit, cursor, max_page)`, `matches_query`.

## Ids, revisions, tags

- The plugin assigns a ULID `id`. Store it in the backend (custom field, description marker, label) so `read` by `ref` works, or set `native_ids = True`: the plugin then keeps `native_id` in `.brain/id-index/` and passes it back as `args.native_id`.
- A revision must change whenever the caller-visible content changes and must be checked on `update` and `delete`. Use the service's etag or version; otherwise hash the content. If the service has no compare-and-set, document that `update` is best effort.
- `tags: "map"` stores key/value tags natively. `tags: "labels"` stores names as labels and the values in the side field named by `storage.tag_values_field`; recombine them on `read` so the map round-trips.

## Conformance kit

```python
from brainctl.conformance import assert_conforms, check, iter_checks

assert_conforms(make_adapter, settings=lambda: {...})        # raises with every failing check listed
check(make_adapter, settings=...)                             # returns [(name, message), ...]
iter_checks(make_adapter, settings=...)                       # (name, callable) pairs for pytest.mark.parametrize
```

`make_adapter()` must return a fresh adapter connected to an empty sandbox; `settings` is a dict or a callable giving fresh settings per check. The kit drives the adapter through the same JSON path as the real process and checks: `describe` shape and capability values; unknown operations and protocol versions; create, read, update and delete round trips (fields, relations, body, unknown fields, tags as a string map); duplicate ids; stale revisions; missing items; `resolve`; full-replace updates; pagination (every item once, no more than `limit`, never more than `max_page`); queries that never under-return; delete confirmation; JSON-serializable results; and `main()` on good and bad input.

Reference implementation: [adapter-template.py](adapter-template.py). Test skeleton: [test-template.py](test-template.py).
