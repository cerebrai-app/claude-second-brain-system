#!/usr/bin/env python3
"""Static checks for the plugin's skills and starters. Needs PyYAML (see TESTING.md).

    python3 tests/check_static.py
"""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def frontmatter(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        failures.append(f"{path}: no frontmatter")
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        failures.append(f"{path}: invalid YAML frontmatter ({str(e).splitlines()[0]})")
        return None


# Skills: valid frontmatter, name equals directory, description present.
for f in sorted(glob.glob(f"{ROOT}/plugins/brain/skills/*/SKILL.md")):
    d = frontmatter(f)
    if d is None:
        continue
    folder = os.path.basename(os.path.dirname(f))
    if d.get("name") != folder:
        failures.append(f"{f}: name {d.get('name')!r} != directory {folder!r}")
    if not d.get("description"):
        failures.append(f"{f}: missing description")

# Starters: only storage semantics (docs/plans/09).
allowed = {"impl", "extends", "version", "storage"}
for f in sorted(glob.glob(f"{ROOT}/plugins/brain/starters/*/*.md")):
    d = frontmatter(f)
    if d is None:
        continue
    extra = set(d) - allowed
    if extra:
        failures.append(f"{f}: keys beyond file storage semantics: {sorted(extra)}")
    if d.get("storage", {}).get("adapter") != "markdown" or "{slug}" not in d.get("storage", {}).get("path", ""):
        failures.append(f"{f}: storage must be the markdown adapter with a {{slug}} path")
    if os.path.basename(f) != f"default-{d.get('extends')}.md":
        failures.append(f"{f}: file name does not match extends")

if failures:
    print("\n".join(failures))
    sys.exit(1)
print("static checks passed")
