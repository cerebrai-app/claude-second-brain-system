import hashlib, pathlib, sys
script = pathlib.Path(sys.argv[1])
files = sorted([script, pathlib.Path("pyproject.toml")] + [p for p in pathlib.Path("lib").rglob("*.py")], key=str)
h = hashlib.sha256()
for p in files:
    h.update(str(p).encode() + b"\0" + p.read_bytes() + b"\0")
print(h.hexdigest())
