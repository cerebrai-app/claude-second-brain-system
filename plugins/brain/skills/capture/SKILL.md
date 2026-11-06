---
name: capture
description: Capture a thought, task, note or person into the vault's Inbox (or create a person). Use when the user runs /brain:capture, or says to capture, jot down, note, or remember something for their second brain.
argument-hint: "[--type task|note|project|area|person] [--trait <name>] <text>"
---

# /brain:capture

Read the `core` skill first.

## Create the item
- **Type:** `--type` if given. Otherwise the default for how the text arrived (typed on the command line, piped, a link, a file) from `capture.type_by_source` in `.brain/config.yml`; the built-in default for every source is `note`. Do not infer the type from the text.
- **Implementation:** the Inbox `defaults.<type>` (Person: the vault's active person implementation).
- **Fields:** `title` from the text (short and specific; for a note put detail in the body). Set only what the user gave. Leave dates, priority and every optional field empty otherwise.
- **Placement:** none. The item is created in the Inbox, which fires `create` and `capture`. Run matching rules (see the automation reference); `claude` proposals follow the approval rules.
- **Area (`--type area`) and Person (`--type person`)** are top-level: created with their default implementation (a person: the active person implementation), not in the Inbox, firing `create` only and never offered for triage. `--trait <name>` (repeatable, person only) attaches traits and prompts for their required fields; otherwise a new person has no traits.

## Then offer triage
After the `capture` rules for that event have run, ask: *Triage now?* with a placement proposal for this item (the `triage` skill's proposal step). *Later* leaves it in the Inbox for `/brain:triage`. Do not offer for areas, persons or for items detected by sync.

Create it with `brainctl create --json '{"type": ..., "title": ..., "body": ...}'` (omit `impl` to get the defaults cascade; for a person pass `name` and `traits`/trait fields). The helper assigns the id, slug and timestamps. Confirm what was created (ref and path). Do not commit unless asked.
