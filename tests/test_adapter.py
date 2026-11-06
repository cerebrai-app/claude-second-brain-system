"""BrainAdapter (the script adapter base class), the reference adapter, and the conformance kit."""
import importlib.util
import io
import json
import os

import pytest

from brainctl import adapter as ad, conformance
from conftest import REPO

TEMPLATE = os.path.join(REPO, "plugins", "brain", "skills", "backend", "references", "adapter-template.py")


def load_template():
    spec = importlib.util.spec_from_file_location("adapter_template", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def template():
    return load_template()


@pytest.fixture
def factory(template, tmp_path):
    counter = iter(range(10_000))
    settings = lambda: {"path": str(tmp_path / f"store-{next(counter)}.json")}      # a fresh sandbox per check
    return template.JsonFileAdapter, settings


# ---- the base class ---------------------------------------------------------------------------------------------------

class Tiny(ad.BrainAdapter):
    name = "tiny"
    requires_env = ["TINY_TOKEN"]

    def read(self, ref, **_):
        if ref == "task:missing":
            raise ad.NotFound("nope")
        if ref == "task:boom":
            raise RuntimeError("bug")
        if ref == "task:limited":
            raise ad.RateLimited("slow down", retry_after=30)
        return ad.envelope("task", ref.split(":")[1], "tiny", {"title": "T"}, revision="r1")


def call(adapter, op, **args):
    return adapter.handle({"protocol": 1, "op": op, "settings": {}, "args": args})


def test_describe_reports_defaults_and_declared_env():
    out = call(Tiny(), "describe")["result"]
    assert out["adapter"] == "tiny" and out["requires_env"] == ["TINY_TOKEN"]
    assert out["capabilities"]["tags"] == "labels" and out["capabilities"]["supports_body"] is False


def test_unimplemented_operations_are_unsupported():
    for op in ("create", "update", "delete", "list", "archive", "unarchive"):
        args = {"envelope": {}} if op in ("create", "update") else {"ref": "task:a"}
        assert call(Tiny(), op, **args)["error"]["code"] == "unsupported"


def test_a_missing_required_argument_is_invalid_not_internal(capsys):
    r = call(Tiny(), "read")
    assert r["error"]["code"] == "invalid" and "ref" in r["error"]["message"]
    assert call(Tiny(), "create")["error"]["code"] == "invalid"
    assert capsys.readouterr().err == ""                              # not a crash: no traceback


def test_unknown_operation_and_bad_requests():
    assert call(Tiny(), "frobnicate")["error"]["code"] == "unsupported"
    assert Tiny().handle({"protocol": 2, "op": "describe"})["error"]["code"] == "invalid"
    assert Tiny().handle("nope")["error"]["code"] == "invalid"
    assert Tiny().handle({"op": "read", "args": "x"})["error"]["code"] == "invalid"


def test_errors_become_error_responses():
    r = call(Tiny(), "read", ref="task:missing")
    assert r == {"ok": False, "error": {"code": "not_found", "message": "nope", "retryable": False}}
    limited = call(Tiny(), "read", ref="task:limited")["error"]
    assert limited["code"] == "rate_limited" and limited["retryable"] is True and limited["retry_after"] == 30


def test_unexpected_exceptions_become_internal_errors(capsys):
    r = call(Tiny(), "read", ref="task:boom")
    assert r["error"]["code"] == "internal" and "RuntimeError" in r["error"]["message"]
    assert "Traceback" in capsys.readouterr().err                 # the traceback goes to stderr, never to the response


def test_extra_args_are_ignored_for_forward_compatibility():
    assert call(Tiny(), "read", ref="task:a", native_id="N1", future_arg=True)["ok"] is True


def test_resolve_defaults_to_a_read():
    assert call(Tiny(), "resolve", ref="task:a")["result"] == {"binding": "tiny", "found": True}
    assert call(Tiny(), "resolve", ref="task:missing")["result"] == {"binding": "tiny", "found": False}


def test_main_speaks_the_process_protocol():
    out, err = io.StringIO(), io.StringIO()
    code = Tiny().main(stdin=io.StringIO(json.dumps({"protocol": 1, "op": "read", "args": {"ref": "task:a"}})), stdout=out, stderr=err)
    assert code == 0 and json.loads(out.getvalue())["result"]["ref"] == "task:a" and err.getvalue() == ""
    out, err = io.StringIO(), io.StringIO()
    code = Tiny().main(stdin=io.StringIO(json.dumps({"protocol": 1, "op": "read", "args": {"ref": "task:missing"}})), stdout=out, stderr=err)
    assert code == 1 and json.loads(out.getvalue())["error"]["code"] == "not_found" and "not_found" in err.getvalue()
    out = io.StringIO()
    assert Tiny().main(stdin=io.StringIO("{"), stdout=out, stderr=io.StringIO()) == 1


def test_env_helper_requires_a_value_without_echoing_it(monkeypatch):
    a = Tiny()
    monkeypatch.delenv("TINY_TOKEN", raising=False)
    with pytest.raises(ad.Unauthorized):
        a.env("TINY_TOKEN")
    monkeypatch.setenv("TINY_TOKEN", "s3cret")
    assert a.env("TINY_TOKEN") == "s3cret"
    assert a.env("MISSING", required=False) is None


def test_ref_helpers():
    assert ad.split_ref("task:01J") == ("task", "01J") and ad.make_ref("note", "x") == "note:x"
    for bad in ("nope", ":x", "task:", None):
        with pytest.raises(ad.Invalid):
            ad.split_ref(bad)


def test_paginate_and_cursor_errors():
    items = list(range(5))
    first = ad.paginate(items, 2, None, 10)
    second = ad.paginate(items, 2, first["cursor"], 10)
    last = ad.paginate(items, 2, second["cursor"], 10)
    assert first["items"] == [0, 1] and second["items"] == [2, 3] and last == {"items": [4], "cursor": None}
    assert len(ad.paginate(items, 99, None, 3)["items"]) == 3                       # capped at max_page
    with pytest.raises(ad.Invalid):
        ad.paginate(items, 2, "abc", 10)


def test_matches_query():
    item = ad.envelope("task", "1", "i", {"status": "open"}, {"belongs_to": ["project:p"]}, updated="2026-11-02T00:00:00Z")
    assert ad.matches_query(item, {})
    assert ad.matches_query(item, {"types": ["task"], "impls": ["i"], "fields_eq": {"status": "open"}, "relations_include": {"belongs_to": "project:p"}})
    assert not ad.matches_query(item, {"types": ["note"]}) and not ad.matches_query(item, {"fields_eq": {"status": "done"}})
    assert not ad.matches_query(item, {"updated_since": "2026-11-03T00:00:00Z"})
    archived = dict(item, archive="archive:archive")
    assert not ad.matches_query(archived, {}) and ad.matches_query(archived, {"include_archived": True})
    assert ad.matches_query(archived, {"archived_only": True}) and not ad.matches_query(item, {"archived_only": True})


# ---- the reference adapter passes the kit ---------------------------------------------------------------------------

def test_the_reference_adapter_conforms(factory):
    cls, settings = factory
    conformance.assert_conforms(cls, settings=settings)


def test_every_check_runs_for_the_reference_adapter(factory):
    cls, settings = factory
    names = [n for n, _ in conformance.iter_checks(cls, settings=settings)]
    assert len(names) >= 18 and "update_with_a_stale_revision_conflicts" in names and "tags_round_trip_as_a_string_map" in names
    for name, run in conformance.iter_checks(cls, settings=settings):
        run()


def test_the_reference_adapter_as_a_real_process(template, tmp_path):
    import subprocess
    import sys
    store = tmp_path / "s.json"
    req = {"protocol": 1, "op": "describe", "settings": {"path": str(store)}, "args": {}}
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "plugins", "brain", "tools"))
    r = subprocess.run([sys.executable, TEMPLATE], input=json.dumps(req), capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout)["result"]["adapter"] == "json-file"
    bad = subprocess.run([sys.executable, TEMPLATE], input="{", capture_output=True, text=True, env=env)
    assert bad.returncode == 1 and json.loads(bad.stdout)["error"]["code"] == "invalid" and bad.stderr


# ---- the kit catches broken adapters -----------------------------------------------------------------------------------

def broken(template, tmp_path, **patches):
    counter = iter(range(10_000))
    settings = lambda: {"path": str(tmp_path / f"s-{next(counter)}.json")}

    class Broken(template.JsonFileAdapter):
        pass

    for name, fn in patches.items():
        setattr(Broken, name, fn)
    return Broken, settings


def failures_of(cls, settings):
    return {n for n, _ in conformance.check(cls, settings=settings)}


def test_kit_catches_updates_that_ignore_revisions(template, tmp_path):
    def update(self, envelope, **_):                                  # never raises conflict
        current = self.store().get(envelope["ref"])
        item = template.envelope_from(current["type"], current["ref"].split(":", 1)[1], dict(envelope, impl=current["impl"]), current["created"], "2026-01-01T00:00:00Z")
        item["revision"] = template.revision_of(item)
        self.store().put(item)
        return item
    cls, settings = broken(template, tmp_path, update=update)
    assert "update_with_a_stale_revision_conflicts" in failures_of(cls, settings)


def test_kit_catches_lost_tags(template, tmp_path):
    original = template.JsonFileAdapter.read

    def read(self, ref, **kw):
        item = dict(original(self, ref, **kw))
        item["fields"] = {k: v for k, v in item["fields"].items() if k != "tags"}
        return item
    cls, settings = broken(template, tmp_path, read=read)
    assert "tags_round_trip_as_a_string_map" in failures_of(cls, settings)


def test_kit_catches_listing_that_drops_items(template, tmp_path):
    original = template.JsonFileAdapter.list

    def list_(self, query=None, limit=None, cursor=None, **kw):
        page = original(self, query, limit, cursor, **kw)
        page["items"] = page["items"][:1]                              # silently drops items from every page
        return page
    cls, settings = broken(template, tmp_path, list=list_)
    assert "list_pages_through_every_item_once" in failures_of(cls, settings)


def test_kit_catches_missing_not_found_and_conflict_on_duplicates(template, tmp_path):
    def read(self, ref, **_):
        return self.store().get(ref) or ad.envelope("task", "x", "i", {}, revision="r")        # pretends everything exists

    def create(self, envelope, **_):                                    # overwrites instead of conflicting
        item = template.envelope_from(envelope["type"], envelope["id"], envelope, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
        item["revision"] = template.revision_of(item)
        self.store().put(item)
        return item
    cls, settings = broken(template, tmp_path, read=read, create=create)
    failed = failures_of(cls, settings)
    assert {"read_missing_is_not_found", "create_duplicate_id_conflicts"} <= failed


def test_kit_catches_delete_without_confirmation(template, tmp_path):
    def delete(self, ref, revision=None, confirm=None, **_):
        self.store().delete(ref)
        return {"ok": True}
    cls, settings = broken(template, tmp_path, delete=delete)
    assert "delete_needs_confirmation" in failures_of(cls, settings)


def test_kit_catches_an_adapter_that_crashes(template, tmp_path):
    def read(self, ref, **_):
        raise RuntimeError("bug")
    cls, settings = broken(template, tmp_path, read=read)
    failed = failures_of(cls, settings)
    assert "create_then_read_round_trips" in failed


def test_kit_catches_a_describe_without_capabilities(template, tmp_path):
    def describe(self):
        return {"protocol": 1, "adapter": "x", "capabilities": {"tags": "weird", "query": ["bogus"], "max_page": 0}, "requires_env": []}
    cls, settings = broken(template, tmp_path, describe=describe)
    assert "describe" in failures_of(cls, settings)


def test_kit_catches_an_unserializable_result(template, tmp_path):
    original = template.JsonFileAdapter.read

    def read(self, ref, **kw):
        item = dict(original(self, ref, **kw))
        item["fields"] = dict(item["fields"], bad=object())
        return item
    cls, settings = broken(template, tmp_path, read=read)
    assert "create_then_read_round_trips" in failures_of(cls, settings) or "results_are_json" in failures_of(cls, settings)
