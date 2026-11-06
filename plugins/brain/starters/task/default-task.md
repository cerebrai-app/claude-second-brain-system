---
impl: default-task
extends: task
version: 1
schema:
  fields:
    slug: { type: string }
storage:
  adapter: markdown
  path: "tasks/{slug}.md"
---
