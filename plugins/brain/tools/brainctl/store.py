"""Deterministic writes for the markdown adapter (docs/plans/03 and 11): create, update, archive, unarchive, delete, convert.

Every command validates what it wrote and rolls back when the item does not pass, keeps unknown front matter keys and key order
(an update edits only the lines of the keys it changes), writes atomically, moves the file when the rendered path changes, and
updates the sync seen state for just the refs it touched, so the next `sync` does not report the helper's own writes.
Script-adapter bindings are not written by this module yet (they raise `unsupported`).
"""
import datetime as _dt
import json
import os
import re

from . import ids, schema, sync as sync_mod, util, validate as validate_mod
from .model import CORE_RELATIONS, CORE_STATUS, CORE_TYPES, COMMON_FIELDS, STATUS_TYPES, TYPE_FIELDS, Item, RESERVED

# keys the helper maintains; a caller may not set them
MANAGED = ("id", "slug", "created", "updated", "revision", "archive", "archived_at", "completed")
IMMUTABLE = ("id", "type", "impl", "created")
TIMESTAMP_KEYS = ("created", "updated", "archived_at", "completed")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PLACEMENT_RELATIONS = ("belongs_to", "area", "about")


class StoreError(Exception):
    """A storage error with a doc 03 code: not_found, conflict, invalid, unsupported or internal."""

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_dict(self):
        return dict({"code": self.code, "message": self.message}, **self.extra)


def now():
    return util.now_iso()


# ---- front matter text ------------------------------------------------------------------------------------------------

def _scalar(value, key=None):
    if value is None:
        return "null"
    if key in TIMESTAMP_KEYS and isinstance(value, str) and ISO_RE.match(value):
        return value
    return util.yaml_scalar(value)


def format_entry(key, value, indent=0):
    """The front matter lines for one key. Strings that would load as another YAML type are quoted."""
    pad = " " * indent
    name = util.yaml_scalar(key) if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$", str(key)) else str(key)
    value = util.jsonable(value)
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{name}: {{}}"]
        out = [f"{pad}{name}:"]
        for k, v in value.items():
            out += format_entry(k, v, indent + 2)
        return out
    if isinstance(value, list):
        if not value:
            return [f"{pad}{name}: []"]
        if all(not isinstance(v, (dict, list)) for v in value):
            return [f"{pad}{name}:"] + [f"{pad}  - {_scalar(v)}" for v in value]
        return [f"{pad}{name}: {json.dumps(value, ensure_ascii=False)}"]
    return [f"{pad}{name}: {_scalar(value, key if indent == 0 else None)}"]


_TOP_KEY = re.compile(r"^([^\s#:-][^:]*|-[^\s:][^:]*):(\s|$)")


def _blocks(raw):
    """Split front matter text into [key or None, [lines]] blocks. Trailing comments/blank lines stay separate from a key's block."""
    blocks = []
    for line in raw.split("\n") if raw else []:
        match = _TOP_KEY.match(line)
        if match:
            blocks.append([match.group(1).strip().strip('"').strip("'"), [line]])
        elif blocks and blocks[-1][0] is not None and (line.startswith((" ", "\t", "- ")) or line == "-"):
            blocks[-1][1].append(line)
        else:
            blocks.append([None, [line]])
    return blocks


def edit_front(raw, changes, removes=()):
    """Rewrite only the blocks of the keys in `changes` (replace or insert) and `removes`; every other line is untouched.

    A new key goes just before `created` when there is one, else at the end of the keys."""
    blocks = _blocks(raw)
    for key in removes:
        blocks = [b for b in blocks if b[0] != key]
    for key, value in changes.items():
        lines = format_entry(key, value)
        for block in blocks:
            if block[0] == key:
                block[1] = lines
                break
        else:
            position = next((i for i, b in enumerate(blocks) if b[0] == "created"), None)
            if position is None:
                position = max([i + 1 for i, b in enumerate(blocks) if b[0] is not None] or [0])
            blocks.insert(position, [key, lines])
    return "\n".join(line for _key, lines in blocks for line in lines)


def dump_front(front):
    return "\n".join(line for key, value in front.items() for line in format_entry(key, value))


def join_file(raw_front, body):
    return f"---\n{raw_front}\n---\n{body}"


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _remove(path):
    os.remove(path)


def _prune_empty(vault, relpath):
    """Remove the now-empty directories above a file that was rolled back, so a refused write leaves no trace."""
    folder = os.path.dirname(vault.path(relpath))
    while folder != vault.root and os.path.isdir(folder) and not os.listdir(folder):
        os.rmdir(folder)
        folder = os.path.dirname(folder)


# ---- finding things ---------------------------------------------------------------------------------------------------

def find_item(vault, ref, archived_ok=False):
    scan = vault.scan(remote=False)
    matches = [i for i in scan.items if i.ref == ref]
    live = [i for i in matches if not i.archived]
    if len(live) > 1 or (not live and len(matches) > 1):
        raise StoreError("conflict", f"{ref} exists in more than one place: " + ", ".join(i.relpath for i in matches))
    pool = live or ([i for i in matches] if archived_ok else [])
    if not pool:
        raise StoreError("not_found", f"no {'live ' if not archived_ok else ''}item {ref}")
    item = pool[0]
    if item.relpath.startswith("script:"):
        raise StoreError("unsupported", f"{ref} is stored by a script adapter; this helper writes markdown bindings only")
    return item


def _markdown_impl(vault, type_, name):
    impl = vault.impl_for(type_, name)
    if impl is None or impl.error:
        raise StoreError("invalid", f"implementation {type_}/{name} is not defined or not valid")
    if impl.adapter != "markdown":
        raise StoreError("unsupported", f"{type_}/{name} uses the {impl.adapter!r} adapter; this helper writes markdown bindings only")
    return impl


def _category(impl, status):
    return status if status in CORE_STATUS else (impl.status_values or {}).get(status)


def _item_for(vault, relpath, binding_archived=False):
    parsed = util.read_markdown(vault.path(relpath))
    if parsed.error or parsed.front is None:
        raise StoreError("internal", f"{relpath} could not be read back: {parsed.error}")
    front = parsed.front
    return Item(relpath, front, parsed.body, parsed.revision, ("archive", "archive") if binding_archived else (front.get("type"), front.get("impl")), binding_archived)


# ---- default implementation (doc 01: Project -> Area -> Inbox) --------------------------------------------------------

def resolve_impl(vault, type_, front):
    if type_ == "person":
        actives = [i for i in vault.impls_of("person") if not i.migration_target and not i.error]
        if not actives:
            raise StoreError("invalid", "no person implementation is defined")
        return actives[0].name
    scan = vault.scan(remote=False)
    by_ref = {}
    for item in scan.items:
        by_ref.setdefault(item.ref, item)

    def defaults_of(ref, seen=()):
        item = by_ref.get(ref)
        if item is None or ref in seen:
            return None
        found = (item.front.get("defaults") or {}).get(type_)
        if found:
            return found
        if item.type == "project":
            for target in _as_list(item.front.get("area")):
                found = defaults_of(target, seen + (ref,))
                if found:
                    return found
        return None

    for relation in PLACEMENT_RELATIONS:
        for target in _as_list(front.get(relation)):
            found = defaults_of(target)
            if found:
                return found
    found = defaults_of("area:inbox")
    if found:
        return found
    raise StoreError("invalid", f"no default {type_} implementation: set `defaults.{type_}` on the project, its area or the Inbox, or pass `impl`")


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


# ---- normalisation ----------------------------------------------------------------------------------------------------

def normalize_tags(tags):
    if tags is None:
        return {}
    if isinstance(tags, list):
        tags = {str(t): "" for t in tags}
    if not isinstance(tags, dict):
        raise StoreError("invalid", "tags must be a map or a list of names")
    out = {}
    for name, value in tags.items():
        key = str(name).strip().lower()
        if not key or re.search(r"\s", key):
            raise StoreError("invalid", f"bad tag name {name!r}: non-empty, no whitespace")
        if isinstance(value, (list, dict)):
            raise StoreError("invalid", f"tag {name!r}: a value must be a string")
        if key in out:
            raise StoreError("invalid", f"tag {name!r} is given twice")
        out[key] = "" if value is None else str(value)
    return out


def _normalize(type_, front):
    out = dict(front)
    if "tags" in out:
        out["tags"] = normalize_tags(out["tags"])
    for relation in CORE_RELATIONS[type_]:
        if relation in out and out[relation] is not None:
            out[relation] = _as_list(out[relation])
    if type_ == "person" and isinstance(out.get("name"), str):
        out["name"] = {"display": out["name"]}
    return out


def _title_source(type_, front):
    if type_ == "person":
        from .model import display_name
        return display_name(front.get("name")) if isinstance(front.get("name"), dict) else None
    title = front.get("title")
    return title if isinstance(title, str) and title.strip() else None


# ---- paths ------------------------------------------------------------------------------------------------------------

def _values(front):
    values = dict(front)
    return values


def _live_path(impl, front):
    path = util.render_path(impl.path_template, _values(front))
    if path is None:
        raise StoreError("invalid", f"the path template {impl.path_template!r} needs a value that the item does not have")
    return path


def _archive_path(vault, front):
    template = vault.archive_template()
    if template is None:
        raise StoreError("unsupported", "the Archive is not a markdown binding; this helper cannot archive into it")
    values = _values(front)
    values.setdefault("slug", front.get("id"))
    path = util.render_path(template, values)
    if path is None:
        raise StoreError("invalid", f"the archive path {template!r} needs a value that the item does not have")
    return path


def _unique_slug(vault, impl, front, source):
    probe = dict(front, slug="__slug__")
    rendered = util.render_path(impl.path_template, probe)
    directory = vault.path(os.path.dirname(rendered)) if rendered else None
    taken = ids.stems(directory) if directory and os.path.isdir(directory) else set()
    return ids.unique_slug(ids.slugify(source), taken)


# ---- validation, seen state, log --------------------------------------------------------------------------------------

def _problems(vault, item):
    """Errors validate reports for this item's ref, plus its non-error findings as warnings."""
    found = validate_mod.validate(vault, item.ref)
    errors = [f for f in found if f["severity"] == "error" and (f["subject"] == item.ref or item.relpath in f["message"])]
    warnings = [f for f in found if f["severity"] == "warning" and f["subject"] == item.ref]
    return errors, warnings


def _seen(vault, upsert=(), remove=()):
    entries, any_state = sync_mod._read_seen(vault)
    if not any_state:
        return
    snapshots = {ref: (e["impl"], e["archived"], e["snapshot"]) for ref, e in entries.items()}
    for ref in remove:
        snapshots.pop(ref, None)
    for item in upsert:
        snapshots[item.ref] = (item.impl if not item.archived else "archive", item.archived, sync_mod.snapshot(vault, item))
    bindings = sorted((t, n) for (t, n), i in vault.impls.items() if i.adapter in ("markdown", "script") and not i.error)
    sync_mod._write_seen(vault, snapshots, bindings)


def log(vault, command, ref=None, outcome="ok", **extra):
    entry = {"ts": now(), "command": command}
    if ref:
        entry["ref"] = ref
    entry["outcome"] = outcome
    entry.update(extra)
    path = vault.path(".brain/automation/log.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(util.jsonable(entry), ensure_ascii=False) + "\n")


def _result(vault, item, command, warnings=(), **extra):
    return dict({"ok": True, "command": command, "ref": item.ref, "path": item.relpath, "revision": item.revision,
                 "front": util.jsonable(item.front), "warnings": [w["message"] for w in warnings]}, **extra)


def _fail_validation(errors, command):
    raise StoreError("invalid", f"{command} would leave the item invalid; nothing was changed",
                     findings=[{"code": f["code"], "message": f["message"]} for f in errors])


# ---- create -----------------------------------------------------------------------------------------------------------

def create(vault, spec):
    spec = dict(spec or {})
    type_ = spec.pop("type", None)
    if type_ not in CORE_TYPES:
        raise StoreError("invalid", f"`type` must be one of {', '.join(CORE_TYPES)}")
    banned = [k for k in MANAGED if k in spec]
    if banned:
        raise StoreError("invalid", f"the helper sets {', '.join(banned)}; do not pass them")
    impl_name = spec.pop("impl", None)
    body = spec.pop("body", "")
    if "id" in spec:
        raise StoreError("invalid", "the helper assigns the id")
    front_in = _normalize(type_, spec)
    impl_name = impl_name or resolve_impl(vault, type_, front_in)
    impl = _markdown_impl(vault, type_, impl_name)
    if impl.extends != type_:
        raise StoreError("invalid", f"{impl_name} does not extend {type_}")
    if type_ != "person" and not _title_source(type_, front_in):
        raise StoreError("invalid", "`title` is required and must be non-empty")
    if type_ == "person" and not _title_source(type_, front_in):
        raise StoreError("invalid", "`name` is required (a display name, or a map with given/family)")

    stamp = now()
    front = {"id": ids.ulid()}
    front["type"] = type_
    front["impl"] = impl_name
    head = ["title"] if type_ != "person" else ["name"]
    if type_ in STATUS_TYPES and "status" not in front_in:
        front_in = dict({head[0]: front_in[head[0]], "status": "open"}, **{k: v for k, v in front_in.items() if k != head[0]})
    for key, value in front_in.items():
        front[key] = value
    for name, value in schema.defaults_for(impl.fields, front).items():
        front[name] = value
    if type_ in STATUS_TYPES and _category(impl, front.get("status")) in ("done", "dropped"):
        front["completed"] = stamp
    if "slug" in impl.fields:
        slug = _unique_slug(vault, impl, front, _title_source(type_, front))
        front = dict([("id", front.pop("id")), ("slug", slug)] + list(front.items()))
    front["created"] = stamp
    front["updated"] = stamp

    relpath = _live_path(impl, front)
    if os.path.exists(vault.path(relpath)):
        raise StoreError("conflict", f"{relpath} already exists")
    write_atomic(vault.path(relpath), join_file(dump_front(front), body or ""))
    item = _item_for(vault, relpath)
    errors, warnings = _problems(vault, item)
    if errors:
        _remove(vault.path(relpath))
        _prune_empty(vault, relpath)
        _fail_validation(errors, "create")
    _seen(vault, upsert=[item])
    log(vault, "create", item.ref)
    return _result(vault, item, "create", warnings)


# ---- update -----------------------------------------------------------------------------------------------------------

def update(vault, ref, patch):
    patch = dict(patch or {})
    item = find_item(vault, ref)
    if item.archived:
        raise StoreError("invalid", f"{ref} is archived; unarchive it first")
    expected = patch.get("revision")
    if expected and expected != item.revision:
        raise StoreError("conflict", f"{ref} changed since you read it (revision {item.revision[:8]}, expected {str(expected)[:8]})", revision=item.revision)
    sets = dict(patch.get("set") or {})
    unsets = list(patch.get("unset") or [])
    for key in list(sets) + unsets:
        if key in MANAGED or key in IMMUTABLE or key in ("type", "impl"):
            raise StoreError("invalid", f"{key!r} is maintained by the helper and cannot be set or removed")
    if set(sets) & set(unsets):
        raise StoreError("invalid", "a key cannot be both set and unset")
    impl = _markdown_impl(vault, item.type, item.impl)
    sets = _normalize(item.type, sets)
    if item.type == "person" and "title" in sets:
        raise StoreError("invalid", "a person has `name`, not `title`")

    new_front = dict(item.front)
    for key in unsets:
        new_front.pop(key, None)
    new_front.update(sets)
    changes = {k: v for k, v in sets.items() if k not in item.front or util.jsonable(item.front[k]) != util.jsonable(v)}
    removes = [k for k in unsets if k in item.front]
    new_body = patch.get("body")
    body_changed = new_body is not None and new_body != item.body
    # completed follows the status category (doc 08)
    if item.type in STATUS_TYPES and "status" in changes:
        category = _category(impl, new_front.get("status"))
        if category in ("done", "dropped") and not item.front.get("completed"):
            changes["completed"] = now()
            new_front["completed"] = changes["completed"]
        elif category == "open" and item.front.get("completed") is not None:
            removes.append("completed")
            new_front.pop("completed", None)
    if not changes and not removes and not body_changed:
        return _result(vault, item, "update", changed=[], moved=False)
    stamp = now()
    changes["updated"] = stamp
    new_front["updated"] = stamp
    parsed = util.read_markdown(vault.path(item.relpath))
    new_raw = edit_front(parsed.raw_front, changes, removes)
    text = join_file(new_raw, new_body if body_changed else parsed.body)

    new_rel = _live_path(impl, new_front)
    moved = new_rel != item.relpath
    old_text = parsed.text
    if moved and os.path.exists(vault.path(new_rel)):
        raise StoreError("conflict", f"{new_rel} already exists")
    write_atomic(vault.path(new_rel), text)
    if moved:
        _remove(vault.path(item.relpath))
    stored = _item_for(vault, new_rel)
    errors, warnings = _problems(vault, stored)
    if errors:
        write_atomic(vault.path(item.relpath), old_text)
        if moved:
            _remove(vault.path(new_rel))
            _prune_empty(vault, new_rel)
        _fail_validation(errors, "update")
    _seen(vault, upsert=[stored])
    changed = sorted(k for k in list(changes) + removes if k != "updated") + (["body"] if body_changed else [])
    log(vault, "update", stored.ref, changed=changed)
    return _result(vault, stored, "update", warnings, changed=changed, moved=moved, previous_path=item.relpath if moved else None)


# ---- archive / unarchive ----------------------------------------------------------------------------------------------

def archive(vault, ref):
    item = find_item(vault, ref)
    if item.type not in CORE_TYPES or item.id in ("inbox", "archive") or item.front.get("system"):
        raise StoreError("invalid", f"{ref} is a system item and cannot be archived")
    stamp = now()
    new_front = dict(item.front, archive="archive:archive", archived_at=stamp, updated=stamp)
    new_rel = _archive_path(vault, new_front)
    if os.path.exists(vault.path(new_rel)):
        raise StoreError("conflict", f"{new_rel} already exists")
    parsed = util.read_markdown(vault.path(item.relpath))
    raw = edit_front(parsed.raw_front, {"archive": "archive:archive", "archived_at": stamp, "updated": stamp})
    write_atomic(vault.path(new_rel), join_file(raw, parsed.body))
    try:
        _remove(vault.path(item.relpath))
    except OSError as exc:
        raise StoreError("internal", f"{ref} was copied to {new_rel} but {item.relpath} could not be removed ({exc}); it now exists twice", path=new_rel)
    stored = _item_for(vault, new_rel, binding_archived=True)
    errors, warnings = _problems(vault, stored)
    _seen(vault, upsert=[stored])
    log(vault, "archive", ref)
    return _result(vault, stored, "archive", warnings, previous_path=item.relpath, validation_errors=[f["message"] for f in errors])


def unarchive(vault, ref):
    item = find_item(vault, ref, archived_ok=True)
    if not item.archived:
        raise StoreError("invalid", f"{ref} is not archived")
    impl = _markdown_impl(vault, item.type, item.impl)
    stamp = now()
    new_front = {k: v for k, v in item.front.items() if k not in ("archive", "archived_at")}
    new_front["updated"] = stamp
    new_rel = _live_path(impl, new_front)
    if os.path.exists(vault.path(new_rel)):
        raise StoreError("conflict", f"{new_rel} already exists; restoring {ref} would overwrite another item")
    parsed = util.read_markdown(vault.path(item.relpath))
    raw = edit_front(parsed.raw_front, {"updated": stamp}, ["archive", "archived_at"])
    write_atomic(vault.path(new_rel), join_file(raw, parsed.body))
    try:
        _remove(vault.path(item.relpath))
    except OSError as exc:
        raise StoreError("internal", f"{ref} was copied to {new_rel} but {item.relpath} could not be removed ({exc}); it now exists twice", path=new_rel)
    stored = _item_for(vault, new_rel)
    errors, warnings = _problems(vault, stored)
    _seen(vault, upsert=[stored])
    log(vault, "unarchive", ref)
    return _result(vault, stored, "unarchive", warnings, previous_path=item.relpath, validation_errors=[f["message"] for f in errors])


# ---- delete -----------------------------------------------------------------------------------------------------------

def delete(vault, ref, confirm):
    if confirm != "permanent":
        raise StoreError("invalid", "delete is permanent; pass --confirm permanent")
    item = find_item(vault, ref, archived_ok=True)
    if item.front.get("system") or item.id in ("inbox", "archive"):
        raise StoreError("invalid", f"{ref} is a system item and cannot be deleted")
    scan = vault.scan(remote=False)
    referenced_by = sorted({i.ref for i in scan.items if i.ref != ref and any(ref in _as_list(i.front.get(r)) for r in i.relation_names(vault.impl_for(i.type, i.impl), set(vault.traits)))})
    _remove(vault.path(item.relpath))
    _seen(vault, remove=[ref])
    log(vault, "delete", ref)
    return {"ok": True, "command": "delete", "ref": ref, "path": item.relpath, "referenced_by": referenced_by}


# ---- convert ----------------------------------------------------------------------------------------------------------

LEFT_ALONE = ("id", "type", "impl", "created", "updated", "slug", "archive", "archived_at")


def _convert_plan(vault, item, target_name):
    source = _markdown_impl(vault, item.type, item.impl)
    target = _markdown_impl(vault, item.type, target_name)
    if target.name == source.name:
        raise StoreError("invalid", f"{item.ref} is already {target_name}")
    trait_names = set(vault.traits)
    rel_names = set(CORE_RELATIONS[item.type]) | set(item.relation_names(source, trait_names))
    core = COMMON_FIELDS | TYPE_FIELDS[item.type] | rel_names | ({"traits"} | trait_names if item.type == "person" else set())
    plan = {"ref": item.ref, "from": item.impl, "to": target_name, "carried": [], "unmapped": [], "invalid": [], "missing": [],
            "filled_by_default": {}, "dropped": []}
    for key, value in item.front.items():
        if key in LEFT_ALONE or key.startswith("_"):
            continue
        if key == "status" and item.type in STATUS_TYPES:
            category = _category(target, value)
            if category is None:
                plan["invalid"].append({"field": key, "value": util.jsonable(value), "reason": f"status {value!r} is not defined by {target_name}"})
                continue
        if key in core:
            plan["carried"].append(key)
        elif key in target.fields:
            problems = [m for s, m in schema.check_value(key, target.fields[key], value) if s == "error"]
            if problems:
                plan["invalid"].append({"field": key, "value": util.jsonable(value), "reason": problems[0]})
            else:
                plan["carried"].append(key)
        elif key in source.fields:
            plan["unmapped"].append({"field": key, "value": util.jsonable(value)})
        else:
            plan["carried"].append(key)             # an unknown key is preserved, like everywhere else
    if "slug" in item.front and "slug" not in target.fields:
        plan["dropped"].append("slug")
    carried_front = {k: item.front[k] for k in plan["carried"]}
    for name, spec in target.fields.items():
        if name == "slug" or name in carried_front:
            continue
        if isinstance(spec, dict) and "default" in spec:
            plan["filled_by_default"][name] = spec["default"]
        elif isinstance(spec, dict) and spec.get("required"):
            plan["missing"].append({"field": name, "type": spec.get("type")})
    plan["body"] = "carried"
    plan["needs_resolution"] = bool(plan["unmapped"] or plan["invalid"] or plan["missing"])
    return source, target, plan


def convert_plan(vault, ref, target_name):
    item = find_item(vault, ref)
    _source, target, plan = _convert_plan(vault, item, target_name)
    plan["ok"] = True
    plan["path_from"] = item.relpath
    return plan


def convert_apply(vault, ref, target_name, resolutions):
    resolutions = resolutions or {}
    item = find_item(vault, ref)
    _source, target, plan = _convert_plan(vault, item, target_name)
    drop = set(resolutions.get("drop") or [])
    rename = dict(resolutions.get("rename") or {})
    fill = dict(resolutions.get("fill") or {})
    front = dict(item.front)
    unresolved = []
    for entry in plan["unmapped"] + plan["invalid"]:
        field = entry["field"]
        if field in drop:
            front.pop(field, None)
        elif field in rename:
            front[rename[field]] = front.pop(field)
        elif field in fill:
            front[field] = fill[field]
        else:
            unresolved.append(field)
    for entry in plan["missing"]:
        field = entry["field"]
        if field in fill:
            front[field] = fill[field]
        else:
            unresolved.append(field)
    if unresolved:
        raise StoreError("invalid", "resolve every reported field first (drop, rename or fill): " + ", ".join(unresolved), plan=plan)
    stamp = now()
    front["impl"] = target_name
    front["updated"] = stamp
    for name, value in schema.defaults_for(target.fields, front).items():
        front[name] = value
    if "slug" in target.fields and "slug" not in front:
        front["slug"] = _unique_slug(vault, target, front, _title_source(item.type, front) or item.id)
    if "slug" not in target.fields:
        front.pop("slug", None)
    for key, value in front.items():
        if key in target.fields and key not in LEFT_ALONE:
            bad = [m for s, m in schema.check_value(key, target.fields[key], value) if s == "error"]
            if bad:
                raise StoreError("invalid", f"{key} is still invalid for {target_name}: {bad[0]}", plan=plan)
    new_rel = _live_path(target, front)
    if os.path.exists(vault.path(new_rel)):
        raise StoreError("conflict", f"{new_rel} already exists")
    parsed = util.read_markdown(vault.path(item.relpath))
    changes = {k: v for k, v in front.items() if k not in item.front or util.jsonable(item.front[k]) != util.jsonable(v)}
    removes = [k for k in item.front if k not in front]
    raw = edit_front(parsed.raw_front, changes, removes)
    old_text = parsed.text
    write_atomic(vault.path(new_rel), join_file(raw, parsed.body))
    marker = vault.path(f".brain/conversions/{item.type}-{item.id}.json")
    try:
        _remove(vault.path(item.relpath))
    except OSError as exc:
        write_atomic(marker, json.dumps({"ref": ref, "from": {"impl": item.impl, "path": item.relpath},
                                         "to": {"impl": target_name, "path": new_rel}, "at": stamp}) + "\n")
        raise StoreError("internal", f"{ref} was created as {new_rel} but the source {item.relpath} could not be deleted ({exc}); "
                                     f"it exists twice. A marker was written; finish the conversion later.", marker=vault.rel(marker))
    stored = _item_for(vault, new_rel)
    errors, warnings = _problems(vault, stored)
    if errors:
        write_atomic(vault.path(item.relpath), old_text)
        _remove(vault.path(new_rel))
        _prune_empty(vault, new_rel)
        _fail_validation(errors, "convert")
    _seen(vault, upsert=[stored])
    log(vault, "convert", ref, to=target_name)
    return _result(vault, stored, "convert", warnings, previous_path=item.relpath, plan=plan)


def finish_conversion(vault, ref):
    """Complete an interrupted conversion: delete the source named in the marker (the target already exists) and clear the marker."""
    type_, _, ident = ref.partition(":")
    marker_path = vault.path(f".brain/conversions/{type_}-{ident}.json")
    if not os.path.isfile(marker_path):
        raise StoreError("not_found", f"no conversion marker for {ref}")
    with open(marker_path, encoding="utf-8") as fh:
        marker = json.load(fh)
    source, target = marker["from"]["path"], marker["to"]["path"]
    if not os.path.isfile(vault.path(target)):
        raise StoreError("conflict", f"the target {target} is missing; do not delete the source {source}")
    if os.path.isfile(vault.path(source)):
        _remove(vault.path(source))
    _remove(marker_path)
    stored = _item_for(vault, target)
    _seen(vault, upsert=[stored])
    log(vault, "convert-finish", ref)
    return _result(vault, stored, "convert-finish", removed=source)


def revision_of(vault, ref):
    """The current revision (git blob hash) of an item, or None."""
    try:
        return find_item(vault, ref, archived_ok=True).revision
    except StoreError:
        return None
