"""Deterministic writes for definitions (docs/plans/01, 05, 09): implementations, vault and implementation rules, traits, and the manifest.

Files are edited with ruamel's round-trip mode, so comments, key order and flow style in a definition the user has touched by hand
survive. Every change is validated against the whole vault before it stays: if it adds any error that was not there before, the files
are restored and the command answers `invalid` with the new findings. Existing items are never touched.
"""
import os
import re

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from . import store, util, validate as validate_mod
from .model import CORE_TYPES, NAME_RE, Vault
from .store import StoreError

PROTECTED = ("impl", "extends", "trait")
IMPL_ORDER = ("impl", "extends", "version", "migration_target", "schema", "status_values", "storage", "sorts", "filters", "automation")


# ---- yaml -------------------------------------------------------------------------------------------------------------

def _yaml():
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    return y


def _rt(value, flow=False):
    """Plain Python data as ruamel nodes. A mapping or list of scalars is written in flow style when `flow` is set."""
    if isinstance(value, dict):
        out = CommentedMap()
        simple = all(not isinstance(v, (dict, list)) or (isinstance(v, list) and all(not isinstance(i, (dict, list)) for i in v)) for v in value.values())
        for k, v in value.items():
            out[k] = _rt(v, flow=flow and simple)
        if flow and simple:
            out.fa.set_flow_style()
        return out
    if isinstance(value, list):
        out = CommentedSeq(_rt(v) for v in value)
        if all(not isinstance(v, (dict, list)) for v in value):
            out.fa.set_flow_style()
        return out
    return value


def _field_specs(fields):
    out = CommentedMap()
    for name, spec in fields.items():
        out[name] = _rt(spec, flow=True)
    return out


def _dumps(node):
    import io
    buf = io.StringIO()
    _yaml().dump(node, buf)
    return buf.getvalue().rstrip("\n")


def _load_definition(path):
    """(front as a round-trip map, body text, raw text) of a definition file."""
    parsed = util.read_markdown(path)
    if parsed.error or parsed.front is None:
        raise StoreError("invalid", f"{os.path.basename(path)} has no readable front matter: {parsed.error or 'none'}")
    return _yaml().load(parsed.raw_front) or CommentedMap(), parsed.body, parsed.text


def _write_definition(path, front, body):
    store.write_atomic(path, f"---\n{_dumps(front)}\n---\n{body}")


# ---- the manifest -----------------------------------------------------------------------------------------------------

def _manifest_path(vault):
    return vault.path(".brain/manifest.yml")


def _manifest_set(vault, section, key, version):
    """Register `key` in the manifest's `implementations` or `traits` section, keeping the section sorted. Only that one line is
    added or replaced; every other line is untouched. Returns the old text for a rollback (None when there is no manifest)."""
    path = _manifest_path(vault)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")
    entry = f"  {key}: {{ version: {version} }}"
    head = next((i for i, line in enumerate(lines) if re.match(rf"^{section}:", line)), None)
    if head is None:
        position = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
        lines[position:position] = [f"{section}:", entry]
    else:
        rest = lines[head].split(":", 1)[1].strip()
        if rest and rest not in ("{}", "[]"):
            raise StoreError("invalid", f"the manifest's {section} section is not in the usual block form; fix it by hand")
        lines[head] = f"{section}:"
        end = head + 1
        while end < len(lines) and lines[end].startswith("  "):
            end += 1
        block = [line for line in lines[head + 1:end] if not re.match(rf"^  {re.escape(key)}:", line)]
        block.append(entry)
        block.sort(key=lambda line: line.strip().split(":", 1)[0])
        lines[head + 1:end] = block
    store.write_atomic(path, "\n".join(lines))
    return text


def _manifest_restore(vault, text):
    if text is not None:
        store.write_atomic(_manifest_path(vault), text)


def _manifest_version(vault, section, key):
    index = (vault.manifest or {}).get(section) or {}
    entry = index.get(key)
    return entry.get("version") if isinstance(entry, dict) else None


# ---- validation by regression -----------------------------------------------------------------------------------------

def _errors(vault):
    return {(f["code"], f["subject"], f["message"]) for f in validate_mod.validate(vault) if f["severity"] == "error"}


def _guard(vault, apply, undo, label):
    """Run `apply()`, then fail (after `undo()`) if the vault has errors it did not have before."""
    before = _errors(vault)
    apply()
    after_vault = Vault(vault.root)
    new = sorted(_errors(after_vault) - before)
    if new:
        undo()
        raise StoreError("invalid", f"{label} would leave the vault invalid; nothing was changed",
                         findings=[{"code": c, "subject": s, "message": m} for c, s, m in new])
    return after_vault


def _name(value, what, hyphens=True):
    if not isinstance(value, str) or not NAME_RE.match(value.replace("-", "_") if hyphens else value):
        allowed = "lowercase letters, digits, - and _" if hyphens else "lowercase letters, digits and _"
        raise StoreError("invalid", f"{what} must start with a letter and use {allowed} (got {value!r})")
    return value


# ---- implementations --------------------------------------------------------------------------------------------------

SLUG_SOURCE = {"person": "display name (`name.display`, or the name parts joined as `display_name` does)"}


def _slug_section(type_, path_template):
    source = SLUG_SOURCE.get(type_, "`title`")
    stem = path_template.replace("{slug}", "{slug}")
    return (f"\n## Slug\n\nThe `slug` is the file name stem (`{stem}`). Make it once, at creation, from the {source}. The mechanics (command, "
            "normalization, collision suffixes, fixed at creation) are in the core skill's `references/ids-and-slugs.md` reference.\n")


def _split_ref(ref):
    type_, _, name = (ref or "").partition("/")
    if type_ not in CORE_TYPES or not name:
        raise StoreError("invalid", f"an implementation is named <type>/<impl>, with type one of {', '.join(CORE_TYPES)} (got {ref!r})")
    return type_, name


def _impl_path(vault, type_, name):
    return vault.path(f".brain/impls/{type_}/{name}.md")


def impl_show(vault, ref):
    type_, name = _split_ref(ref)
    path = _impl_path(vault, type_, name)
    if not os.path.isfile(path):
        raise StoreError("not_found", f"no implementation {ref}")
    parsed = util.read_markdown(path)
    return {"ok": True, "ref": ref, "path": vault.rel(path), "front": util.jsonable(parsed.front), "body": parsed.body,
            "manifest_version": _manifest_version(vault, "implementations", ref)}


def impl_add(vault, spec):
    """Add an implementation. spec: type, impl, from? (copy another implementation of the type), fields?, status_values?, sorts?,
    filters?, automation?, storage? or path?, version?, body?."""
    spec = dict(spec or {})
    type_ = spec.get("type")
    name = _name(spec.get("impl"), "impl")
    if type_ not in CORE_TYPES:
        raise StoreError("invalid", f"`type` must be one of {', '.join(CORE_TYPES)}")
    ref = f"{type_}/{name}"
    path = _impl_path(vault, type_, name)
    if os.path.exists(path) or vault.impl_for(type_, name):
        raise StoreError("conflict", f"implementation {ref} already exists")
    front, body = CommentedMap(), None
    if spec.get("from"):
        base_type, base_name = _split_ref(spec["from"])
        if base_type != type_:
            raise StoreError("invalid", "a variant must be of the same type as the implementation it copies")
        base_path = _impl_path(vault, base_type, base_name)
        if not os.path.isfile(base_path):
            raise StoreError("not_found", f"no implementation {spec['from']} to copy")
        front, body, _ = _load_definition(base_path)
        front["impl"] = name
        front["version"] = 1
        front.pop("migration_target", None)
    else:
        front["impl"] = name
        front["extends"] = type_
        front["version"] = int(spec.get("version") or 1)
    if spec.get("version") and spec.get("from"):
        front["version"] = int(spec["version"])
    fields = dict(spec.get("fields") or {})
    storage = dict(spec.get("storage") or {})
    if spec.get("path"):
        storage.setdefault("adapter", "markdown")
        storage["path"] = spec["path"]
    if storage:
        if isinstance(storage.get("path"), str):
            storage["path"] = DoubleQuotedScalarString(storage["path"])
        front["storage"] = _rt(storage)
    elif not spec.get("from"):
        raise StoreError("invalid", "give `path` (a markdown path template such as \"notes/{slug}.md\") or `storage`")
    template = (front.get("storage") or {}).get("path") or ""
    auto_slug = "{slug}" in template and "slug" not in fields and "slug" not in ((front.get("schema") or {}).get("fields") or {})
    if auto_slug:
        fields = dict({"slug": {"type": "string"}}, **fields)
    if fields:
        schema = front.get("schema") or CommentedMap()
        merged = schema.get("fields") or CommentedMap()
        for k, v in _field_specs(fields).items():
            merged[k] = v
        schema["fields"] = merged
        front["schema"] = schema
    for key in ("status_values", "sorts", "filters", "automation"):
        if key in spec:
            front[key] = _rt(spec[key])
    if spec.get("migration_target"):
        front["migration_target"] = True
    ordered = CommentedMap((k, front[k]) for k in IMPL_ORDER if k in front)
    for k in front:
        if k not in ordered:
            ordered[k] = front[k]
    if spec.get("body") is not None:
        body = spec["body"]
    elif body is None:
        body = _slug_section(type_, template) if "slug" in ((ordered.get("schema") or {}).get("fields") or {}) else ""
    manifest_before = []

    def apply():
        _write_definition(path, ordered, "\n" + body.lstrip("\n") if body else "")
        manifest_before.append(_manifest_set(vault, "implementations", ref, ordered["version"]))

    def undo():
        os.remove(path)
        _manifest_restore(vault, manifest_before[0] if manifest_before else None)
        store._prune_empty(vault, vault.rel(path))

    new_vault = _guard(vault, apply, undo, f"adding {ref}")
    store.log(new_vault, "impl-add", None, impl=ref)
    return {"ok": True, "command": "impl-add", "ref": ref, "path": new_vault.rel(path), "version": ordered["version"], "slug_field_added": auto_slug}


def impl_update(vault, ref, patch):
    """Change an implementation. patch: set {top-level key: value}, unset [keys], fields {name: spec}, remove_fields [names],
    body?, bump? (version + 1, recorded in the manifest). `impl` and `extends` cannot change."""
    patch = dict(patch or {})
    type_, name = _split_ref(ref)
    path = _impl_path(vault, type_, name)
    if not os.path.isfile(path):
        raise StoreError("not_found", f"no implementation {ref}")
    front, body, old_text = _load_definition(path)
    for key in list((patch.get("set") or {})) + list(patch.get("unset") or []):
        if key in PROTECTED or key == "version":
            raise StoreError("invalid", f"{key!r} cannot be changed here" + (" (use bump)" if key == "version" else ""))
    for key, value in (patch.get("set") or {}).items():
        if key == "storage" and isinstance(value, dict) and isinstance(value.get("path"), str):
            value = dict(value, path=DoubleQuotedScalarString(value["path"]))
        front[key] = _rt(value)
    for key in patch.get("unset") or []:
        front.pop(key, None)
    if patch.get("fields") or patch.get("remove_fields"):
        schema = front.get("schema")
        if schema is None:
            schema = CommentedMap()
            front["schema"] = schema
        fields = schema.get("fields")
        if fields is None:
            fields = CommentedMap()
            schema["fields"] = fields
        for k, v in _field_specs(patch.get("fields") or {}).items():
            fields[k] = v
        for k in patch.get("remove_fields") or []:
            fields.pop(k, None)
    version = front.get("version")
    if patch.get("bump"):
        version = int(version or 1) + 1
        front["version"] = version
    new_body = patch.get("body") if patch.get("body") is not None else body
    manifest_before = []

    def apply():
        _write_definition(path, front, new_body)
        if patch.get("bump"):
            manifest_before.append(_manifest_set(vault, "implementations", ref, version))

    def undo():
        store.write_atomic(path, old_text)
        if manifest_before:
            _manifest_restore(vault, manifest_before[0])

    new_vault = _guard(vault, apply, undo, f"changing {ref}")
    store.log(new_vault, "impl-update", None, impl=ref)
    return {"ok": True, "command": "impl-update", "ref": ref, "path": new_vault.rel(path), "version": version}


# ---- rules ------------------------------------------------------------------------------------------------------------

def _rules_target(vault, scope):
    """(path, kind, key) for a rule scope: `vault` or `<type>/<impl>`."""
    if scope == "vault":
        return vault.path(".brain/automation.yml"), "vault", "rules"
    type_, name = _split_ref(scope)
    path = _impl_path(vault, type_, name)
    if not os.path.isfile(path):
        raise StoreError("not_found", f"no implementation {scope}")
    return path, "impl", "automation"


def _load_rules(path, kind, key):
    if kind == "impl":
        front, body, text = _load_definition(path)
        return front, body, text
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        data = _yaml().load(text) or CommentedMap()
        return data, None, text
    data = CommentedMap()
    return data, None, None


def _save_rules(path, kind, node, body):
    if kind == "impl":
        _write_definition(path, node, body)
    else:
        store.write_atomic(path, _dumps(node) + "\n")


def rule_list(vault, scope=None):
    out = []
    scopes = [scope] if scope else ["vault"] + [f"{t}/{n}" for (t, n), i in sorted(vault.impls.items()) if i.automation]
    for sc in scopes:
        try:
            path, kind, key = _rules_target(vault, sc)
        except StoreError:
            continue
        if kind == "vault" and not os.path.isfile(path):
            continue
        node, _body, _text = _load_rules(path, kind, key)
        for rule in node.get(key) or []:
            out.append({"scope": sc, "id": rule.get("id"), "on": util.jsonable(rule.get("on")), "enabled": rule.get("enabled", True)})
    return {"ok": True, "count": len(out), "rules": out}


def rule_add(vault, spec):
    """Add (or with replace: true, replace) a rule. spec: scope (`vault` or `<type>/<impl>`), rule {id, on, do, ...}, replace?."""
    spec = dict(spec or {})
    rule = spec.get("rule")
    if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"]:
        raise StoreError("invalid", "rule must be a mapping with an `id`")
    path, kind, key = _rules_target(vault, spec.get("scope"))
    node, body, old_text = _load_rules(path, kind, key)
    rules = node.get(key)
    if rules is None:
        rules = CommentedSeq()
        node[key] = rules
    new_rule = _rt(dict(rule))
    existing = next((i for i, r in enumerate(rules) if r.get("id") == rule["id"]), None)
    if existing is not None and not spec.get("replace"):
        raise StoreError("conflict", f"rule {rule['id']} already exists in {spec['scope']}; pass replace: true to replace it")
    if existing is not None:
        rules[existing] = new_rule
    else:
        rules.append(new_rule)

    def apply():
        _save_rules(path, kind, node, body)

    def undo():
        if old_text is None:
            os.remove(path)
        else:
            store.write_atomic(path, old_text)

    new_vault = _guard(vault, apply, undo, f"adding rule {rule['id']}")
    store.log(new_vault, "rule-add", None, rule=f"{spec['scope']}/{rule['id']}")
    return {"ok": True, "command": "rule-add", "scope": spec["scope"], "id": rule["id"], "path": new_vault.rel(path), "replaced": existing is not None}


def rule_remove(vault, scope, rule_id):
    path, kind, key = _rules_target(vault, scope)
    if kind == "vault" and not os.path.isfile(path):
        raise StoreError("not_found", f"no rule {rule_id} in {scope}")
    node, body, old_text = _load_rules(path, kind, key)
    rules = node.get(key) or []
    index = next((i for i, r in enumerate(rules) if r.get("id") == rule_id), None)
    if index is None:
        raise StoreError("not_found", f"no rule {rule_id} in {scope}")
    del rules[index]
    if not rules and kind == "impl":
        del node[key]

    def apply():
        _save_rules(path, kind, node, body)

    def undo():
        store.write_atomic(path, old_text)

    new_vault = _guard(vault, apply, undo, f"removing rule {rule_id}")
    store.log(new_vault, "rule-remove", None, rule=f"{scope}/{rule_id}")
    return {"ok": True, "command": "rule-remove", "scope": scope, "id": rule_id}


# ---- traits -----------------------------------------------------------------------------------------------------------

def trait_add(vault, spec):
    spec = dict(spec or {})
    name = _name(spec.get("name"), "name", hyphens=False)
    path = vault.path(f".brain/traits/{name}.md")
    if os.path.exists(path):
        raise StoreError("conflict", f"trait {name} already exists")
    front = CommentedMap(trait=name, version=int(spec.get("version") or 1))
    fields = spec.get("fields") or {}
    if fields:
        schema = CommentedMap()
        schema["fields"] = _field_specs(fields)
        front["schema"] = schema
    body = spec.get("body") or ""
    manifest_before = []

    def apply():
        _write_definition(path, front, "\n" + body.lstrip("\n") if body else "")
        manifest_before.append(_manifest_set(vault, "traits", name, front["version"]))

    def undo():
        os.remove(path)
        _manifest_restore(vault, manifest_before[0] if manifest_before else None)

    new_vault = _guard(vault, apply, undo, f"adding trait {name}")
    store.log(new_vault, "trait-add", None, trait=name)
    return {"ok": True, "command": "trait-add", "name": name, "path": new_vault.rel(path)}
