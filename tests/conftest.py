"""Shared fixtures: a clean scratch vault built the way `/brain:setup` builds one (minus the real uv workspace)."""
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "plugins", "brain", "tools")
STARTERS = os.path.join(REPO, "plugins", "brain", "starters")
sys.path.insert(0, TOOLS)

from brainctl import ids, util  # noqa: E402
from brainctl.model import Vault  # noqa: E402

CORE = ("task", "note", "project", "area", "person")
GITIGNORE = """__pycache__/
.venv
lib/
!.brain/python/lib/
.brain/index/
.brain/cache/
.brain/automation/seen/
.brain/automation/pending/
.brain/automation/log.jsonl
.brain/conversions/
.brain/python/outputs/
"""


class Builder:
    """Builds and edits a scratch vault on disk. Item files are written the way the skills describe."""

    def __init__(self, root):
        self.root = str(root)

    # ---- files ---------------------------------------------------------------------------------------------------
    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        full = self.path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
        return full

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def remove(self, rel):
        os.remove(self.path(rel))

    def exists(self, rel):
        return os.path.exists(self.path(rel))

    def edit(self, rel, old, new):
        text = self.read(rel)
        assert old in text, f"{old!r} not in {rel}"
        self.write(rel, text.replace(old, new, 1))

    def add_front(self, rel, lines):
        """Add front matter lines before `updated` (what a plugin write does) and refresh `updated`."""
        text = self.read(rel)
        text = text.replace("\nupdated:", "\n" + lines + "updated:", 1)
        self.write(rel, text)

    # ---- the vault ---------------------------------------------------------------------------------------------------
    def setup(self, workspace=True):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        self.write(".gitignore", GITIGNORE)
        for t in CORE:
            os.makedirs(self.path(f".brain/impls/{t}"), exist_ok=True)
            shutil.copy(os.path.join(STARTERS, t, f"default-{t}.md"), self.path(f".brain/impls/{t}/default-{t}.md"))
        self.write(".brain/config.yml",
                   'version: 1\nname: scratch\narchive:\n  adapter: markdown\n  path: "archive/{type}/{impl}/{slug}.md"\n'
                   "impls: .brain/impls\npython:\n  tool: uv\ncapture:\n  type_by_source: {}\n")
        now = util.now_iso()
        self.write("areas/inbox.md",
                   f"---\nid: inbox\nslug: inbox\ntype: area\nimpl: default-area\ntitle: Inbox\nsystem: true\ndefaults:\n"
                   f"  task: default-task\n  note: default-note\n  project: default-project\n  area: default-area\n"
                   f"created: {now}\nupdated: {now}\n---\n")
        if workspace:
            self.write(".brain/python/pyproject.toml", '[project]\nname = "brain-workspace"\nversion = "0.1.0"\nrequires-python = ">=3.12"\ndependencies = []\n')
            self.write(".brain/python/uv.lock", "version = 1\n")
            self.write(".brain/python/registry.yml", "scripts: []\n")
            for d in ("scripts", "lib", "tests"):
                self.write(f".brain/python/{d}/.gitkeep", "")
        self.write_manifest()
        return self

    def install_helper(self):
        """Copy the helper into the workspace the way `/brain:setup` does (modules only, no caches or tests)."""
        src = os.path.join(TOOLS, "brainctl")
        dst = self.path(".brain/python/brainctl")
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
        return dst

    def write_manifest(self):
        lines = ["core_version: 1", "migrations: []", "implementations:"]
        for (t, n) in sorted(self.vault().impls):
            lines.append(f"  {t}/{n}: {{ version: 1 }}")
        traits = sorted(self.vault().traits)
        lines.append("traits:" + (" {}" if not traits else ""))
        lines += [f"  {t}: {{ version: 1 }}" for t in traits]
        self.write(".brain/manifest.yml", "\n".join(lines) + "\n")

    def vault(self):
        return Vault(self.root)

    def impl(self, type_, name, fields="", extra="", path=None, version=1):
        """Add an implementation definition. `fields` and `extra` are YAML text (already indented for the front matter)."""
        path = f"{type_}s/{name}/{{slug}}.md" if path is None else path
        text = f"---\nimpl: {name}\nextends: {type_}\nversion: {version}\n"
        if fields:
            text += f"schema:\n  fields:\n{fields}"
        text += f'storage:\n  adapter: markdown\n  path: "{path}"\n{extra}---\n'
        self.write(f".brain/impls/{type_}/{name}.md", text)
        self.write_manifest()

    def trait(self, name, fields="    employer: { type: string }\n"):
        self.write(f".brain/traits/{name}.md", f"---\ntrait: {name}\nversion: 1\nschema:\n  fields:\n{fields}---\n")
        self.write_manifest()

    # ---- items -------------------------------------------------------------------------------------------------------
    def item(self, type_, impl, directory, title, extra="", slug=None, body="", ident=None, name_block=None):
        """Create an item file: ULID id, unique zero-padded slug, front matter. Returns (id, slug)."""
        d = self.path(directory)
        s = ids.unique_slug(slug or ids.slugify(title), ids.stems(d))
        i, t = ident or ids.ulid(), util.now_iso()
        head = name_block if name_block else f"title: {util.yaml_scalar(title)}\n"
        self.write(f"{directory}/{s}.md", f"---\nid: {i}\nslug: {util.yaml_scalar(s)}\ntype: {type_}\nimpl: {impl}\n{head}{extra}created: {t}\nupdated: {t}\n---\n{body}")
        return i, s


@pytest.fixture
def b(tmp_path):
    """A clean, valid scratch vault (no items besides the Inbox)."""
    return Builder(tmp_path).setup()


@pytest.fixture
def vault_of():
    return lambda builder: builder.vault()


def codes(findings, severity=None):
    return sorted({f["code"] for f in findings if severity is None or f["severity"] == severity})
