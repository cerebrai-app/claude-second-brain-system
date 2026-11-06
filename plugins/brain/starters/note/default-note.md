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

The `slug` is the file name stem (`notes/{slug}.md`). Make it once, at creation, from the `title`. A title that is already a date (`2026-11-06`) yields itself, which is how journal notes get date file names. The mechanics (command, normalization, collision suffixes, fixed at creation) are in the core skill's `references/ids-and-slugs.md` reference.
