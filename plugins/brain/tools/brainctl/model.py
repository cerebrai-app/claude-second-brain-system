"""The vault model: core constants, loading configuration and definitions, and scanning items (markdown adapter)."""
import glob
import os
import re

from . import util

CORE_TYPES = ("note", "task", "project", "area", "person")
STATUS_TYPES = ("task", "project")
CORE_STATUS = ("open", "done", "dropped")
PLACEMENT = {"task": "belongs_to", "note": "about", "project": "area"}  # areas and persons are top-level
PLACED_TARGETS = {"task": ("project", "area"), "note": ("project", "area"), "project": ("area",)}

# name -> (allowed target types, maximum targets or None)
CORE_RELATIONS = {
    "note": {"about": (("project", "area", "person"), None), "links": (("note",), None)},
    "task": {"belongs_to": (("project", "area"), 1), "assigned_to": (("person",), None), "blocked_by": (("task",), None)},
    "project": {"area": (("area",), 1), "owner": (("person",), 1)},
    "area": {"parent": (("area",), 1)},
    "person": {},
}
ALL_CORE_RELATIONS = {name for rels in CORE_RELATIONS.values() for name in rels}

RESERVED = {
    "id", "type", "impl", "created", "updated", "revision", "archive", "archived_at", "body", "title", "name", "tags",
    "status", "completed", "outcome", "defaults", "system", "traits", "contains", "about", "links", "belongs_to", "assigned_to",
    "blocked_by", "area", "owner", "parent",
}
ENVELOPE_KEYS = {"id", "type", "impl", "created", "updated", "archive", "archived_at"}
FIELD_TYPES = ("string", "text", "integer", "number", "boolean", "date", "datetime", "enum", "list")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REF_RE = re.compile(r"^(note|task|project|area|person|archive):([^\s:]+)$")
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

# fields every type may carry, beyond envelope keys and relations
COMMON_FIELDS = {"title", "tags"}
TYPE_FIELDS = {
    "note": set(),
    "task": {"status", "completed"},
    "project": {"status", "completed", "outcome", "defaults"},
    "area": {"defaults", "system"},
    "person": {"name", "traits"},
}


class Impl:
    """An implementation definition (`.brain/impls/<type>/<impl>.md`)."""

    def __init__(self, type_, name, relpath, front, body, error=None):
        self.type = type_
        self.name = name
        self.relpath = relpath
        self.front = front or {}
        self.body = body
        self.error = error
        self.extends = self.front.get("extends")
        self.version = self.front.get("version")
        self.storage = self.front.get("storage") or {}
        self.fields = ((self.front.get("schema") or {}).get("fields")) or {}
        self.status_values = self.front.get("status_values") or {}
        self.sorts = self.front.get("sorts") or {}
        self.filters = self.front.get("filters") or {}
        self.automation = self.front.get("automation") or []
        self.migration_target = bool(self.front.get("migration_target"))

    @property
    def adapter(self):
        return self.storage.get("adapter")

    @property
    def path_template(self):
        return self.storage.get("path")


class Item:
    """One stored item. `binding` is (type, impl) of the directory it was found in; `front` is the raw front matter."""

    def __init__(self, relpath, front, body, revision, binding, archived=False):
        self.relpath = relpath
        self.front = front
        self.body = body
        self.revision = revision
        self.binding = binding
        self.archived = archived

    @property
    def id(self):
        return self.front.get("id")

    @property
    def type(self):
        return self.front.get("type")

    @property
    def impl(self):
        return self.front.get("impl")

    @property
    def ref(self):
        return f"{self.type}:{self.id}"

    @property
    def title(self):
        name = self.front.get("name")
        if self.type == "person" and isinstance(name, dict):
            return display_name(name)
        return self.front.get("title")

    def relation_names(self, impl=None, trait_names=()):
        """Relation keys in this item: core relations for the type, plus a person's named relations (lists of refs that are
        not fields, traits or reserved keys)."""
        names = [n for n in CORE_RELATIONS.get(self.type, {}) if n in self.front]
        if self.type == "person":
            fields = set(impl.fields) if impl else set()
            for key, value in self.front.items():
                if key in RESERVED or key in fields or key in trait_names or key in names:
                    continue
                if isinstance(value, list) and value and all(isinstance(v, str) and REF_RE.match(v) for v in value):
                    names.append(key)
        return names

    def relations(self, impl=None, trait_names=()):
        out = {}
        for name in self.relation_names(impl, trait_names):
            value = self.front.get(name)
            out[name] = [v for v in (value if isinstance(value, list) else [value]) if v is not None]
        return out


def display_name(name):
    if not isinstance(name, dict):
        return None
    for key in ("display",):
        if isinstance(name.get(key), str) and name[key].strip():
            return name[key].strip()
    parts = [str(name[k]).strip() for k in ("given", "middle", "family") if isinstance(name.get(k), str) and name[k].strip()]
    if parts:
        return " ".join(parts)
    nick = name.get("nickname")
    return nick.strip() if isinstance(nick, str) and nick.strip() else None


class Scan:
    """The result of reading every binding. `problems` are (code, relpath, message) for files that cannot be used."""

    def __init__(self):
        self.items = []        # live and archived items with full identity, in binding order
        self.unadopted = []    # (type, impl, relpath, ParsedFile)
        self.problems = []     # (code, relpath, message)
        self.skipped = []      # (type, impl, reason): bindings this helper cannot read yet

    def live(self):
        return [i for i in self.items if not i.archived]

    def by_ref(self):
        out = {}
        for item in self.items:
            out.setdefault(item.ref, []).append(item)
        return out


class Vault:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.brain = os.path.join(self.root, ".brain")
        self.load_errors = []  # (code, relpath, message)
        self.config = self._load_yaml(".brain/config.yml", "config")
        self.manifest = self._load_yaml(".brain/manifest.yml", "manifest")
        self.impls = {}        # (type, impl) -> Impl
        self.traits = {}       # name -> dict
        self._load_impls()
        self._load_traits()

    # ---- discovery ------------------------------------------------------------------------------------------------
    @staticmethod
    def discover(start="."):
        path = os.path.abspath(start)
        while True:
            if os.path.isdir(os.path.join(path, ".brain")):
                return Vault(path)
            parent = os.path.dirname(path)
            if parent == path:
                return None
            path = parent

    def path(self, relpath):
        return os.path.join(self.root, relpath)

    def rel(self, abspath):
        return os.path.relpath(abspath, self.root).replace(os.sep, "/")

    # ---- loading --------------------------------------------------------------------------------------------------
    def _load_yaml(self, rel, what):
        full = self.path(rel)
        if not os.path.isfile(full):
            return None
        try:
            data = util.load_yaml_file(full)
        except Exception as exc:
            self.load_errors.append((f"{what}-invalid", rel, f"{what} is not valid YAML ({str(exc).splitlines()[0]})"))
            return None
        if data is None:
            data = {}
        if not isinstance(data, dict):
            self.load_errors.append((f"{what}-invalid", rel, f"{what} is not a mapping"))
            return None
        return data

    def _load_impls(self):
        for full in sorted(glob.glob(self.path(".brain/impls/*/*.md"))):
            rel = self.rel(full)
            type_dir = os.path.basename(os.path.dirname(full))
            name = os.path.splitext(os.path.basename(full))[0]
            parsed = util.read_markdown(full)
            impl = Impl(type_dir, name, rel, parsed.front, parsed.body, parsed.error)
            if parsed.front is None and not parsed.error:
                impl.error = "no front matter"
            key = (type_dir, name)
            self.impls[key] = impl

    def _load_traits(self):
        for full in sorted(glob.glob(self.path(".brain/traits/*.md"))):
            rel = self.rel(full)
            name = os.path.splitext(os.path.basename(full))[0]
            parsed = util.read_markdown(full)
            if parsed.error or parsed.front is None:
                self.load_errors.append(("trait-invalid", rel, parsed.error or "no front matter"))
                continue
            self.traits[name] = dict(parsed.front, _relpath=rel)

    # ---- queries --------------------------------------------------------------------------------------------------
    def impl_for(self, type_, name):
        return self.impls.get((type_, name))

    def impls_of(self, type_):
        return [i for (t, _), i in sorted(self.impls.items()) if t == type_]

    def config_get(self, *keys, default=None):
        node = self.config
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def archive_template(self):
        archive = (self.config or {}).get("archive") or {}
        if archive.get("adapter") == "markdown":
            return archive.get("path") or "archive/{type}/{impl}/{slug}.md"
        return None

    def _scan_script(self, scan, type_, name, impl, remote):
        if not remote:
            scan.skipped.append((type_, name, "script adapters are not read in this mode"))
            return
        from . import client as client_mod
        try:
            c = client_mod.ScriptClient.for_impl(self, impl)
            envelopes = c.list_all({"types": [type_], "impls": [name], "include_archived": True})
        except client_mod.ClientError as err:
            scan.skipped.append((type_, name, f"script adapter unavailable: {err.message}"))
            return
        for env in envelopes:
            try:
                front = client_mod.envelope_to_front(env)
            except (KeyError, AttributeError, IndexError):
                scan.problems.append(("bad-envelope", f"script:{name}", f"adapter returned a malformed envelope: {str(env)[:80]}"))
                continue
            archived = bool(front.get("archive"))
            binding = ("archive", "archive") if archived else (type_, name)
            scan.items.append(Item(f"script:{name}/{front['id']}", front, env.get("body") or "", env.get("revision"), binding, archived=archived))

    # ---- scanning (markdown adapter) --------------------------------------------------------------------------------
    def scan(self, remote=True):
        """Read every binding. With remote=False script bindings are skipped (no processes are started)."""
        scan = Scan()
        matched = {}  # relpath -> [(type, impl)] bindings whose directory pattern matches the file
        patterns = []
        for (type_, name), impl in sorted(self.impls.items()):
            if impl.error or type_ not in CORE_TYPES:
                continue
            if impl.adapter == "script":
                self._scan_script(scan, type_, name, impl, remote)
                continue
            if impl.adapter != "markdown" or not impl.path_template:
                scan.skipped.append((type_, name, f"adapter {impl.adapter!r} is not supported by this helper yet"))
                continue
            patterns.append((type_, name, impl.path_template, False))
        archive_tpl = self.archive_template()
        if archive_tpl:
            patterns.append(("archive", "archive", archive_tpl, True))
        for type_, name, template, is_archive in patterns:
            for full in sorted(glob.glob(self.path(util.template_glob(template)))):
                if os.path.isfile(full):
                    matched.setdefault(self.rel(full), []).append((type_, name, is_archive))
        for rel in sorted(matched):
            bindings = matched[rel]
            parsed = util.read_markdown(self.path(rel))
            if parsed.error:
                scan.problems.append(("unparseable-file", rel, parsed.error))
                continue
            front = parsed.front
            live = [b for b in bindings if not b[2]]
            archived = [b for b in bindings if b[2]]
            if front is not None and all(k in front for k in ("id", "type", "impl")):
                if live and any(b[0] == front["type"] and b[1] == front["impl"] for b in live):
                    scan.items.append(Item(rel, front, parsed.body, parsed.revision, (front["type"], front["impl"])))
                elif archived and front.get("archive"):
                    scan.items.append(Item(rel, front, parsed.body, parsed.revision, ("archive", "archive"), archived=True))
                else:
                    where = ", ".join(f"{t}/{n}" for t, n, _ in bindings)
                    scan.problems.append(("wrong-binding", rel, f"item is {front['type']}/{front['impl']} but the file is in the directory of {where}"))
                continue
            # missing identity fields: an unadopted file, but only when exactly one live binding matches
            if archived and not live:
                scan.problems.append(("unidentified-archive-file", rel, "file in the Archive directory has no identity fields"))
                continue
            if len(live) != 1:
                where = ", ".join(f"{t}/{n}" for t, n, _ in live)
                scan.problems.append(("ambiguous-file", rel, f"file matches more than one binding ({where}); nothing adopted"))
                continue
            scan.unadopted.append((live[0][0], live[0][1], rel, parsed))
        return scan
