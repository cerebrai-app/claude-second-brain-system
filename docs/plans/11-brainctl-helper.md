# 11 — The `brainctl` Helper

Status: **Draft, partly implemented** (`validate`, `sync`, `read`, `list`, `id`, `slug`, `approve-hash`, `approve`, `render`, `create`, `update`, `archive`, `unarchive`, `delete`, `convert`, `op`, `pending`, `log`; version 0.3.2) · Depends on: [03](03-storage-contract.md), [05](05-automation.md), [07](07-python-workspace.md), [08](08-core-types.md) · Origin: the first rehearsal ([10](10-plugin-skills.md), findings 1 and 2)

## Goal

Every mechanical step of working with the vault is deterministic: assigning ids and slugs, validating, writing a file atomically, keeping `updated` and `completed` right, moving a file, updating the sync seen state, the id index and the refs index,
adopting hand-written files, hashing a script for approval. In the rehearsal, doing these by hand from prose instructions caused real mistakes. `brainctl` is a small tool that does them, so the skills call it instead and **Claude supplies only judgment**
(what to propose, which area an item belongs to, what a natural-language filter means).

## Shape *(Decided)*

- **Runs in the vault's Python workspace** (doc 07), which is therefore **required**. It uses `ruamel.yaml` (locked in the workspace) so frontmatter round-trips with comments and key order intact.
- **Shipped in the plugin** at `plugins/brain/tools/brainctl/`; setup **copies** its modules (not its tests) to `.brain/python/brainctl/`, so the vault pins the version it uses. Its version is recorded in the manifest (`helper_version`); `/brain:upgrade` copies the files that differ from the plugin's version (new and changed files only, nothing else is touched or migrated) and records the new version; a core migration may also adapt the copy. It is plugin code, not user code: it is not part of a
  script's approval hash and cannot be edited through the `python` skill.
- **Runs only in the workspace virtualenv** (`.brain/python/.venv`). An installed copy refuses to start under any other interpreter (`wrong_environment`, exit 2); only a copy run from the plugin source (development, tests) is exempt. Script adapters and hooks written as workspace scripts get the same rule from the client: it runs them with `.venv/bin/python` and fails with `unavailable` when the environment does not exist (sync the workspace first).
- Invoked through the workspace tool from `.brain/python`, for example `uv run --frozen python -m brainctl <command>`; the skills use the tool recorded in `python.tool`.
- **Non-interactive.** It never prompts, never commits, and makes no network calls itself (script adapters make their own). Structured input is JSON on stdin; results are JSON on stdout; diagnostics go to stderr; the exit code maps to the storage error codes (doc 03) plus `0` for success.
- **Never trusted blindly.** It validates every write against the schemas on disk. A command that needs a human decision (an approval, a conversion resolution) takes the decision as input; the skill obtains it from the user.

## Commands

| Command | What it does |
|---|---|
| `id [-n N]` | New ULID(s). (`ids.py`, shipped now.) |
| `slug <title> [--dir D]` | A unique slug for the title (doc 08, Slug). (`ids.py`, shipped now.) |
| `create --json` | `{type, impl?, title or name, body?, tags?, fields, relations}`. Picks `impl` by the defaults cascade when absent (Project, Area, Inbox; a person: the active person implementation), assigns `id`, `slug` (when declared), `created`, `updated`, schema defaults, `status: open` and `completed`, normalises tags and relations, validates, writes atomically, then updates the seen state for that ref and appends to the log. Rolls back and answers `invalid` (with the findings) when the result does not validate. Returns the stored item and its `revision`. Markdown bindings only; a script binding answers `unsupported`. |
| `read <ref>` / `list` | Read an item, or list items by structural query, across bindings and the Archive. `list` keys results by ref **and** binding, so a duplicate ref is visible. |
| `update <ref> --json` | `{set, unset, body?, revision?}` (a patch, not a full replace: the skills turn `set_field` and `set_relation` into it). Edits only the lines of the changed keys, so comments, unknown keys and key order survive; sets `updated`; keeps `completed` in step with the status category (doc 08); moves the file when the rendered path changes; validates and rolls back on failure. `conflict` if `revision` differs. `id`, `type`, `impl`, `slug`, `created` and the other plugin-maintained keys cannot be set. A change that alters nothing writes nothing. |
| `archive <ref>` / `unarchive <ref>` | Move to and from the Archive path (an item with no `slug` is named by its `id`), setting or clearing `archive` and `archived_at`. The Inbox and other system items refuse. If the old file cannot be removed the error says the item now exists twice. |
| `delete <ref> --confirm permanent` | Permanent delete; refuses without the flag and for system items. Reports `referenced_by`. Runs no rules. |
| `convert plan <ref> --to <impl>` | The deterministic mapping and report as JSON: `carried`, `unmapped`, `invalid`, `missing`, `filled_by_default`, `dropped` (the slug, when the target declares none), `needs_resolution`. |
| `convert apply <ref> --to <impl> --json` | Resolutions `{drop, rename, fill}`; refuses until every unmapped, invalid and missing field is resolved. Creates in the target with the same id, deletes the source, updates the seen state, and writes the half-converted marker (shape below) if the source delete fails. `convert finish <ref>` completes an interrupted conversion from its marker. |
| `validate [--ref R]` | Every mechanical check in the `validate` skill: manifest and config, definitions, items, relations, duplicates across bindings, unadopted files, leftover markers, ignored-path checks, workspace approvals, rule templates, the automation log. JSON findings with severity. |
| `find` | `--type`, `--impl`, repeatable `--where field=value` (dotted paths), `--include-archived`. Items whose fields equal the values; exit 1 when none match. The deterministic lookup behind `unless_exists` (doc 05). |
| `sync` | Detect: scan all bindings and the Archive, match by ref across bindings, diff against the seen state, **adopt** hand-written files and **complete** the identity fields (slug, title, status, created, updated) of items that have an id but lack them (doc 05), and return the sync report and ordered event list. Updates the seen state, except for externally changed items that fail validation (held back so they are reported again). `--no-adopt` reports without editing files; `--dry-run` writes nothing; `--refresh` accepts the current state as seen (no events, no adoption), for use after the plugin's own writes. Script-adapter bindings are read through `client.py` (doc 12, Client); one that cannot be read is reported as incomplete and its items are never reported as missing. The one-minute `rate_limited` retry applies to script calls. |
| `render <template> [--vars JSON] [--var N=V] [--now ISO]` / `render --json <value>` | Resolve `{{ today }}`, `{{ now }}` and bound variables with the filters `checklist`, `bullets`, `refs`, `table` (doc 05, Template variables). `--json` resolves every string in a JSON value. Exit 2 on an unknown variable or filter. `templates.py`; `validate` uses the same parser (`rule-template`). |
| `op --json` | One rule operation (a rule action with `action:` is accepted as written): `set_field`, `set_relation`, `add_relation`, `archive`, `unarchive`, `create_item`. `create_item` takes the whole action: `unless_exists` (found: nothing is created, the result says `skipped: exists` with the ref) and `place` (a ref, or `{find, create_if_missing}`: the area is found by its fields, more than one match is a `conflict`, none is created when asked, and the new item gets the placement relation). Built-in actions, hooks and approved proposals all reduce to these; `convert` and `notify` are not handled here. |
| `pending add --json` / `list [--prune]` / `apply <id> [--json {operations}]` / `reject <id>` | The pending-approval queue (doc 05). `add` takes `{rule, event, instruction, rationale, operations}` and fills `id`, `status`, `created`, `expires` and `revision`. `list` marks each entry `fresh`, `stale` (the item changed or is gone) or `expired`; `--prune` drops expired ones. `apply` acts on the user's approval and refuses anything but a fresh entry. |
| `log --json` | Append a rule-run line; checks the outcome vocabulary (doc 05). |
| `approve-hash <script>` | The workspace approval hash (below). |
| `approve <script> \| --all --by WHO` | Record the current hash as the approval in `registry.yml` (`approved: {sha256, at, by}`), keeping the file's comments. `--all` covers every script that is unapproved or changed. The skill shows the user the diff first; the command only records the answer. `--by` is required and names the person who approved (their name or email); the helper refuses to guess it from the git identity, which may be a tool's. |
| `index rebuild` | Rebuild the derived refs index by scanning frontmatter ids. |

Script adapters (doc 03) are called by the same commands through their JSON protocol, so the skills have one interface whatever the backend.

### What stays with Claude

Proposals and judgment (triage placement, `claude` actions, `when` conditions, evaluating natural-language sorts and filters), choosing and applying rules, and talking to the user. The skills turn approved operations into helper calls (`set_field` is an `update`, `archive` is `archive`).

### Rule for the skills

**Item files are written only through `brainctl`.** The `core` skill states this. Input is JSON given as `--json '<json>'`, `--json @file` or `--json -`; stdin is never read implicitly, so a command cannot hang on an open pipe. Output is JSON; exit 0 on success, 1 with `{ok: false, error: {code, message}}` for a storage error (`invalid`, `conflict`, `not_found`, `unsupported`, `internal`), 2 for bad usage. A hand edit by the user is normal; sync picks it up.

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

**Pending entry** `.brain/automation/pending/<timestamp>-<type>-<impl-id>-<rule-id>.json` (git-ignored): the shape is in the automation reference (Pending entry file). Its `event` is a sync event, including the stable `id` (`ev_` and a hash of ref, trigger, revision before and after, relation).

**Half-converted marker** `.brain/conversions/<type>-<id>.json` (git-ignored)

```json
{ "ref": "task:01M6...", "from": { "impl": "default-task", "path": "tasks/draft-q4-plan.md" },
  "to": { "impl": "gtd-task", "path": "tasks/gtd/draft-q4-plan.md" }, "at": "2026-11-06T01:26:00Z" }
```

**Log line** `.brain/automation/log.jsonl`: `{ "ts", "rule", "trigger", "event", "actions", "outcome", "duration_ms" }`, one per rule run, plus one per helper write (`"command"`, `"ref"`). `outcome` uses the fixed vocabulary in doc 05 (Logging).

## Package layout and tests

The helper is the package `plugins/brain/tools/brainctl/` (`__main__.py` CLI, `model.py` vault and scanning, `schema.py` field types, `validate.py`, `sync.py`, `approval.py`, `templates.py`, `store.py` (the markdown writes), `pending.py` (operations, queue, log), `ids.py`, `util.py`, `client.py` (runs script adapters), and for backend authors `adapter.py` and `conformance.py`, doc 12). Setup copies the package without tests or caches. Its tests are pytest tests in `tests/` (see `TESTING.md`): unit tests for ids, schema, scanning and the approval hash; one test per `validate` check; sync tests for baseline, events, adoption, conversions and refresh; CLI tests including the installed-copy layout.

## Implementation order

Built incrementally, each step usable alone:

1. ~~`id`, `slug`~~ — done (`ids.py`).
2. ~~Parsing, schema loading and `validate`~~ — done: front matter, definitions, traits, items, relations, tags, rules, git-ignore, workspace approvals (`validate.py`, `schema.py`, `model.py`).
3. ~~`read`, `list`, `sync` (detect, then adopt)~~ — done for the markdown adapter and the Archive directory (`sync.py`). Script adapters are read through `client.py` (with the rate-limit retry and the `brainctl adapter` command). Not yet: write commands and id-index maintenance.
4. `create`, `update`, `archive`, `unarchive`, `delete`.
5. `convert plan` / `convert apply`.
6. `approve-hash`, `index rebuild`, packaging, and the migration that updates the copy.

## Open questions

1. **Performance on large vaults.** `list` and `sync` scan files. Is a persistent index (beyond the refs index) needed, and when?
2. **A long-running mode.** Each call pays interpreter and import start-up (`ruamel.yaml`). A `brainctl serve` over stdin for batch work, or just batch commands?
3. **Testing.** A fixture vault in the plugin repo exercised by the helper's tests, which the rehearsal vault can seed.
4. **Self-update.** How the vault's copy is checked against the plugin's version at session start (doc 02 check).

## Next steps

1. Implement step 4 onward from the list above: `create`, `update`, `archive`, `unarchive`, `delete`, then `convert`. Until `create`/`update` exist, the skills write item files by hand and run `sync --refresh`.
2. Update the skills to call `brainctl` and to forbid hand-writing item files (done in the same change as each command lands).
3. ~~Helper copy step~~ — done as `/brain:upgrade` (copies changed files; `helper_version` in the manifest). Still to do: tell migrations (doc 02) to call it, and a session-start check that warns when the vault's copy is older than the plugin's.
