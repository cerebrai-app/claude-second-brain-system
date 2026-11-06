# 11 — The `brainctl` Helper

Status: **Draft** · Depends on: [03](03-storage-contract.md), [05](05-automation.md), [07](07-python-workspace.md), [08](08-core-types.md) · Origin: the first rehearsal ([10](10-plugin-skills.md), findings 1 and 2)

## Goal

Every mechanical step of working with the vault is deterministic: assigning ids and slugs, validating, writing a file atomically, keeping `updated` and `completed` right, moving a file, updating the sync seen state, the id index and the refs index,
adopting hand-written files, hashing a script for approval. In the rehearsal, doing these by hand from prose instructions caused real mistakes. `brainctl` is a small tool that does them, so the skills call it instead and **Claude supplies only judgment**
(what to propose, which area an item belongs to, what a natural-language filter means).

## Shape *(Decided)*

- **Runs in the vault's Python workspace** (doc 07), which is therefore **required**. It uses `ruamel.yaml` (locked in the workspace) so frontmatter round-trips with comments and key order intact.
- **Shipped in the plugin** at `plugins/brain/tools/brainctl/`; setup **copies** it to `.brain/python/brainctl/`, so the vault pins the version it uses. Its version is recorded in the manifest (`helper_version`); a core migration updates the copy. It is plugin code, not user code: it is not part of a
  script's approval hash and cannot be edited through the `python` skill.
- Invoked through the workspace tool from `.brain/python`, for example `uv run --frozen python -m brainctl <command>`; the skills use the tool recorded in `python.tool`.
- **Non-interactive.** It never prompts, never commits, and makes no network calls itself (script adapters make their own). Structured input is JSON on stdin; results are JSON on stdout; diagnostics go to stderr; the exit code maps to the storage error codes (doc 03) plus `0` for success.
- **Never trusted blindly.** It validates every write against the schemas on disk. A command that needs a human decision (an approval, a conversion resolution) takes the decision as input; the skill obtains it from the user.

## Commands

| Command | What it does |
|---|---|
| `id [-n N]` | New ULID(s). (`ids.py`, shipped now.) |
| `slug <title> [--dir D]` | A unique slug for the title (doc 08, Slug). (`ids.py`, shipped now.) |
| `create` | Take an envelope, assign `id`, `slug`, `created`, `updated`, apply schema defaults, validate, write through the binding's adapter, then update the seen state, refs index and id index and append to the log. Returns the stored envelope. |
| `read <ref>` / `list` | Read an item, or list items by structural query, across bindings and the Archive. `list` keys results by ref **and** binding, so a duplicate ref is visible. |
| `update` | Full replace with the `revision` read. Sets `updated` and `completed` (doc 08), validates, writes atomically, moves the file when the rendered path changes, refreshes derived state. `conflict` if the revision differs. |
| `archive <ref>` / `unarchive <ref>` | Doc 03, with ordering and failure handling; refreshes derived state. |
| `delete <ref> --confirm permanent` | Permanent delete. Refuses without the flag. Runs no rules (rules are the skill's job). |
| `convert plan <ref> --to <impl>` | The deterministic mapping and report (carried, unmapped, invalid, missing, filled by default), as JSON. |
| `convert apply <ref> --to <impl>` | With the user's resolutions on stdin: validate, create in the target with the same id, record the native id, delete the source, refresh derived state, and write or clear the half-converted marker. |
| `validate [--ref R]` | Every mechanical check in the `validate` skill: manifest and config, definitions, items, relations, duplicates across bindings, unadopted files, leftover markers, ignored-path checks, workspace approvals. JSON findings with severity. |
| `sync` | Detect: scan all bindings, match by ref across bindings, diff against the seen state, **adopt** hand-written files (doc 05), and return the sync report and ordered event list. Updates the seen state only for events it returns. `--no-adopt` reports without writing. Honors the one-minute `rate_limited` retry. |
| `approve-hash <script>` | The workspace approval hash (below). |
| `index rebuild` | Rebuild the derived refs index by scanning frontmatter ids. |

Script adapters (doc 03) are called by the same commands through their JSON protocol, so the skills have one interface whatever the backend.

### What stays with Claude

Proposals and judgment (triage placement, `claude` actions, `when` conditions, evaluating natural-language sorts and filters), choosing and applying rules, and talking to the user. The skills turn approved operations into helper calls (`set_field` is an `update`, `archive` is `archive`).

### Rule for the skills

**Item files are written only through `brainctl`.** The `core` skill states this. A hand edit by the user is normal; sync picks it up.

## Approval hash *(Decided)*

SHA-256 over the following files, sorted by path (relative to `.brain/python`, `/` separators): the script, every `lib/**/*.py`, and `pyproject.toml`. Each file contributes `path`, a NUL byte, its bytes, and a NUL byte. Only `brainctl approve-hash` computes it, so every machine agrees.

## Files the helper owns

These formats were unspecified before the rehearsal. Keys may be added later; unknown keys are preserved.

**`.brain/config.yml`**

```yaml
version: 1                     # config format version
name: second-brain
archive:                       # the Archive's registration: there is no Archive item file
  adapter: markdown            # or `script` with `command:`
  path: "archive/{type}/{impl}/{slug}.md"
impls: .brain/impls            # where implementation definitions live
python:
  tool: uv                     # uv | poetry | pdm | venv
capture:
  type_by_source: {}           # e.g. { file: note, cli: note }
```

**Seen state** `.brain/automation/seen/<type>/<impl-id>.json` (git-ignored, rebuildable)

```json
{ "impl": "gtd-task",
  "checkpoint": { "cursor": null, "updated_since": "2026-11-06T01:27:13Z" },
  "entries": { "task:01M6...": { "revision": "<hash>", "fields": { }, "relations": { } } } }
```

**Pending entry** `.brain/automation/pending/<timestamp>-<type>-<impl-id>-<rule-id>.json` (git-ignored)

```json
{ "rule": "note/default-note/suggest-tags",
  "event": { "trigger": "capture", "ref": "note:01M6...", "origin": "external/note/default-note",
             "depth": 0, "detected_at": "2026-11-06T01:26:26Z", "revision": "<hash>" },
  "proposal": { "rationale": "...", "operations": [ { "op": "set_field", "ref": "note:01M6...", "field": "tags", "value": { } } ] },
  "created": "2026-11-06T01:26:34Z" }
```

**Half-converted marker** `.brain/conversions/<type>-<id>.json` (git-ignored)

```json
{ "ref": "task:01M6...", "from": { "impl": "default-task", "path": "tasks/draft-q4-plan.md" },
  "to": { "impl": "gtd-task", "path": "tasks/gtd/draft-q4-plan.md" }, "at": "2026-11-06T01:26:00Z" }
```

**Log line** `.brain/automation/log.jsonl`: `{ "ts", "rule", "trigger", "event", "actions", "outcome", "duration_ms" }`, one per rule run, plus one per helper write (`"command"`, `"ref"`).

## Implementation order

Built incrementally, each step usable alone:

1. `id`, `slug` (done: `ids.py`, with tests).
2. Parsing, schema loading and `validate` (read-only, safest first).
3. `read`, `list`, `sync` (detect, then adopt).
4. `create`, `update`, `archive`, `unarchive`, `delete`.
5. `convert plan` / `convert apply`.
6. `approve-hash`, `index rebuild`, packaging, and the migration that updates the copy.

## Open questions

1. **Performance on large vaults.** `list` and `sync` scan files. Is a persistent index (beyond the refs index) needed, and when?
2. **A long-running mode.** Each call pays interpreter and import start-up (`ruamel.yaml`). A `brainctl serve` over stdin for batch work, or just batch commands?
3. **Testing.** A fixture vault in the plugin repo exercised by the helper's tests, which the rehearsal vault can seed.
4. **Self-update.** How the vault's copy is checked against the plugin's version at session start (doc 02 check).

## Next steps

1. Implement step 2 onward from the list above, starting with `validate`.
2. Update the skills to call `brainctl` and to forbid hand-writing item files (done in the same change as each command lands).
3. Add the helper version and copy step to the migration doc (doc 02).
