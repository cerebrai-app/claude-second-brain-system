---
impl: default-note
extends: note
version: 1
schema:
  fields: {}
storage:
  adapter: markdown
  path: "notes/{id}.md"
sorts:
  recent-first:
    rule: "Most recently updated first."
    keys:
      - { name: updated, type: datetime, direction: desc }
filters:
  untagged:
    rule: "Notes that have no tags."
    scope: {}
---
Guidance for Claude when working with notes of this implementation.

- A note holds one idea, fact or captured thought in its `body` (markdown). Keep the title short and specific.
- Use `about` to attach a note to the Project or Area it belongs to (at most one of those), and to any People it concerns.
- Use `links` to connect related notes. Prefer links over copying text between notes.
- Tags are free labels (`tags` is a name-to-string map); do not invent tags the user did not ask for.
