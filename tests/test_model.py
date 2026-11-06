"""Path templates and scanning the markdown adapter."""
import datetime as dt
import os

import pytest

from brainctl import util
from brainctl.model import display_name


# ---- path templates (docs/plans/03) ----------------------------------------------------------------------------------

def test_template_glob_and_names():
    assert util.template_glob("tasks/{status}/{slug}.md") == "tasks/*/*.md"
    assert util.template_names("journal/{created:%Y-%m-%d}.md") == ["created"]


@pytest.mark.parametrize("template, values, expected", [
    ("tasks/{slug}.md", {"slug": "draft-q4-plan"}, "tasks/draft-q4-plan.md"),
    ("tasks/{status}/{slug}.md", {"slug": "a", "status": "open"}, "tasks/open/a.md"),
    ("journal/{date}.md", {"date": dt.date(2026, 11, 6)}, "journal/2026-11-06.md"),
    ("journal/{created:%Y-%m-%d}.md", {"created": "2026-11-06T09:30:00Z"}, "journal/2026-11-06.md"),
    ("journal/{created:%Y}/{created:%m}/{slug}.md", {"created": dt.datetime(2026, 1, 2, 3, 4, 5), "slug": "x"}, "journal/2026/01/x.md"),
    ("journal/{created:%Y/%m}/{slug}.md", {"created": dt.datetime(2026, 1, 2, 3, 4, 5), "slug": "x"}, "journal/2026-01/x.md"),  # a "/" inside a format is sanitized
    ("notes/{title}.md", {"title": "a/b"}, "notes/a-b.md"),            # path separators in a value are sanitized
])
def test_render_path(template, values, expected):
    assert util.render_path(template, values) == expected


def test_render_path_without_a_value_is_none():
    assert util.render_path("tasks/{slug}.md", {}) is None
    assert util.render_path("j/{created:%Y}.md", {"created": "not a date"}) is None


def test_git_blob_hash_matches_git(tmp_path):
    import subprocess
    f = tmp_path / "x.md"
    f.write_bytes(b"hello\n")
    expected = subprocess.run(["git", "hash-object", str(f)], capture_output=True, text=True).stdout.strip()
    assert util.git_blob_hash(b"hello\n") == expected


# ---- front matter -----------------------------------------------------------------------------------------------------

def test_front_matter_parsing():
    p = util.ParsedFile("---\nid: 1\ntitle: T\n---\nbody\nmore")
    assert p.front == {"id": 1, "title": "T"} and p.body == "body\nmore" and p.error is None


def test_no_front_matter():
    p = util.ParsedFile("# Just a heading\ntext")
    assert p.front is None and p.error is None and p.body.startswith("# Just")


def test_empty_front_matter():
    assert util.ParsedFile("---\n---\nbody").front == {}


@pytest.mark.parametrize("text", ["---\ntitle: [unclosed\n---\n", "---\n- a\n- b\n---\n", "---\ntitle: x\n"])
def test_bad_front_matter_is_an_error(text):
    assert util.ParsedFile(text).error


def test_display_name():
    assert display_name({"given": "Alex", "family": "Rivera"}) == "Alex Rivera"
    assert display_name({"display": "Lex", "given": "Alex"}) == "Lex"
    assert display_name({"nickname": "Lex"}) == "Lex"
    assert display_name({"given": " "}) is None


# ---- scanning ---------------------------------------------------------------------------------------------------------

def test_scan_finds_items_in_every_binding(b):
    b.item("task", "default-task", "tasks", "One", "status: open\n")
    b.item("note", "default-note", "notes", "Two")
    scan = b.vault().scan()
    assert {i.ref.split(":")[0] for i in scan.items} == {"task", "note", "area"}      # the Inbox is an item too
    assert scan.problems == [] and scan.unadopted == []


def test_scan_reports_unadopted_unparseable_and_wrong_binding(b):
    b.write("notes/by-hand.md", "# By hand\n")
    b.write("notes/broken.md", "---\ntitle: [oops\n---\n")
    b.item("task", "default-task", "notes", "In the wrong directory", "status: open\n")
    scan = b.vault().scan()
    assert [u[2] for u in scan.unadopted] == ["notes/by-hand.md"]
    assert {p[0] for p in scan.problems} == {"unparseable-file", "wrong-binding"}


def test_scan_ambiguous_directory(b):
    b.impl("note", "twin", path="notes/{slug}.md")            # same directory pattern as default-note
    b.write("notes/by-hand.md", "just text\n")
    scan = b.vault().scan()
    assert scan.unadopted == []
    assert [p[0] for p in scan.problems] == ["ambiguous-file"]


def test_scan_reads_archived_items(b):
    i, _ = b.item("note", "default-note", "archive/note/default-note", "Old", "archive: archive:archive\narchived_at: 2026-11-06T00:00:00Z\n")
    scan = b.vault().scan()
    assert [x.ref for x in scan.items if x.archived] == [f"note:{i}"]


def test_scan_skips_script_adapters(b):
    b.write(".brain/impls/task/remote.md", "---\nimpl: remote\nextends: task\nversion: 1\nstorage:\n  adapter: script\n  command: python:remote\n---\n")
    assert [s[:2] for s in b.vault().scan().skipped] == [("task", "remote")]


def test_vault_discovery_walks_up(b):
    deep = os.path.join(b.root, ".brain", "python")
    os.makedirs(deep, exist_ok=True)
    from brainctl.model import Vault
    assert Vault.discover(deep).root == os.path.abspath(b.root)
    assert Vault.discover("/") is None


# ---- writing YAML scalars safely ------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["2026-11-06", "yes", "010", "1.5", "true", "null", "a: b", "# not a comment", " padded ", "", "[x]", "- dash", "it's"])
def test_yaml_scalar_round_trips_ambiguous_strings(value):
    assert util.load_yaml("v: " + util.yaml_scalar(value)) == {"v": value}


@pytest.mark.parametrize("value", ["Draft Q4 plan", "idea-from-the-bus", "Café"])
def test_yaml_scalar_leaves_plain_strings_alone(value):
    assert util.yaml_scalar(value) == value
