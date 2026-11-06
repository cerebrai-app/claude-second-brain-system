---
impl: default-area
extends: area
version: 1
schema:
  fields:
    slug: { type: string }
storage:
  adapter: markdown
  path: "areas/{slug}.md"
---

## Slug

The `slug` is the file name stem (`areas/{slug}.md`). Make it once, at creation, from the `title`. The Inbox is the exception: setup creates it with the slug `inbox`. The mechanics (command, normalization, collision suffixes, fixed at creation) are in the core skill's `references/ids-and-slugs.md` reference.
