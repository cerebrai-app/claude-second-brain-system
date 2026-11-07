---
impl: default-project
extends: project
version: 1
schema:
  fields:
    slug: { type: string }
storage:
  adapter: markdown
  path: "projects/{slug}.md"
---

## Slug

The `slug` is the file name stem (`projects/{slug}.md`). Make it once, at creation, from the `title`. The mechanics (command, normalization, collision suffixes, fixed at creation) are in the core skill's `references/ids-and-slugs.md` reference.
