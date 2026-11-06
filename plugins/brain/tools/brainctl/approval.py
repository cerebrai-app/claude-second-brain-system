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
