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
sorts:
  by-name:
    rule: "Alphabetical by family name, then given name; people with only a display name sort by that."
    keys:
      - { name: family,  type: string, direction: asc, missing: last }
      - { name: given,   type: string, direction: asc, missing: last }
      - { name: display, type: string, direction: asc, missing: last }
---
Guidance for Claude when working with people of this implementation.

- `name` is structured: `given`, `middle`, `family`, `nickname`, `display`. Fill only the parts the user gave; do not guess a family name from a single name.
- A person is top-level: never put one in an Area or Project. Connect people to other items with named relations on the person (for example `works_with`, `owner_of`), or from the other side with `assigned_to`, `owner` and `about`.
- Traits add structured fields for kinds of people (see the vault's `.brain/traits/`). Attach one only when the user asks.
- Keep contact details in `email` and `phone`; do not copy them into other items.
