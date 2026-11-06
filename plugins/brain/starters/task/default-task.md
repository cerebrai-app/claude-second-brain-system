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
  recent-first:
    rule: "Most recently updated first."
    keys:
      - { name: updated, type: datetime, direction: desc }
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
automation:
  - id: today
    on: manual
    do:
      - action: surface
        filter: actionable-today
        sort: due-then-priority
---
Guidance for Claude when working with tasks of this implementation.

- A task is one concrete action. If it needs several steps, suggest a Project and move the steps into tasks under it.
- `status` uses the core values (`open`, `done`, `dropped`). This implementation adds no custom values.
- `due` is a calendar date with no time. Leave it empty rather than guessing; undated tasks sort last.
- `priority` defaults to `med`; only set `high` or `low` when the user said so.
- A task is blocked while any task in `blocked_by` is still `open`.
