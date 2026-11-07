"""The workspace approval hash (docs/plans/11)."""
import hashlib

from brainctl import approval


def make(b):
    b.write(".brain/python/scripts/a.py", "print(1)\n")
    return b.path(".brain/python")


def h(b, script="scripts/a.py"):
    return approval.approval_hash(b.path(".brain/python"), script)


def test_hash_is_a_sha256_hex_digest(b):
    make(b)
    assert len(h(b)) == 64 and int(h(b), 16) >= 0


def test_hash_follows_the_documented_recipe(b):
    py = make(b)
    b.write(".brain/python/lib/helper.py", "X = 1\n")
    d = hashlib.sha256()
    for rel in ("lib/helper.py", "pyproject.toml", "scripts/a.py"):               # sorted by path
        d.update(rel.encode() + b"\0" + open(f"{py}/{rel}", "rb").read() + b"\0")
    assert h(b) == d.hexdigest()


def test_script_lib_and_pyproject_all_change_the_hash(b):
    make(b)
    base = h(b)
    b.write(".brain/python/scripts/a.py", "print(2)\n")
    assert h(b) != base
    b.write(".brain/python/scripts/a.py", "print(1)\n")
    assert h(b) == base
    b.write(".brain/python/lib/helper.py", "X = 1\n")
    with_lib = h(b)
    assert with_lib != base
    b.edit(".brain/python/pyproject.toml", "dependencies = []", 'dependencies = ["x"]')
    assert h(b) != with_lib


def test_other_files_do_not_change_the_hash(b):
    make(b)
    base = h(b)
    b.write(".brain/python/lib/notes.txt", "not python\n")
    b.write(".brain/python/scripts/b.py", "print(3)\n")
    b.write(".brain/python/uv.lock", "version = 1\n# different lock\n")
    assert h(b) == base
