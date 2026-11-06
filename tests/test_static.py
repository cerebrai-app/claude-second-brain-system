"""Static checks on the plugin's skills and starters (formerly tests/check_static.py)."""
import glob
import os
import re

import pytest

from brainctl import util
from conftest import REPO

SKILLS = sorted(glob.glob(f"{REPO}/plugins/brain/skills/*/SKILL.md"))
STARTERS = sorted(glob.glob(f"{REPO}/plugins/brain/starters/*/*.md"))


def front(path):
    parsed = util.ParsedFile(open(path, encoding="utf-8").read())
    assert parsed.error is None, f"{path}: {parsed.error}"          # a colon inside an unquoted description once broke one
    assert parsed.front is not None, f"{path}: no front matter"
    return parsed.front


def test_the_expected_skills_exist():
    names = {os.path.basename(os.path.dirname(p)) for p in SKILLS}
    assert names == {"core", "setup", "capture", "triage", "sync", "pending", "run", "validate", "python", "backend", "upgrade"}


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_skill_front_matter(path):
    d = front(path)
    assert d.get("name") == os.path.basename(os.path.dirname(path))
    assert isinstance(d.get("description"), str) and d["description"].strip()


def test_mutating_skills_are_not_model_invocable():
    flags = {os.path.basename(os.path.dirname(p)): front(p).get("disable-model-invocation") for p in SKILLS}
    assert {n for n, v in flags.items() if v} == {"setup", "triage", "pending", "run", "upgrade"}


@pytest.mark.parametrize("path", STARTERS, ids=lambda p: os.path.basename(p))
def test_starters_hold_only_the_slug_field_and_file_storage_semantics(path):
    d = front(path)
    assert set(d) <= {"impl", "extends", "version", "schema", "storage"}
    assert d["schema"] == {"fields": {"slug": {"type": "string"}}}
    assert d["storage"]["adapter"] == "markdown" and "{slug}" in d["storage"]["path"]
    assert os.path.basename(path) == f"default-{d['extends']}.md"


def test_there_is_one_starter_per_extensible_type():
    assert sorted(os.path.basename(os.path.dirname(p)) for p in STARTERS) == ["area", "note", "person", "project", "task"]


def test_the_references_the_skills_point_at_exist():
    for ref in ("core-types.md", "storage.md", "automation.md"):
        assert os.path.isfile(f"{REPO}/plugins/brain/skills/core/references/{ref}")
    for ref in ("adapter-protocol.md", "spec-template.md", "adapter-template.py", "test-template.py"):
        assert os.path.isfile(f"{REPO}/plugins/brain/skills/backend/references/{ref}")


def test_relative_links_in_skills_resolve():
    link = re.compile(r"\]\((references/[^)#]+)\)")
    for path in SKILLS:
        for target in link.findall(open(path, encoding="utf-8").read()):
            assert os.path.exists(os.path.join(os.path.dirname(path), target)), f"{path}: broken link {target}"
