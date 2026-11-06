"""`brainctl sync`: detect changes made outside the plugin and adopt hand-written files (docs/plans/05, "Detecting changes made outside the plugin").

Matching is by ref across all bindings, so a conversion is one `update` with `impl` in `changed`. The seen state is
`.brain/automation/seen/<type>/<impl>.json`. Events are returned to the caller, which dispatches them; sync runs no rules.
"""
import hashlib
import json
import os

from . import ids, schema, util
from .model import CORE_STATUS, PLACEMENT, STATUS_TYPES


# ---- seen state -------------------------------------------------------------------------------------------------------

def _seen_path(vault, type_, impl):
    return vault.path(f".brain/automation/seen/{type_}/{impl}.json")


def _read_seen(vault):
    """Return (entries, any_state). entries: ref -> {"impl", "archived", "snapshot"} across every seen-state file."""
    entries, any_state = {}, False
    seen_root = vault.path(".brain/automation/seen")
    if not os.path.isdir(seen_root):
        return entries, any_state
    for type_dir in sorted(os.listdir(seen_root)):
        folder = os.path.join(seen_root, type_dir)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            any_state = True
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            for ref, snap in (data.get("entries") or {}).items():
                entries[ref] = {"impl": data.get("impl"), "archived": bool(data.get("archived")), "snapshot": snap}
    return entries, any_state


def _write_seen(vault, snapshots, bindings):
    """Rewrite one seen-state file per binding from the current snapshots. `snapshots`: ref -> (impl, archived, snapshot)."""
    for type_, impl in bindings:
        entries = {ref: snap for ref, (i, archived, snap) in snapshots.items() if i == impl and not archived and ref.startswith(type_ + ":")}
        path = _seen_path(vault, type_, impl)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"impl": impl, "checkpoint": None, "entries": entries}, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    archived = {ref: snap for ref, (i, a, snap) in snapshots.items() if a}
    path = _seen_path(vault, "archive", "archive")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"impl": "archive", "archived": True, "checkpoint": None, "entries": archived}, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def snapshot(vault, item):
    """Compact snapshot for the seen state: revision, fields, relations (no body, only its hash)."""
    impl = vault.impl_for(item.type, item.impl)
    relations = item.relations(impl, set(vault.traits))
    rel_names = set(relations)
    fields = {k: util.jsonable(v) for k, v in item.front.items() if k not in rel_names and k not in ("id", "type", "impl")}
    return {
        "revision": item.revision,
        "fields": fields,
        "relations": {k: util.jsonable(v) for k, v in relations.items()},
        "body_sha": hashlib.sha256(item.body.encode("utf-8")).hexdigest(),
    }


def _changed(old, new, old_impl, new_impl):
    names = set()
    for key in set(old["fields"]) | set(new["fields"]):
        if key == "updated":
            continue
        if old["fields"].get(key) != new["fields"].get(key):
            names.add(key)
    for key in set(old["relations"]) | set(new["relations"]):
        if sorted(old["relations"].get(key, [])) != sorted(new["relations"].get(key, [])):
            names.add(key)
    if old.get("body_sha") != new.get("body_sha"):
        names.add("body")
    if old_impl != new_impl:
        names.add("impl")
    return sorted(names)


# ---- the Inbox --------------------------------------------------------------------------------------------------------

def in_inbox(item):
    """Placed types (task, note, project) with no placement relation, or one pointing at area:inbox. Areas and persons are top-level."""
    relation = PLACEMENT.get(item.type)
    if not relation or item.archived:
        return False
    targets = item.front.get(relation) or []
    if not isinstance(targets, list):
        targets = [targets]
    if item.type == "note":
        targets = [t for t in targets if isinstance(t, str) and (t.startswith("project:") or t.startswith("area:"))]
    return not targets or targets == ["area:inbox"]


# ---- adoption (docs/plans/05) -----------------------------------------------------------------------------------------

def _heading(body):
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _yaml_scalar(value):
    return util.yaml_scalar(value)


def plan_adoption(vault, type_, impl_name, relpath, parsed):
    """Return (additions, problems). additions: ordered dict of frontmatter keys to add; problems: why it cannot be adopted."""
    impl = vault.impl_for(type_, impl_name)
    front = parsed.front or {}
    stem = os.path.splitext(os.path.basename(relpath))[0]
    full = vault.path(relpath)
    additions = {}
    problems = []
    if "type" in front and front["type"] != type_:
        problems.append(f"type is {front['type']!r} but the directory belongs to {type_}")
    if "impl" in front and front["impl"] != impl_name:
        problems.append(f"impl is {front['impl']!r} but the directory belongs to {impl_name}")
    if "id" not in front:
        additions["id"] = ids.ulid()
    if "type" not in front:
        additions["type"] = type_
    if "impl" not in front:
        additions["impl"] = impl_name
    if "slug" not in front:
        additions["slug"] = stem
    merged = dict(front)
    merged.update(additions)
    if type_ == "person":
        if "name" not in merged:
            additions["name"] = {"display": _heading(parsed.body) or stem.replace("-", " ")}
    elif "title" not in merged:
        additions["title"] = _heading(parsed.body) or stem.replace("-", " ")
    if type_ in STATUS_TYPES and "status" not in merged:
        additions["status"] = "open"
    stamp = util.now_iso()
    if "created" not in front:
        created = _first_commit_time(vault, relpath) or _mtime(full) or stamp
        additions["created"] = created
    if "updated" not in front:
        additions["updated"] = stamp
    merged.update(additions)
    for name, value in schema.defaults_for(impl.fields if impl else {}, merged).items():
        additions[name] = value
    merged.update(additions)
    if impl:
        for severity, _code, message in schema.check_fields(merged, impl.fields):
            if severity == "error":
                problems.append(message)
    return additions, problems


COMPLETABLE = ("slug", "title", "name", "status", "created", "updated")


def plan_completion(vault, item):
    """Identity fields a hand-written item that already has an id, type and impl is missing: slug, title or name, status, created,
    updated. Returns the additions (possibly empty). Schema defaults are not filled and nothing existing is touched."""
    if item.archived or item.relpath.startswith("script:"):
        return {}
    parsed = util.read_markdown(vault.path(item.relpath))
    if parsed.error or parsed.front is None:
        return {}
    additions, _problems = plan_adoption(vault, item.type, item.impl, item.relpath, parsed)
    return {k: v for k, v in additions.items() if k in COMPLETABLE and k not in parsed.front}


def _mtime(path):
    import datetime as dt
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def _first_commit_time(vault, relpath):
    if not util.is_git_repo(vault.root):
        return None
    import subprocess
    try:
        r = subprocess.run(["git", "log", "--diff-filter=A", "--follow", "--format=%cI", "--", relpath], cwd=vault.root, capture_output=True, text=True)
    except OSError:
        return None
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if r.returncode != 0 or not lines:
        return None
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(lines[-1]).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def adopt_file(vault, relpath, parsed, additions):
    """Insert the missing keys at the top of the front matter. Never touches existing keys, their order, or the body."""
    lines = []
    for key, value in additions.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {k}: {_yaml_scalar(v)}" for k, v in value.items()]
        elif isinstance(value, list):
            lines.append(f"{key}:" + (" []" if not value else ""))
            lines += [f"  - {_yaml_scalar(v)}" for v in value]
        else:
            lines.append(f"{key}: {_yaml_scalar(value) if key not in ('created', 'updated') else value}")
    block = "\n".join(lines) + "\n"
    text = parsed.text
    if parsed.front is not None and parsed.raw_front is not None:
        first_newline = text.index("\n") + 1
        new_text = text[:first_newline] + block + text[first_newline:]
    else:
        new_text = "---\n" + block + "---\n" + text
    with open(vault.path(relpath), "w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)


# ---- sync -------------------------------------------------------------------------------------------------------------

def sync(vault, adopt=True, dry_run=False, refresh=False):
    """Return {"events", "report"}. With dry_run nothing is written (no adoption, no seen state).

    With refresh the current state is accepted as seen, with no events and no adoption: use it after the plugin's own writes so
    they are not later reported as outside changes.
    """
    if refresh:
        return _refresh(vault)
    scan = vault.scan()
    report = {
        "baseline": False,
        "adopted": [],
        "unadopted": [],
        "invalid": [],
        "missing": [],
        "incomplete": [{"binding": f"{t}/{n}", "reason": r} for t, n, r in scan.skipped],
        "problems": [{"code": c, "path": p, "message": m} for c, p, m in scan.problems],
    }
    # adoption (the main session's job in the design; the helper performs it when asked)
    events = []
    pending_adopt = []
    for type_, impl_name, relpath, parsed in scan.unadopted:
        additions, problems = plan_adoption(vault, type_, impl_name, relpath, parsed)
        if problems:
            report["invalid"].append({"path": relpath, "reasons": problems})
            report["unadopted"].append(relpath)
        elif adopt and not dry_run:
            adopt_file(vault, relpath, parsed, additions)
            report["adopted"].append(relpath)
            pending_adopt.append(relpath)
        else:
            report["unadopted"].append(relpath)
    # items that already have an id but lack identity fields (a slug, say): complete them additively, like adoption
    report["completed"] = []
    report["incomplete_identity"] = []
    for item in scan.items:
        additions = plan_completion(vault, item)
        if not additions:
            continue
        if adopt and not dry_run:
            adopt_file(vault, item.relpath, util.read_markdown(vault.path(item.relpath)), additions)
            report["completed"].append({"path": item.relpath, "added": sorted(additions)})
            pending_adopt.append(item.relpath)
        else:
            report["incomplete_identity"].append({"path": item.relpath, "missing": sorted(additions)})
    if pending_adopt:
        scan = vault.scan()

    old, any_state = _read_seen(vault)
    unreadable = {(t, n) for t, n, _ in scan.skipped}      # a binding that failed to read must not make its items look deleted
    report["baseline"] = not any_state
    refs = scan.by_ref()
    current = {}
    detected = util.now_iso()
    for ref, items in refs.items():
        live = [i for i in items if not i.archived]
        item = live[0] if live else items[0]
        current[ref] = item
    snapshots = {ref: (it.impl if not it.archived else "archive", it.archived, snapshot(vault, it)) for ref, it in current.items()}
    held_back = set()  # invalid external changes: not advanced, so they are reported again until fixed

    if not report["baseline"]:
        for ref, item in current.items():
            impl = vault.impl_for(item.type, item.impl)
            new_snap = snapshots[ref][2]
            was = old.get(ref)
            if was is None or was["snapshot"].get("revision") != new_snap["revision"] or was["impl"] != snapshots[ref][0] or was["archived"] != item.archived:
                bad = _invalid_reasons(vault, item, impl)
                if bad:
                    report["invalid"].append({"path": item.relpath, "ref": ref, "reasons": bad})
                    held_back.add(ref)
                    continue
            origin = f"external/{item.type}/{item.impl}"
            base = {"ref": ref, "type": item.type, "impl": item.impl, "origin": origin, "depth": 0, "detected_at": detected,
                    "revision": new_snap["revision"], "path": item.relpath}
            if was is None:
                events.append(dict(base, trigger="create", after=new_snap))
                if in_inbox(item):
                    events.append(dict(base, trigger="capture", after=new_snap))
                continue
            old_snap = was["snapshot"]
            if was["archived"] != item.archived:
                events.append(dict(base, trigger="archive" if item.archived else "unarchive", before=old_snap, after=new_snap))
                continue
            if old_snap.get("revision") != new_snap["revision"] or was["impl"] != item.impl:
                changed = _changed(old_snap, new_snap, was["impl"], item.impl)
                events.append(dict(base, trigger="update", changed=changed, before=old_snap, after=new_snap))
                for name in sorted(set(old_snap["relations"]) | set(new_snap["relations"])):
                    before = set(old_snap["relations"].get(name, []))
                    after = set(new_snap["relations"].get(name, []))
                    if before != after:
                        events.append(dict(base, trigger="relation", relation=name, added=sorted(after - before), removed=sorted(before - after)))
        for ref, was in old.items():
            if ref not in current and (ref.split(":", 1)[0], was["impl"]) not in unreadable:
                report["missing"].append(ref)
    else:
        for ref, item in current.items():
            bad = _invalid_reasons(vault, item, vault.impl_for(item.type, item.impl))
            if bad:
                report["invalid"].append({"path": item.relpath, "ref": ref, "reasons": bad})

    if not dry_run:
        write = {ref: val for ref, val in snapshots.items() if ref not in held_back}
        # keep the previous snapshot for held-back items so they are detected again
        for ref in held_back:
            if ref in old:
                write[ref] = (old[ref]["impl"], old[ref]["archived"], old[ref]["snapshot"])
        # items that vanished stay out of the new state; they are in the report
        # a binding that could not be read is not rewritten, so its previous state stays
        _write_seen(vault, write, _readable_bindings(vault, scan))
    return {"events": events, "report": report}


def _readable_bindings(vault, scan):
    skipped = {(t, n) for t, n, _ in scan.skipped}
    return sorted((t, n) for (t, n), i in vault.impls.items() if i.adapter in ("markdown", "script") and not i.error and (t, n) not in skipped)


def _refresh(vault):
    scan = vault.scan()
    snapshots = {}
    for item in scan.items:
        if item.ref in snapshots and item.archived:
            continue
        snapshots[item.ref] = (item.impl if not item.archived else "archive", item.archived, snapshot(vault, item))
    _write_seen(vault, snapshots, _readable_bindings(vault, scan))
    report = {"baseline": False, "adopted": [], "unadopted": [u[2] for u in scan.unadopted], "invalid": [], "missing": [], "incomplete": [], "problems": [],
              "refreshed": len(snapshots)}
    return {"events": [], "report": report}


def _invalid_reasons(vault, item, impl):
    """Schema problems that stop rules from running on an externally created or changed item."""
    if impl is None or impl.error:
        return [f"implementation {item.type}/{item.impl} has no valid definition"]
    out = [message for severity, _code, message in schema.check_fields(item.front, impl.fields) if severity == "error"]
    if item.type in STATUS_TYPES:
        status = item.front.get("status")
        if status is None:
            out.append("status is required")
        elif status not in set(CORE_STATUS) | set(impl.status_values):
            out.append(f"status {status!r} is not valid")
    if item.type == "person":
        name = item.front.get("name")
        if not isinstance(name, dict) or not any(isinstance(v, str) and v.strip() for v in name.values()):
            out.append("name needs at least one non-empty part")
    else:
        title = item.front.get("title")
        if not isinstance(title, str) or not title.strip():
            out.append("title is required")
    return out
