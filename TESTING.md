# Testing

How the plugin is tested today, and how to reproduce each step. There are two layers: an automated **pytest suite** (seconds) for the `brainctl` helper, the skills' front matter and the starters, and a **manual rehearsal** on a scratch vault, because the skills are instructions that Claude follows and cannot be unit tested.

**Status.** The suite covers the helper's `validate` and `sync` (markdown adapter and the Archive directory), ids and slugs, field types, scanning, the approval hash and the command line. Nothing has been run through the *installed* plugin (`/brain:*`) yet; the rehearsal so far followed the skills by hand and used `brainctl` where it exists. Findings are recorded in `docs/plans/10-plugin-skills.md`.

## Prerequisites

| Need | For | Check |
|---|---|---|
| Python 3.12 or newer | everything | `python3 --version` |
| `git` | the scratch vaults the tests build | `git --version` |
| `pytest` and `ruamel.yaml` | the suite | see below |
| `uv` (optional) | the `workspace` test and the manual rehearsal | `uv --version`; needs network for `uv lock` |

## Running the suite

```bash
uv run --with pytest --with ruamel.yaml pytest                 # no install step: uv builds a throwaway environment
```

or, with a virtual environment of your own:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r tests/requirements.txt
pytest
```

Useful variations:

```bash
pytest -m "not workspace"             # skip the one test that builds a real uv workspace (needs uv and network)
pytest tests/test_validate.py -k cycle
pytest -x -q                          # stop at the first failure, quiet
```

Expect all tests to pass (about 250, a few seconds). `pytest.ini` sets `testpaths = tests` and registers the `workspace` marker. The helper is imported from `plugins/brain/tools/` by `tests/conftest.py`, so nothing needs installing.

## What is covered

| File | Covers |
|---|---|
| `tests/test_ids.py` | ULID shape, ordering and monotonicity; slug rules (lowercase, Unicode kept, punctuation collapsed, `untitled`, truncation at 60); **zero-padded collision suffixes** (`-02` ... `-13`) sorting alphabetically; the `ids.py` command line. |
| `tests/test_schema.py` | The field type vocabulary (`string`, `text`, `integer`, `number`, `boolean`, `date`, `datetime`, `enum`, `list`) and constraints (`min`/`max`, lengths, `pattern`, `values`, `required`, `default`): valid and invalid values and definitions. |
| `tests/test_model.py` | Path templates (`{slug}`, `{field:%Y-%m-%d}`, sanitizing), the git blob hash, front matter parsing, `display_name`, **scanning** (unadopted, unparseable, wrong-directory, ambiguous, archived, script bindings), vault discovery, and writing ambiguous YAML scalars safely (`2026-11-06`, `yes`). |
| `tests/test_validate.py` | One test per `brainctl validate` check: vault files and manifest, definitions, traits, items (required fields, status and `completed`, tags, person names, defaults), relations (targets, cardinality, dangling, archived, cycles), duplicates across bindings, half-converted markers, **ignored paths** (the `lib/` bug), the Python workspace and script approval states, and automation (schedule, pinned sorts, undefined filters, `place`, vault rule `requires`). |
| `tests/test_sync.py` | The silent baseline, quiet second sync, `create`/`capture` rules (areas and persons never fire `capture`), `update` with `changed`, relation events, missing items, archive/unarchive, **conversion as one update with `impl` changed**, an interrupted conversion, **adoption** of hand-written files (additive, keeps name, body and key order; fills status and defaults; refuses invalid or ambiguous files), invalid external changes held back until fixed, `--dry-run`, `--refresh`, and script bindings reported incomplete. |
| `tests/test_cli.py` | Exit codes (0 clean, 1 findings, 2 usage), JSON and `--text` output, `list`, `read`, `id`, `slug`, `approve-hash`, `approve` (one script, `--all`, comments kept, `--by` required), and the **installed layout**: a copy of the package in `.brain/python/brainctl/` run as `python -m brainctl` from `.brain/python`, as the skills do. |
| `tests/test_adapter.py` | `BrainAdapter` (dispatch, error mapping, missing arguments are `invalid`, unknown arguments ignored, `main()` as a real process), its helpers, **the reference adapter passing the conformance kit**, and the kit **catching deliberately broken adapters** (ignored revisions, lost tags, listing that drops items, missing `not_found`, delete without confirmation, crashes, bad `describe`, non-JSON results). |
| `tests/test_client.py` | The script adapter client with real subprocesses: approval states, the scrubbed environment, timeout, garbage output, the single `rate_limited` retry, cursors; then `list`, `read`, `adapter`, `sync` (events from a backend, an unreadable binding is never "missing") and the `describe` checks in `validate`. |
| (in `test_sync.py`, `test_validate.py`, `test_cli.py`) | Completing identity fields of items that have an id (only the missing identity keys, no defaults, a quiet second sync, `--no-adopt`/`--dry-run` report `incomplete_identity`); `unless_exists` shape checks; the several-tags warning; `brainctl find` (impl, dotted fields, archived, exit codes). |
| `tests/test_upgrade.py` | `/brain:upgrade`'s script: only new and changed files are copied (an unchanged file is not rewritten), `--dry-run`, files the plugin no longer ships are left alone, tests and caches are never copied, `helper_version` is recorded once without touching the rest of the manifest; and the `brainctl` environment guard (an installed copy refuses a non-workspace interpreter). |
| `tests/test_approval.py` | The approval hash recipe (sorted paths, `path NUL bytes NUL`), and that the script, `lib/**/*.py` and `pyproject.toml` change it while other files do not. |
| (in `test_sync.py`, `test_validate.py`) | Stable sync event ids (same change, same id); the automation log vocabulary (`log-outcome`, `log-line`). |
| `tests/test_store.py` | The deterministic writes: create (id, slug, defaults cascade, status, tags, rollback and no stray directories), update (only the changed lines, comments kept, `completed`, moves, conflict, forbidden keys), archive and unarchive, delete, convert (plan, resolutions, unmapped fields, a failed source delete and `finish`), rule operations, the pending queue (fresh, stale, expired, apply, reject) and the log. Every write is followed by an empty `sync` event list. |
| `tests/test_templates.py` | Template resolution: `today` in the configured time zone, `now`, filters (`checklist`, `bullets`, `refs`, `table`), errors for unknown names, nested `--json` resolution, `brainctl render`, and the `validate` checks (`rule-template`, `config-timezone`, a misnamed vault rules list). |
| `tests/test_static.py` | Skill front matter is valid YAML (a colon in an unquoted description once broke one), names match directories, the right skills are user-only, starters hold **only** the `slug` field and file storage semantics with a `{slug}` path, referenced files exist. |
| `tests/test_scenario.py` | The mechanical rehearsal end to end: the Python-template `.gitignore` bug and its negation fix; slugs, collisions and a date-named journal note; capture, triage placements, a conversion with a half-converted marker, hand-written file adoption and sync. The `workspace` test builds a real `uv` workspace and runs a script with a scrubbed environment. |

### Writing a test

`tests/conftest.py` provides a `b` fixture: a **clean, valid scratch vault** (git repo, five starters, config, Inbox, manifest, workspace files) and a builder to change it:

```python
def test_example(b):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], required: true }\n", path="tasks/gtd/{slug}.md")
    i, slug = b.item("task", "gtd", "tasks/gtd", "Draft Q4 plan", "status: open\n")     # ULID id, unique zero-padded slug
    b.add_front(f"tasks/gtd/{slug}.md", "context: work\n")                               # an edit the plugin would make
    assert validate.validate(b.vault()) == []
```

Build the vault state, run the helper, assert on findings, events or files. Prefer the smallest vault that shows the behaviour.

## Manual rehearsal on a scratch vault

This is what exercises the skills. Use a throwaway branch of a scratch repo (we used `devinsba/second-brain`, branch `claude/admiring-rubin-4sq9mk`, which starts with only a README and a Python `.gitignore`, a useful trap).

**How to run it**
- Install the plugin from a local checkout (`/plugin marketplace add <path to this repo>`, then `/plugin install brain@claude-second-brain-system`), start Claude Code **in the scratch repo**, and use the `/brain:*` commands. Until that works in your session, follow each `SKILL.md` by hand, exactly as written, and note every place the text was unclear or wrong.
- Use the helper wherever it exists. From `.brain/python`: `uv run --frozen python -m brainctl validate --text` and `... sync --text`. After a hand edit of an item file, run `... sync --refresh` so your own write is not reported as an outside change.
- **Headless**: `CLAUDE_CONFIG_DIR=<isolated dir> claude -p "/brain:setup" --permission-mode acceptEdits --allowedTools "Bash,Read,Write,Edit,Glob,Grep"` in the scratch repo, then `claude -p -c "go" ...` to answer its confirmation. Give later prompts the approvals in advance ("I approve all of these") or a `-p` run stops to ask. Add `< /dev/null` when scripting. Reinstall the plugin first (`claude plugin marketplace update`, `uninstall`, `install`) because the version is still `0.0.1`, so a stale cache is easy to miss.
- Keep a findings list as you go: what you did and what happened, not what you expected. Move findings to `docs/plans/10-plugin-skills.md` afterwards.

| # | Step | Expect |
|---|---|---|
| 1 | `/brain:setup`. Check preflight (Python 3.12+, tool detected), the summary, and the one confirmation. | Files created in order: `config.yml`, five `default-*` impls, Inbox (`areas/inbox.md`), the Python workspace (with `brainctl/` and `ruamel.yaml` locked), `.gitignore` lines, `manifest.yml` **last**. `brainctl validate` reports 0 errors. One commit "brain: initial setup". `git check-ignore -v .brain/python/lib/x.py` prints nothing. Re-running setup reports a complete vault and changes nothing. |
| 2 | `/brain:capture` a note, a task (`--type task`), a person (`--type person --trait colleague`, after defining the trait), an area (`--type area`), a project (`--type project`). Capture the same note title twice. | Files named by slug: `notes/<slug>.md`; the repeat is `<slug>-02.md`. Notes, tasks and projects fire `capture`; the area and person do not and are not offered triage. Person `name` is structured; trait fields are nested under the trait name. `validate` stays clean. |
| 3 | Add a second task implementation, `gtd-task`, with a required enum `context`, `priority` default `med`, path `tasks/gtd/{slug}.md`; set the project's `defaults.task: gtd-task`. | `validate` accepts it; the manifest lists it after the next write. |
| 4 | `/brain:triage`. Place the project under an area, the note under the project, the task under the project. | Areas never appear as candidates. The note and project are plain updates. The task triggers a conversion with a report: `context` **missing** (you fill it), `priority` **filled by default**. The user sees the final diff and approves. |
| 5 | Repeat step 4's conversion but make the source delete fail (or stop after the create). Run `brainctl validate`. | A marker in `.brain/conversions/`; the duplicate ref is an **error**. Finishing clears both. |
| 6 | `brainctl sync` right after setup, then hand-edit a note, add a note by hand in the editor **with an id and a slug**, and add one **without** frontmatter (sync completes the missing slug and lists it under `completed`). Sync again. | First sync: silent baseline. Edit a title with the exact quoting it has in the file. Then `update`, `create`+`capture`, and the id-less file adopted (name and body unchanged, listed under `adopted`). Your own writes from steps 1 to 5 do **not** show as external if you refreshed after each. |
| 7 | Add a `capture` rule with a `claude` action to the note implementation (one tag key per tag: a map holds one value per key), then add a hand-written note and sync. | A pending entry is written, not a prompt. `/brain:pending` re-checks staleness, shows the diff, applies on approval, and removes the file. `updated` is refreshed. |
| 8 | Define a `journal` note implementation (path `journal/{slug}.md`, with the date as the slug; a path with neither `{slug}` nor `{id}` is rejected) and a vault rule with `requires: [note/journal]`, a `create_item` (`title: "{{ today }}"`, resolved by `brainctl render`) with `unless_exists: { type: note, impl: journal, where: { title: "{{ today }}" } }`, and `place: { find: { type: area, where: { title: Journals } }, create_if_missing: true }`. Run `/brain:run vault/<id>` twice. | A date-named file placed under the `Journals` area (so **not** a triage candidate); the second run changes nothing, because `brainctl find` finds today's note and the action is skipped (`skipped: exists`). `validate` has no `rule-unplaced` warning. |
| 9 | `/brain:python`: write a small script, register it, approve it, run it with `requires_env: []`. Change `pyproject.toml`. | `brainctl approve-hash` gives the hash and `brainctl approve` records it; `validate` reports `script-changed` after the change; `approve --all` re-approves after showing the diff once. |
| 10 | `brainctl validate` on the finished vault; commit and push the branch. | 0 errors and 0 warnings. |

**Reset**: delete the scratch branch or add a commit that removes the vault (we did the latter to keep history). Nothing outside the scratch repo is touched.

## When to update the tests

- Changing a design doc: change the matching skill or `core/references/` file, and the test that covers it. The suite mirrors the rules in docs 03, 05, 06, 08 and 11.
- A new finding in the manual rehearsal: reproduce it as a failing pytest first if it is mechanical, then fix it.
- Adding a `brainctl` command (`create`, `update`, `archive`, `convert`, ...): add its tests to the same files above, and extend `test_cli.py` for its exit codes.

## Known gaps

- No automated test drives Claude or the `/brain:*` commands; the manual rehearsal is the only coverage of the skills.
- The `convert` mapping rules and write commands are not implemented in `brainctl`, so they are not covered. Script adapters are covered only against the reference adapter and fake scripts, never a real service.
- Sorting caveat found while testing slugs: byte-wise sorting of whole file names puts `a.md` **after** `a-02.md` (`-` sorts before `.`). Sorting by stem, or most locale-aware listings, puts the unsuffixed name first. If that matters, the suffix separator is the thing to change.
- The suite builds its own scratch vaults; it does not read the real `second-brain` repo. Run `brainctl validate` there (see the rehearsal) as a smoke test.
