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
    rule: "Open projects that are not on hold."
    scope: { fields_eq: { status: open } }
---
`target` is the date the outcome should be reached; leave it empty if the user did not give one. `on_hold` counts as `open` for anything that looks at the status category.
