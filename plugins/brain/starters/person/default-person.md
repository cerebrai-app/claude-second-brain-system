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
