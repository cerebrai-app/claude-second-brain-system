#!/usr/bin/env python3
"""Copy the changed files of the plugin's brainctl into a vault's .brain/python/brainctl/ (standard library only).

    python3 upgrade.py --vault . [--source DIR] [--dry-run]

Compares byte for byte, copies files that are new or different, leaves files the plugin no longer ships alone (reports them),
and records the helper version in .brain/manifest.yml. Prints one JSON object. Exit 0 ok, 2 usage.
"""
import argparse
import json
import os
import re
import shutil
import sys

SKIP_DIRS = {"__pycache__"}


def shipped(source):
    """Relative paths of the helper's files: modules only, no tests or caches."""
    out = []
    for dirpath, dirs, names in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name.startswith("test_") or name.endswith((".pyc", ".pyo")):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, name), source).replace(os.sep, "/"))
    return out


def version_of(directory):
    try:
        with open(os.path.join(directory, "__init__.py"), encoding="utf-8") as fh:
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def record_version(manifest, version):
    """Set `helper_version: <v>` as a top-level line, replacing an existing one; nothing else in the file changes."""
    with open(manifest, encoding="utf-8") as fh:
        text = fh.read()
    line = f'helper_version: "{version}"'
    if re.search(r"^helper_version:.*$", text, re.M):
        new = re.sub(r"^helper_version:.*$", line, text, count=1, flags=re.M)
    else:
        new = text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    if new != text:
        with open(manifest, "w", encoding="utf-8") as fh:
            fh.write(new)


def upgrade(vault, source, dry_run=False):
    dest = os.path.join(vault, ".brain", "python", "brainctl")
    if not os.path.isdir(os.path.join(vault, ".brain")):
        return {"ok": False, "error": "not_a_vault", "message": f"no .brain directory in {vault}"}
    if not os.path.isdir(source):
        return {"ok": False, "error": "no_source", "message": f"no helper source at {source}"}
    wanted = shipped(source)
    added, changed, unchanged = [], [], []
    for rel in wanted:
        target = os.path.join(dest, rel)
        if not os.path.isfile(target):
            added.append(rel)
        elif read(target) != read(os.path.join(source, rel)):
            changed.append(rel)
        else:
            unchanged.append(rel)
    extra = []
    if os.path.isdir(dest):
        for rel in shipped(dest):
            if rel not in wanted:
                extra.append(rel)
    result = {"ok": True, "dry_run": dry_run, "from": version_of(dest), "to": version_of(source), "added": added, "changed": changed,
              "unchanged": len(unchanged), "not_shipped": extra, "copied": 0}
    if dry_run:
        return result
    for rel in added + changed:
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(source, rel), target)
        result["copied"] += 1
    manifest = os.path.join(vault, ".brain", "manifest.yml")
    if os.path.isfile(manifest) and result["to"]:
        record_version(manifest, result["to"])
    return result


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vault", default=".", help="vault root (default: current directory)")
    p.add_argument("--source", default=os.path.normpath(os.path.join(here, "..", "..", "tools", "brainctl")),
                   help="the plugin's brainctl directory (default: found relative to this script)")
    p.add_argument("--dry-run", action="store_true", help="report what would be copied; change nothing")
    args = p.parse_args(argv)
    result = upgrade(os.path.abspath(args.vault), os.path.abspath(args.source), args.dry_run)
    print(json.dumps(result, indent=1))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
