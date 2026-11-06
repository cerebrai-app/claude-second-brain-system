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

"Not model-invocable" skills change data or apply approvals, so only the user starts them. `capture`, `sync`, `validate` and `python` may also be started by Claude when the user's request calls for them.
Every command skill begins by reading `core`.

## Principles

- **One home for each rule.** A rule lives in `core` (or its references) when it is a system semantic, in a command skill when it is about that command's flow, and in a vault definition only when it is implementation-specific (doc 09).
- **The skills restate the docs; the docs remain the design record.** When a doc changes, update the matching skill or reference in the same change.
- **Approvals are never skipped.** Every skill that applies a `claude` proposal, a script, a hook or a conversion shows it and waits for approval, and records the result.

## Not yet written

1. **Migration command.** Doc 02's flow (check on session start, dry run, generated `migrate.py`, apply per step) has no skill yet.
2. **Session-start behavior.** The design says sync, the migration check and the pending count run at session start; the plugin needs a `SessionStart` hook for that.
3. **`lib/brain_adapter.py`.** Setup and the `python` skill copy it into the workspace, but the module is not yet in the plugin.
4. **System-provided views and rules** (doc 09, gap 2): generic named sorts, filters and rules, and how they are referenced.
5. **Shipped `README.md` and starter `pyproject.toml`** for the Python workspace (doc 07).

## Rehearsal findings (first run on a scratch vault)

The skills were exercised on a branch of the `second-brain` repo (`claude/admiring-rubin-4sq9mk`). The plugin was not installed in that session, so the skills were **followed by hand** (setup, capture, a triage with a conversion, a simulated
half-converted failure, validate, sync, the pending queue, a vault-level rule, and a Python script run with `uv`), with two small throwaway scripts to emulate the deterministic parts of sync and validate. Nothing here has been run
through `/brain:*` itself. The vault commits are the record.

**What worked:** the setup order and manifest-last idea, plain-update and conversion triage, the half-converted marker plus validate finding the duplicate, deferral of `claude` proposals to the pending queue with a staleness check, the journal vault rule
(idempotent `replace_section`), and the Python workspace on `uv` (`init --bare`, `lock`, `sync --frozen`, `run --frozen`, even with a scrubbed environment).

### Needs a decision or a design change

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
16. The workspace `README.md`, `lib/brain_adapter.py` and a session-start hook are still unwritten (see Not yet written).

## Next steps

1. Decide the rehearsal findings above (especially 1, 3, 4, 5 and 6), then fix the skills and references.
2. Write the migration skill (and the session-start hook).
3. Write `brain_adapter.py`, the deterministic helper and the workspace starter files.
4. Specify system-provided views and rules.
5. Try the skills end to end against a scratch vault and fix what the rehearsal exposes.
