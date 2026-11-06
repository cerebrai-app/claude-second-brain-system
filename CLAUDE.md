# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Claude Code **plugin marketplace**: a thin JSON layer (`.claude-plugin/marketplace.json`) that points at one or more plugins, each living under `plugins/<name>/` with its own `.claude-plugin/plugin.json` manifest. There is no build system or package manager. The "code" is marketplace/plugin metadata plus whatever skills, commands, agents, or hooks each plugin defines, and the `brainctl` helper under `plugins/brain/tools/`, which has a pytest suite in `tests/`.

Currently there is a single plugin, `brain` (`plugins/brain/`), intended to become a "Second Brain System" built around Claude Code. Its design is in `docs/plans/`; its skills (`plugins/brain/skills/`) and starter implementations (`plugins/brain/starters/`) are first drafts that have not been exercised against a real vault yet.

## Architecture

- `.claude-plugin/marketplace.json` — the marketplace manifest. Lists each plugin's `name`, `source` (relative path), `description`, and `version`. Adding a new plugin means adding both the directory under `plugins/` and an entry here.
- `plugins/<plugin-name>/.claude-plugin/plugin.json` — per-plugin manifest (`name`, `description`, `version`, `author`). This is what Claude Code reads when a user runs `/plugin install <plugin-name>@<marketplace-name>`.
- `plugins/<plugin-name>/skills/` — where that plugin's skills live (one subdirectory per skill, each with a `SKILL.md`). The `brain` plugin's skills are listed in `docs/plans/10-plugin-skills.md`; they restate the design docs, so update the matching skill or `core/references/` file whenever a design doc changes. A plugin can also define `commands/`, `agents/`, or `hooks/` directories following the same convention once those are introduced.
- `plugins/brain/starters/<type>/default-<type>.md` — the built-in starter implementation definitions that `/brain setup` copies into a vault's `.brain/impls/`. Design docs for the whole system are in `docs/plans/` (see `docs/plans/09-starter-implementations.md`).
- `plugins/brain/tools/brainctl/` — the deterministic helper (a Python package) that `/brain:setup` copies into a vault's `.brain/python/brainctl/`. It implements `validate`, `sync`, `read`, `list`, `id`, `slug` and `approve-hash`, plus `adapter.py` (the script adapter base class) and `conformance.py` (the adapter conformance kit); write commands and the client side for script adapters are not built yet. Specs in `docs/plans/11-brainctl-helper.md` and `docs/plans/12-backends.md` (the `/brain:backend` skill); tests in `tests/` (pytest).
- Keep plugin and marketplace `version` fields in sync when bumping a plugin's version — the marketplace entry is not derived automatically from the plugin manifest.

## GitHub Agentic Workflows (gh-aw)

- `.github/workflows/*.md` are gh-aw workflow sources; the matching `*.lock.yml` is generated — never hand-edit a `.lock.yml`. After editing a workflow `.md`, run `gh aw compile <workflow-name>` to regenerate its lock file and commit both.
- In `.github/workflows/semver-bump-advisor.md`, the PR comment table header posted in step 6 and the retraction-path match string in step 7 must stay textually identical (each has a `sync-with-step-N` comment marking the other side) — the retraction logic finds its own prior comment by matching that exact header string, so an edit to one without the other makes retraction silently stop working instead of erroring.

## Tests

See `TESTING.md`. Quick run: `uv run --with pytest --with ruamel.yaml pytest` (or `pip install -r tests/requirements.txt && pytest`). The suite needs `git`; the one test marked `workspace` also needs `uv` and network (`-m "not workspace"` skips it).

## Installing / testing locally

Users consume this repo via:

```
/plugin marketplace add devinsba/claude-second-brain-system
/plugin install brain@claude-second-brain-system
```

To test changes locally before publishing, add the marketplace by local path instead of the GitHub slug (`/plugin marketplace add <local-path>`), then reinstall/reload the plugin to pick up changes.

There are no lint or build commands. Run the pytest suite for the helper, the skills' front matter and the starters, and validate the skills themselves by exercising the installed plugin in a Claude Code session.
