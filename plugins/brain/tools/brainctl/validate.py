"""`brainctl validate`: every mechanical check of the vault (docs/plans/11, the `validate` skill). Read-only."""
import os
import re

from . import CORE_VERSION, approval, model, schema, util
from .model import (ALL_CORE_RELATIONS, CORE_RELATIONS, CORE_STATUS, CORE_TYPES, ENVELOPE_KEYS, NAME_RE, REF_RE, RESERVED,
                    STATUS_TYPES, ULID_RE)

TRIGGERS = {"create", "update", "capture", "archive", "unarchive", "relation", "before_delete", "manual"}
PLACED_CREATORS = ("task", "note", "project")
LOCK_FILES = ("uv.lock", "poetry.lock", "pdm.lock", "requirements.lock")
MUST_BE_IGNORED = [
    ".brain/index/x", ".brain/cache/x", ".brain/automation/seen/x", ".brain/automation/pending/x",
    ".brain/automation/log.jsonl", ".brain/conversions/x", ".brain/python/.venv/x", ".brain/python/outputs/x",
]


class Findings(list):
    def add(self, severity, code, subject, message):
        self.append({"severity": severity, "code": code, "subject": subject, "message": message})

    def error(self, code, subject, message):
        self.add("error", code, subject, message)

    def warn(self, code, subject, message):
        self.add("warning", code, subject, message)


def validate(vault, ref=None):
    findings = Findings()
    for code, rel, message in vault.load_errors:
        findings.error(code, rel, message)
    if not os.path.isdir(vault.brain):
        findings.error("not-a-vault", ".brain", "no .brain directory")
        return findings
    _check_vault_files(vault, findings)
    _check_definitions(vault, findings)
    _check_traits(vault, findings)
    scan = vault.scan()
    _check_scan_problems(vault, scan, findings)
    _check_script_bindings(vault, findings)
    _check_inbox(vault, scan, findings)
    _check_items(vault, scan, findings)
    _check_automation(vault, findings)
    _check_conversions(vault, findings)
    _check_gitignore(vault, findings)
    _check_workspace(vault, findings)
    if ref:
        findings = Findings(f for f in findings if f["subject"] == ref or f["subject"].startswith(ref))
    return findings


def _check_script_bindings(vault, f):
    """Ask each approved script adapter to describe itself and compare it with the binding (docs/plans/03, `describe`)."""
    from . import client as client_mod
    for (type_, name), impl in sorted(vault.impls.items()):
        if impl.error or impl.adapter != "script":
            continue
        subject = f"{type_}/{name}"
        try:
            c = client_mod.ScriptClient.for_impl(vault, impl)
            c.check_approved()
        except client_mod.ClientError:
            continue                    # unregistered and unapproved scripts are reported elsewhere
        missing = [v for v in (c.entry.get("requires_env") or []) if v not in os.environ]
        if missing:
            f.warn("adapter-env-missing", subject, f"environment variable(s) not set: {', '.join(missing)}")
        try:
            described = c.describe() or {}
        except client_mod.ClientError as err:
            f.error("adapter-describe", subject, f"describe failed: {err.message}")
            continue
        caps = described.get("capabilities") or {}
        if described.get("protocol") not in (None, 1):
            f.error("adapter-protocol", subject, f"adapter speaks protocol {described.get('protocol')!r}; this helper speaks 1")
        if caps.get("tags") == "labels" and not impl.storage.get("tag_values_field"):
            f.error("adapter-tags", subject, "the adapter stores tags as labels (names only); the binding needs storage.tag_values_field for the values")
        if type_ == "person" and caps.get("supports_traits") is False:
            f.error("adapter-traits", subject, "the adapter does not support traits, which person items can carry")
        if caps.get("supports_body") is False:
            f.warn("adapter-body", subject, "the adapter does not store item bodies; bodies will be lost on this binding")
        extra = [k for k in impl.fields if k not in ("title",)]
        if extra and caps.get("preserves_unknown_fields") is False:
            f.warn("adapter-fields", subject, "the adapter may drop fields it does not know; the implementation defines extra fields")


# ---- vault files ------------------------------------------------------------------------------------------------------

def _check_vault_files(vault, f):
    if vault.config is None and not any(c == "config-invalid" for c, *_ in vault.load_errors):
        f.error("config-missing", ".brain/config.yml", "config.yml is missing")
    if vault.manifest is None and not any(c == "manifest-invalid" for c, *_ in vault.load_errors):
        f.error("manifest-missing", ".brain/manifest.yml", "manifest.yml is missing: setup did not finish (run /brain:setup)")
    if vault.config is not None:
        archive = vault.config.get("archive")
        if not isinstance(archive, dict) or archive.get("adapter") not in ("markdown", "script"):
            f.error("archive-config", ".brain/config.yml", "config needs archive.adapter (markdown or script)")
        elif archive["adapter"] == "markdown" and "{slug}" not in str(archive.get("path", "{slug}")) and "{id}" not in str(archive.get("path", "")):
            f.error("archive-path", ".brain/config.yml", "archive.path must include {slug} or {id}")
    if vault.manifest is not None:
        core = vault.manifest.get("core_version")
        if not isinstance(core, int):
            f.error("manifest-core-version", ".brain/manifest.yml", "core_version must be an integer")
        elif core < CORE_VERSION:
            f.warn("migration-available", ".brain/manifest.yml", f"vault is at core version {core}; the helper is at {CORE_VERSION} (migrate with an explicit command)")
        elif core > CORE_VERSION:
            f.error("core-version-ahead", ".brain/manifest.yml", f"vault core version {core} is newer than this helper ({CORE_VERSION})")
        index = vault.manifest.get("implementations") or {}
        on_disk = {f"{t}/{n}" for (t, n) in vault.impls}
        for key in sorted(on_disk - set(index)):
            f.warn("manifest-index", ".brain/manifest.yml", f"implementation {key} is not in the manifest index")
        for key in sorted(set(index) - on_disk):
            f.warn("manifest-index", ".brain/manifest.yml", f"manifest lists {key} but no definition exists")
        trait_index = vault.manifest.get("traits") or {}
        for name in sorted(set(vault.traits) - set(trait_index)):
            f.warn("manifest-index", ".brain/manifest.yml", f"trait {name} is not in the manifest index")


# ---- implementation definitions ---------------------------------------------------------------------------------------

def _check_definitions(vault, f):
    for (type_, name), impl in sorted(vault.impls.items()):
        subject = impl.relpath
        if impl.error:
            f.error("impl-invalid", subject, f"definition cannot be read: {impl.error}")
            continue
        if type_ not in CORE_TYPES:
            f.error("impl-type", subject, f"{type_!r} is not an extensible core type")
            continue
        if impl.front.get("impl") != name:
            f.error("impl-name", subject, f"`impl` is {impl.front.get('impl')!r} but the file is named {name}.md")
        if impl.extends != type_:
            f.error("impl-extends", subject, f"`extends` is {impl.extends!r} but the definition is in .brain/impls/{type_}/")
        if not isinstance(impl.version, int):
            f.error("impl-version", subject, "`version` must be an integer")
        _check_storage(vault, impl, f)
        for field_name, spec in impl.fields.items():
            for code, message in schema.check_spec(field_name, spec):
                f.error(code, subject, message)
            if field_name in vault.traits:
                f.error("field-trait-clash", subject, f"field {field_name!r} has the same name as a trait")
        for value, target in impl.status_values.items():
            if type_ not in STATUS_TYPES:
                f.error("status-values", subject, f"status_values is only valid for {', '.join(STATUS_TYPES)}")
                break
            if value in CORE_STATUS:
                f.error("status-values", subject, f"custom status {value!r} duplicates a core value")
            if target not in CORE_STATUS:
                f.error("status-values", subject, f"custom status {value!r} must map to one of {', '.join(CORE_STATUS)}")
        for kind, table in (("sort", impl.sorts), ("filter", impl.filters)):
            for rule_name, definition in (table or {}).items():
                text = definition.get("rule") if isinstance(definition, dict) else definition
                if not isinstance(text, str) or not text.strip():
                    f.error(f"{kind}-rule", subject, f"{kind} {rule_name!r} needs a rule text")
    persons = vault.impls_of("person")
    active = [i for i in persons if not i.migration_target and not i.error]
    targets = [i for i in persons if i.migration_target]
    if persons and len(active) != 1:
        f.error("person-impl", ".brain/impls/person", f"exactly one active person implementation is required, found {len(active)}")
    if len(targets) > 1:
        f.error("person-impl", ".brain/impls/person", "at most one person implementation may be a migration_target")
    if not persons and vault.impls:
        f.warn("person-impl", ".brain/impls/person", "no person implementation is defined")


def _check_storage(vault, impl, f):
    subject = impl.relpath
    adapter = impl.adapter
    if adapter == "markdown":
        template = impl.path_template
        if not isinstance(template, str) or not template:
            f.error("storage-path", subject, "markdown storage needs a path template")
        else:
            names = util.template_names(template)
            if "slug" not in names and "id" not in names:
                f.error("storage-path", subject, "the path template must include {slug} or {id} so every item has its own file")
            if not template.endswith(".md"):
                f.warn("storage-path", subject, "the path template should end with .md")
    elif adapter == "script":
        command = impl.storage.get("command")
        if not command:
            f.error("storage-command", subject, "script storage needs a command")
        elif isinstance(command, str) and command.startswith("python:"):
            registry = _load_registry(vault)
            if registry is None or command[len("python:"):] not in registry:
                f.error("command-unregistered", subject, f"{command} is not a script in the Python workspace registry")
        timeout = impl.storage.get("timeout_seconds")
        if timeout is not None and (not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1):
            f.error("storage-timeout", subject, "timeout_seconds must be a positive integer")
        if not os.path.isfile(vault.path(f".brain/backends/{impl.name}.md")):
            f.warn("backend-spec-missing", subject, f"no backend spec at .brain/backends/{impl.name}.md (run /brain:backend to write one)")
    else:
        f.error("storage-adapter", subject, f"unknown storage adapter {adapter!r}")


def _check_traits(vault, f):
    person = [i for i in vault.impls_of("person") if not i.migration_target]
    person_fields = set().union(*[set(i.fields) for i in person]) if person else set()
    for name, trait in sorted(vault.traits.items()):
        subject = trait["_relpath"]
        if not NAME_RE.match(name):
            f.error("trait-name", subject, f"trait name {name!r} must match [a-z][a-z0-9_]*")
        if name in RESERVED:
            f.error("trait-name", subject, f"trait name {name!r} is reserved")
        if name in person_fields:
            f.error("trait-name", subject, f"trait name {name!r} is also a field of the person implementation")
        if trait.get("trait") != name:
            f.error("trait-name", subject, f"`trait` is {trait.get('trait')!r} but the file is named {name}.md")
        for field_name, spec in ((trait.get("schema") or {}).get("fields") or {}).items():
            for code, message in schema.check_spec(field_name, spec):
                f.error(code, subject, f"{message}")


# ---- scan problems, inbox ---------------------------------------------------------------------------------------------

def _check_scan_problems(vault, scan, f):
    for code, rel, message in scan.problems:
        severity = f.warn if code in ("ambiguous-file",) else f.error
        severity(code, rel, message)
    for type_, impl, rel, _parsed in scan.unadopted:
        f.warn("unadopted-file", rel, f"no identity fields (id, type, impl); sync will adopt it into {type_}/{impl}")
    for type_, impl, reason in scan.skipped:
        f.warn("binding-skipped", f"{type_}/{impl}", reason)
    for ref, items in scan.by_ref().items():
        live = [i for i in items if not i.archived]
        if len(live) > 1:
            f.error("duplicate-ref", ref, "exists in more than one binding: " + ", ".join(i.relpath for i in live))
        elif live and len(items) > len(live):
            f.error("duplicate-ref", ref, "exists both live and in the Archive")


def _check_inbox(vault, scan, f):
    if vault.config is None:
        return
    inbox = next((i for i in scan.live() if i.ref == "area:inbox"), None)
    if inbox is None:
        f.error("inbox-missing", "area:inbox", "the Inbox area is missing")
        return
    if inbox.front.get("system") is not True:
        f.error("inbox-system", "area:inbox", "the Inbox must have system: true")


# ---- items ------------------------------------------------------------------------------------------------------------

def _check_items(vault, scan, f):
    refs = scan.by_ref()
    for item in scan.items:
        _check_item(vault, scan, item, refs, f)
    _check_cycles(scan, vault, f)


def _item_problem(f, severity, code, item, message):
    f.add(severity, code, item.ref, f"{item.relpath}: {message}")


def _check_item(vault, scan, item, refs, f):
    front = item.front
    impl = vault.impl_for(item.type, item.impl)
    if impl is None or impl.error:
        _item_problem(f, "error", "impl-missing", item, f"implementation {item.type}/{item.impl} has no valid definition")
        return
    e = lambda code, msg: _item_problem(f, "error", code, item, msg)
    w = lambda code, msg: _item_problem(f, "warning", code, item, msg)

    # envelope
    ident = front.get("id")
    if not isinstance(ident, str) or not ident:
        e("id", "id must be a non-empty string")
    elif not ULID_RE.match(ident) and ident != "inbox":
        w("id-format", f"id {ident!r} is not a ULID")
    if item.type not in CORE_TYPES:
        e("type", f"unknown type {item.type!r}")
        return
    stem = os.path.splitext(os.path.basename(item.relpath))[0]
    slug = front.get("slug")
    template = impl.path_template or ""
    if slug is not None and not isinstance(slug, str):
        w("slug-type", f"slug is read as a {type(slug).__name__}, not a string; quote it (slug: \"{slug}\")")
    elif not isinstance(slug, str) or not slug:
        w("slug-missing", "slug is missing")
    elif "{slug}" in template and not item.archived and stem != slug:
        w("slug-mismatch", f"slug {slug!r} differs from the file name {stem!r}")
    for key in ("created", "updated"):
        value = front.get(key)
        if value is None:
            w(f"{key}-missing", f"{key} is missing")
        elif schema.check_value(key, {"type": "datetime"}, value):
            e(f"{key}-invalid", f"{key} is not a datetime")

    # titles and core fields
    if item.type == "person":
        _check_person(vault, item, front, impl, e, w)
    else:
        title = front.get("title")
        if title is not None and not isinstance(title, str):
            e("title-type", f"title is read as a {type(title).__name__}, not a string; quote it (title: \"{title}\")")
        elif not isinstance(title, str) or not title.strip():
            e("required-field", "title is required and must be non-empty")
    _check_tags(front, e, w)
    allowed = ENVELOPE_KEYS | model.COMMON_FIELDS | model.TYPE_FIELDS[item.type] | set(impl.fields) | set(CORE_RELATIONS[item.type])
    if item.type == "person":
        allowed |= set(front.get("traits") or []) | {"traits"}
    relation_names = set(item.relation_names(impl, set(vault.traits)))
    for key in front:
        if key in allowed or key in relation_names or key.startswith("_"):
            continue
        if key in model.RESERVED or key in ALL_CORE_RELATIONS:
            e("misplaced-key", f"{key!r} is not valid on a {item.type}")
        else:
            w("unknown-field", f"{key!r} is not in the {item.impl} schema (preserved, not validated)")

    # status
    if item.type in STATUS_TYPES:
        status = front.get("status")
        valid = set(CORE_STATUS) | set(impl.status_values)
        if status is None:
            e("required-field", "status is required")
        elif status not in valid:
            e("status-invalid", f"status {status!r} is not one of {sorted(valid)}")
        else:
            category = status if status in CORE_STATUS else impl.status_values.get(status)
            completed = front.get("completed")
            if category in ("done", "dropped") and completed is None:
                w("completed-missing", f"status {status!r} is {category} but `completed` is not set")
            if category == "open" and completed is not None:
                w("completed-stale", "status is open but `completed` is set")
    elif "completed" in front:
        e("misplaced-key", f"'completed' is not valid on a {item.type}")

    # schema fields
    for severity, code, message in schema.check_fields(front, impl.fields):
        _item_problem(f, severity, code, item, message)

    # defaults, system
    if item.type in ("area", "project") and "defaults" in front:
        _check_defaults(vault, item, front["defaults"], e)
    if item.type == "area" and front.get("system") and item.id != "inbox":
        e("system-flag", "only the Inbox may set system: true")
    if item.type == "project" and front.get("outcome") is not None and not isinstance(front["outcome"], str):
        e("field-value", "outcome must be a string")

    # relations
    _check_relations(vault, item, impl, refs, e, w)


def _check_person(vault, item, front, impl, e, w):
    name = front.get("name")
    if not isinstance(name, dict):
        e("required-field", "name must be a mapping of parts (given, family, ...)")
    else:
        parts = {k: v for k, v in name.items() if isinstance(v, str)}
        if not any(v.strip() for v in parts.values()):
            e("required-field", "name needs at least one non-empty part")
        for key, value in name.items():
            if not isinstance(value, str):
                e("field-value", f"name.{key} must be a string")
    traits = front.get("traits")
    if traits is not None and (not isinstance(traits, list) or not all(isinstance(t, str) for t in traits)):
        e("traits", "traits must be a list of trait names")
        return
    listed = list(traits or [])
    for trait_name in listed:
        trait = vault.traits.get(trait_name)
        if trait is None:
            e("trait-unknown", f"trait {trait_name!r} is not defined in .brain/traits/")
            continue
        value = front.get(trait_name)
        if value is not None and not isinstance(value, dict):
            e("trait-fields", f"fields of trait {trait_name!r} must be a mapping")
            continue
        fields = (trait.get("schema") or {}).get("fields") or {}
        for severity, code, message in schema.check_fields(value or {}, fields):
            f_msg = f"{trait_name}.{message}"
            (e if severity == "error" else w)(code, f_msg)
        for key in (value or {}):
            if key not in fields:
                w("unknown-field", f"{trait_name}.{key} is not in the trait schema")
    for key in vault.traits:
        if key in front and key not in listed:
            e("trait-fields", f"fields of trait {key!r} are present but the trait is not listed in `traits`")


def _check_tags(front, e, w):
    tags = front.get("tags")
    if tags is None:
        return
    if isinstance(tags, list):
        if not all(isinstance(t, str) for t in tags):
            e("tags", "tags given as a list must contain only names")
        else:
            w("tags-shorthand", "tags were written as a list; they will be normalized to a name-to-value map")
        names = tags if all(isinstance(t, str) for t in tags) else []
    elif isinstance(tags, dict):
        names = list(tags)
        for name, value in tags.items():
            if isinstance(value, (list, dict)):
                e("tags", f"tag {name!r}: a value must be a string, not a list or map")
            elif not isinstance(value, str):
                w("tags-value", f"tag {name!r}: the value is not a string and will be converted")
    else:
        e("tags", "tags must be a map of names to string values")
        return
    seen = set()
    for name in names:
        text = str(name)
        norm = text.strip().lower()
        if not norm or re.search(r"\s", norm) or re.search(r"[\x00-\x1f]", norm):
            e("tags", f"tag name {text!r} must be non-empty with no whitespace or control characters")
        elif norm != text:
            w("tags-name", f"tag name {text!r} will be normalized to {norm!r}")
        if norm in seen:
            e("tags", f"tag name {text!r} is duplicated")
        seen.add(norm)


def _check_defaults(vault, item, defaults, e):
    if not isinstance(defaults, dict):
        e("defaults", "defaults must be a mapping of core type to implementation")
        return
    allowed = {"project": ("task", "note"), "area": tuple(t for t in CORE_TYPES if t != "person")}[item.type]
    for type_, impl_name in defaults.items():
        if type_ not in allowed:
            e("defaults", f"defaults.{type_} is not valid on a {item.type} (allowed: {', '.join(allowed)})")
        elif vault.impl_for(type_, impl_name) is None:
            e("defaults", f"defaults.{type_} names {impl_name!r}, which is not defined")


def _check_relations(vault, item, impl, refs, e, w):
    declared = CORE_RELATIONS.get(item.type, {})
    for name, targets in item.relations(impl, set(vault.traits)).items():
        allowed, maximum = declared.get(name, (None, None))
        raw = item.front.get(name)
        if raw is not None and not isinstance(raw, list):
            e("relation-shape", f"{name} must be a list of refs")
        if maximum is not None and len(targets) > maximum:
            e("relation-cardinality", f"{name} allows at most {maximum} target(s), found {len(targets)}")
        project_or_area = 0
        for target in targets:
            m = REF_RE.match(target) if isinstance(target, str) else None
            if not m:
                e("relation-ref", f"{name}: {target!r} is not a ref like type:id")
                continue
            if allowed is not None and m.group(1) not in allowed:
                e("relation-target", f"{name} cannot point at a {m.group(1)} ({target})")
            if item.type == "note" and name == "about" and m.group(1) in ("project", "area"):
                project_or_area += 1
            if target == "area:inbox":
                continue
            found = refs.get(target)
            if not found:
                w("dangling-ref", f"{name} -> {target} does not resolve")
            elif all(t.archived for t in found):
                w("archived-target", f"{name} -> {target} is archived")
        if item.type == "note" and name == "about" and project_or_area > 1:
            e("relation-cardinality", "about allows at most one Project or Area target")


def _check_cycles(scan, vault, f):
    live = {i.ref: i for i in scan.items}
    for type_, relation, severity, code in (("area", "parent", "error", "parent-cycle"), ("task", "blocked_by", "warning", "blocked-cycle")):
        graph = {}
        for item in live.values():
            if item.type == type_:
                targets = item.front.get(relation) or []
                graph[item.ref] = [t for t in (targets if isinstance(targets, list) else []) if t in live]
        state = {}
        reported = set()

        def visit(node, stack):
            state[node] = 1
            for nxt in graph.get(node, []):
                if state.get(nxt) == 1:
                    cycle = stack[stack.index(nxt):] + [nxt] if nxt in stack else [node, nxt]
                    key = frozenset(cycle)
                    if key not in reported:
                        reported.add(key)
                        f.add(severity, code, node, f"{relation} cycle: " + " -> ".join(cycle))
                elif nxt not in state:
                    visit(nxt, stack + [nxt])
            state[node] = 2

        for node in graph:
            if node not in state:
                visit(node, [node])


# ---- automation -------------------------------------------------------------------------------------------------------

def _check_automation(vault, f):
    sources = []
    for (type_, name), impl in sorted(vault.impls.items()):
        if impl.automation:
            sources.append((f"{type_}/{name}", impl.relpath, impl.automation, impl, False))
    vault_rules = None
    vault_file = vault.path(".brain/automation.yml")
    if os.path.isfile(vault_file):
        try:
            data = util.load_yaml_file(vault_file) or {}
            vault_rules = data.get("automation") or []
            sources.append(("vault", ".brain/automation.yml", vault_rules, None, True))
        except Exception as exc:
            f.error("automation-invalid", ".brain/automation.yml", f"not valid YAML ({str(exc).splitlines()[0]})")
    registry = _load_registry(vault)
    for label, rel, rules, owner, is_vault in sources:
        if not isinstance(rules, list):
            f.error("automation-invalid", rel, "`automation` must be a list")
            continue
        seen_ids = set()
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                f.error("rule-invalid", rel, f"rule #{index + 1} is not a mapping")
                continue
            rule_id = rule.get("id") or f"#{index + 1}"
            subject = f"{label}/{rule_id}" if not is_vault else f"vault/{rule_id}"
            if rule.get("id") in seen_ids:
                f.error("rule-id", subject, "duplicate rule id")
            seen_ids.add(rule.get("id"))
            if not rule.get("id"):
                f.error("rule-id", subject, "rule needs an id")
            _check_rule(vault, rule, subject, owner, is_vault, registry, f)


def _load_registry(vault):
    path = vault.path(".brain/python/registry.yml")
    if not os.path.isfile(path):
        return None
    try:
        data = util.load_yaml_file(path) or {}
    except Exception:
        return None
    return {s.get("name"): s for s in (data.get("scripts") or []) if isinstance(s, dict)}


def _trigger_name(on):
    if isinstance(on, str):
        return on
    if isinstance(on, dict) and on:
        return next(iter(on))
    return None


TAG_QUANTITY_RE = re.compile(r"\b(two|three|four|several|multiple|\d+)\s+(\w+\s+)?tags\b|\bup to \w+ (\w+\s+)?tags\b", re.I)
TAG_DISTINCT_RE = re.compile(r"\b(distinct|different|separate|unique)\b|\bkeys\b", re.I)


def _check_rule(vault, rule, subject, owner, is_vault, registry, f):
    trigger = _trigger_name(rule.get("on"))
    if trigger == "schedule":
        f.error("schedule-unsupported", subject, "schedule triggers are not supported yet")
    elif trigger not in TRIGGERS:
        f.error("rule-trigger", subject, f"unknown trigger {rule.get('on')!r}")
    elif is_vault and trigger != "manual":
        f.error("vault-trigger", subject, "vault-level rules may only use the manual trigger")
    required = {}
    if is_vault:
        requires = rule.get("requires")
        if not isinstance(requires, list) or not requires:
            f.error("rule-requires", subject, "a vault rule must list the implementations it requires")
            requires = []
        for entry in requires:
            if not isinstance(entry, dict) or "type" not in entry or "impl" not in entry:
                f.error("rule-requires", subject, f"bad requires entry {entry!r}")
                continue
            required[(entry["type"], entry["impl"])] = entry
            impl = vault.impl_for(entry["type"], entry["impl"])
            if impl is None:
                f.error("rule-blocked", subject, f"blocked: required implementation {entry['type']}/{entry['impl']} is missing")
            elif "min_version" in entry and isinstance(impl.version, int) and impl.version < entry["min_version"]:
                f.error("rule-blocked", subject, f"blocked: {entry['type']}/{entry['impl']} is version {impl.version}, needs {entry['min_version']}")
    actions = rule.get("do") or []
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        kind = action.get("action")
        if kind == "surface":
            impl = _action_impl(vault, action, owner, subject, required, is_vault, f)
            if impl is not None:
                if action.get("filter") and action["filter"] not in impl.filters:
                    f.error("rule-blocked", subject, f"blocked: filter {action['filter']!r} is not defined in {impl.type}/{impl.name}")
                sort_name = action.get("sort")
                if sort_name:
                    sort = impl.sorts.get(sort_name)
                    if sort is None:
                        f.error("rule-blocked", subject, f"blocked: sort {sort_name!r} is not defined in {impl.type}/{impl.name}")
                    elif not (isinstance(sort, dict) and sort.get("keys")):
                        f.error("sort-unpinned", subject, f"sort {sort_name!r} is used by automation but has no pinned keys")
        elif kind == "hook":
            run = str(action.get("run", ""))
            if run.startswith("python:") and registry is not None and run[len("python:"):] not in registry:
                f.error("hook-unregistered", subject, f"{run} is not in the Python workspace registry")
        elif kind == "claude":
            text = str(action.get("instruction", ""))
            if TAG_QUANTITY_RE.search(text) and not TAG_DISTINCT_RE.search(text):
                f.warn("tags-one-per-key", subject, "the instruction asks for several tags, but tags are a map with one value per key; name distinct keys")
        elif kind == "create_item":
            unless = action.get("unless_exists")
            if unless is not None:
                if not isinstance(unless, dict) or unless.get("type") not in CORE_TYPES or not isinstance(unless.get("where"), dict) or not unless["where"]:
                    f.error("unless-exists", subject, "unless_exists needs a core `type` and a non-empty `where` mapping of field values")
                elif is_vault and unless.get("impl") and (unless["type"], unless["impl"]) not in required:
                    f.error("rule-undeclared-impl", subject, f"{unless['type']}/{unless['impl']} is used in `unless_exists` but not in `requires`")
            if action.get("type") in PLACED_CREATORS and "place" not in action:
                f.warn("rule-unplaced", subject, f"creates a {action['type']} without `place`; it will land in the Inbox")
        elif kind == "write_body":
            target = action.get("target")
            if isinstance(target, dict) and target.get("create_if_missing"):
                find = target.get("find") or {}
                if find.get("type") in PLACED_CREATORS and "place" not in target:
                    f.warn("rule-unplaced", subject, f"creates a {find['type']} without `place`; it will land in the Inbox")
                if is_vault and find.get("impl") and (find.get("type"), find["impl"]) not in required:
                    f.error("rule-undeclared-impl", subject, f"{find.get('type')}/{find['impl']} is used but not in `requires`")
                place = target.get("place")
                if is_vault and isinstance(place, dict):
                    ptype = (place.get("find") or {}).get("type")
                    if ptype and not any(k[0] == ptype for k in required):
                        f.error("rule-undeclared-impl", subject, f"`place` uses an {ptype} but no {ptype} implementation is in `requires`")


def _action_impl(vault, action, owner, subject, required, is_vault, f):
    name = action.get("impl")
    if owner is not None:
        return vault.impl_for(owner.type, name) if name and name != owner.name else owner
    if not name:
        candidates = {k for k in required}
        if len(candidates) == 1:
            type_, name = next(iter(candidates))
            return vault.impl_for(type_, name)
        f.error("rule-impl", subject, "surface needs `impl` when the rule requires more than one implementation")
        return None
    match = [i for (t, n), i in vault.impls.items() if n == name]
    if not match:
        f.error("rule-blocked", subject, f"blocked: implementation {name!r} is not defined")
        return None
    if is_vault and not any(k[1] == name for k in required):
        f.error("rule-undeclared-impl", subject, f"{name} is used but not in `requires`")
    return match[0]


# ---- conversions, git, workspace --------------------------------------------------------------------------------------

def _check_conversions(vault, f):
    folder = vault.path(".brain/conversions")
    if not os.path.isdir(folder):
        return
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json"):
            f.warn("half-converted", f".brain/conversions/{name}", "a conversion did not finish; finish it to remove the duplicate item")


def _check_gitignore(vault, f):
    if not util.is_git_repo(vault.root):
        return
    must_commit = [".brain/config.yml", ".brain/manifest.yml", ".brain/id-index/x/x.json", ".brain/traits/x.md"]
    must_commit += [f".brain/impls/{t}/x.md" for t in CORE_TYPES]
    if os.path.isdir(vault.path(".brain/python")):
        must_commit += [".brain/python/pyproject.toml", ".brain/python/registry.yml", ".brain/python/lib/x.py",
                        ".brain/python/scripts/x.py", ".brain/python/tests/x.py", ".brain/python/brainctl/x.py"]
    for impl in vault.impls.values():
        template = impl.path_template
        if impl.adapter == "markdown" and isinstance(template, str):
            must_commit.append(re.sub(r"\{[^}]+\}", "x", template))
    archive = vault.archive_template()
    if archive:
        must_commit.append(re.sub(r"\{[^}]+\}", "x", archive))
    for rel in dict.fromkeys(must_commit):
        if util.git_ignored(vault.root, rel):
            f.error("gitignored-path", rel, "this path must be committed but git ignores it; add a negation line to .gitignore (for example !.brain/python/lib/)")
    for rel in MUST_BE_IGNORED:
        if util.git_ignored(vault.root, rel) is False:
            f.warn("gitignore-missing", rel, "derived state should be git-ignored; add it to .gitignore")


def _check_workspace(vault, f):
    py = vault.path(".brain/python")
    if not os.path.isdir(py):
        f.error("workspace-missing", ".brain/python", "the Python workspace is required (run /brain:setup)")
        return
    if not os.path.isfile(os.path.join(py, "pyproject.toml")):
        f.error("workspace-project", ".brain/python/pyproject.toml", "pyproject.toml is missing")
    if not any(os.path.isfile(os.path.join(py, name)) for name in LOCK_FILES):
        f.error("workspace-lock", ".brain/python", "no lock file (uv.lock, poetry.lock, pdm.lock or requirements.lock)")
    registry_path = os.path.join(py, "registry.yml")
    if not os.path.isfile(registry_path):
        f.error("workspace-registry", ".brain/python/registry.yml", "registry.yml is missing")
        return
    try:
        data = util.load_yaml_file(registry_path) or {}
    except Exception as exc:
        f.error("workspace-registry", ".brain/python/registry.yml", f"not valid YAML ({str(exc).splitlines()[0]})")
        return
    for script in data.get("scripts") or []:
        if not isinstance(script, dict) or not script.get("name") or not script.get("path"):
            f.error("workspace-registry", ".brain/python/registry.yml", f"bad registry entry {script!r}")
            continue
        subject = f"python:{script['name']}"
        full = os.path.join(py, script["path"])
        if not os.path.isfile(full):
            f.error("script-missing", subject, f"{script['path']} does not exist")
            continue
        approved = (script.get("approved") or {}).get("sha256")
        if not approved:
            f.warn("script-unapproved", subject, "never approved; it cannot run until the user approves it")
        elif approved != approval.approval_hash(py, script["path"]):
            f.warn("script-changed", subject, "changed since approval; show the diff and ask again")
