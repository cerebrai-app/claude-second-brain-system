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
