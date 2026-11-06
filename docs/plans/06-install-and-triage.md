# 06 — Install Flow and Triage

Status: **Draft** · Depends on: [01 — Core Data Model](01-core-data-model.md), [02 — Versioning and Migrations](02-versioning-and-migrations.md), [03 — Storage Contract](03-storage-contract.md), [05 — Automation](05-automation.md) · See also: [07 — Python Workspace](07-python-workspace.md)

## Goal

Define how a vault is created (**install / setup**) and how new items move out of the Inbox into their proper place (**capture** and **triage**),
including converting an item between implementations when its destination uses a different one. Everything here goes through the storage
contract (doc 03) and core validation, like any other change.

## Install flow

### Command and preconditions

`/brain setup` initializes a vault in the brain repo (`second-brain`). It is also suggested at session start when no `.brain/manifest.yml` exists.

- The working directory must be a git repository (the repo is the vault). If it is not, setup stops and says so; it does not run `git init`.
- If `.brain/` already contains a **complete** vault (manifest present), `/brain setup` does **not** reinitialize. It runs validation and repair
  (below) and reports.
- Setup never overwrites an existing file. Anything it would create that already exists is reported and left alone.

### Style: accept defaults, then tweak *(Decided)*

Setup asks **one** question. It shows a summary of what it will create and asks for a single confirmation; there is no per-type interview.

| Choice | Default |
|---|---|
| Vault `name` | The repo directory name. |
| Storage for every core type | Built-in `markdown` adapter in the brain repo. |
| Archive adapter | **Built-in `markdown` adapter** in the brain repo, at `archive/{type}/{impl}/{slug}.md` (doc 03). The adapter is fixed at install; this is the only place it is chosen, so the summary states it plainly. A user who wants a `script` adapter edits the summary's choice before confirming; it must report `archive_adapter: true` (doc 03) or setup refuses it. |
| Inbox `defaults` | One built-in starter implementation per non-person core type: `default-task`, `default-note`, `default-project`, `default-area`. (There is no `person` default; see next row.) |
| Person implementation | Exactly one per vault *(Decided)*: `default-person`, `markdown` storage in its own directory, `people/{slug}.md`. |
| Python workspace | Created at `.brain/python/` with the package manager detected on the machine (`uv`, `poetry`, `pdm`, else `venv` + `pip`), shown in the summary and changeable before confirming (doc 07). Requires Python 3.12 or newer: an existing interpreter is used, otherwise the summary asks approval to fetch one with the user's tool. **Required** *(Decided)*: the deterministic helper (doc 11) runs in it, so setup stops before creating anything, with instructions, if no suitable Python is found and the user declines to fetch one. Installs one locked dependency, `ruamel.yaml` (shown in the summary; needs network). POSIX only for now. |

The summary lists the files to be created and the defaults above. The user may answer *go*, *change <choice>*, or *cancel*. Everything after install is changed
by editing files (or asking Claude to), not by a setup wizard: Inbox `defaults` live on the Inbox area item and are validated like any `defaults` (doc 01);
the Archive adapter stays fixed.

### What setup creates

In this order, so an interrupted run is recoverable:

1. `.brain/config.yml`: `version`, the vault `name`, the `archive` adapter choice, and the location of implementation definitions (doc 01).
2. `.brain/impls/<type>/default-<type>.md` for each of the five extensible types (including the single `person` implementation): the built-in starter definitions, copied from the plugin
   (`plugins/brain/`). Copied, not linked, so the vault owns them (doc 01, Ownership). Each starts at `version: 1`.
3. The **Archive** (`archive:archive`), registered with the chosen Archive adapter (doc 03).
4. The **Inbox** area item (`area:inbox`, `system: true`) with `defaults` for each core type pointing at the starters. It is stored by `default-area`'s binding.
5. The **Python workspace** (doc 07), required: `.brain/python/` with `pyproject.toml` (one dependency, `ruamel.yaml`), the lock file, an empty `registry.yml`, the agents' `README.md`, `brainctl/` (the deterministic helper, copied from the plugin, doc 11; it includes the script adapter base class and conformance kit, doc 12), and empty `scripts/`, `lib/` and `tests/` (each with a `.gitkeep`). The detected tool is recorded as `python.tool` in `config.yml`. A **preflight** before step 1 checks for Python 3.12 or newer and a tool, or asks approval to fetch Python (doc 07); if neither works, setup stops without creating anything.
6. `.gitignore` entries for derived, rebuildable state: `.brain/index/`, `.brain/cache/`, `.brain/automation/seen/`, `.brain/automation/pending/`,
   `.brain/automation/log.jsonl`, `.brain/conversions/`, `.brain/python/.venv/`, `.brain/python/outputs/`, `__pycache__/`. (`.brain/id-index/` and the rest of `.brain/python/` are committed.) Existing entries are kept; missing ones appended.
7. **`.brain/manifest.yml` last** (doc 02): `core_version` = the plugin's current core version, empty `migrations`, and the `implementations` index for the starters.

`.brain/automation.yml` (vault-level automation, doc 05) is **not** created at install; it is created on first use.

The manifest is written last on purpose: a vault without a manifest is *incomplete*, so a failed setup is re-runnable. On re-run, setup detects which of steps 1 to 6
already exist, validates them against the same defaults, creates only the missing pieces, and then writes the manifest. If an existing file conflicts with what setup
would have written (for example a hand-edited `config.yml` with a different Archive adapter), setup stops and asks rather than replacing it.

When done, setup makes **one git commit** ("brain: initial setup") after the user's confirmation, and reports the vault summary. The first sync (doc 05) builds its baseline
silently, so installing into an existing repo of notes causes no `create` event storm.

### Validation and repair

`/brain setup` on a complete vault, and `/brain validate`, check without changing anything unless the user approves a fix:

- Manifest and `config.yml` present and consistent with the implementation definitions on disk.
- Exactly one Archive; the Inbox exists, is an Area, and cannot be deleted; its `defaults` name implementations that exist.
- Impl ids are unique within each core type (doc 03), and there is exactly one **active** `person` implementation (plus at most one flagged `migration_target`, doc 01).
- Required `.gitignore` entries present.
- If `.brain/python/` exists: `pyproject.toml` and the lock file are present, the lock matches the project, and every registered script exists and is approved at its current hash (otherwise reported as *changed since approval* or *never approved*).
- No leftover half-converted markers in `.brain/conversions/` (each offers to finish its conversion).

Fixes (for example re-creating a deleted starter definition or the Inbox) are shown as a proposal and applied only on approval. A missing or mismatched Archive adapter is
reported, never "fixed", since it is fixed at install.

## Placement: what "in the Inbox" means

Each core type has one **placement relation**, the relation that puts an item under an Area or Project (doc 01):

| Type | Placement relation | Notes |
|---|---|---|
| `Task` | `belongs_to` → Project/Area | |
| `Note` | `about` → Project/Area/Person | Only the (at most one) Project or Area target counts as placement (doc 08). |
| `Project` | `area` → Area | |
| `Area` | none | **Top-level** *(Decided)*: an Area is never in the Inbox and is never triaged. `parent` only nests Areas for organization (doc 08); a top-level Area is normal, so an absent `parent` does not mean "unplaced". |
| `Person` | none | **Top-level** *(Decided)*: a person is not placed in any Area or Project, is never in the Inbox, and is never triaged. Its relations are named relations to any item (doc 01). |

An item is **in the Inbox** when its placement relation is absent or points at `area:inbox`. System items (the Inbox, the Archive) and archived items are never candidates.
Finding candidates uses `list` per binding of the three placed types (`task`, `note`, `project`) (paged) and filters client-side, because the structural `query` can test that a relation is present but not that
it is absent (doc 03). The sync seen state (doc 05) can narrow the scan for large vaults.

## Capture

`/brain capture [--type <type>] <text>` creates a new item in the Inbox:

- The type defaults **by input source** *(Decided)*: how the text arrived (for example typed on the command line, piped in, a link or a file) selects the default type through `capture.type_by_source` in `.brain/config.yml`. The built-in default for every source is `note`. `--type task` (and so on) always overrides it. Claude does not infer the type. The implementation is the Inbox `defaults.<type>` (doc 01 resolution, step 3).
- The item is created with no placement relation, so it is in the Inbox. This fires `create` and `capture` (doc 05).
- `--trait <name>` (repeatable) attaches traits at creation, for `--type person` only; the trait's required fields are prompted for. A new item otherwise starts with no traits (doc 01).
- **`--type area` and `--type person` are exceptions:** an area or a person is top-level, so it is created with the vault's active person implementation, is not in the Inbox, fires `create` only (no `capture`), and is never offered for triage.
- Items created outside the plugin that land in the Inbox are detected by sync and fire `capture` as well (`origin: external/...`), but **do not** trigger the inline
  offer below; they simply appear in the triage backlog.

## Triage

Triage places an item: it assigns a placement relation (an Area and/or a Project) and, if the resolved default implementation for the destination differs from the item's current
implementation, **converts** it. Both entry points use the same proposal and apply path *(Decided)*.

### Entry points

1. **Capture-time (inline).** Right after `/brain capture`, the plugin offers *Triage now?* with a Claude-drafted placement proposal for that item. Answering *later* leaves it in
   the Inbox for the backlog. A user can also attach their own `capture` rules (doc 05, for example the `triage-suggest` `claude` action) for richer suggestions; those follow doc 05's
   approval rules (including deferral when the event is sync-detected).
2. **Backlog: `/brain triage`.** Walks the Inbox candidates one at a time, oldest `created` first (an argument can limit it to a type, or to items matching a named filter, doc 04).
   A session reports the count first and can be stopped at any time; remaining items stay in the Inbox.

### Proposal (shared by both)

Claude receives the item and read-only access to Areas and Projects (and, for context, their `defaults`), and returns a **triage proposal**, in the same form as a `claude` action
proposal (doc 05): an ordered operation list plus a short rationale. It cannot write anything while proposing. The operations are drawn from:

- `set_relation` (the placement relation), `set_field` (for example a due date implied by the text), and
- `convert` (below), included only when the destination's resolved implementation differs from the current one.

The user sees the item, the proposed operations as diffs, and the rationale, and may **approve**, **edit** (placement, implementation override, or fields; re-validated), **skip** (the
item stays in the Inbox and is not re-offered this session), or **archive** it (the normal archive operation, doc 03). Approval applies the operations exactly as shown, as in doc 05.
Rejection is logged.

The destination's implementation is the doc 01 cascade for the item's type, evaluated for the **new** placement (Project → Area → Inbox → built-in). The user can override it
in the edit step.

### Placement without conversion

If the resolved implementation equals the item's current one, triage is a single `update` through the storage contract (relation and any fields), carrying the revision read.
A `conflict` means re-read and re-propose.

### Conversion (same id, different implementation) *(Decided)*

Conversion moves an item to another implementation of the **same core type**, keeping its `id` and therefore every existing reference (doc 03). Converting to a different core type
is not triage and is out of scope.

Trait lists and namespaced trait fields travel with the item and carry over unchanged when the target adapter supports traits (doc 01, 03); a target that does not is blocked.

Conversion is a plugin operation, not tied to triage: the same mapping, report, apply order and failure handling serve any item, including a **person** moving to a migration-target
implementation (doc 01). Persons are never triaged, but they can be converted individually. A bulk command that converts many items (all persons, or all items of an implementation)
by repeating this operation is post-MVP (see `deferred.md`).

**Mapping is deterministic.** Claude is not involved in deciding what carries over:

| Part of the item | Rule |
|---|---|
| Core fields | Carried over unchanged. |
| Source fields that **also exist** in the target schema | Carried over if the value validates against the target field's type and constraints; otherwise reported as *invalid*. |
| Source fields **not in the target schema** | Reported as *unmapped*. |
| Target fields with a **`default`** and no mapped value | Filled with the default (conversion is a create in the target) and listed in the report as *filled by default*; no resolution needed. |
| Target fields that are **required and have no value or default** | Reported as *missing*. |
| Relations | Core relations carry over. Implementation-specific relations carry over if the target allows the same relation name; otherwise reported as *unmapped*. |
| `body` | Carried over. If the target's binding has `supports_body: false` and the body is non-empty, conversion is **blocked** until the user resolves it (doc 03). |

If nothing is reported, the conversion needs no extra input. Otherwise the plugin shows a **conversion report** and the user resolves **each** reported field before anything is
written: *drop* it, *rename* it to a target field, *fill in* a value (for missing/invalid), or *cancel* the conversion. Claude may be asked to suggest a rename or value, but a
suggestion is only a pre-filled choice the user confirms; nothing is applied automatically. The resolved choices become part of the proposal shown for approval.

**Apply order** (doc 03: multi-item operations must be ordered so a failure midway is recoverable and re-runnable):

1. Validate the converted envelope against the target implementation's schema. Any failure stops here; nothing has changed.
2. `create` in the target binding with the **same id**.
3. If the target is a `script` adapter, the plugin records the returned `native_id` in the id index (doc 03).
4. `delete` from the source binding. This is the sanctioned permanent delete (doc 03): it needs no extra confirmation, and `before_delete` rules (doc 05) **do not fire**, because the item lives on.
5. Update the sync seen state for both bindings so the plugin's own conversion is not later detected as an external change (doc 05).

**Failure.** Step 1 or 2 fails: nothing changed, report. Step 4 fails after 2 succeeded: the item exists twice (doc 03: `resolve` order picks the default binding). The plugin reports it
and writes a *half-converted* marker to `.brain/conversions/<type>-<id>.json` (git-ignored) holding the ref, the source and target bindings, and a timestamp; re-running triage on that item, or `/brain validate`, finds the
marker and offers to **finish** by retrying the source delete. The marker is removed once the delete succeeds. It never re-creates the item.

**Events (doc 05).** A conversion is an `update` of the existing item, delivered to the **target** implementation's rules, with `changed` including `impl` and the placement relation. It
does **not** fire `create` or `capture`, since the item is not new. Added or removed relations also fire `relation` events. Rules of the source implementation see nothing; permanent delete
is not a trigger.

### Logging and commits

Each triage operation is logged like a rule run (doc 05). For the markdown adapter, triage leaves changes uncommitted and offers **one commit at the end of the session**
("brain: triage N items"). Conversions across external backends cannot be reverted with git; the proposal's diff is the user's only check, so it is always shown.

## Open questions

1. ~~Persons and placement~~ — resolved: **persons are top-level**: no Area or Project, never in the Inbox, never triaged. They can have named relations to any item (doc 01).
2. ~~Type inference at capture~~ — resolved: **no inference.** The default type depends on the input source (`capture.type_by_source`, built-in default `note`), and `--type` overrides it.
3. ~~Bulk triage~~ — resolved: **deferred past the MVP.** Triage is one item at a time (see `deferred.md`).
4. ~~Candidate discovery cost~~ — resolved: **the storage contract is unchanged** (no "relation absent" query key). Discovery filters client-side; where that is too slow, the flow is optimized **per adapter** as needed, guided by the latency log (doc 03).
5. ~~Commit granularity~~ — resolved: **one commit per session**, offered at the end of `/brain triage`.
6. ~~Half-converted marker location~~ — resolved: its own git-ignored file, `.brain/conversions/<type>-<id>.json`, removed when the source delete succeeds.
7. **Bulk conversion command.** Selection (all items of an implementation, a filter), one combined report vs. per-item, and ordering/resumability for large vaults. Post-MVP.
8. **Undoing a conversion.** Triage back to the original implementation is the only path; is a dedicated "undo last triage" worth having?

## Next steps

1. ~~Resolve the open questions~~ — done; only the deferred bulk conversion command and undo remain (see `deferred.md`).
2. ~~Update docs 01, 02 and 05~~ — done: doc 01 points here and no longer says "conversion mechanics TBD"; doc 02 already states the manifest is written by setup; doc 05 has `set_relation`, `convert` (interactive only) and the capture inline offer.
3. ~~Write the built-in starter implementations~~ — done: [09 — Built-in Starter Implementations](09-starter-implementations.md), shipped at `plugins/brain/starters/`.
