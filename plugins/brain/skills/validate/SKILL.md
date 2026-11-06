---
name: validate
description: Check the vault for problems (manifest, config, implementations, dangling references, invalid items, leftover half-converted markers, Python workspace approvals) and offer fixes. Use when the user runs /brain:validate or asks whether their vault is healthy.
---

# /brain:validate

Read the `core` skill first.

**Run the helper.** From `.brain/python`: `<tool> run python -m brainctl validate` (see "Running `brainctl`" in the `core` skill). It returns JSON `{ok, errors, warnings, findings[]}`; each finding has `severity`, `code`, `subject` and `message`, and exit code 1 means at least one error. Report the findings grouped by subject, errors first, in plain words. **Do not re-derive the checks by hand.** The helper is read-only; propose fixes and apply them only after approval, then validate again.

## What the helper checks (so you know what a clean result means)

- **Vault:** `.brain/manifest.yml` and `config.yml` present and consistent with the definitions on disk; manifest `core_version` vs the plugin's (report if behind; migrating needs an explicit command).
- **Archive and Inbox:** exactly one Archive; the Inbox exists, is an Area, `system: true`, and its `defaults` name implementations that exist (never `person`).
- **Implementations:** impl ids unique within each type; exactly one **active** `person` implementation plus at most one `migration_target`; status value mappings valid; reserved names not used; every adapter can honor its binding (`supports_body`, `supports_traits`, `tags`).
- **Items:** required fields, types and constraints, relation targets and cardinality, `Area.parent` cycles (error), `Task.blocked_by` cycles (warning), `completed` consistent with status category, tags normalized.
- **Duplicates:** the same ref present in two bindings (a half-converted item) is an error.
- **Unadopted files:** markdown files in a binding's directory without `id`/`type`/`impl` are reported (sync adopts them).
- **References:** dangling refs are reported, never dropped; relations to archived items are warnings.
- **Conversions:** any file in `.brain/conversions/` is a half-converted item; offer to finish the source delete.
- **Automation:** vault rules whose `requires` cannot be satisfied are *blocked*; so is any rule that names a filter or sort its implementation does not define; rules using `schedule` are invalid; a rule that creates a `task`, `note` or `project` without `place` is a warning.
- **Gitignore:** the required entries are present, and every path that must be committed (`.brain/python/lib/`, `.brain/id-index/`, items) is **not** ignored. Check with `git check-ignore -v`; fix an ignored path with a negation line (for example `!.brain/python/lib/`).
- **Python workspace (required):** `pyproject.toml` and the lock file present and consistent; every registered script exists and is approved at its current hash (`changed since approval` or `never approved` otherwise).

Fixes (re-create a deleted starter or the Inbox, finish a conversion, add gitignore lines) are shown as a proposal. A missing or mismatched Archive adapter is reported, never "fixed", since it is fixed at install.
