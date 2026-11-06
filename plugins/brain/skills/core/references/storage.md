# Storage: item shape and operations

## Item (envelope)

`ref` (`<type>:<id>`), `type`, `impl`, `fields`, `relations` (lists of refs), `body`, `created`, `updated`, `archive` (null or `archive:archive`), `archived_at`, `revision` (opaque, for optimistic concurrency). Unknown fields are preserved on round trip. In markdown, fields and relations are flat in YAML frontmatter; the body follows.

## Operations (every adapter)

`create`, `read`, `update` (full replace; `conflict` if the revision differs), `archive`, `unarchive`, `delete` (permanent, needs `confirm: "permanent"`), `list` (paged, structural query), `resolve` (existence check), `describe` (capabilities). Errors: `not_found`, `conflict`, `invalid`, `unauthorized`, `rate_limited`, `unavailable`, `unsupported`, `internal`.
Re-read and retry (or ask) on `conflict`. No cross-item transactions: order multi-item operations so a failure leaves a recoverable, re-runnable state.

## Archive

`archive` is the default way to remove an item: write it unchanged (ref, type, impl, fields, relations, body) to the Archive adapter, then remove it from its source binding. `unarchive` reverses it, back to the implementation's binding. Archiving an Area or Project: ask whether to archive its contained items too, and recommend yes; archive them one at a time. Archived items are never purged automatically. A relation to an archived item is not dangling; it is a warning.

## Permanent delete

Rare. Always confirm with the user first, then run any `before_delete` rules (they can veto). Exceptions that need no confirmation and fire no `before_delete`: the delete that completes an `archive` or a conversion.

## Markdown adapter (default)

One file per item at the binding's path template (placeholders `{slug}`, `{id}`, `{type}`, `{impl}`, or any scalar field, with an optional format `{field:%Y-%m-%d}` for date and datetime fields; default starters use `<dir>/{slug}.md`; `{slug}` is allowed only when the implementation declares a `slug` field. A collision on `{slug}` gets the next free zero-padded `-02`, `-03` suffix at creation; slugs never change afterwards, so files do not move when the title changes). Write atomically (temp file in the same directory, then rename). Preserve unknown frontmatter keys and key order. Revision = git blob hash of the file as read. If a changed field changes the rendered path, move the file. Quote strings that YAML would read as another type (`yes`, `010`, `2026-12-01`). Archived items live at `archive/{type}/{impl}/{slug}.md` with `archive` and `archived_at` set. The adapter never commits.

## Script adapters

The binding's `command` is an executable or `python:<name>` (a registered, approved workspace script). One process per operation: JSON request on stdin, JSON result on stdout, stderr shown on failure. The plugin records the backend's `native_id` in `.brain/id-index/<type>/<impl>.json` after a successful create. Credentials come from environment variables the script declares.
`describe` reports capabilities (`supports_body`, `preserves_unknown_fields`, `supports_traits`, `tags: "map" | "labels"`, `archive_adapter`, `hard_delete`, `query` keys). Refuse a binding the adapter cannot honor. Backends that store tag names only keep tag values in the implementation's `storage.tag_values_field`.

## References across adapters

An `id` is unique across the vault. To follow a ref, ask the bindings that can hold that type to `resolve` it (default implementations first, then the rest), then the Archive. A ref that resolves nowhere is dangling: report it, never silently drop it.

## Conversion (same id, different implementation)

Only within the same core type. Deterministic mapping: core fields carry over; same-name fields carry over if valid for the target; relations carry over if allowed; body carries over if the target supports it. Fields the target defines with a `default` and no mapped value are filled by default (conversion is a create in the target) and listed as *filled by default*. List every *unmapped*, *invalid*, *missing* (required, no value/default) field; the user resolves each (drop, rename, fill, cancel) before anything is written. Apply: validate the target envelope; `create` in the target with the same id; record the native id if needed; delete the source (no confirmation, no `before_delete`); update sync seen state. If the source delete fails, the item exists twice: write `.brain/conversions/<type>-<id>.json` (ref, both bindings, timestamp) and offer to finish later; never re-create. The target implementation's rules see an `update` (with `changed` including `impl`), not `create` or `capture`.
