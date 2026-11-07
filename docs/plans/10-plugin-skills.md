# 10 — Plugin Skills

Status: **Draft** · Depends on: all of [01](01-core-data-model.md) to [09](09-starter-implementations.md)

## Goal

The plugin has no application code. Its behavior is carried by **skills**: instructions Claude loads and follows, plus the deterministic scripts and adapters in the vault. This doc lists the system skills, what each owns, and how
they relate to the design docs. The skills are self-contained (the installed plugin does not include `docs/plans/`), so the rules the docs describe are restated in each skill's `references/`.

## The skill set

All live in `plugins/brain/skills/<name>/SKILL.md`. A plugin skill is invoked as `/brain:<name>`; the design docs write the same commands as `/brain <name>` for brevity.

| Skill | Command | Model-invocable | Owns |
|---|---|---|---|
| `core` | none (background knowledge) | yes | Core types, fields, relations, statuses, tags, traits, field types, placement and the Inbox, archive and delete rules, defaults, storage and automation references (`references/core-types.md`, `storage.md`, `automation.md`). Replaces the core semantics removed from the starters (doc 09). |
| `setup` | `/brain:setup` | no | Install flow and repair (doc 06). |
| `capture` | `/brain:capture` | yes | Creating items in the Inbox and persons (doc 06). |
| `triage` | `/brain:triage` | no | Placement and conversion (doc 06). |
| `sync` | `/brain:sync` | yes | Detecting external changes, events, and deferred dispatch (doc 05). |
| `pending` | `/brain:pending` | no | Reviewing deferred `claude` proposals (doc 05). |
| `run` | `/brain:run` | no | Listing rules and running `manual` rules (doc 05). |
| `validate` | `/brain:validate` | yes | Vault health checks and repair proposals (docs 06, 07, 08). |
| `python` | `/brain:python` | yes | The managed Python workspace and the "prefer a script to repetition" rule (doc 07). |
| `upgrade` | `/brain:upgrade` | no | Copying the changed files of the plugin's `brainctl` into the vault's pinned copy (doc 11). |
| `backend` | `/brain:backend` | yes | Specifying, building, testing, binding and changing a storage backend for an outside service (doc 12). |

"Not model-invocable" skills change data or apply approvals, so only the user starts them. `capture`, `sync`, `validate`, `python` and `backend` may also be started by Claude when the user's request calls for them (each has its own approval checkpoints).
Every command skill begins by reading `core`.

## Principles

- **One home for each rule.** A rule lives in `core` (or its references) when it is a system semantic, in a command skill when it is about that command's flow, and in a vault definition only when it is implementation-specific (doc 09).
- **The skills restate the docs; the docs remain the design record.** When a doc changes, update the matching skill or reference in the same change.
- **Approvals are never skipped.** Every skill that applies a `claude` proposal, a script, a hook or a conversion shows it and waits for approval, and records the result.

## Not yet written

1. **Migration command.** Doc 02's flow (check on session start, dry run, generated `migrate.py`, apply per step) has no skill yet.
2. **Session-start behavior.** The design says sync, the migration check and the pending count run at session start; the plugin needs a `SessionStart` hook for that.
3. ~~`lib/brain_adapter.py`~~ — superseded: `brainctl.adapter` and `brainctl.conformance` ship in the helper (doc 12).
4. **System-provided views and rules** (doc 09, gap 2): generic named sorts, filters and rules, and how they are referenced.
5. **Shipped `README.md` and starter `pyproject.toml`** for the Python workspace (doc 07).

## Rehearsal findings (first run on a scratch vault)

The skills were exercised on a branch of the `second-brain` repo (`claude/admiring-rubin-4sq9mk`). The plugin was not installed in that session, so the skills were **followed by hand** (setup, capture, a triage with a conversion, a simulated
half-converted failure, validate, sync, the pending queue, a vault-level rule, and a Python script run with `uv`), with two small throwaway scripts to emulate the deterministic parts of sync and validate. Nothing here has been run
through `/brain:*` itself. The vault commits are the record.

**What worked:** the setup order and manifest-last idea, plain-update and conversion triage, the half-converted marker plus validate finding the duplicate, deferral of `claude` proposals to the pending queue with a staleness check, the journal vault rule
(idempotent `replace_section`), and the Python workspace on `uv` (`init --bare`, `lock`, `sync --frozen`, `run --frozen`, even with a scrubbed environment).

### Decisions taken after the rehearsal

- **1 and 2 (hand-editing, ids):** yes to a deterministic helper, `brainctl` (doc 11), running in the Python workspace, which is now **required**. `ids.py` (ULID and slug generation, with tests) is shipped; the rest is specified.
- **Human-readable file names:** items are named by a `slug` (doc 08), fixed at creation; path templates gain `{slug}` and `{field:FORMAT}` (doc 03). Journal notes get date file names from a date title or a formatted date field.
- **3 (Areas):** Areas are top-level and never triaged.
- **4 (automation-created items):** `place:` on `create_item` and on `write_body` targets (doc 05); without it the item lands in the Inbox and the rule gets a warning.
- **5 (hand-written files):** sync adopts them automatically and additively, and reports them (doc 05).
- **6 (sync across bindings):** matched by ref across bindings, so a conversion is one `update` with `impl` changed. *Proposed by me; you were unsure.*
- **7 (defaults on conversion):** schema defaults apply, shown as *filled by default*. *Proposed by me; you were unsure.*
- **Small fixes 13 to 15 and gaps 8, 9, 12:** setup and validate now check ignored paths and add negations, skip redundant lines, and add `.gitkeep`; file formats and the approval hash are in doc 11; duplicate refs are a validate check. Still open: gap 10 (template variables and formatters in rules) and gap 11 (blocked rules) is now in `validate`.

### Findings as first recorded (items marked above are decided)

1. **Hand-editing is the weak point.** Writing items as markdown by hand means Claude must also maintain `updated`, `revision`, the sync seen state, the id index and conversion markers, and move files. During the rehearsal I forgot to refresh the seen state after my own writes (sync then reported
   them as external updates) and forgot `updated` once. These steps are deterministic and error-prone as prose. **Recommendation:** ship a small deterministic helper (a script in the workspace or the plugin) for create, update, archive, validate and sync, and have the skills call it instead of describing the steps.
2. **IDs.** Nothing says how a ULID is produced, and Claude cannot mint one reliably. The helper above should do it.
3. **Areas look permanently untriaged.** A top-level Area has no `parent`, which is exactly "unplaced", so every Area is a triage candidate forever. Likely fix: Areas are not triaged (top-level is normal), or `parent` is required to be explicit.
4. **Automation-created items land in the Inbox** (the journal note) and become permanent triage candidates. They need explicit placement or an exclusion.
5. **Hand-created files** without `id`/`type`/`impl` are silently ignored. The design has no "adopt" step (assign the identity fields) and sync does not report unrecognized files.
6. **Sync matches per binding.** A conversion appears as a `create` in the target and a missing item in the source. Sync should match by ref across bindings and emit one `update` with `impl` in `changed`.
7. **Does `default` apply on conversion?** Creating in the target applies schema defaults (`priority: med` appeared). Decide and state it.

### Gaps to specify

8. `config.yml` shape, how the Archive is "registered", and the file formats of the seen state, pending entries and conversion markers.
9. Approval-hash algorithm (file ordering and framing). I used sorted paths with `path NUL content NUL`; it must be identical everywhere, so ship it in the helper.
10. Template variables and formatters in rules (`{{ today }}`, `| checklist`) are only illustrative in doc 05. A journal title must be written quoted (`"2026-11-06"`) or YAML reads it as a date.
11. Validate and run should say that a rule referencing a filter or sort the implementation does not define is blocked (starters now ship none).
12. Duplicate refs across bindings (a half-converted item) need an explicit check in validate and a ref-keyed lister.

### Small fixes to the skills

13. **`.brain/python/lib/` was git-ignored** by the vault's own Python `.gitignore` template (`lib/`). Setup and validate must check, with `git check-ignore`, that every path that should be committed is not ignored, and add a negation (`!.brain/python/lib/`).
14. Setup appended gitignore lines that were already covered (`.venv`, `__pycache__`); it should skip lines whose effect already holds.
15. Empty directories (`scripts/`, `lib/`, `tests/`) need a `.gitkeep`.
16. The workspace `README.md` and a session-start hook are still unwritten (see Not yet written).

## Second rehearsal (installed plugin, headless)

The vault was wiped and rebuilt through the installed plugin (`claude -p`, steps 1 to 4 and 6 to 9 of `TESTING.md`; step 5 was not rerun). Setup, capture, `gtd-task`, triage with a conversion, sync with adoption, the pending queue, the journal rule and a script all worked as designed, and `validate` ended at 0 errors and 0 warnings. Findings:

1. **A date-only journal path is rejected.** `journal/{created:%Y-%m-%d}.md` fails `validate` (a path template needs `{slug}` or `{id}`). Use `journal/{slug}.md` with the date as the slug; the file name is the same, and a clash gets `-02` instead of an overwrite. *Fixed in the rehearsal text.*
2. **No structural "create unless it exists".** A manual rule that should do nothing on its second run needs a `when` condition, which Claude judges itself, so idempotence depends on Claude's reading. *Resolved:* `create_item.unless_exists` plus `brainctl find` (doc 05, doc 11).
3. **One value per tag key.** Tags are a map, so a rule that asks for "two `topic` tags" can produce only one. Rule instructions should name distinct keys. *Resolved:* `validate` warns (`tags-one-per-key`) when a `claude` instruction asks for several tags without naming distinct keys. It is a wording heuristic, not a proof.
4. **Sync adopts only files without identity fields.** A hand-written file with an `id` but no `slug` is not completed by sync; `validate` warns and a person fixes it. *Resolved:* sync now completes missing identity fields (slug, title or name, status, created, updated) on such files and reports them as `completed` (doc 05).
5. **Changing a project's `defaults.task` does not convert existing tasks.** As designed; only new tasks use the new implementation. The skill says so, and triage is the way to convert.
6. **Ignored state was tracked.** A previous vault had committed `.brain/automation/seen/*`; setup now untracks them (`git rm --cached`) before its commit. Setup should do this by design, not by luck.
7. **Headless runs need `-c`** (continue) to answer setup's confirmation, and `--allowedTools` for the file tools. `uv` chose Python 3.12.3 although 3.13 was installed; both satisfy the minimum.

## Third rehearsal (slug as a schema field, shared ids-and-slugs reference)

Wiped a scratch vault repo and ran steps 1 to 10 headless through the installed plugin (`claude -p`, isolated config, local marketplace). All ten steps behaved as expected and the vault ends with 0 errors and 0 warnings: the `default-*` starters with their `slug` field and Slug section, a `gtd-task` and a `journal` implementation that each declare `slug`, a triage conversion, an interrupted conversion (duplicate-ref error and marker, then finished), sync adoption of a plain file (slug from its file name), a pending entry applied, a date-named journal note created once and skipped on the second run, and an approved script. Findings:

1. **`defaults` syntax is undocumented.** Setting a project's `defaults.task` worked only because the model guessed `defaults: { task: gtd-task }`. *Fixed:* example added to `core-types.md` (`defaults`).
2. **Nothing writes pending entries.** `brainctl sync` emits events; the model hand-wrote the pending JSON. *Fixed:* the main session writes it when dispatching the sync event list; the file shape is in the automation reference. A `brainctl` helper to write it is still open.
3. **Vault rules cannot say "today".** The journal rule had to carry a literal `<today's date>` placeholder, resolved by hand. *Fixed:* `{{ today }}` and `{{ now }}` are built-in template variables (doc 05, automation reference), resolved by `brainctl render`, not by Claude. The full formatter set (`| checklist`) is still open.
4. **`brainctl approve --all` does not exist.** TESTING step 9 and the `python` skill mention it; the model recomputed the hash and edited `registry.yml`. *Fixed:* `brainctl approve <script> | --all` records the hash in `registry.yml` and keeps its comments.
5. **The conversion marker layout is the model's own.** The spec only says ref, both bindings and a timestamp; *Fixed:* the shape (doc 11: `ref`, `from`, `to`, `at`) is now in the storage reference and `validate` checks it (`conversion-marker`).
6. **`/brain:run` must be invoked as a slash command.** Asked in prose, the model reported it as unavailable and ran the steps by hand (it is user-only). Not a plugin bug; the headless instructions in `TESTING.md` already use slash commands.

## Fourth rehearsal (after the fixes: `render`, `approve`, `defaults`, marker shape, `rules:`)

Wiped the scratch vault and reran steps 1 to 10 headless on brainctl 0.2.0 (then 0.2.1). All steps behaved as expected and the vault ends with 0 errors and 0 warnings. Confirmed fixed: the model found the `defaults` format and the conversion marker shape from the references alone; timestamps and `today` came from `brainctl render`; the journal rule used `{{ today }}` with no hand-resolved placeholder and ran once, then skipped; the script was approved and re-approved with `brainctl approve` / `approve --all`; the pending entry followed the documented shape. Findings:

1. **Fixed: `created` taken from a deleted file's history.** Adopting an untracked file at a path that once held another (committed, since deleted) file used that old file's first commit time. Adoption now uses git history only for a tracked file (0.2.1).
2. **Fixed: sync events have no `id`.** Events now carry a stable `id` (a hash of the transition), documented in the automation reference (0.2.2).
3. **Fixed: `approve` recorded `by` from git `user.email`** (`noreply@anthropic.com` in a headless session). `--by` is now required.
4. **Fixed: every item write was the model editing files.** `brainctl` 0.3.0 has `create`, `update`, `archive`, `unarchive`, `delete`, `convert`, `op`, `pending` and `log` for markdown bindings, and the skills call them. The next rehearsal should confirm the model uses them. Still hand-written by design: the Inbox at setup, and sync adoption of the user's own files. Script-adapter bindings answer `unsupported` for writes.
5. **Fixed: run outcomes in the log were free text.** The vocabulary is fixed (doc 05, Logging) and `validate` checks it.

## Fifth rehearsal (the write commands, brainctl 0.3.x)

Wiped the vault and ran steps 1 to 10 headless with prompts that name no brainctl command, to see whether the skills steer the model to the helper. They did: every item write was `create`, `update`, `op`, `convert plan|apply|finish` or `pending add|apply`, and `log` lines came from the helper. The step 5 failure was real (the source file made immutable, so the delete failed): the helper returned `internal`, wrote the marker, `validate` showed `duplicate-ref` and `half-converted`, and `convert finish` cleared both. Hand edits (step 6) were the only events `sync` reported; none of the helper's own writes were. The vault ends with 0 errors and 0 warnings. Findings:

1. **Fixed: `op create_item` ignored `place` and `unless_exists`.** The model had to create the Journals area and set the placement by hand. `op` now finds or creates the area, places the item, and skips with `exists` (0.3.1).
2. **Fixed: `op` demanded `op:` where rules write `action:`.** It now accepts the action as written (0.3.2).
3. **Fixed: refs were quoted in front matter** (`"project:01M..."`), unlike hand-written files. They are plain now.
4. **Fixed: `create` gave no way to see the body landed.** The result reports `body_length`.
5. **Fixed: definitions were edited by hand.** `brainctl impl add|update|show`, `rule add|remove|list` and `trait add` (0.4.0) write implementations, rules, traits and the manifest, keep comments, and refuse any change that adds a vault error. Checked headless: given only the goal, the model chose these commands and the manifest diff was two lines.
6. **Open: `place` with `create_if_missing` creates the area with only the `where` fields,** and a `write_body` target is not handled by `op` (no `write_body` operation yet).

## Next steps

1. Continue `brainctl` (doc 11): `create`, `update`, `archive`, `unarchive`, `delete`, `convert`. The `validate`, `sync` and `core` skills already call it.
2. Define template variables and formatters for rules (`{{ today }}`, `| checklist`).
3. Write the migration skill (and the session-start hook).
4. Write the workspace starter files.
5. Specify system-provided views and rules.
6. Rehearsal rerun done once (above). Still to try: step 5 (the interrupted conversion) through the plugin, a real backend through `/brain:backend`, and `/brain:upgrade` on a vault with an older helper. Findings 2 to 4 are resolved; the test vault's journal rule still uses a `when` condition until it is rebuilt with `unless_exists`.
