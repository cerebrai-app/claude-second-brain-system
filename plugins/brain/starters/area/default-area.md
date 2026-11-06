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
