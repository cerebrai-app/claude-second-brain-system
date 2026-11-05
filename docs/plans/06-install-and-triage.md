# 06 — Install Flow and Triage

Status: **Draft** · Depends on: [01 — Core Data Model](01-core-data-model.md), [02 — Versioning and Migrations](02-versioning-and-migrations.md), [03 — Storage Contract](03-storage-contract.md), [05 — Automation](05-automation.md)

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
| Archive adapter | **Built-in `markdown` adapter** in the brain repo, at `archive/{type}/{impl}/{id}.md` (doc 03). The adapter is fixed at install; this is the only place it is chosen, so the summary states it plainly. A user who wants a `script` adapter edits the summary's choice before confirming; it must report `archive_adapter: true` (doc 03) or setup refuses it. |
| Inbox `defaults` | One built-in starter implementation per core type: `default-task`, `default-note`, `default-project`, `default-person`, `default-area`. |

The summary lists the files to be created and the defaults above. The user may answer *go*, *change <choice>*, or *cancel*. Everything after install is changed
by editing files (or asking Claude to), not by a setup wizard: Inbox `defaults` live on the Inbox area item and are validated like any `defaults` (doc 01);
the Archive adapter stays fixed.

### What setup creates

In this order, so an interrupted run is recoverable:

1. `.brain/config.yml`: `version`, the vault `name`, the `archive` adapter choice, and the location of implementation definitions (doc 01).
2. `.brain/impls/<type>/default-<type>.md` for each of the five extensible types: the built-in starter definitions, copied from the plugin
   (`plugins/brain/`). Copied, not linked, so the vault owns them (doc 01, Ownership). Each starts at `version: 1`.
3. The **Archive** (`archive:archive`), registered with the chosen Archive adapter (doc 03).
4. The **Inbox** area item (`area:inbox`, `system: true`) with `defaults` for each core type pointing at the starters. It is stored by `default-area`'s binding.
5. `.gitignore` entries for derived, rebuildable state: `.brain/index/`, `.brain/cache/`, `.brain/automation/seen/`, `.brain/automation/pending/`,
   `.brain/automation/log.jsonl`. (`.brain/id-index/` is committed, doc 03.) Existing entries are kept; missing ones appended.
6. **`.brain/manifest.yml` last** (doc 02): `core_version` = the plugin's current core version, empty `migrations`, and the `implementations` index for the starters.

`.brain/automation.yml` (vault-level automation, doc 05) is **not** created at install; it is created on first use.

The manifest is written last on purpose: a vault without a manifest is *incomplete*, so a failed setup is re-runnable. On re-run, setup detects which of steps 1 to 5
already exist, validates them against the same defaults, creates only the missing pieces, and then writes the manifest. If an existing file conflicts with what setup
would have written (for example a hand-edited `config.yml` with a different Archive adapter), setup stops and asks rather than replacing it.

When done, setup makes **one git commit** ("brain: initial setup") after the user's confirmation, and reports the vault summary. The first sync (doc 05) builds its baseline
silently, so installing into an existing repo of notes causes no `create` event storm.

### Validation and repair

`/brain setup` on a complete vault, and `/brain validate`, check without changing anything unless the user approves a fix:

- Manifest and `config.yml` present and consistent with the implementation definitions on disk.
- Exactly one Archive; the Inbox exists, is an Area, and cannot be deleted; its `defaults` name implementations that exist.
- Impl ids are unique within each core type (doc 03).
- Required `.gitignore` entries present.

Fixes (for example re-creating a deleted starter definition or the Inbox) are shown as a proposal and applied only on approval. A missing or mismatched Archive adapter is
reported, never "fixed", since it is fixed at install.

## Placement: what "in the Inbox" means

Each core type has one **placement relation**, the relation that puts an item under an Area or Project (doc 01):

| Type | Placement relation | Notes |
|---|---|---|
| `Task` | `belongs_to` → Project/Area | |
| `Note` | `about` → Project/Area/Person | Only an `about` target of Project or Area counts as placement. |
| `Project` | `area` → Area | |
| `Area` | `parent` → Area | |
| `Person` | none | **Top-level** *(Decided)*: a person is not placed in any Area or Project, is never in the Inbox, and is never triaged. Its relations are named relations to any item (doc 01). |

An item is **in the Inbox** when its placement relation is absent or points at `area:inbox`. System items (the Inbox, the Archive) and archived items are never candidates.
Finding candidates uses `list` per binding of the four placed types (paged) and filters client-side, because the structural `query` can test that a relation is present but not that
it is absent (doc 03). The sync seen state (doc 05) can narrow the scan for large vaults.

## Capture

`/brain capture [--type <type>] <text>` creates a new item in the Inbox:

- The type defaults to `note`; `--type task` (and so on) overrides it. The implementation is the Inbox `defaults.<type>` (doc 01 resolution, step 3).
- The item is created with no placement relation, so it is in the Inbox. This fires `create` and `capture` (doc 05).
- **`--type person` is the exception:** a person is top-level, so it is created with the vault-wide `person` default, is not in the Inbox, fires `create` only (no `capture`), and is never offered for triage.
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

**Mapping is deterministic.** Claude is not involved in deciding what carries over:

| Part of the item | Rule |
|---|---|
| Core fields | Carried over unchanged. |
| Source fields that **also exist** in the target schema | Carried over if the value validates against the target field's type and constraints; otherwise reported as *invalid*. |
| Source fields **not in the target schema** | Reported as *unmapped*. |
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
and records a *half-converted* marker (the ref and both bindings) in `.brain/automation/pending/`-style local state; re-running triage on that item, or `/brain validate`, offers to
**finish** by retrying the source delete. It never re-creates the item.

**Events (doc 05).** A conversion is an `update` of the existing item, delivered to the **target** implementation's rules, with `changed` including `impl` and the placement relation. It
does **not** fire `create` or `capture`, since the item is not new. Added or removed relations also fire `relation` events. Rules of the source implementation see nothing; permanent delete
is not a trigger.

### Logging and commits

Each triage operation is logged like a rule run (doc 05). For the markdown adapter, triage leaves changes uncommitted and offers **one commit at the end of the session**
("brain: triage N items"). Conversions across external backends cannot be reverted with git; the proposal's diff is the user's only check, so it is always shown.

## Open questions

1. ~~Persons and placement~~ — resolved: **persons are top-level**: no Area or Project, never in the Inbox, never triaged. They can have named relations to any item (doc 01).
2. **Type inference at capture.** `capture` currently defaults to `note`. Should Claude infer the type (task vs. note) and ask for confirmation?
3. **Bulk triage.** Apply one Area/Project to several selected items in a single approval.
4. **Candidate discovery cost.** A client-side scan of four types across all bindings; do we need a structural "relation absent" query key in doc 03?
5. **Commit granularity.** One commit per session (as written), or one per converted item so each conversion can be reverted separately.
6. **Half-converted marker location.** Reuses the pending-style local state in this draft; may deserve its own file under `.brain/`.
7. **Undoing a conversion.** Triage back to the original implementation is the only path; is a dedicated "undo last triage" worth having?

## Next steps

1. Resolve the open questions above.
2. Update doc 01 (install-time setup and triage sections) to point at this doc and drop "conversion mechanics TBD"; update doc 02 to note the manifest is written by setup (already stated) and last.
3. Add the `convert` and `set_relation` operations to doc 05's operation set, and the `capture` inline offer to its triggers table.
4. Detail the per-type core fields and the built-in starter implementations (`default-*`) that setup copies.
