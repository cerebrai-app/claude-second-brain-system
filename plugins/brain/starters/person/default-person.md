---
impl: default-person
extends: person
version: 1
schema:
  fields:
    slug: { type: string }
storage:
  adapter: markdown
  path: "people/{slug}.md"
---

## Slug

The `slug` of a person is the stem of its file name (`people/{slug}.md`). The id stays the stable identity; the slug is only a name.

- **Derive** it once, when the person is created, from the display name (`name.display`, or the name parts joined as `display_name` does): run `python3 -I .brain/python/brainctl/ids.py slug "<display name>" --dir people`. The helper lowercases, keeps Unicode letters and digits, replaces every other run of characters with one `-`, trims leading and trailing `-`, cuts to 60 characters (at a `-` where possible) and uses `untitled` for an empty result.
- **Unique** within `people/`: a collision takes a hyphen and a zero-padded two-digit number (`alex-rivera`, `alex-rivera-02`, ..., `-10`; past 99 the number grows to three digits). Numbers that are part of the name are left as written.
- **Fixed at creation.** Never change it when the name changes; the file does not move. Only an explicit rename command may change it (it moves the file; refs use `id`, so they survive).
- **Not user-editable**: set by the plugin. A hand-created file gets its slug from its file name when sync adopts it. Quote it in YAML if the plain form would load as another type (`2026-11-06`, `yes`, `010`).
- It is plain data, so it travels when the person is archived or converted; on conversion the target decides the file name and the slug keeps, with a new suffix if it collides there.
