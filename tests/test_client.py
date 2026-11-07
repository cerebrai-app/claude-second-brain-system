"""The script adapter client: approval, scrubbed environment, timeouts, rate-limit retry, and sync/list/validate over a script binding."""
import json
import os
import sys

import pytest

from brainctl import approval, client, ids, sync as sync_mod, util, validate as validate_mod
from brainctl.__main__ import main as cli_main
from conftest import REPO

TEMPLATE = os.path.join(REPO, "plugins", "brain", "skills", "backend", "references", "adapter-template.py")


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(client, "RETRY_DELAY", 0)


def register(b, name, source, requires_env=(), approve=True, timeout=20):
    """Write a script into the workspace and register it (approved unless asked not to)."""
    path = f"scripts/{name}.py"
    b.write(f".brain/python/{path}", source)
    entry = {"name": name, "path": path, "requires_env": list(requires_env), "timeout": timeout}
    if approve:
        entry["approved"] = {"sha256": approval.approval_hash(b.path(".brain/python"), path), "at": "2026-11-06", "by": "user"}
    reg_path = b.path(".brain/python/registry.yml")
    data = util.load_yaml_file(reg_path) or {}
    data["scripts"] = [s for s in (data.get("scripts") or []) if s["name"] != name] + [entry]
    b.write(".brain/python/registry.yml", json.dumps(data))     # JSON is valid YAML
    return entry


def bind(b, tmp_path, name="remote", type_="task", **storage):
    b.fake_venv()
    store = str(tmp_path / "store.json")
    extra = "".join(f"  {k}: {json.dumps(v)}\n" for k, v in storage.items())
    b.write(f".brain/impls/{type_}/{name}.md",
            f"---\nimpl: {name}\nextends: {type_}\nversion: 1\nstorage:\n  adapter: script\n  command: python:{name}\n"
            f"  settings: {{path: {json.dumps(store)}}}\n{extra}---\n")
    b.write_manifest()
    return store


@pytest.fixture
def remote(b, tmp_path):
    b.install_helper()
    register(b, "remote", open(TEMPLATE).read())
    bind(b, tmp_path)
    return b


def impl_of(b, name="remote"):
    return b.vault().impls[("task", name)]


def envelope(ident=None, title="Call mum", status="open"):
    ident = ident or ids.ulid()
    return {"id": ident, "ref": f"task:{ident}", "type": "task", "impl": "remote", "fields": {"title": title, "status": status, "slug": "call-mum"},
            "relations": {}, "body": "", "created": None, "updated": None}


def test_calls_round_trip_through_a_real_process(remote):
    c = client.ScriptClient.for_impl(remote.vault(), impl_of(remote))
    made = c.call("create", envelope=envelope("01J0000000000000000000000A"))
    assert made["ref"] == "task:01J0000000000000000000000A" and made["revision"]
    assert c.call("read", ref=made["ref"])["fields"]["title"] == "Call mum"
    assert [e["ref"] for e in c.list_all()] == [made["ref"]]
    with pytest.raises(client.ClientError) as err:
        c.call("read", ref="task:nope")
    assert err.value.code == "not_found"


def test_unregistered_unapproved_and_changed_scripts_do_not_run(b, tmp_path):
    b.install_helper()
    bind(b, tmp_path)
    with pytest.raises(client.ClientError) as err:
        client.ScriptClient.for_impl(b.vault(), impl_of(b))
    assert err.value.code == "unsupported"
    register(b, "remote", open(TEMPLATE).read(), approve=False)
    with pytest.raises(client.ClientError) as err:
        client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe")
    assert err.value.code == "unauthorized" and "not been approved" in err.value.message
    register(b, "remote", open(TEMPLATE).read())
    b.write(".brain/python/scripts/remote.py", open(TEMPLATE).read() + "\n# edited\n")
    with pytest.raises(client.ClientError) as err:
        client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe")
    assert err.value.code == "unauthorized" and "changed since" in err.value.message


def test_the_environment_is_scrubbed_to_requires_env(b, tmp_path, monkeypatch):
    b.install_helper()
    monkeypatch.setenv("SECRET_A", "a")
    monkeypatch.setenv("SECRET_B", "b")
    src = ("import json, os, sys\njson.load(sys.stdin)\n"
           "print(json.dumps({'ok': True, 'result': {'a': os.environ.get('SECRET_A'), 'b': os.environ.get('SECRET_B')}}))\n")
    register(b, "remote", src, requires_env=["SECRET_A"])
    bind(b, tmp_path)
    assert client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe") == {"a": "a", "b": None}


def test_a_timeout_is_unavailable(b, tmp_path):
    b.install_helper()
    register(b, "remote", "import time\ntime.sleep(30)\n")
    bind(b, tmp_path, timeout_seconds=1)
    with pytest.raises(client.ClientError) as err:
        client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe")
    assert err.value.code == "unavailable" and err.value.retryable


def test_garbage_output_is_internal_with_the_stderr_tail(b, tmp_path):
    b.install_helper()
    register(b, "remote", "import sys\nsys.stderr.write('boom\\n')\nprint('not json')\n")
    bind(b, tmp_path)
    with pytest.raises(client.ClientError) as err:
        client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe")
    assert err.value.code == "internal" and "boom" in err.value.message or "not json" in err.value.message


RATE_LIMITED = """import json, os, sys
json.load(sys.stdin)
counter = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls")
n = int(open(counter).read()) if os.path.exists(counter) else 0
open(counter, "w").write(str(n + 1))
if n < LIMIT:
    print(json.dumps({"ok": False, "error": {"code": "rate_limited", "message": "slow", "retryable": True}}))
else:
    print(json.dumps({"ok": True, "result": {"calls": n + 1}}))
"""


def test_rate_limited_is_retried_once_and_then_fails(b, tmp_path):
    b.install_helper()
    register(b, "remote", RATE_LIMITED.replace("LIMIT", "1"))
    bind(b, tmp_path)
    assert client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe") == {"calls": 2}      # one retry succeeded
    os.remove(b.path(".brain/python/scripts/calls"))
    register(b, "remote", RATE_LIMITED.replace("LIMIT", "5"))
    with pytest.raises(client.ClientError) as err:
        client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe")
    assert err.value.code == "rate_limited"
    assert open(b.path(".brain/python/scripts/calls")).read() == "2"                                  # exactly one retry


def test_list_all_follows_cursors(remote, monkeypatch):
    c = client.ScriptClient.for_impl(remote.vault(), impl_of(remote))
    for i in range(5):
        c.call("create", envelope=envelope(f"01J000000000000000000000{i}A", title=f"t{i}"))
    monkeypatch.setattr(client, "PAGE", 2)
    assert len(c.list_all()) == 5


# ---- through brainctl -------------------------------------------------------------------------------------------------

def test_list_read_and_adapter_commands(remote, capsys):
    ident = "01J0000000000000000000000B"
    assert cli_main(["--vault", remote.root, "adapter", "remote", "create", "--args", json.dumps({"envelope": envelope(ident)})]) == 0
    capsys.readouterr()
    assert cli_main(["--vault", remote.root, "list"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert f"task:{ident}" in [r["ref"] for r in out["items"]] and out["incomplete"] == []
    assert cli_main(["--vault", remote.root, "read", f"task:{ident}"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["front"]["title"] == "Call mum"


def test_adapter_command_rejects_unknown_impls_and_reports_errors(remote, capsys):
    assert cli_main(["--vault", remote.root, "adapter", "nope", "describe"]) == 2
    capsys.readouterr()
    assert cli_main(["--vault", remote.root, "adapter", "remote", "read", "--args", '{"ref": "task:zzz"}']) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "not_found"


def test_an_unapproved_binding_is_incomplete_not_empty(b, tmp_path, capsys):
    b.install_helper()
    register(b, "remote", open(TEMPLATE).read(), approve=False)
    bind(b, tmp_path)
    assert cli_main(["--vault", b.root, "list"]) == 0
    incomplete = json.loads(capsys.readouterr().out)["incomplete"]
    assert incomplete and incomplete[0]["binding"] == "task/remote" and "not been approved" in incomplete[0]["reason"]


def make(remote, ident, title="Call mum", status="open"):
    c = client.ScriptClient.for_impl(remote.vault(), impl_of(remote))
    return c.call("create", envelope=envelope(ident, title, status))


def test_sync_detects_changes_in_a_script_backend(remote):
    ident = "01J0000000000000000000000C"
    sync_mod.sync(remote.vault())                                       # baseline
    make(remote, ident)
    events = sync_mod.sync(remote.vault())["events"]
    assert [(e["trigger"], e["ref"], e["origin"]) for e in events] == [(t, f"task:{ident}", "external/task/remote") for t in ("create", "capture")]   # no placement: it is in the Inbox
    assert sync_mod.sync(remote.vault())["events"] == []
    c = client.ScriptClient.for_impl(remote.vault(), impl_of(remote))
    current = c.call("read", ref=f"task:{ident}")
    current["fields"]["status"] = "done"
    c.call("update", envelope=current)
    events = sync_mod.sync(remote.vault())["events"]
    assert [(e["trigger"], e["changed"]) for e in events] == [("update", ["status"])]


def test_an_unreadable_binding_does_not_make_its_items_missing(remote):
    ident = "01J0000000000000000000000D"
    make(remote, ident)
    sync_mod.sync(remote.vault())
    sync_mod.sync(remote.vault())
    register(remote, "remote", open(TEMPLATE).read(), approve=False)        # now it cannot run
    report = sync_mod.sync(remote.vault())["report"]
    assert report["missing"] == [] and [i["binding"] for i in report["incomplete"]] == ["task/remote"]
    register(remote, "remote", open(TEMPLATE).read())                       # approved again: nothing changed, nothing reported
    result = sync_mod.sync(remote.vault())
    assert result["events"] == [] and result["report"]["missing"] == []


def test_validate_checks_the_binding_against_describe(remote, tmp_path):
    findings = validate_mod.validate(remote.vault())
    assert [f for f in findings if f["code"].startswith("adapter-")] == []
    labels = open(TEMPLATE).read().replace('tags = "map"', 'tags = "labels"')
    assert labels != open(TEMPLATE).read(), "template changed: update this test"
    register(remote, "remote", labels)
    codes = [f["code"] for f in validate_mod.validate(remote.vault())]
    assert "adapter-tags" in codes
    bind(remote, tmp_path, tag_values_field="tag_values")
    assert "adapter-tags" not in [f["code"] for f in validate_mod.validate(remote.vault())]


def test_validate_reports_a_failing_describe_and_missing_env(b, tmp_path):
    b.install_helper()
    register(b, "remote", "import sys\nsys.exit(3)\n", requires_env=["NOT_SET_ANYWHERE_XYZ"])
    bind(b, tmp_path)
    codes = [f["code"] for f in validate_mod.validate(b.vault())]
    assert "adapter-describe" in codes and "adapter-env-missing" in codes


def test_scripts_run_only_in_the_workspace_venv(b, tmp_path):
    b.install_helper()
    register(b, "remote", open(TEMPLATE).read())
    bind(b, tmp_path)
    os.remove(b.path(".brain/python/.venv/bin/python"))                    # no environment: nothing runs, whatever interpreter is current
    with pytest.raises(client.ClientError) as err:
        client.ScriptClient.for_impl(b.vault(), impl_of(b))
    assert err.value.code == "unavailable" and ".venv" in err.value.message
    assert not hasattr(client, "sys")


def test_the_venv_interpreter_is_the_one_used(b, tmp_path):
    b.install_helper()
    register(b, "remote", "import json\nprint(json.dumps({'ok': True, 'result': {}}))\n")
    bind(b, tmp_path)
    marker = tmp_path / "used-venv"
    with open(b.path(".brain/python/.venv/bin/python"), "w") as fh:
        fh.write(f'#!/bin/sh\ntouch "{marker}"\nexec "{sys.executable}" "$@"\n')
    client.ScriptClient.for_impl(b.vault(), impl_of(b)).call("describe")
    assert marker.exists()
