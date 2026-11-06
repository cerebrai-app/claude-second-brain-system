"""Small shared helpers: YAML, front matter, hashing, timestamps, path templates, git."""
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess

from ruamel.yaml import YAML

_yaml = YAML(typ="safe", pure=True)


def load_yaml(text):
    return _yaml.load(text)


def load_yaml_file(path):
    with open(path, encoding="utf-8") as f:
        return _yaml.load(f)


def yaml_scalar(value):
    """A YAML scalar for `value`, quoted whenever the plain form would load as something else (a date, a number, `yes`, ...)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    plain_ok = bool(text) and text == text.strip() and not re.search(r"[:#\n\r\t\"'\[\]{},&*!|>%@`]", text) and text[0] not in "-?"
    if plain_ok:
        try:
            plain_ok = load_yaml(f"v: {text}") == {"v": text}
        except Exception:
            plain_ok = False
    return text if plain_ok else json.dumps(text, ensure_ascii=False)


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_blob_hash(data):
    """The hash `git hash-object` gives a file's bytes (the markdown adapter's revision, docs/plans/03)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def jsonable(value):
    """Make YAML-loaded values JSON-serializable (dates become ISO strings)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, _dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(_dt.timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, _dt.date):
        return value.isoformat()
    return value


def dumps(obj):
    return json.dumps(jsonable(obj), indent=2, sort_keys=False, ensure_ascii=False)


# ---- front matter -----------------------------------------------------------------------------------------------------

class ParsedFile:
    """A markdown file split into front matter and body. `front` is None when there is none; `error` explains a parse failure."""

    def __init__(self, text):
        self.text = text
        self.front = None
        self.raw_front = None
        self.body = text
        self.error = None
        lines = text.split("\n")
        if not lines or lines[0].rstrip("\r ") != "---":
            return
        for i in range(1, len(lines)):
            if lines[i].rstrip("\r ") == "---":
                self.raw_front = "\n".join(lines[1:i])
                self.body = "\n".join(lines[i + 1:])
                try:
                    data = load_yaml(self.raw_front) if self.raw_front.strip() else {}
                except Exception as exc:  # ruamel raises several error types
                    self.error = f"front matter is not valid YAML ({str(exc).splitlines()[0]})"
                    return
                if data is None:
                    data = {}
                if not isinstance(data, dict):
                    self.error = "front matter is not a mapping"
                    return
                self.front = data
                return
        self.error = "front matter is not closed with ---"


def read_markdown(path):
    with open(path, "rb") as f:
        data = f.read()
    parsed = ParsedFile(data.decode("utf-8", errors="replace"))
    parsed.revision = git_blob_hash(data)
    return parsed


# ---- path templates (docs/plans/03) -----------------------------------------------------------------------------------

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)(?::([^}]*))?\}")
_STRFTIME = ("%Y", "%m", "%d", "%H", "%M", "%S")


def template_glob(template):
    return PLACEHOLDER.sub("*", template)


def template_names(template):
    return [m.group(1) for m in PLACEHOLDER.finditer(template)]


def _as_datetime(value):
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _sanitize(segment):
    return re.sub(r"[/\x00-\x1f]", "-", segment)


def render_path(template, values):
    """Render a path template for an item; None if a placeholder has no value. `values` holds slug, id, type, impl and fields."""
    def one(match):
        name, fmt = match.group(1), match.group(2)
        value = values.get(name)
        if value is None or isinstance(value, (dict, list)):
            raise KeyError(name)
        if fmt:
            when = _as_datetime(value)
            if when is None:
                raise KeyError(name)
            out = fmt
            for code in _STRFTIME:
                out = out.replace(code, {"%Y": f"{when.year:04d}", "%m": f"{when.month:02d}", "%d": f"{when.day:02d}",
                                         "%H": f"{when.hour:02d}", "%M": f"{when.minute:02d}", "%S": f"{when.second:02d}"}[code])
            return _sanitize(out)
        return _sanitize(str(jsonable(value)))
    try:
        return PLACEHOLDER.sub(one, template)
    except KeyError:
        return None


# ---- git ---------------------------------------------------------------------------------------------------------------

def is_git_repo(root):
    return os.path.isdir(os.path.join(root, ".git")) or os.path.isfile(os.path.join(root, ".git"))


def git_ignored(root, relpath):
    """True/False whether git would ignore `relpath`; None when git is unavailable or the root is not a repository."""
    if not is_git_repo(root):
        return None
    try:
        r = subprocess.run(["git", "check-ignore", "-q", "--", relpath], cwd=root, capture_output=True)
    except OSError:
        return None
    if r.returncode == 0:
        return True
    return False if r.returncode == 1 else None
