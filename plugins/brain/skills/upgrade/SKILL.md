---
name: upgrade
description: Update the vault's installed copy of the brainctl helper to the version shipped with the plugin, copying only the files that changed. Use when the user runs /brain:upgrade, or when a skill finds the vault's brainctl is older than the plugin's.
disable-model-invocation: true
---

# /brain:upgrade

Read the `core` skill first. The vault pins its own copy of `brainctl` at `.brain/python/brainctl/` (doc 11); this skill refreshes that copy from the plugin install. It does nothing else: no migrations, no changes to items, scripts or the registry.

1. **Preview.** Run `python3 <this skill's directory>/upgrade.py --vault <vault root> --dry-run` (standard library only; it finds the plugin's `tools/brainctl/` relative to itself). It prints JSON with the `from` and `to` versions and the `added`, `changed` and `not_shipped` files. If nothing is added or changed, say the helper is already current and stop.
2. **Show and copy.** Tell the user the versions and list the added and changed files, then run the same command without `--dry-run`. It copies only those files, never touches `test_*.py` or caches, and records `helper_version` in `.brain/manifest.yml`. Files in `not_shipped` are left where they are; mention them, since a file the plugin dropped may be dead code.
3. **Check.** Run `brainctl validate` through the workspace tool (see "Running `brainctl`" in the `core` skill) and report the result. If the vault's seen state or items look affected, run `brainctl sync --refresh` only if the user asks.
4. **Commit.** Offer to commit the change as one commit ("Upgrade brainctl to <version>"). The helper is plugin code, so it is not part of any script's approval hash and nothing needs re-approval.

`brainctl` and every workspace script run only in the workspace virtualenv (`.brain/python/.venv`). If it is missing, sync the workspace first (the `python` skill) and then upgrade.
