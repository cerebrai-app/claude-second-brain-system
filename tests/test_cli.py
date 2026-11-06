"""The command line, including running the installed copy the way the skills do: `python -m brainctl` from .brain/python."""
import json
import os
import subprocess
import sys

import pytest

from brainctl import __main__ as cli


def run_cli(b, *args):
    """Run a command in-process; return (exit code, parsed JSON or text)."""
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["--vault", b.root, *args])
    text = out.getvalue()
    try:
        return code, json.loads(text)
    except ValueError:
        return code, text


def test_validate_clean_vault_exits_zero(b):
    code, out = run_cli(b, "validate")
    assert code == 0 and out["ok"] is True and out["findings"] == []


def test_validate_exits_one_on_errors_but_not_on_warnings(b):
    b.write("notes/by-hand.md", "# By hand\n")                       # a warning
    code, out = run_cli(b, "validate")
    assert code == 0 and out["warnings"] == 1 and out["errors"] == 0
    b.write("notes/broken.md", "---\ntitle: [x\n---\n")               # an error
    code, out = run_cli(b, "validate")
    assert code == 1 and out["ok"] is False and out["errors"] == 1


def test_validate_text_output(b):
    b.write("notes/by-hand.md", "# By hand\n")
    code, text = run_cli(b, "validate", "--text")
    assert code == 0 and "unadopted-file" in text and "0 error(s), 1 warning(s)" in text


def test_sync_json_and_dry_run(b):
    b.write("notes/by-hand.md", "# By hand\n")
    code, out = run_cli(b, "sync", "--dry-run")
    assert code == 0 and out["report"]["unadopted"] == ["notes/by-hand.md"] and out["events"] == []
    code, out = run_cli(b, "sync")
    assert out["report"]["adopted"] == ["notes/by-hand.md"]
    code, out = run_cli(b, "sync")
    assert out["events"] == [] and out["report"]["baseline"] is False


def test_list_and_read(b):
    i, _ = b.item("note", "default-note", "notes", "An idea", body="text\n")
    code, out = run_cli(b, "list")
    assert f"note:{i}" in [row["ref"] for row in out["items"]]
    code, out = run_cli(b, "read", f"note:{i}")
    assert code == 0 and out["items"][0]["front"]["title"] == "An idea" and out["items"][0]["body"] == "text\n"
    code, out = run_cli(b, "read", "note:missing")
    assert code == 1 and out["error"] == "not_found"


def test_id_and_slug(b, capsys):
    assert cli.main(["--vault", b.root, "id", "-n", "2"]) == 0
    assert len(capsys.readouterr().out.split()) == 2
    assert cli.main(["--vault", b.root, "slug", "Draft Q4 plan", "--taken", "draft-q4-plan"]) == 0
    assert capsys.readouterr().out.strip() == "draft-q4-plan-02"


def test_approve_hash_matches_the_library(b, capsys):
    from brainctl import approval
    b.write(".brain/python/scripts/a.py", "print(1)\n")
    assert cli.main(["--vault", b.root, "approve-hash", "scripts/a.py"]) == 0
    assert capsys.readouterr().out.strip() == approval.approval_hash(b.path(".brain/python"), "scripts/a.py")


def test_approve_records_the_hash_and_keeps_the_registry_comments(b, capsys):
    from brainctl import approval
    b.write(".brain/python/scripts/a.py", "print(1)\n")
    b.write(".brain/python/scripts/b.py", "print(2)\n")
    b.write(".brain/python/registry.yml", "# my scripts\nscripts:\n  - { name: a, path: scripts/a.py }\n  - { name: b, path: scripts/b.py }\n")
    py = b.path(".brain/python")
    assert cli.main(["--vault", b.root, "approve", "a", "--by", "me@example.com"]) == 0
    capsys.readouterr()
    text = b.read(".brain/python/registry.yml")
    assert text.startswith("# my scripts") and approval.approval_hash(py, "scripts/a.py") in text and "me@example.com" in text
    assert cli.main(["--vault", b.root, "validate"]) == 0                 # b is still unapproved (a warning)
    assert "script-unapproved" in capsys.readouterr().out
    assert cli.main(["--vault", b.root, "approve", "--all", "--by", "me@example.com"]) == 0      # only b needed it
    assert [x["name"] for x in json.loads(capsys.readouterr().out)["approved"]] == ["b"]
    assert cli.main(["--vault", b.root, "validate"]) == 0
    capsys.readouterr()
    b.write(".brain/python/scripts/a.py", "print(3)\n")                    # a changed since approval
    assert cli.main(["--vault", b.root, "approve", "--all", "--by", "me@example.com"]) == 0
    assert [x["name"] for x in json.loads(capsys.readouterr().out)["approved"]] == ["a"]


def test_approve_needs_exactly_one_target_and_a_registered_script(b, capsys):
    assert cli.main(["--vault", b.root, "approve", "--by", "me"]) == 2
    assert cli.main(["--vault", b.root, "approve", "nope", "--by", "me"]) == 2


def test_approve_requires_a_named_approver(b, capsys):
    b.write(".brain/python/scripts/a.py", "print(1)\n")
    b.write(".brain/python/registry.yml", "scripts:\n  - { name: a, path: scripts/a.py }\n")
    assert cli.main(["--vault", b.root, "approve", "a"]) == 2
    assert cli.main(["--vault", b.root, "approve", "a", "--by", "  "]) == 2
    assert "approved:" not in b.read(".brain/python/registry.yml")


def test_not_a_vault_exits_two(tmp_path):
    old = os.getcwd()
    os.chdir(tmp_path)                                 # no .brain in this directory or above it (tmp_path is isolated)
    try:
        with pytest.raises(SystemExit) as e:
            cli.main(["validate"])
        assert e.value.code == 2
    finally:
        os.chdir(old)


def test_the_installed_copy_runs_from_the_workspace_directory(b):
    """What the skills do: cd .brain/python and run `python -m brainctl ...`; the vault is found by walking up."""
    b.install_helper()
    cwd = b.path(".brain/python")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run([sys.executable, "-m", "brainctl", "validate"], cwd=cwd, capture_output=True, text=True, env=env)
    assert r.returncode == 2 and json.loads(r.stdout)["error"] == "wrong_environment"        # not the workspace venv: refused
    import ruamel.yaml
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", ".venv"], cwd=cwd, check=True)     # a real workspace venv
    py = os.path.join(cwd, ".venv", "bin", "python")
    env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.dirname(ruamel.yaml.__file__)))        # stands in for the locked ruamel.yaml
    r = subprocess.run([py, "-m", "brainctl", "validate"], cwd=cwd, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["ok"] is True
    r = subprocess.run([py, "-m", "brainctl", "id"], cwd=cwd, capture_output=True, text=True, env=env)
    assert len(r.stdout.strip()) == 26
    r = subprocess.run([py, "-I", ".brain/python/brainctl/ids.py", "ulid"], cwd=b.root, capture_output=True, text=True, env=env)
    assert len(r.stdout.strip()) == 26                                  # ids.py also works standalone, as the core skill uses it
    assert not os.path.exists(b.path(".brain/python/brainctl/test_ids.py"))


def test_sync_refresh_flag(b):
    run_cli(b, "sync")
    b.write("notes/n.md", "# N\n")
    code, out = run_cli(b, "sync", "--refresh")
    assert code == 0 and out["events"] == [] and out["report"]["adopted"] == []
    code, out = run_cli(b, "sync", "--refresh", "--dry-run")
    assert code == 2 and out["error"] == "invalid"


def test_find_matches_type_impl_and_field_values(b):
    b.item("note", "default-note", "notes", "2026-11-06", "tags:\n  topic: pricing\n")
    b.item("note", "default-note", "notes", "Other")
    b.item("task", "default-task", "tasks", "2026-11-06", "status: open\n")
    code, out = run_cli(b, "find", "--type", "note", "--where", "title=2026-11-06")
    assert code == 0 and out["count"] == 1 and out["items"][0]["title"] == "2026-11-06"
    code, out = run_cli(b, "find", "--type", "note", "--where", "tags.topic=pricing")                 # dotted paths reach nested fields
    assert code == 0 and out["count"] == 1
    code, out = run_cli(b, "find", "--type", "note", "--impl", "journal", "--where", "title=2026-11-06")
    assert code == 1 and out["count"] == 0                                                              # none: exit 1
    code, out = run_cli(b, "find", "--type", "note", "--where", "oops")
    assert code == 2 and out["error"] == "invalid"


def test_find_skips_archived_items_unless_asked(b):
    b.write("archive/note/default-note/old.md", "---\nid: 01J0000000000000000000000Z\nslug: old\ntype: note\nimpl: default-note\ntitle: Old\narchive: archive:archive\narchived_at: 2026-11-01T10:00:00Z\ncreated: 2026-11-01T10:00:00Z\nupdated: 2026-11-01T10:00:00Z\n---\n")
    assert run_cli(b, "find", "--type", "note", "--where", "title=Old")[0] == 1
    assert run_cli(b, "find", "--type", "note", "--where", "title=Old", "--include-archived")[0] == 0


def _run(b, capsys, *argv):
    code = cli.main(["--vault", b.root, *argv])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith("{") else out)


def test_write_commands_end_to_end(b, capsys):
    code, made = _run(b, capsys, "create", "--json", json.dumps({"type": "note", "title": "Hello there", "body": "hi\n"}))
    assert code == 0 and made["path"] == "notes/hello-there.md"
    ref = made["ref"]
    code, upd = _run(b, capsys, "update", ref, "--json", json.dumps({"set": {"tags": {"x": "1"}}, "revision": made["revision"]}))
    assert code == 0 and upd["changed"] == ["tags"]
    code, bad = _run(b, capsys, "update", ref, "--json", json.dumps({"set": {"slug": "nope"}}))
    assert code == 1 and bad["ok"] is False and bad["error"]["code"] == "invalid"
    code, stale = _run(b, capsys, "update", ref, "--json", json.dumps({"set": {"title": "Z"}, "revision": made["revision"]}))
    assert code == 1 and stale["error"]["code"] == "conflict"
    code, arch = _run(b, capsys, "archive", ref)
    assert code == 0 and arch["path"].startswith("archive/")
    code, _ = _run(b, capsys, "unarchive", ref)
    assert code == 0
    code, refused = _run(b, capsys, "delete", ref)
    assert code == 1 and refused["error"]["code"] == "invalid"
    code, gone = _run(b, capsys, "delete", ref, "--confirm", "permanent")
    assert code == 0 and gone["ref"] == ref
    code, missing = _run(b, capsys, "archive", ref)
    assert code == 1 and missing["error"]["code"] == "not_found"
    assert cli.main(["--vault", b.root, "validate"]) == 0


def test_op_log_and_pending_commands(b, capsys):
    code, note = _run(b, capsys, "create", "--json", json.dumps({"type": "note", "title": "N"}))
    code, _ = _run(b, capsys, "op", "--json", json.dumps({"op": "set_field", "ref": note["ref"], "field": "tags", "value": {"a": "b"}}))
    assert code == 0
    code, _ = _run(b, capsys, "log", "--json", json.dumps({"rule": "vault/r", "outcome": "skipped", "reason": "exists"}))
    assert code == 0
    code, bad = _run(b, capsys, "log", "--json", json.dumps({"outcome": "nonsense"}))
    assert code == 1 and bad["error"]["code"] == "invalid"
    proposal = {"rule": "note/default-note/r", "event": {"id": "ev_1", "trigger": "capture", "ref": note["ref"]}, "rationale": "because",
                "operations": [{"op": "set_field", "ref": note["ref"], "field": "tags", "value": {"c": "d"}}]}
    code, added = _run(b, capsys, "pending", "add", "--json", json.dumps(proposal))
    assert code == 0
    code, listed = _run(b, capsys, "pending", "list")
    assert listed["count"] == 1 and listed["entries"][0]["state"] == "fresh"
    code, applied = _run(b, capsys, "pending", "apply", added["id"])
    assert code == 0 and applied["applied"] == 1
    assert _run(b, capsys, "pending", "apply")[0] == 2
    assert cli.main(["--vault", b.root, "validate"]) == 0
    capsys.readouterr()


def test_convert_commands(b, capsys):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], required: true }\n", path="tasks/gtd/{slug}.md")
    code, made = _run(b, capsys, "create", "--json", json.dumps({"type": "task", "title": "Plan"}))
    code, plan = _run(b, capsys, "convert", "plan", made["ref"], "--to", "gtd")
    assert code == 0 and plan["needs_resolution"]
    code, refused = _run(b, capsys, "convert", "apply", made["ref"], "--to", "gtd", "--json", "{}")
    assert code == 1 and refused["error"]["code"] == "invalid"
    code, done = _run(b, capsys, "convert", "apply", made["ref"], "--to", "gtd", "--json", json.dumps({"fill": {"context": "work"}}))
    assert code == 0 and done["path"] == "tasks/gtd/plan.md"
