"""Template and reference adapter: a complete script adapter whose "backend" is a JSON file.

Copy it to .brain/python/scripts/<name>.py, rename the class, and replace `Store` with a client for your service. Keep the
service access behind `Store` so tests can swap in a fake (see the conformance kit in brainctl/conformance.py).

Settings:  {"path": "<json file>"}   (the template's only setting; a real adapter might take a project or workspace id)
"""
import json
import os
import re

from brainctl import util
from brainctl.adapter import (BrainAdapter, Conflict, Invalid, NotFound, envelope, matches_query, paginate, split_ref)


class Store:
    """The backend. Replace with a thin client for the service (HTTP or SDK): get, put, delete, all. Raise the adapter errors
    (RateLimited, Unauthorized, Unavailable) from here when the service answers with them."""

    def __init__(self, path):
        self.path = path

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, ref):
        return self._load().get(ref)

    def put(self, item):
        data = self._load()
        data[item["ref"]] = item
        self._save(data)

    def delete(self, ref):
        data = self._load()
        data.pop(ref, None)
        self._save(data)

    def all(self):
        return [v for _, v in sorted(self._load().items())]


def revision_of(item):
    """Opaque revision: a hash of everything the caller can change. A real backend would use its etag or version number."""
    body = {k: item.get(k) for k in ("fields", "relations", "body", "archive", "archived_at")}
    return util.git_blob_hash(json.dumps(body, sort_keys=True).encode())


class JsonFileAdapter(BrainAdapter):
    name = "json-file"
    settings_schema = {"path": {"type": "string", "required": True}}
    query = ["types", "impls", "fields_eq", "relations_include", "updated_since", "include_archived"]
    supports_body = True
    preserves_unknown_fields = True
    supports_traits = True
    tags = "map"
    hard_delete = True
    archive_adapter = True

    def store(self):
        return Store(self.setting("path", required=True))

    def create(self, envelope):
        type_, ident = _identity(envelope)
        store = self.store()
        ref = f"{type_}:{ident}"
        if store.get(ref):
            raise Conflict(f"{ref} already exists")
        now = util.now_iso()
        item = envelope_from(type_, ident, envelope, created=now, updated=now)
        item["revision"] = revision_of(item)
        store.put(item)
        return item

    def read(self, ref, **_):
        split_ref(ref)
        item = self.store().get(ref)
        if item is None:
            raise NotFound(f"no such item: {ref}")
        return item

    def update(self, envelope, **_):
        ref = envelope.get("ref")
        split_ref(ref)
        store = self.store()
        current = store.get(ref)
        if current is None:
            raise NotFound(f"no such item: {ref}")
        if envelope.get("revision") != current["revision"]:
            raise Conflict("the stored revision differs; re-read and retry", stored=current["revision"])
        type_, ident = split_ref(ref)
        item = envelope_from(type_, ident, dict(envelope, impl=current["impl"]), created=current["created"], updated=util.now_iso())
        item["archive"], item["archived_at"] = current["archive"], current["archived_at"]
        item["revision"] = revision_of(item)
        store.put(item)
        return item

    def delete(self, ref, revision=None, confirm=None, **_):
        if confirm != "permanent":
            raise Invalid('permanent delete needs confirm: "permanent"')
        store = self.store()
        current = store.get(ref)
        if current is None:
            raise NotFound(f"no such item: {ref}")
        if revision != current["revision"]:
            raise Conflict("the stored revision differs; re-read and retry")
        store.delete(ref)
        return {"ok": True}

    def list(self, query=None, limit=None, cursor=None, **_):
        found = [i for i in self.store().all() if matches_query(i, query)]
        return paginate(found, limit, cursor, self.max_page)


def _identity(env):
    ident = env.get("id")
    type_ = env.get("type")
    if not ident or not type_ or not env.get("impl"):
        raise Invalid("create needs id, type and impl")
    if re.search(r"\s", str(ident)):
        raise Invalid("id must not contain whitespace")
    return type_, ident


def envelope_from(type_, ident, env, created, updated):
    return envelope(type_, ident, env.get("impl"), env.get("fields"), env.get("relations"), env.get("body", ""),
                    created=created, updated=updated, archive=env.get("archive"), archived_at=env.get("archived_at"))


if __name__ == "__main__":
    JsonFileAdapter.run()
