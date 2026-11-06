---
name: triage
description: Walk the Inbox and place each item under an Area and/or Project, converting it to another implementation when the destination calls for it. Use when the user runs /brain:triage or asks to process or sort their inbox.
argument-hint: "[--type task|note|project] [--filter <name>]"
disable-model-invocation: true
---

# /brain:triage

Read the `core` skill first (placement, defaults, conversion in `storage.md`).

## Candidates
Items of types `task`, `note`, `project` that are in the Inbox: their placement relation is absent or points at `area:inbox`. Never areas or persons, system items (Inbox, Archive) or archived items. List each binding of those types (paged) and filter client-side. Oldest `created` first. `--type` limits to a type; `--filter` limits to items matching a named filter. Report the count first; the user can stop at any time and the rest stay in the Inbox.

## Per item (one at a time)
1. **Propose** (read-only): read the item and the Areas and Projects (and their `defaults`) and return an operation list with a short rationale: `set_relation` for the placement relation, optional `set_field` for something clearly implied by the text, and `convert` only if needed. Do not write anything yet.
2. The destination implementation is the defaults cascade for the **new** placement (Project, then Area, then Inbox, then built-in). `convert` appears only when it differs from the item's current one.
3. **Show** the item, the operations as diffs, and the rationale. The user can **approve**, **edit** (placement, implementation override, fields; re-validate), **skip** (stays in the Inbox, not re-offered this session) or **archive** it.
4. **Apply** approved operations exactly as shown.

## Placement relation by type
`task.belongs_to`, `note.about` (its single Project or Area target), `project.area`. Areas and persons are top-level and are never triaged.

## Without conversion
A single update with the revision you read. On `conflict`, re-read and re-propose.

## Conversion
Follow "Conversion" in `../core/references/storage.md`: deterministic mapping, a conversion report (unmapped, invalid and missing fields that the user resolves field by field; fields *filled by default* shown for information), create with the same id, delete the source, and the half-converted marker if the delete fails. The conversion runs only after the user approves the final diff. Trait lists and trait fields carry over only if the target adapter supports traits. Triage back to the original implementation is the only undo.

## Finish
Log each operation. Offer **one** git commit at the end of the session ("brain: triage N items"). Conversions on external backends cannot be reverted with git, so always show the diff first.
