---
impl: default-person
extends: person
version: 1
schema:
  fields:
    email: { type: string }
    phone: { type: string }
storage:
  adapter: markdown
  path: "people/{id}.md"
---
Contact details live in `email` and `phone`; do not copy them into other items.
