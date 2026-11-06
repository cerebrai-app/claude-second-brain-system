"""`/brain:upgrade`: copy only the changed helper files from the plugin into the vault, and the environment guard."""
import importlib.util
import json
import os
import shutil

from brainctl import __main__ as cli
from conftest import REPO, TOOLS

SCRIPT = os.path.join(REPO, "plugins", "brain", "skills", "upgrade", "upgrade.py")
spec = importlib.util.spec_from_file_location("upgrade_script", SCRIPT)
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)
SOURCE = os.path.join(TOOLS, "brainctl")


def installed(b):
    return b.install_helper()


def test_a_current_copy_has_nothing_to_do(b):
    installed(b)
    r = up.upgrade(b.root, SOURCE)
    assert r["ok"] and r["added"] == [] and r["changed"] == [] and r["copied"] == 0 and r["from"] == r["to"]


def test_only_changed_and_new_files_are_copied(b):
    dest = installed(b)
    open(os.path.join(dest, "sync.py"), "a").write("# stale edit\n")
    os.remove(os.path.join(dest, "client.py"))
    keep = os.path.join(dest, "util.py")
    before = os.stat(keep).st_mtime_ns
    r = up.upgrade(b.root, SOURCE)
    assert r["changed"] == ["sync.py"] and r["added"] == ["client.py"] and r["copied"] == 2
    assert open(os.path.join(dest, "sync.py"), "rb").read() == open(os.path.join(SOURCE, "sync.py"), "rb").read()
    assert os.stat(keep).st_mtime_ns == before                        # an unchanged file is not rewritten


def test_dry_run_changes_nothing_and_extra_files_are_left_alone(b):
    dest = installed(b)
    os.remove(os.path.join(dest, "client.py"))
    open(os.path.join(dest, "old_module.py"), "w").write("x = 1\n")
    r = up.upgrade(b.root, SOURCE, dry_run=True)
    assert r["added"] == ["client.py"] and r["not_shipped"] == ["old_module.py"] and not os.path.exists(os.path.join(dest, "client.py"))
    up.upgrade(b.root, SOURCE)
    assert os.path.exists(os.path.join(dest, "client.py")) and os.path.exists(os.path.join(dest, "old_module.py"))


def test_tests_and_caches_are_never_copied(tmp_path, b):
    src = tmp_path / "src"
    shutil.copytree(SOURCE, src)
    (src / "test_something.py").write_text("assert True\n")
    (src / "__pycache__").mkdir(exist_ok=True)
    (src / "__pycache__" / "x.pyc").write_bytes(b"\0")
    dest = installed(b)
    up.upgrade(b.root, str(src))
    assert not os.path.exists(os.path.join(dest, "test_something.py")) and not os.path.exists(os.path.join(dest, "__pycache__", "x.pyc"))


def test_helper_version_is_recorded_without_touching_the_rest_of_the_manifest(b):
    installed(b)
    manifest = b.path(".brain/manifest.yml")
    before = open(manifest).read()
    up.upgrade(b.root, SOURCE)
    after = open(manifest).read()
    assert after.startswith(before) and after.endswith('helper_version: "0.2.0"\n')
    up.upgrade(b.root, SOURCE)                                          # idempotent: replaces, never duplicates
    assert open(manifest).read().count("helper_version") == 1
    assert b.vault().manifest["helper_version"] == "0.2.0"


def test_not_a_vault_and_main(tmp_path, capsys):
    assert up.upgrade(str(tmp_path), SOURCE)["error"] == "not_a_vault"
    assert up.main(["--vault", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


# ---- the environment guard --------------------------------------------------------------------------------------------

def test_an_installed_copy_must_run_in_the_workspace_venv(b, tmp_path):
    dest = installed(b)
    venv = b.path(".brain/python/.venv")
    os.makedirs(venv)
    assert cli.environment_problem(dest, prefix=venv) is None
    problem = cli.environment_problem(dest, prefix=str(tmp_path))
    assert problem and "workspace environment" in problem


def test_running_from_the_plugin_source_is_not_restricted(tmp_path):
    assert cli.environment_problem(SOURCE, prefix=str(tmp_path)) is None
