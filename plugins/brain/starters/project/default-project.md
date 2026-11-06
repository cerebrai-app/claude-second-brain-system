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
