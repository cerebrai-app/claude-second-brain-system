# Ids and slugs

The single place that says how ids and slugs are made. Everything else (the core skill, the `default-*` implementation files, the design docs) links here instead of restating it.

Both come from the helper, never from you. Run it from the vault root.

## Ids (ULID)

Every item has an `id`, a 26-character ULID assigned once, when the item is created. It is the stable identity; refs (`<type>:<id>`) use it.

```
python3 -I .brain/python/brainctl/ids.py ulid          # one new id (-n N for several)
```

Never invent an id. The Inbox (`inbox`) is the one fixed id.

## Slugs

A slug is the stem of an item's file name, in an implementation that declares a `slug` field in `schema.fields` (the `default-*` ones do; alternates need not). The implementation's own **Slug** section says what the slug is made from; the mechanics are the same everywhere:

```
python3 -I .brain/python/brainctl/ids.py slug "<text>" --dir <directory>
```

- **Normalization.** Lowercase; Unicode letters and digits kept; every other run of characters becomes one `-`; leading and trailing `-` trimmed; cut to 60 characters (at a `-` where possible); an empty result becomes `untitled`. Text that is already a date (`2026-11-06`) yields itself.
- **Unique in its directory.** A collision takes a hyphen and a zero-padded two-digit number (`draft-q4-plan`, `draft-q4-plan-02`, ..., `-10`; past 99 the number grows to three digits). Numbers that are part of the text are left as written. `--dir` makes the helper check the directory for you.
- **Fixed at creation.** Stored in the item and never changed when the title or name changes, so the file does not move. Only an explicit rename command may change it (it moves the file; refs survive because they use `id`).
- **Set by the plugin, not user-editable.** A hand-created file gets its slug from its file name when sync adopts it, or completes it.
- **Travels with the item.** It is plain data, so it is kept on archive and conversion; on conversion the target's path template decides the file name and a collision there gets a new suffix.

## YAML quoting

Quote an id, slug, title or name in YAML when the plain form would load as another type (`2026-11-06`, `yes`, `010`).
