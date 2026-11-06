---
impl: default-task
extends: task
version: 1
schema:
  fields:
    due:      { type: date }
    priority: { type: enum, values: [low, med, high], default: med }
storage:
  adapter: markdown
  path: "tasks/{id}.md"
sorts:
  due-then-priority:
    rule: "Soonest due date first; undated tasks last; ties broken by higher priority first."
    keys:
      - { name: due,      type: date, direction: asc, missing: last }
      - { name: priority, type: enum, order: [high, med, low] }
filters:
  actionable-today:
    rule: "Open tasks that are not blocked and are either undated or due today or earlier."
    scope: { fields_eq: { status: open } }
    examples:
      - item: { fields: { status: open, due: 2026-11-02 }, relations: { blocked_by: [] } }
        include: true
      - item: { fields: { status: open } }
        include: true
      - item: { fields: { status: open, due: 2026-11-20 } }
        include: false
  overdue:
    rule: "Open tasks whose due date is before today."
    scope: { fields_eq: { status: open } }
---
`due` is a calendar date with no time; leave it empty rather than guessing. `priority` defaults to `med`; set `high` or `low` only when the user said so.
