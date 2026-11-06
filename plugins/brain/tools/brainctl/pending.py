"""Rule operations and the pending-approval queue (docs/plans/05, "Pending approvals" and "Logging").

`apply_operation` is the deterministic executor for the operation set (`set_field`, `set_relation`, `add_relation`, `archive`,
`unarchive`, `create_item`) that built-in actions, hooks and approved `claude` proposals all produce. The queue functions write, list,
apply and reject `.brain/automation/pending/*.json` entries; applying one re-checks that the item has not changed since the proposal.
Approval itself is a human decision that the skill obtains; these functions only act on it.
"""
import datetime as _dt
import json
import os
import re

from . import store, util
from .model import LOG_OUTCOMES
from .store import StoreError

OPERATIONS = ("set_field", "set_relation", "add_relation", "archive", "unarchive", "create_item")
DEFAULT_EXPIRY_DAYS = 14


def _need(op, *keys):
    missing = [k for k in keys if k not in op]
    if missing:
        raise StoreError("invalid", f"operation {op.get('op')!r} needs {', '.join(missing)}")


def apply_operation(vault, op):
    """Run one operation; returns the store result. Raises StoreError (a bad or failing operation changes nothing)."""
    if isinstance(op, dict) and "op" not in op and "action" in op:          # a rule action works as it is written
        op = dict(op, op=op["action"])
    if not isinstance(op, dict) or op.get("op") not in OPERATIONS:
        raise StoreError("unsupported", f"operation {op.get('op') if isinstance(op, dict) else op!r} is not one of {', '.join(OPERATIONS)}")
    kind = op["op"]
    if kind == "set_field":
        _need(op, "ref", "field", "value")
        return store.update(vault, op["ref"], {"set": {op["field"]: op["value"]}, "revision": op.get("revision")})
    if kind in ("set_relation", "add_relation"):
        _need(op, "ref", "relation")
        current = store.find_item(vault, op["ref"])
        existing = store._as_list(current.front.get(op["relation"]))
        if kind == "set_relation":
            _need(op, "value")
            value = store._as_list(op["value"])
        else:
            _need(op, "target")
            targets = store._as_list(op["target"])
            value = existing + [t for t in targets if t not in existing]
        if value == existing:
            return store.update(vault, op["ref"], {})
        if not value:
            return store.update(vault, op["ref"], {"unset": [op["relation"]], "revision": op.get("revision")})
        return store.update(vault, op["ref"], {"set": {op["relation"]: value}, "revision": op.get("revision")})
    if kind == "archive":
        _need(op, "ref")
        return store.archive(vault, op["ref"])
    if kind == "unarchive":
        _need(op, "ref")
        return store.unarchive(vault, op["ref"])
    return _create_item(vault, op)


PLACEMENT = {"task": "belongs_to", "note": "about", "project": "area"}


def _resolve_place(vault, place, for_type):
    """The ref a `place:` points at: a ref (or list of refs), or {find: {type, impl?, where}, create_if_missing}."""
    relation = PLACEMENT.get(for_type)
    if relation is None:
        raise StoreError("invalid", f"a {for_type} is top-level and is never placed")
    if isinstance(place, (str, list)):
        return relation, store._as_list(place), None
    find = place.get("find") if isinstance(place, dict) else None
    if not isinstance(find, dict) or not find.get("type"):
        raise StoreError("invalid", "place must be a ref or {find: {type, where}, create_if_missing}")
    where = dict(find.get("where") or {})
    rows, _scan = store.find_items(vault, find["type"], find.get("impl"), where)
    if len(rows) > 1:
        raise StoreError("conflict", f"place matches more than one {find['type']}: " + ", ".join(r.ref for r in rows))
    if rows:
        return relation, [rows[0].ref], None
    if not place.get("create_if_missing"):
        raise StoreError("not_found", f"place finds no {find['type']} matching {where}")
    if any("." in key for key in where):
        raise StoreError("invalid", "create_if_missing needs plain field names in `where`")
    made = store.create(vault, dict(where, type=find["type"], **({"impl": find["impl"]} if find.get("impl") else {})))
    return relation, [made["ref"]], made["ref"]


def _create_item(vault, op):
    _need(op, "type")
    unless = op.get("unless_exists")
    if unless:
        if not isinstance(unless, dict) or not unless.get("type") or not isinstance(unless.get("where"), dict) or not unless["where"]:
            raise StoreError("invalid", "unless_exists needs a `type` and a non-empty `where`")
        rows, _scan = store.find_items(vault, unless["type"], unless.get("impl"), unless["where"])
        if rows:
            return {"ok": True, "command": "create_item", "skipped": "exists", "ref": rows[0].ref, "path": rows[0].relpath}
    spec = dict(op.get("fields") or {})
    spec["type"] = op["type"]
    for key in ("impl", "body", "title", "name"):
        if key in op:
            spec[key] = op[key]
    created_placement = None
    if op.get("place"):
        relation, targets, created_placement = _resolve_place(vault, op["place"], op["type"])
        spec.setdefault(relation, targets)
    result = store.create(vault, spec)
    if created_placement:
        result["created_placement"] = created_placement
    return result


# ---- the queue --------------------------------------------------------------------------------------------------------

def _dir(vault):
    return vault.path(".brain/automation/pending")


def _stamp(when):
    return when.strftime("%Y%m%dT%H%M%SZ")


def _entry_path(vault, entry_id):
    if not re.match(r"^[A-Za-z0-9_.@-]+$", entry_id or ""):
        raise StoreError("invalid", f"bad pending id {entry_id!r}")
    return os.path.join(_dir(vault), entry_id + ".json")


def _read(vault, entry_id):
    path = _entry_path(vault, entry_id)
    if not os.path.isfile(path):
        raise StoreError("not_found", f"no pending entry {entry_id}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _parse_rule(rule):
    if isinstance(rule, str):
        parts = rule.split("/")
        if len(parts) == 3:
            return {"type": parts[0], "impl": parts[1], "id": parts[2]}
        if len(parts) == 2 and parts[0] == "vault":
            return {"type": "vault", "impl": "vault", "id": parts[1]}
        raise StoreError("invalid", "rule must be <type>/<impl>/<rule-id> or vault/<rule-id>")
    if isinstance(rule, dict) and all(isinstance(rule.get(k), str) for k in ("type", "impl", "id")):
        return {k: rule[k] for k in ("type", "impl", "id")}
    raise StoreError("invalid", "rule must be {type, impl, id}")


def add(vault, spec):
    """Queue a `claude` proposal. spec: rule, event (a sync event), instruction, rationale, operations."""
    rule = _parse_rule(spec.get("rule"))
    event = spec.get("event")
    if not isinstance(event, dict) or not event.get("ref") or not event.get("trigger"):
        raise StoreError("invalid", "event must be a sync event with at least `ref` and `trigger` (copy it from `brainctl sync`)")
    operations = spec.get("operations")
    if not isinstance(operations, list) or not operations:
        raise StoreError("invalid", "operations must be a non-empty list")
    for op in operations:
        if not isinstance(op, dict) or op.get("op") not in OPERATIONS:
            raise StoreError("unsupported", f"operation {op!r} is not one of {', '.join(OPERATIONS)}")
    if not spec.get("rationale"):
        raise StoreError("invalid", "a proposal needs a rationale")
    created = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    days = int(spec.get("expires_days") or vault.config_get("pending_expiry_days", default=DEFAULT_EXPIRY_DAYS))
    entry_id = f"{_stamp(created)}-{rule['type']}-{rule['impl']}-{rule['id']}"
    path = _entry_path(vault, entry_id)
    n = 2
    while os.path.exists(path):
        entry_id = f"{_stamp(created)}-{rule['type']}-{rule['impl']}-{rule['id']}-{n:02d}"
        path, n = _entry_path(vault, entry_id), n + 1
    revision = spec.get("revision") or store.revision_of(vault, event["ref"])
    entry = {
        "id": entry_id, "status": "pending",
        "created": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": (created + _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": rule,
        "event": {k: event[k] for k in ("id", "trigger", "ref", "origin", "depth") if k in event},
        "instruction": spec.get("instruction", ""),
        "revision": revision,
        "rationale": spec["rationale"],
        "operations": operations,
    }
    store.write_atomic(path, json.dumps(util.jsonable(entry), indent=2, ensure_ascii=False) + "\n")
    store.log(vault, "pending-add", event["ref"], outcome="queued", rule=f"{rule['type']}/{rule['impl']}/{rule['id']}", event=event.get("id"), pending=entry_id)
    return {"ok": True, "id": entry_id, "path": vault.rel(path), "expires": entry["expires"]}


def _state(vault, entry, today):
    if entry.get("expires") and entry["expires"] < today:
        return "expired"
    ref = (entry.get("event") or {}).get("ref")
    current = store.revision_of(vault, ref) if ref else None
    if ref and current is None:
        return "stale"
    if entry.get("revision") and current and entry["revision"] != current:
        return "stale"
    return "fresh"


def list_entries(vault, prune=False):
    """Every pending entry with its state: fresh, stale (the item changed or is gone) or expired. `prune` drops expired ones."""
    folder = _dir(vault)
    today = util.now_iso()
    out = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            out.append({"id": name[:-5], "state": "unreadable"})
            continue
        state = _state(vault, entry, today)
        if prune and state == "expired":
            os.remove(os.path.join(folder, name))
            store.log(vault, "pending-expire", (entry.get("event") or {}).get("ref"), outcome="expired", pending=entry.get("id"))
            continue
        out.append({"id": entry.get("id", name[:-5]), "state": state, "rule": entry.get("rule"), "ref": (entry.get("event") or {}).get("ref"),
                    "created": entry.get("created"), "expires": entry.get("expires"), "rationale": entry.get("rationale"),
                    "operations": entry.get("operations")})
    return {"ok": True, "count": len(out), "entries": out}


def apply(vault, entry_id, operations=None):
    """Apply an approved entry (optionally with the user's edited operations). Refuses a stale or expired entry."""
    entry = _read(vault, entry_id)
    state = _state(vault, entry, util.now_iso())
    if state != "fresh":
        raise StoreError("conflict", f"{entry_id} is {state}: re-check the proposal against the item's current state before applying", state=state)
    ops = operations if operations is not None else entry.get("operations")
    applied = []
    for op in ops:
        try:
            apply_operation(vault, op)
        except StoreError as err:
            store.log(vault, "pending-apply", (entry.get("event") or {}).get("ref"), outcome="failed", error=err.message, pending=entry_id)
            raise StoreError(err.code, f"operation {len(applied) + 1} failed after {len(applied)} applied: {err.message}", applied=applied, pending=entry_id)
        applied.append(op)
    os.remove(_entry_path(vault, entry_id))
    rule = entry["rule"]
    store.log(vault, "pending-apply", (entry.get("event") or {}).get("ref"), outcome="approved-applied",
              rule=f"{rule['type']}/{rule['impl']}/{rule['id']}", event=(entry.get("event") or {}).get("id"), pending=entry_id, operations=len(applied))
    return {"ok": True, "id": entry_id, "applied": len(applied)}


def reject(vault, entry_id):
    entry = _read(vault, entry_id)
    os.remove(_entry_path(vault, entry_id))
    store.log(vault, "pending-reject", (entry.get("event") or {}).get("ref"), outcome="rejected", pending=entry_id)
    return {"ok": True, "id": entry_id, "rejected": True}


def append_log(vault, spec):
    """Append a rule-run line (docs/plans/05, Logging) after checking the outcome vocabulary."""
    outcome = spec.get("outcome")
    if outcome not in LOG_OUTCOMES:
        raise StoreError("invalid", f"outcome must be one of {', '.join(LOG_OUTCOMES)}")
    if outcome == "skipped" and not spec.get("reason"):
        raise StoreError("invalid", "a skipped run needs a `reason`")
    if outcome == "failed" and not spec.get("error"):
        raise StoreError("invalid", "a failed run needs an `error`")
    entry = {k: v for k, v in spec.items() if k not in ("ts", "outcome")}
    command = entry.pop("command", "rule")
    ref = entry.pop("ref", None)
    store.log(vault, command, ref, outcome=outcome, **entry)
    return {"ok": True}
