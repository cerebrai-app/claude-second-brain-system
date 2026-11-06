---
name: backend
description: Specify, build, test and change a storage backend for an implementation, that is, a script adapter that keeps items in an outside service such as Todoist, Notion, Linear, Trello or a database. Use when the user runs /brain:backend, or asks to store tasks, notes, projects, areas or people in an external service, or to change how an existing backend maps its data.
argument-hint: "[new <name> | change <name> | list] [--type task|note|project|area|person]"
---

# /brain:backend

Read the `core` and `python` skills first, and `../core/references/storage.md` (script adapters). Details you will need are in this skill's references:

- [references/adapter-protocol.md](references/adapter-protocol.md): the request/response protocol, operations, error mapping, the `BrainAdapter` base class and the conformance kit.
- [references/spec-template.md](references/spec-template.md): the backend spec you write with the user.
- [references/adapter-template.py](references/adapter-template.py): a complete working adapter to copy (its "backend" is a JSON file).
- [references/test-template.py](references/test-template.py): the pytest file to copy for the adapter's tests.

A **backend** is a script in `.brain/python/scripts/` that subclasses `brainctl.adapter.BrainAdapter`, speaks the script adapter protocol, and is bound to one implementation through `storage: {adapter: script, command: python:<name>}`. This skill takes it from an idea to a tested, approved, bound backend, in phases. **Each phase ends with a checkpoint where the user approves before you continue.**

## Ground rules
- **Spec before code.** Write the backend spec and get it approved before writing the adapter.
- **No secrets, ever.** Credentials are environment variables the script reads, declared in `requires_env` in the registry and in `describe`. Never ask the user to paste a token into chat, never write one to a file, the spec, a test or a log, and never print one. Tell the user which variables to set in their shell.
- **Nothing touches the user's real account without approval.** Build and test against a fake client first. Real calls start read-only, and anything that creates, changes or deletes happens only in a sandbox area the user names, with approval, and is cleaned up.
- **Deterministic code.** The adapter makes no model calls, no network call at import time, and sets a timeout on every request (at most the binding's `timeout_seconds`).
- **Fit the contract.** Ids are plugin-assigned ULIDs; revisions are opaque and checked on update; update is a full replace; tags are a name-to-string map; the adapter never invents data. Raise the adapter errors, do not return error shapes by hand.
- **Do not change defaults or move items.** Binding a new implementation does not make it the default for its type and does not migrate existing items. That is the user's decision, made later (`defaults` on the Inbox, an Area or a Project; conversion in triage).
- **Honest limits.** `brainctl list`, `read`, `sync` and `validate` read script bindings (the script must be registered and approved, and its `requires_env` set). `brainctl` has no write commands yet, so call writes through `brainctl adapter <impl> <op> --args '<json>'`. A binding that cannot be read is reported as incomplete, not empty. A backend is verified by its conformance tests first, then by `brainctl adapter` against the sandbox. Say so to the user.
- **Current helper.** The backend work needs `adapter.py`, `conformance.py` and `client.py` in the vault's `.brain/python/brainctl/`. If any is missing, tell the user and suggest `/brain:upgrade` (it copies only the changed files); do not copy them by hand.

## `list`
Show every implementation with `adapter: script`: name, type, command, whether `.brain/backends/<impl>.md` exists, whether `.brain/python/tests/test_<name>.py` exists, and the script's approval state (`brainctl validate` reports `script-unapproved`, `script-changed`, `backend-spec-missing`). Offer `new` or `change`.

## `new <name>`

### 1. Discover
Ask a few questions at a time, not all at once. Use the service's official API documentation (search or fetch it) rather than memory for auth, endpoints, pagination, rate limits and what the service calls its fields. Establish:
1. **Core type** the backend stores (`task`, `note`, `project`, `area` or `person`) and the **implementation name** (an id like `todoist-task`; unique within the type; `person` allows only one active implementation, so a new one is a `migration_target`).
2. **Service and client:** which service, its official SDK (name, version) or plain HTTP, and the API version.
3. **Auth:** method and the **environment variable names** (never values). Scopes needed.
4. **Source of truth and scope:** which workspace, project, database or list; the `settings` the binding needs (ids and names, not secrets).
5. **Field mapping:** how each core field maps (`title`, `status`, `tags`, body, `due` and other service fields as implementation schema fields with a type from the vocabulary).
6. **Status mapping:** the service's states to the core `open`, `done`, `dropped`, and any custom `status_values` that map to them.
7. **Relations:** which relations the service can express (parent/project, assignee, dependency, links) and how; the rest are unsupported and must be said so.
8. **Tags:** native key/value (`tags: "map"`) or labels only (`tags: "labels"`; then name a side field for the values as `storage.tag_values_field`).
9. **Ids:** can the service hold the plugin id (custom field, description marker)? If not, the id index is used and `native_ids` is true.
10. **Operations:** read-only or read-write; hard delete or none (`hard_delete`); revision source (etag, version, updated timestamp; if there is no compare-and-set, say update is best effort).
11. **Query pushdown:** which structural query keys the service can filter natively; the rest are filtered by the caller.
12. **Limits:** page size (`max_page`), rate limits, anything that errors in surprising ways.
13. **Archive:** whether this backend could ever be the vault's Archive adapter (almost never; say no unless it meets every requirement in the storage reference).

### 2. Specify (checkpoint: user approves the spec)
Copy [references/spec-template.md](references/spec-template.md) to `.brain/backends/<impl>.md`, fill every section from the discovery, list open questions, and show the user a short summary of the decisions that matter (the mapping tables, capabilities, ids, limits). **Do not continue until the user says the spec is approved.** Offer a commit.

### 3. Build
1. **Dependencies:** add the SDK (and `pytest` as a dev dependency) through the `python` skill's approved dependency flow. Remember that changing `pyproject.toml` invalidates every script's approval.
2. **Script:** copy [references/adapter-template.py](references/adapter-template.py) to `.brain/python/scripts/<name>.py`. Keep three layers separate: a thin **client** for the service (the only code that does I/O, injectable), **pure mapping functions** between service objects and envelopes (`to_envelope`, `from_envelope`, status and tag mapping), and the **adapter class** that wires them to the operations. Implement exactly the operations the spec says, in this order: `describe`, `read`, `list`, `resolve`, then `create`, `update`, `delete`.
3. **Errors:** map the service's failures with the table in the protocol reference (401 and 403 to `Unauthorized`, 404 to `NotFound`, 409 and 412 to `Conflict`, 400 and 422 to `Invalid`, 429 to `RateLimited` with `retry_after`, 5xx and timeouts to `Unavailable`).
4. **Declare capabilities truthfully** as class attributes (`tags`, `supports_body`, `preserves_unknown_fields`, `query`, `max_page`, `hard_delete`, `native_ids`, `requires_env`). A capability you cannot honor must be false.

### 4. Test (checkpoint: show the results)
1. Copy [references/test-template.py](references/test-template.py) to `.brain/python/tests/test_<name>.py`. Write a **fake client** that behaves like the service (including its limits and its errors), and run `brainctl.conformance` against the adapter wired to it. Add tests for the mapping functions (every status, relation, tag and body case in the spec).
2. Run the tests through the workspace tool (`<tool> run pytest .brain/python/tests/test_<name>.py`). **All conformance checks must pass.** Show the user the output; fix the adapter, not the kit.
3. Register the script in `registry.yml` (`name`, `path`, `description`, `requires_env`, `timeout`, `created_by`) and run the approval flow from the `python` skill (show the script, then record the hash).

### 5. Bind (checkpoint: user approves the definition)
Write `.brain/impls/<type>/<impl>.md`: `impl`, `extends`, `version: 1`, `schema.fields` for service-specific data, `status_values`, `storage: {adapter: script, command: "python:<name>", settings: {...}, timeout_seconds: 30}` (and `tag_values_field` when `tags` is `labels`), plus any sorts and filters the user asked for. Add it to the manifest index. Run `brainctl validate`: it must report no errors (a missing spec or an unregistered command is an error or warning there). Do **not** change any `defaults`, do not make it the default for its type, and do not move items.

### 6. Verify against the real service (optional; only with approval)
Only if the user wants it. Ask them to set the environment variables themselves. Confirm a **sandbox** area (a throwaway project or database) and what will be created there. Start read-only by calling the script directly:

```
echo '{"protocol":1,"op":"describe","settings":{...},"args":{}}' | <tool> run python .brain/python/scripts/<name>.py
echo '{"protocol":1,"op":"list","settings":{...},"args":{"query":{},"limit":3}}' | <tool> run python .brain/python/scripts/<name>.py
```

Then, with explicit approval and only in the sandbox, run the conformance kit against the real adapter (`brainctl.conformance.check` with a factory that points at the sandbox) and clean up everything it created. Never run `delete` against anything but items you created in the sandbox. Report results, including anything the real service did differently from the fake client, and update the spec and the fake.

## `change <name>`
1. Read the spec, the script, its tests and the implementation definition. State the change in terms of the spec.
2. **Update the spec first** and get approval, then the code, then the tests. Run the whole test file.
3. A change that alters how stored data maps (field or status mapping, id strategy, `tag_values_field`, `path`-like settings) is a **schema change**: bump the implementation `version`, add a migration note at `.brain/impls/<type>/<impl>.migrations/<from>-to-<to>.md`, and tell the user items already stored will need migrating. Do not change the id strategy of a backend that holds items without a migration plan.
4. Re-approve the script (its hash changed) and run `brainctl validate`.

## Done when
The spec is approved and committed; the adapter, its fake client and its tests exist; every conformance check passes; the script is registered and approved at its current hash; the implementation definition validates; credentials appear nowhere in the repo; and the user knows the current limits (sync and validate do not read script bindings yet; nothing has been made the default).
