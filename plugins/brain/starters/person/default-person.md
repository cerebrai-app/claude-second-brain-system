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

The `slug` is the file name stem (`people/{slug}.md`). Make it once, at creation, from the display name (`name.display`, or the name parts joined as `display_name` does). The mechanics (command, normalization, collision suffixes, fixed at creation) are in the core skill's `references/ids-and-slugs.md` reference.
