---
impl: default-area
extends: area
version: 1
schema:
  fields: {}
storage:
  adapter: markdown
  path: "areas/{id}.md"
sorts:
  by-title:
    rule: "Alphabetical by title."
    keys:
      - { name: title, type: string, direction: asc }
---
Guidance for Claude when working with areas of this implementation.

- An area is an ongoing responsibility with no end date (health, finances, a team). When it is no longer relevant, archive it instead of deleting it.
- Areas can nest with `parent`. Do not create cycles.
- `defaults` on an area chooses the implementation used for new tasks, notes, projects and areas placed in it. It never accepts a `person` key.
- The Inbox (`area:inbox`) is a system area: do not rename, archive or delete it. Its `defaults` are the vault-wide defaults.
