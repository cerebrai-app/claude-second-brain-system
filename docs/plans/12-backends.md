# 12 — Backends: Specifying and Building New Implementations

Status: **Draft** · Depends on: [03 — Storage Contract](03-storage-contract.md), [07 — Python Workspace](07-python-workspace.md), [11 — brainctl](11-brainctl-helper.md) · Skill: `/brain:backend` ([10](10-plugin-skills.md))

## Goal

A vault's items can live in an outside service (Todoist, Notion, Linear, a database, anything with an API). A **backend** is the script adapter that makes one service look like a storage binding for one implementation (doc 03). This doc defines how a new backend is *specified*, *built*, *tested* and *changed*, and the tools that support it. The user decides the service; nothing here is specific to any one.

## The pieces

| Piece | Where | Owned by |
|---|---|---|
| **Backend spec** | `.brain/backends/<impl>.md` (committed) | the vault; written with the user before any code |
| **Adapter script** | `.brain/python/scripts/<name>.py`, registered and approved (doc 07) | the vault |
| **Tests** | `.brain/python/tests/test_<name>.py` | the vault |
| **Implementation definition** | `.brain/impls/<type>/<impl>.md` with `storage: {adapter: script, command: python:<name>, settings, timeout_seconds}` | the vault |
| **`brainctl.adapter`** | `BrainAdapter` base class, error classes, helpers | the plugin (copied with `brainctl`) |
| **`brainctl.conformance`** | the conformance kit | the plugin |
| **Templates and protocol reference** | `plugins/brain/skills/backend/references/` | the plugin |

## Workflow (the `/brain:backend` skill)

1. **Discover** the service, auth, mapping, ids, capabilities and limits with the user, from the service's own documentation.
2. **Specify** in `.brain/backends/<impl>.md` (template in the skill). **Checkpoint: the user approves the spec before any code.**
3. **Build**: add the SDK through the approved dependency flow; write the script in three layers (an injectable client, pure mapping functions, the adapter class); declare capabilities truthfully.
4. **Test**: a fake client plus the conformance kit plus mapping tests; all checks pass; register and approve the script. **Checkpoint: the user sees the results.**
5. **Bind**: write the implementation definition; `brainctl validate` has no errors. **The new implementation is never made a default and no item is moved.**
6. **Verify against the real service** (optional): read-only first, then only in a user-named sandbox, with approval and cleanup.
7. **Change** an existing backend: spec first, then code, then tests; a mapping or id-strategy change is a schema change (bump `version`, add a migration note) and the script is re-approved.

Rules that hold throughout: no secrets in the repo, spec, registry, tests or chat (credentials are environment variables listed in `requires_env`); no model calls and no import-time network in the adapter; a timeout on every request; nothing touches the real account without approval.

## `brainctl.adapter`

`BrainAdapter` implements the process boundary of doc 03: it reads one JSON request from stdin, dispatches to the method for the operation, maps `AdapterError` subclasses to the documented error codes (anything else becomes `internal` with the traceback on stderr), and writes one JSON response. It supplies `describe` from class attributes, a default `resolve`, argument checking (a missing required argument is `invalid`, unknown arguments are ignored for forward compatibility), and helpers (`envelope`, `paginate`, `matches_query`, `split_ref`, `self.env`, `self.setting`). It replaces the planned `lib/brain_adapter.py` (docs 06 and 07): living in `brainctl`, it does not change a script's approval hash.

`archive` and `unarchive` are optional on an adapter: the plugin archives by creating the item in the Archive adapter and deleting it from the source binding (doc 03), so a backend needs `delete` (or must declare `hard_delete: false` and be non-archivable).

## `brainctl.conformance`

A fresh adapter on an empty sandbox is driven through the same JSON path as the real process. About twenty checks cover the contract (see the protocol reference in the skill for the list). The kit is the definition of "this adapter honors doc 03"; a backend is not bound until it passes. Each check was written with a deliberately broken adapter that it must catch (stale revisions ignored, tags dropped, pages that drop items, missing `not_found`, delete without confirmation, crashes, bad `describe`), and `tests/test_adapter.py` keeps that proof.

## Client

`brainctl/client.py` runs a registered script once per operation, as the contract in docs 03 and 07 describes:

- The script must be in `registry.yml` and approved for its current hash; otherwise the call fails with `unauthorized` and nothing runs.
- A scrubbed environment: a minimal base plus only the script's `requires_env`. `PYTHONPATH` is the workspace, so `brainctl.adapter` and `lib/` import. The interpreter is the one running `brainctl` (override with `BRAINCTL_PYTHON`, for example the workspace venv's).
- A timeout per call (`storage.timeout_seconds`, else the registry `timeout`, else 30 seconds); a timeout is `unavailable`.
- `rate_limited` is retried once after a minute; a second one in a row fails.
- `list` is followed through every cursor.

`brainctl list`, `read`, `sync` and `validate` read script bindings through it. A binding that cannot be read (unregistered, unapproved, failing, timed out) is reported as **incomplete**, never as empty: `sync` does not report its items as missing and leaves its seen state alone. `brainctl adapter <impl> <op> --args '<json>'` makes one call, for testing and for skills.

`validate` also asks each approved adapter to `describe` itself and compares it with the binding: `adapter-describe` (fails), `adapter-env-missing` (warning), `adapter-protocol`, `adapter-tags` (labels without `tag_values_field`), `adapter-traits` (person on an adapter without trait support), `adapter-body` and `adapter-fields` (warnings).

## Validation additions

`brainctl validate` now checks script implementations: `command` is present and, for `python:<name>`, registered in the workspace registry (`command-unregistered`, an error); `timeout_seconds` is a positive integer; and a backend spec exists at `.brain/backends/<impl>.md` (`backend-spec-missing`, a warning).

## Current limitations

- **Reads only.** `brainctl` calls script adapters for `list`, `read`, `sync` and `validate` (see Client below) and, for testing, any operation through `brainctl adapter`. Its write commands (`create`, `update`, `archive`, ...) do not exist yet, so the plugin's own writes to a backend are still done by skills calling `brainctl adapter <impl> <op>`; id-index maintenance for `native_ids` backends is part of those write commands and is not built.
- Real-service verification is manual and by direct invocation (the skill describes it).
- The Archive adapter must be markdown for now; a script adapter as the Archive adapter is unsupported until the client side and the `archive_adapter` requirements are exercised.

## Open questions

1. Webhooks or change feeds as an alternative to scanning for `sync` (docs/plans/05 assumes scanning).
2. A shared library of mapping helpers (status maps, tag-label recombination) so each backend does not rewrite them.
3. Whether the conformance kit should also run a recorded-response replay mode for services that cannot be faked easily.
4. Secrets: keep to environment variables, or add a documented hook for a user's secret store.

## Next steps

1. Write commands in `brainctl` (`create`, `update`, `archive`, `unarchive`, `delete`, `convert`), including id-index maintenance for `native_ids` backends.
2. Try the skill end to end on a real service in a sandbox (we have none yet) and fold the findings into the skill and templates.
3. Decide open question 2 once two real backends exist.
