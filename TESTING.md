# Testing

How the plugin is tested today, and how to reproduce each step. There are four layers. The first three are automated and run in seconds; the fourth is a manual rehearsal on a scratch vault, because the skills are instructions that Claude follows and cannot be unit tested.

**Status.** Nothing has been run through the installed plugin (`/brain:*`) yet. The rehearsal so far followed the skills by hand, with `tests/rehearsal/brainsim.py` standing in for the unwritten `brainctl` helper (`docs/plans/11-brainctl-helper.md`). Findings are recorded in `docs/plans/10-plugin-skills.md`.

## Prerequisites

| Need | For | Check |
|---|---|---|
| Python 3.12 or newer | everything | `python3 --version` |
| `git` | the scratch vault | `git --version` |
| PyYAML | static checks, `brainsim.py` | `python3 -c "import yaml"`; install with `python3 -m pip install pyyaml` (or run scripts as `uv run --with pyyaml python3 ...`) |
| `uv` (optional) | the Python workspace checks | `uv --version`; needs network for `uv lock` |

## 1. Unit tests: ids and slugs

```bash
cd plugins/brain/tools/brainctl
python3 -m unittest -v test_ids
```

Expect `OK` (15 tests). Run it **without** `-I`: isolated mode removes the working directory from `sys.path`, so `import ids` would fail. The tests cover ULID shape, ordering and monotonicity, and slug rules: lowercase, Unicode kept, punctuation collapsed, empty becomes `untitled`, truncation at 60, and zero-padded collision suffixes (`-02` ... `-10`).

Manual spot checks of the CLI:

```bash
python3 -I plugins/brain/tools/brainctl/ids.py ulid -n 3
python3 -I plugins/brain/tools/brainctl/ids.py slug "Draft Q4 plan" --taken draft-q4-plan     # draft-q4-plan-02
python3 -I plugins/brain/tools/brainctl/ids.py slug "2026-11-06"                                # 2026-11-06
```

## 2. Static checks: skills and starters

```bash
python3 tests/check_static.py
```

Expect `static checks passed`. It verifies that every `SKILL.md` has valid YAML frontmatter (a colon inside an unquoted `description` once broke one), that `name` equals the directory, that a description exists, and that every starter holds **only** file storage semantics (`impl`, `extends`, `version`, `storage`) with the markdown adapter and a `{slug}` path (`docs/plans/09-starter-implementations.md`).

## 3. Scripted scenario: the mechanical rehearsal

```bash
python3 tests/rehearsal/scenario.py                  # temporary vault, deleted afterwards
python3 tests/rehearsal/scenario.py --workspace      # also builds the uv workspace (needs uv and network)
python3 tests/rehearsal/scenario.py --keep           # keep the temporary vault to inspect it
python3 tests/rehearsal/scenario.py --vault /tmp/v   # use a specific new directory
```

Expect `19/19 checks passed` with `--workspace` (17 without). It builds a fresh git repo, copies the starters, writes the config, Inbox and manifest, then asserts:

| Area | Check |
|---|---|
| Ignore rules | A Python-template `.gitignore` ignores `.brain/python/lib/`; a negation line fixes it (the first-rehearsal bug). |
| Workspace (`--workspace`) | `uv init --bare`, `lock`, `sync --frozen`, and a script run with a scrubbed environment (`env -i`). |
| Sync baseline | The first sync builds a baseline and emits no events. |
| Slugs | Human-readable names; collisions get zero-padded suffixes that sort alphabetically by stem through `-11`; a date title gives a date file name. |
| Events | New items give `create`; tasks, notes and projects also give `capture`; **areas do not** (they are top-level). |
| Adoption | A hand-written file with no id is adopted (id, type, impl, slug from the file name, created, updated, title from the heading), keeps its name and body, and gives `create` and `capture`. A second sync is quiet. |
| Conversion | An item present in two bindings is a `validate` error; a half-converted marker is reported; finishing clears them; sync sees the conversion as **one `update` with the impl changed**, not a create plus a missing item. |
| Approval hash (`--workspace`) | The hash changes when `pyproject.toml` changes. |

Exit code is non-zero on any failure, so it can run in CI. The scenario creates files the way the skills describe (ULID from `ids.py`, unique slug, frontmatter); it does not exercise Claude.

`brainsim.py` is a **stand-in** for `brainctl`. It handles the markdown adapter only and covers listing across bindings (keyed by ref and binding), `validate`, `sync` (ref-level matching, adoption, seen state). When the real helper exists, point the scenario at it and delete the stand-in.

## 4. Manual rehearsal on a scratch vault

This is what exercises the skills. Use a throwaway branch of a scratch repo (we used `devinsba/second-brain`, branch `claude/admiring-rubin-4sq9mk`, which starts with only a README and a Python `.gitignore`, a useful trap).

**Setup of the run**
- Install the plugin from a local checkout (`/plugin marketplace add <path to this repo>`, then `/plugin install brain@claude-second-brain-system`), start Claude Code **in the scratch repo**, and use the `/brain:*` commands. Until the plugin can be installed in the session, follow each `SKILL.md` by hand, exactly as written, and note every place the text was unclear or wrong.
- Keep a findings list as you go. Record what you did and what happened, not what you expected. Move findings to `docs/plans/10-plugin-skills.md` afterwards.
- Replace any ids in the examples below with the ones you generate (`ids.py ulid`).

| # | Step | Expect |
|---|---|---|
| 1 | `/brain:setup`. Check preflight (Python 3.12+, tool detected), the summary, and the one confirmation. | Files created in order: `config.yml`, five `default-*` impls, Inbox (`areas/inbox.md`), the Python workspace (with `brainctl/`), `.gitignore` lines, `manifest.yml` **last**. One commit "brain: initial setup". `git check-ignore -v .brain/python/lib/x.py` prints nothing. `uv sync --frozen` and `uv run --frozen python -c "print(1)"` work in `.brain/python`. Re-running setup reports a complete vault and changes nothing. |
| 2 | `/brain:capture` a note, a task (`--type task`), a person (`--type person --trait colleague`, after defining the trait), an area (`--type area`), a project (`--type project`). Capture the same note title twice. | Files named by slug: `notes/<slug>.md`; the repeat is `<slug>-02.md`. Notes, tasks and projects fire `capture`; the area and person do not and are not offered triage. Person `name` is structured; trait fields are nested under the trait name. |
| 3 | Add a second task implementation, `gtd-task`, with a required enum `context`, `priority` default `med`, path `tasks/gtd/{slug}.md`; set the project's `defaults.task: gtd-task`. | `/brain:validate` accepts it; manifest lists it after the next write. |
| 4 | `/brain:triage`. Place the project under an area, the note under the project, the task under the project. | Areas never appear as candidates. The note and project are plain updates. The task triggers a conversion with a report: `context` **missing** (you fill it), `priority` **filled by default**. The user sees the final diff and approves. |
| 5 | Repeat step 4's conversion but make the source delete fail (or stop after the create). Run `/brain:validate`. | A marker in `.brain/conversions/`, the duplicate ref reported as an error. Finishing clears both. |
| 6 | `/brain:sync` right after setup, then hand-edit a note, add a note by hand in the editor **with an id**, and add one **without** frontmatter. Sync again. | First sync: silent baseline. Then `update`, `create`+`capture`, and the id-less file adopted (name and body unchanged, `adopted` in the report). Your own writes from steps 1 to 5 do **not** show as external. |
| 7 | Add a `capture` rule with a `claude` action to the note implementation, then add a hand-written note. | A pending entry is written, not a prompt. `/brain:pending` re-checks staleness, shows the diff, applies on approval, and removes the file. `updated` is refreshed. |
| 8 | Define a `journal` note implementation (path `journal/{slug}.md`, or `journal/{created:%Y-%m-%d}.md`) and a vault rule with `place: { find: { type: area, where: { title: Journals } }, create_if_missing: true }`. Run `/brain:run vault/<id>` twice. | A date-named file placed under the `Journals` area (so **not** a triage candidate); the second run changes nothing. |
| 9 | `/brain:python`: write a small script, register it, approve it, run it with `requires_env: []`. Change `pyproject.toml`. | The hash is computed by the helper; the change invalidates approval; `approve --all` re-approves after showing the diff once. |
| 10 | `/brain:validate` on the finished vault; commit and push the branch. | No errors; leftover markers, ignored paths and unadopted files absent. |

**Reset**: delete the scratch branch or recreate it from the initial commit. Nothing outside the scratch repo is touched.

## When to update these tests

- Changing a design doc: change the matching skill or `core/references/` file, and the check here that covers it. `tests/rehearsal/scenario.py` mirrors the rules in docs 03, 05, 06 and 08.
- A new finding in the manual rehearsal: reproduce it in `scenario.py` first if it is mechanical, then fix it.
- When `brainctl` lands: run the scenario against it instead of `brainsim.py`, and add the unit tests it needs (`validate`, `sync`, `create`, `update`).

## Known gaps

- No automated test drives Claude or the `/brain:*` commands; the manual rehearsal is the only coverage of the skills.
- Script adapters, the Archive, and the `convert` mapping rules are not covered by the scripted scenario.
- Sorting caveat found while testing slugs: byte-wise sorting of whole file names puts `a.md` **after** `a-02.md` (`-` sorts before `.`). Sorting by stem, or most locale-aware listings, puts the unsuffixed name first. If that matters, the suffix separator is the thing to change.
