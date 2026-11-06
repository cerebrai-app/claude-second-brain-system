"""Template resolution for rule values (docs/plans/05, "Template variables"): `{{ name }}` and `{{ name | filter }}`.

Deterministic, so a rule never depends on Claude to fill in a date or format a list. Built-in variables:
  today  the current date, YYYY-MM-DD, in the vault's time zone (config.yml `timezone`, default UTC)
  now    the current instant, UTC, YYYY-MM-DDThh:mm:ssZ
Other variables are bindings the caller supplies (a `surface` result set bound with `as:`). Filters format a list of items
(`{ref, fields, ...}`): checklist, bullets, refs, table.
"""
import datetime as _dt
import re

TEMPLATE_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BUILTINS = ("today", "now")


class TemplateError(Exception):
    pass


# ---- context ----------------------------------------------------------------------------------------------------------

def zone(name):
    """A tzinfo for an IANA name (None or '' means UTC). Raises TemplateError for an unknown name."""
    if not name or name.upper() == "UTC":
        return _dt.timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception as exc:                                    # ZoneInfoNotFoundError, ValueError, missing tzdata
        raise TemplateError(f"unknown time zone {name!r}") from exc


def builtins(tz_name=None, now=None):
    """{'today': ..., 'now': ...}. `now` is an aware or naive-UTC datetime (default: the current instant)."""
    instant = now or _dt.datetime.now(_dt.timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_dt.timezone.utc)
    return {
        "today": instant.astimezone(zone(tz_name)).strftime("%Y-%m-%d"),
        "now": instant.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---- parsing ----------------------------------------------------------------------------------------------------------

def parse(template):
    """[(name, [filters])] for each `{{ ... }}` in the string. Raises TemplateError on bad syntax."""
    out = []
    stripped = TEMPLATE_RE.sub("", template)
    if "{{" in stripped or "}}" in stripped:
        raise TemplateError(f"unbalanced braces in {template!r}")
    for match in TEMPLATE_RE.finditer(template):
        parts = [p.strip() for p in match.group(1).split("|")]
        name, filters = parts[0], parts[1:]
        if not NAME_RE.match(name):
            raise TemplateError(f"bad variable name {name!r} in {match.group(0)!r}")
        for flt in filters:
            if flt not in FILTERS:
                raise TemplateError(f"unknown filter {flt!r} in {match.group(0)!r} (known: {', '.join(sorted(FILTERS))})")
        out.append((name, filters))
    return out


def check(template, known):
    """Problems with a template string, given the variable names that are in scope: [message]. Never raises."""
    try:
        refs = parse(template)
    except TemplateError as exc:
        return [str(exc)]
    return [f"unknown variable {name!r} (in scope: {', '.join(sorted(known)) or 'none'})" for name, _ in refs if name not in known]


# ---- filters ----------------------------------------------------------------------------------------------------------

def _title(item):
    fields = item.get("fields") or {}
    name = fields.get("name")
    if isinstance(name, dict):
        return name.get("display") or " ".join(str(v) for v in (name.get("given"), name.get("family")) if v) or item.get("ref", "")
    return str(fields.get("title") or item.get("ref", ""))


def _items(value, filter_name):
    if not isinstance(value, list) or not all(isinstance(i, dict) for i in value):
        raise TemplateError(f"filter {filter_name!r} needs a list of items, got {type(value).__name__}")
    return value


def _checklist(value):
    rows = []
    for item in _items(value, "checklist"):
        done = (item.get("fields") or {}).get("status") in ("done", "dropped")
        rows.append(f"- [{'x' if done else ' '}] {_title(item)}")
    return "\n".join(rows)


def _bullets(value):
    return "\n".join(f"- {_title(item)}" for item in _items(value, "bullets"))


def _refs(value):
    return ", ".join(str(item.get("ref", "")) for item in _items(value, "refs"))


def _cell(value):
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(value):
    items = _items(value, "table")
    if not items:
        return ""
    columns = ["title"]
    for item in items:
        for key, val in (item.get("fields") or {}).items():
            if key not in columns and key not in ("name",) and not isinstance(val, (dict, list)):
                columns.append(key)
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for item in items:
        fields = item.get("fields") or {}
        lines.append("| " + " | ".join(_cell(_title(item) if c == "title" else fields.get(c)) for c in columns) + " |")
    return "\n".join(lines)


FILTERS = {"checklist": _checklist, "bullets": _bullets, "refs": _refs, "table": _table}


# ---- rendering --------------------------------------------------------------------------------------------------------

def _text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        raise TemplateError("a list or map needs a filter (checklist, bullets, refs or table)")
    return str(value)


def render(template, variables):
    """Replace every `{{ name | filter }}` in `template`. `variables` maps name to value. Raises TemplateError."""
    parse(template)                                             # syntax and filter names first, so errors do not depend on data

    def one(match):
        parts = [p.strip() for p in match.group(1).split("|")]
        name = parts[0]
        if name not in variables:
            raise TemplateError(f"unknown variable {name!r} (in scope: {', '.join(sorted(variables)) or 'none'})")
        value = variables[name]
        for flt in parts[1:]:
            value = FILTERS[flt](value)
        return _text(value)

    return TEMPLATE_RE.sub(one, template)


def resolve(value, variables):
    """Render every string inside a nested dict/list (keys are left alone). Other values are returned unchanged."""
    if isinstance(value, str):
        return render(value, variables) if "{{" in value or "}}" in value else value
    if isinstance(value, list):
        return [resolve(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, variables) for k, v in value.items()}
    return value


def strings(value):
    """Every string inside a nested dict/list, for checking."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
