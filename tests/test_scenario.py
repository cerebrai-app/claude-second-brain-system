"""The mechanical part of the rehearsal (TESTING.md, section 3), run end to end against `brainctl` on a scratch vault."""
import os
import shutil
import subprocess
import time

import pytest

from brainctl import approval, sync as sync_mod, util, validate
from conftest import Builder, GITIGNORE


def errors(b):
    return [f for f in validate.validate(b.vault()) if f["severity"] == "error"]


def test_a_python_template_gitignore_hides_the_workspace_lib_until_a_negation_is_added(tmp_path):
    """The first-rehearsal bug: `lib/` in the vault's own .gitignore ignores .brain/python/lib/."""
    b = Builder(tmp_path).setup()
    b.write(".gitignore", GITIGNORE.replace("!.brain/python/lib/\n", ""))
    assert util.git_ignored(b.root, ".brain/python/lib/x.py") is True
    assert any(f["code"] == "gitignored-path" and "lib" in f["subject"] for f in validate.validate(b.vault()))
    b.write(".gitignore", b.read(".gitignore") + "!.brain/python/lib/\n")
    assert util.git_ignored(b.root, ".brain/python/lib/x.py") is False
    assert errors(b) == []


def test_slugs_collisions_and_date_named_journal_notes(b):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    b.impl("note", "journal", path="journal/{slug}.md")
    _, s1 = b.item("note", "default-note", "notes", "Look into spaced repetition")
    _, s2 = b.item("note", "default-note", "notes", "Look into spaced repetition")
    assert (s1, s2) == ("look-into-spaced-repetition", "look-into-spaced-repetition-02")
    for _ in range(9):
        b.item("note", "default-note", "notes", "Look into spaced repetition")
    stems = sorted(n[:-3] for n in os.listdir(b.path("notes")))
    assert stems == ["look-into-spaced-repetition"] + [f"look-into-spaced-repetition-{n:02d}" for n in range(2, 12)]
    _, js = b.item("note", "journal", "journal", today)
    assert js == today and b.exists(f"journal/{today}.md")
    assert errors(b) == []
    # the date file name can also come from a date field
    b.impl("note", "dated", fields="    day: { type: date }\n", path="dated/{day}.md")
    assert util.render_path("dated/{day}.md", {"day": "2026-11-06"}) == "dated/2026-11-06.md"


def test_capture_triage_conversion_adoption_and_sync(b):
    b.trait("colleague")
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], required: true }\n"
                                 "    priority: { type: enum, values: [low, med, high], default: med }\n", path="tasks/gtd/{slug}.md")
    v = sync_mod.sync(b.vault())
    assert v["report"]["baseline"] and v["events"] == []

    # capture
    note, ns = b.item("note", "default-note", "notes", "Look into spaced repetition")
    task, ts = b.item("task", "default-task", "tasks", "Draft Q4 plan", "status: open\n")
    area, _ = b.item("area", "default-area", "areas", "Work")
    proj, ps = b.item("project", "default-project", "projects", "Q4 planning", "status: open\ndefaults:\n  task: gtd\n")
    pers, _ = b.item("person", "default-person", "people", "Alex Rivera", name_block="name:\n  given: Alex\n  family: Rivera\n",
                     extra="traits: [colleague]\ncolleague:\n  employer: Acme\n")
    result = sync_mod.sync(b.vault())
    created = {e["ref"] for e in result["events"] if e["trigger"] == "create"}
    captured = {e["ref"] for e in result["events"] if e["trigger"] == "capture"}
    assert created == {f"note:{note}", f"task:{task}", f"area:{area}", f"project:{proj}", f"person:{pers}"}
    assert captured == {f"note:{note}", f"task:{task}", f"project:{proj}"}            # areas and persons are top-level
    assert errors(b) == []

    # triage: plain placements
    b.add_front(f"projects/{ps}.md", f"area: [area:{area}]\n")
    b.add_front(f"notes/{ns}.md", f"about: [project:{proj}]\n")
    # triage: conversion default-task -> gtd with `context` supplied and `priority` filled by default; the source delete "fails"
    created_line = [l for l in b.read(f"tasks/{ts}.md").splitlines() if l.startswith("created:")][0]
    b.write(f"tasks/gtd/{ts}.md", f"---\nid: {task}\nslug: {ts}\ntype: task\nimpl: gtd\ntitle: Draft Q4 plan\nstatus: open\ncontext: work\n"
                                  f"priority: med\nbelongs_to: [project:{proj}]\n{created_line}\nupdated: {util.now_iso()}\n---\n")
    b.write(f".brain/conversions/task-{task}.json", "{}")
    found = validate.validate(b.vault())
    assert any(f["code"] == "duplicate-ref" for f in found) and any(f["code"] == "half-converted" for f in found)
    b.remove(f"tasks/{ts}.md")
    b.remove(f".brain/conversions/task-{task}.json")
    assert errors(b) == []
    result = sync_mod.sync(b.vault())
    mine = [e for e in result["events"] if e["ref"] == f"task:{task}"]
    assert [e["trigger"] for e in mine if e["trigger"] != "relation"] == ["update"]
    assert "impl" in next(e for e in mine if e["trigger"] == "update")["changed"]
    assert result["report"]["missing"] == []
    assert not any(e["ref"] in (f"area:{area}",) for e in result["events"])             # nothing is fired for the Area

    # nothing placed is left in the Inbox, except whatever has no placement
    assert sync_mod.sync(b.vault())["events"] == []

    # a hand-written note is adopted and fires create and capture
    hand = "# Idea from the bus\nWhat if triage had a mobile view?\n"
    b.write("notes/idea-from-the-bus.md", hand)
    result = sync_mod.sync(b.vault())
    assert result["report"]["adopted"] == ["notes/idea-from-the-bus.md"]
    assert b.read("notes/idea-from-the-bus.md").endswith(hand)
    new_ref = "note:" + util.ParsedFile(b.read("notes/idea-from-the-bus.md")).front["id"]
    assert {(e["trigger"], e["ref"]) for e in result["events"]} >= {("create", new_ref), ("capture", new_ref)}
    assert sync_mod.sync(b.vault())["events"] == [] and errors(b) == []


@pytest.mark.workspace
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_a_real_uv_workspace_runs_scripts_with_a_scrubbed_environment(tmp_path):
    b = Builder(tmp_path).setup(workspace=False)
    py = b.path(".brain/python")
    os.makedirs(py)
    run = lambda *cmd: subprocess.run(cmd, cwd=py, capture_output=True, text=True, check=True)
    run("uv", "init", "--bare", "--name", "brain-workspace", "--python", ">=3.12")
    run("uv", "lock")
    run("uv", "sync", "--frozen")
    for d in ("scripts", "lib", "tests"):
        b.write(f".brain/python/{d}/.gitkeep", "")
    b.write(".brain/python/registry.yml", "scripts: []\n")
    b.write(".brain/python/scripts/hello.py", "import sys, json\nprint(json.dumps({'hi': True}))\n")
    r = subprocess.run(["env", "-i", f"PATH={os.environ['PATH']}", "uv", "run", "--frozen", "python", "scripts/hello.py"], cwd=py, capture_output=True, text=True)
    assert r.returncode == 0 and '"hi": true' in r.stdout
    before = approval.approval_hash(py, "scripts/hello.py")
    with open(os.path.join(py, "pyproject.toml"), "a") as f:
        f.write("# touched\n")
    assert approval.approval_hash(py, "scripts/hello.py") != before
    assert errors(b) == [] or all(f["code"] != "workspace-project" for f in errors(b))
