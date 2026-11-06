---
impl: default-note
extends: note
version: 1
schema:
  fields:
    slug: { type: string }
storage:
  adapter: markdown
  path: "notes/{slug}.md"
---

## Slug

The `slug` of a note is the stem of its file name (`notes/{slug}.md`). The id stays the stable identity; the slug is only a name.

- **Derive** it once, when the note is created, from its `title`: run `python3 -I .brain/python/brainctl/ids.py slug "<title>" --dir notes`. The helper lowercases, keeps Unicode letters and digits, replaces every other run of characters with one `-`, trims leading and trailing `-`, cuts to 60 characters (at a `-` where possible) and uses `untitled` for an empty result. A title that is already a date (`2026-11-06`) yields itself, which is how journal notes get date file names.
- **Unique** within `notes/`: a collision takes a hyphen and a zero-padded two-digit number (`draft-q4-plan`, `draft-q4-plan-02`, ..., `-10`; past 99 the number grows to three digits). Numbers that are part of the title are left as written.
- **Fixed at creation.** Never change it when the title changes; the file does not move. Only an explicit rename command may change it (it moves the file; refs use `id`, so they survive).
- **Not user-editable**: set by the plugin. A hand-created file gets its slug from its file name when sync adopts it. Quote it in YAML if the plain form would load as another type (`2026-11-06`, `yes`, `010`).
- It is plain data, so it travels when the note is archived or converted; on conversion the target decides the file name and the slug keeps, with a new suffix if it collides there.
