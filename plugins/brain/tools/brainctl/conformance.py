"""Conformance kit for script adapters (docs/plans/12-backends.md).

You give it a factory that returns a *fresh adapter connected to an empty sandbox* (a fake client in tests, or a throwaway
project on the real service). `settings` may be a dict, or a callable returning a fresh dict for each check. It drives the adapter through the same `handle` path the process boundary uses, with every
request and response round-tripped through JSON, and reports what does not match the storage contract (docs/plans/03).

    from brainctl.conformance import check, assert_conforms, iter_checks

    def test_conforms():
        assert_conforms(lambda: MyAdapter.with_client(FakeClient()), settings={"project": "p"})

    @pytest.mark.parametrize("name, run", iter_checks(factory, settings=...))
    def test_each(name, run):
        run()
"""
import json

from . import adapter as adapter_mod, ids

REQUIRED_CAPABILITIES = ("query", "archive_adapter", "hard_delete", "native_ids", "transactions", "supports_body",
                         "preserves_unknown_fields", "supports_traits", "tags", "max_page")
QUERY_KEYS = ("types", "impls", "fields_eq", "relations_include", "updated_since", "include_archived")


class ConformanceFailure(AssertionError):
    pass


class Harness:
    """Talks to a fresh adapter the way the plugin does: JSON in, JSON out."""

    def __init__(self, factory, settings=None, type_="task", impl="conformance-test"):
        self.factory = factory
        self.settings = (settings() if callable(settings) else settings) or {}      # a callable gives each check fresh settings (a new sandbox)
        self.type = type_
        self.impl = impl
        self.adapter = factory()
        self.caps = None

    def raw(self, op, **args):
        request = json.loads(json.dumps({"protocol": 1, "op": op, "settings": self.settings, "args": args}))
        response = self.adapter.handle(request)
        try:
            return json.loads(json.dumps(response))              # the response must survive JSON
        except (TypeError, ValueError) as exc:
            raise ConformanceFailure(f"{op}: response is not JSON-serializable ({exc})") from exc

    def ok(self, op, **args):
        response = self.raw(op, **args)
        if not response.get("ok"):
            raise ConformanceFailure(f"{op} failed: {response.get('error')}")
        return response["result"]

    def err(self, op, code, **args):
        response = self.raw(op, **args)
        if response.get("ok"):
            raise ConformanceFailure(f"{op} should fail with {code!r} but succeeded: {response.get('result')}")
        error = response.get("error") or {}
        if error.get("code") not in adapter_mod.ERROR_CODES:
            raise ConformanceFailure(f"{op}: error code {error.get('code')!r} is not one of {adapter_mod.ERROR_CODES}")
        if error.get("code") != code:
            raise ConformanceFailure(f"{op} should fail with {code!r} but failed with {error.get('code')!r}: {error.get('message')}")
        if not isinstance(error.get("message"), str) or not isinstance(error.get("retryable"), bool):
            raise ConformanceFailure(f"{op}: an error needs a string message and a boolean retryable, got {error}")
        return error

    def capabilities(self):
        if self.caps is None:
            self.caps = self.ok("describe")["capabilities"]
        return self.caps

    def new_item(self, title="Draft Q4 plan", **overrides):
        """The create input for a plugin-assigned id."""
        env = {
            "id": ids.ulid(), "type": self.type, "impl": self.impl,
            "fields": {"title": title, "status": "open", "tags": {"urgent": "", "owner": "alex"}},
            "relations": {"belongs_to": ["project:01JPROJECTPROJECTPROJECT01"]},
            "body": "First line.\n\nSecond paragraph.\n",
        }
        env.update(overrides)
        return env


# ---- the checks ------------------------------------------------------------------------------------------------------

def check_describe(h):
    result = h.ok("describe")
    if result.get("protocol") != 1:
        raise ConformanceFailure("describe should report protocol 1")
    if not result.get("adapter"):
        raise ConformanceFailure("describe should name the adapter")
    caps = result.get("capabilities") or {}
    missing = [k for k in REQUIRED_CAPABILITIES if k not in caps]
    if missing:
        raise ConformanceFailure(f"describe is missing capabilities: {missing}")
    if caps["tags"] not in ("map", "labels"):
        raise ConformanceFailure("capabilities.tags must be 'map' or 'labels'")
    unknown = [k for k in caps["query"] if k not in QUERY_KEYS]
    if unknown:
        raise ConformanceFailure(f"capabilities.query names unknown keys: {unknown}")
    if not isinstance(caps["max_page"], int) or caps["max_page"] < 1:
        raise ConformanceFailure("capabilities.max_page must be a positive integer")
    if not isinstance(result.get("requires_env"), list):
        raise ConformanceFailure("describe should list requires_env (an empty list if none)")


def check_unknown_operation_is_unsupported(h):
    h.err("frobnicate", "unsupported")


def check_bad_protocol_is_invalid(h):
    response = h.adapter.handle({"protocol": 99, "op": "describe"})
    if response.get("ok") or response["error"]["code"] != "invalid":
        raise ConformanceFailure("an unsupported protocol version should fail with 'invalid'")


def check_create_then_read_round_trips(h):
    item = h.new_item()
    created = h.ok("create", envelope=item)
    ref = f"{h.type}:{item['id']}"
    if created.get("ref") != ref:
        raise ConformanceFailure(f"create should return ref {ref}, got {created.get('ref')}")
    if not created.get("revision") or not isinstance(created["revision"], str):
        raise ConformanceFailure("create should return an opaque string revision")
    if not created.get("created") or not created.get("updated"):
        raise ConformanceFailure("create should set created and updated")
    read = h.ok("read", ref=ref, **_native(created))
    for key in ("ref", "type", "impl", "fields", "relations", "revision"):
        if read.get(key) != created.get(key):
            raise ConformanceFailure(f"read differs from create in {key}: {read.get(key)!r} vs {created.get(key)!r}")
    if read["fields"].get("title") != item["fields"]["title"] or read["fields"].get("status") != "open":
        raise ConformanceFailure("fields did not round-trip")
    if read["relations"] != item["relations"]:
        raise ConformanceFailure(f"relations did not round-trip: {read['relations']}")


def check_tags_round_trip_as_a_string_map(h):
    item = h.new_item()
    h.ok("create", envelope=item)
    read = h.ok("read", ref=f"{h.type}:{item['id']}")
    if read["fields"].get("tags") != item["fields"]["tags"]:
        raise ConformanceFailure(f"tags must round-trip as the same name-to-string map (capabilities.tags={h.capabilities()['tags']!r}); "
                                 f"got {read['fields'].get('tags')!r}. With 'labels', keep the values in storage.tag_values_field and recombine them on read.")


def check_body_round_trips_when_supported(h):
    item = h.new_item()
    h.ok("create", envelope=item)
    read = h.ok("read", ref=f"{h.type}:{item['id']}")
    if h.capabilities()["supports_body"]:
        if read.get("body") != item["body"]:
            raise ConformanceFailure(f"supports_body is true but the body changed: {read.get('body')!r}")
    elif read.get("body") not in ("", None):
        raise ConformanceFailure("supports_body is false but a body came back")


def check_unknown_fields_preserved_when_declared(h):
    if not h.capabilities()["preserves_unknown_fields"]:
        return
    item = h.new_item()
    item["fields"]["x_custom"] = "kept"
    item["fields"]["x_number"] = 7
    h.ok("create", envelope=item)
    read = h.ok("read", ref=f"{h.type}:{item['id']}")
    for key in ("x_custom", "x_number"):
        if read["fields"].get(key) != item["fields"][key]:
            raise ConformanceFailure(f"preserves_unknown_fields is true but {key} came back as {read['fields'].get(key)!r}")


def check_create_duplicate_id_conflicts(h):
    item = h.new_item()
    h.ok("create", envelope=item)
    h.err("create", "conflict", envelope=item)


def check_read_missing_is_not_found(h):
    h.err("read", "not_found", ref=f"{h.type}:01JNOSUCHITEMNOSUCHITEM0001")


def check_resolve(h):
    item = h.new_item()
    h.ok("create", envelope=item)
    found = h.ok("resolve", ref=f"{h.type}:{item['id']}")
    missing = h.ok("resolve", ref=f"{h.type}:01JNOSUCHITEMNOSUCHITEM0001")
    if found.get("found") is not True or missing.get("found") is not False:
        raise ConformanceFailure(f"resolve should report found true/false, got {found} and {missing}")


def check_update_changes_content_and_revision(h):
    item = h.new_item()
    created = h.ok("create", envelope=item)
    ref = created["ref"]
    changed = dict(created, fields=dict(created["fields"], status="done"), body=created["body"] + "More.\n")
    updated = h.ok("update", envelope=changed)
    if updated["revision"] == created["revision"]:
        raise ConformanceFailure("update should return a new revision")
    read = h.ok("read", ref=ref)
    if read["fields"]["status"] != "done":
        raise ConformanceFailure("update did not store the new status")
    if h.capabilities()["supports_body"] and not read["body"].endswith("More.\n"):
        raise ConformanceFailure("update did not store the new body")
    if read["created"] != created["created"]:
        raise ConformanceFailure("update must not change created")


def check_update_with_a_stale_revision_conflicts(h):
    created = h.ok("create", envelope=h.new_item())
    h.ok("update", envelope=dict(created, fields=dict(created["fields"], status="done")))
    h.err("update", "conflict", envelope=dict(created, fields=dict(created["fields"], title="Late edit")))


def check_update_missing_is_not_found(h):
    created = h.ok("create", envelope=h.new_item())
    ghost = dict(created, ref=f"{h.type}:01JNOSUCHITEMNOSUCHITEM0001")
    h.err("update", "not_found", envelope=ghost)


def check_update_removes_relations_and_fields(h):
    created = h.ok("create", envelope=h.new_item())
    stripped = dict(created, relations={}, fields={"title": created["fields"]["title"], "status": "open"})
    h.ok("update", envelope=stripped)
    read = h.ok("read", ref=created["ref"])
    if read["relations"].get("belongs_to"):
        raise ConformanceFailure("update is a full replace: a removed relation must be gone")
    if read["fields"].get("tags"):
        raise ConformanceFailure("update is a full replace: removed tags must be gone")


def check_list_pages_through_every_item_once(h):
    refs = {f"{h.type}:{h.ok('create', envelope=h.new_item(title=f'Item {n}'))['ref'].split(':', 1)[1]}" for n in range(5)}
    seen, cursor, pages = [], None, 0
    while True:
        page = h.ok("list", query={}, limit=2, cursor=cursor)
        pages += 1
        if not isinstance(page.get("items"), list) or len(page["items"]) > 2:
            raise ConformanceFailure("list must return at most `limit` items per page")
        seen += [i["ref"] for i in page["items"]]
        cursor = page.get("cursor")
        if cursor is None:
            break
        if pages > 20:
            raise ConformanceFailure("list never ended: the cursor kept coming")
    if len(seen) != len(set(seen)):
        raise ConformanceFailure("list returned an item more than once across pages")
    if refs - set(seen):
        raise ConformanceFailure(f"list returned fewer items than exist: missing {sorted(refs - set(seen))}")


def check_list_returns_full_envelopes(h):
    h.ok("create", envelope=h.new_item())
    items = h.ok("list", query={}, limit=10)["items"]
    for key in ("ref", "type", "impl", "fields", "relations", "revision"):
        if key not in items[0]:
            raise ConformanceFailure(f"list must return full envelopes; {key} is missing")


def check_list_never_returns_fewer_than_match(h):
    """An adapter may over-return for query keys it does not honor (the caller filters), but never under-return."""
    a = h.ok("create", envelope=h.new_item(title="A"))
    other = h.new_item(title="B", fields={"title": "B", "status": "done", "tags": {}})
    h.ok("create", envelope=other)
    got = {i["ref"] for i in h.ok("list", query={"fields_eq": {"status": "open"}}, limit=50)["items"]}
    if a["ref"] not in got:
        raise ConformanceFailure("list with fields_eq dropped a matching item")
    caps = h.capabilities()
    if "fields_eq" in caps["query"] and f"{h.type}:{other['id']}" in got:
        raise ConformanceFailure("fields_eq is declared as honored natively but a non-matching item came back")
    if "types" in caps["query"]:
        got = {i["ref"] for i in h.ok("list", query={"types": ["note"]}, limit=50)["items"]}
        if a["ref"] in got:
            raise ConformanceFailure("types is declared as honored natively but an item of another type came back")


def check_list_respects_max_page(h):
    cap = h.capabilities()["max_page"]
    page = h.ok("list", query={}, limit=cap + 1000)
    if len(page["items"]) > cap:
        raise ConformanceFailure("list returned more than capabilities.max_page items")


def check_delete_needs_confirmation(h):
    created = h.ok("create", envelope=h.new_item())
    if not h.capabilities()["hard_delete"]:
        h.err("delete", "unsupported", ref=created["ref"], revision=created["revision"], confirm="permanent")
        return
    h.err("delete", "invalid", ref=created["ref"], revision=created["revision"])
    h.err("delete", "conflict", ref=created["ref"], revision="stale", confirm="permanent")
    h.ok("delete", ref=created["ref"], revision=created["revision"], confirm="permanent")
    h.err("read", "not_found", ref=created["ref"])


def check_results_are_json(h):
    created = h.ok("create", envelope=h.new_item())
    json.dumps(created)
    json.dumps(h.ok("list", query={}, limit=5))


def check_main_speaks_the_process_protocol(h):
    import io
    out, err = io.StringIO(), io.StringIO()
    code = h.factory().main(stdin=io.StringIO(json.dumps({"protocol": 1, "op": "describe", "settings": h.settings, "args": {}})), stdout=out, stderr=err)
    if code != 0 or not json.loads(out.getvalue())["ok"]:
        raise ConformanceFailure("main() should answer a describe request with ok and exit code 0")
    out, err = io.StringIO(), io.StringIO()
    code = h.factory().main(stdin=io.StringIO("not json"), stdout=out, stderr=err)
    body = json.loads(out.getvalue())
    if code == 0 or body["ok"] or body["error"]["code"] != "invalid" or not err.getvalue():
        raise ConformanceFailure("main() should answer bad input with an 'invalid' error, a non-zero exit code and a message on stderr")


CHECKS = [(name[len("check_"):], fn) for name, fn in sorted(globals().items()) if name.startswith("check_")]


# ---- entry points ----------------------------------------------------------------------------------------------------

def iter_checks(factory, settings=None, type_="task", impl="conformance-test"):
    """Yield (name, callable) pairs, each running one check on a fresh adapter: handy for pytest parametrization."""
    for name, fn in CHECKS:
        yield name, (lambda fn=fn: fn(Harness(factory, settings, type_, impl)))


def check(factory, settings=None, type_="task", impl="conformance-test"):
    """Run every check; return a list of (name, message) failures (empty when the adapter conforms)."""
    failures = []
    for name, run in iter_checks(factory, settings, type_, impl):
        try:
            run()
        except ConformanceFailure as exc:
            failures.append((name, str(exc)))
        except Exception as exc:  # an unexpected crash is a failure too
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    return failures


def assert_conforms(factory, settings=None, type_="task", impl="conformance-test"):
    failures = check(factory, settings, type_, impl)
    if failures:
        raise ConformanceFailure("adapter does not conform:\n" + "\n".join(f"  - {n}: {m}" for n, m in failures))


def _native(envelope):
    return {"native_id": envelope["native_id"]} if envelope.get("native_id") else {}
