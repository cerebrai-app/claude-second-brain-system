"""The workspace script approval hash (docs/plans/11): SHA-256 over the script, every lib/**/*.py and pyproject.toml."""
import hashlib
import os


def approval_hash(python_dir, script):
    """`python_dir` is .brain/python; `script` is a path relative to it (for example scripts/x.py)."""
    files = {script.replace(os.sep, "/"), "pyproject.toml"}
    lib = os.path.join(python_dir, "lib")
    for dirpath, _dirs, names in os.walk(lib):
        for name in names:
            if name.endswith(".py"):
                files.add(os.path.relpath(os.path.join(dirpath, name), python_dir).replace(os.sep, "/"))
    digest = hashlib.sha256()
    for rel in sorted(files):
        with open(os.path.join(python_dir, rel), "rb") as f:
            data = f.read()
        digest.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()


class ApprovalError(Exception):
    pass


def approve(python_dir, names, by, at):
    """Record the current approval hash of registered scripts in registry.yml, keeping the file's comments and layout.

    `names` is a list of script names, or None for every script that is unapproved or changed since approval. Returns
    [(name, sha256)] for the scripts written. The caller shows the diff and asks the user first; this only records the answer."""
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString

    yaml = YAML()
    yaml.preserve_quotes = True
    path = os.path.join(python_dir, "registry.yml")
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f) or {}
    scripts = data.get("scripts") or []
    by_name = {s.get("name"): s for s in scripts if hasattr(s, "get")}
    missing = [n for n in (names or []) if n not in by_name]
    if missing:
        raise ApprovalError(f"not in the registry: {', '.join(missing)}")
    done = []
    for name, script in by_name.items():
        if names is not None and name not in names:
            continue
        digest = approval_hash(python_dir, script["path"])
        if names is None and (script.get("approved") or {}).get("sha256") == digest:
            continue
        script["approved"] = {"sha256": digest, "at": DoubleQuotedScalarString(at), "by": by}
        done.append((name, digest))
    if done:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
    return done
