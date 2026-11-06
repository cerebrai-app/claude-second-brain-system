---
impl: default-project
extends: project
version: 1
schema:
  fields:
    target: { type: date }
status_values:
  on_hold: open
storage:
  adapter: markdown
  path: "projects/{id}.md"
sorts:
  target-date:
    rule: "Soonest target date first; projects without a target date last; ties by title."
    keys:
      - { name: target, type: date,   direction: asc, missing: last }
      - { name: title,  type: string, direction: asc }
filters:
  active:
    rule: "Projects whose status is open (not on hold, done or dropped)."
    scope: { fields_eq: { status: open } }
---
Guidance for Claude when working with projects of this implementation.

- A project is an outcome with an end state. `outcome` is optional; ask for it when the user is planning the project, not when merely capturing it.
- `status` uses the core values plus `on_hold`, which counts as `open` for cross-implementation features.
- `target` is the date the outcome should be reached; leave it empty if the user did not give one.
- Assign a project to an Area with `area` and an owner with `owner`. Tasks and notes belong to the project through their own relations.
