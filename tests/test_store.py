"""The deterministic writes: create, update, archive, unarchive, delete, convert, rule operations, the pending queue and the log."""
import json
import os

import pytest

from brainctl import pending, store, sync as sync_mod, util, validate
from brainctl.store import StoreError


def front(b, rel):
    return util.ParsedFile(b.read(rel)).front


def lint(b):
    return [f for f in validate.validate(b.vault()) if f["severity"] == "error"]


@pytest.fixture
def v(b):
    sync_mod.sync(b.vault())                               # a baseline seen state, as after setup
    return b.vault()


# ---- create -----------------------------------------------------------------------------------------------------------

def test_create_assigns_everything_and_validates(b, v):
    r = store.create(v, {"type": "note", "title": "Idea from the bus", "body": "What if?\n", "tags": ["Ux", "review"]})
    assert r["path"] == "notes/idea-from-the-bus.md" and r["ref"].startswith("note:")
    f = front(b, r["path"])
    assert list(f)[:5] == ["id", "slug", "type", "impl", "title"] and f["slug"] == "idea-from-the-bus"
    assert f["impl"] == "default-note" and f["tags"] == {"ux": "", "review": ""}
    assert f["created"] == f["updated"] and len(f["id"]) == 26
    assert b.read(r["path"]).endswith("---\nWhat if?\n")
    assert lint(b) == []


def test_create_same_title_gets_the_zero_padded_suffix(b, v):
    store.create(v, {"type": "note", "title": "Same"})
    second = store.create(v, {"type": "note", "title": "Same"})
    assert second["path"] == "notes/same-02.md" and front(b, second["path"])["slug"] == "same-02"


def test_create_task_defaults_status_and_the_helper_writes_do_not_show_as_external(b, v):
    r = store.create(v, {"type": "task", "title": "Draft Q4 plan"})
    assert front(b, r["path"])["status"] == "open"
    assert sync_mod.sync(b.vault())["events"] == []        # the seen state already knows this write


def test_create_done_task_sets_completed(b, v):
    r = store.create(v, {"type": "task", "title": "Old", "status": "done"})
    assert front(b, r["path"])["completed"]


def test_create_person_with_a_trait(b, v):
    b.trait("colleague")
    r = store.create(b.vault(), {"type": "person", "name": "Alex Rivera", "traits": ["colleague"], "colleague": {"employer": "Acme"}})
    f = front(b, r["path"])
    assert r["path"] == "people/alex-rivera.md" and f["name"] == {"display": "Alex Rivera"} and f["colleague"] == {"employer": "Acme"}
    assert lint(b) == []


def test_create_follows_the_defaults_cascade(b, v):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], default: work }\n", path="tasks/gtd/{slug}.md")
    project = store.create(v, {"type": "project", "title": "Q4"})
    store.update(b.vault(), project["ref"], {"set": {"defaults": {"task": "gtd"}}})
    r = store.create(b.vault(), {"type": "task", "title": "Plan", "belongs_to": project["ref"]})
    assert r["path"] == "tasks/gtd/plan.md" and front(b, r["path"])["context"] == "work"      # impl from the project; schema default applied
    assert front(b, r["path"])["belongs_to"] == [project["ref"]]
    plain = store.create(b.vault(), {"type": "task", "title": "Plain"})
    assert plain["path"] == "tasks/plain.md"                                                  # no placement: the Inbox default


def test_create_refuses_bad_input_and_changes_nothing(b, v):
    before = sorted(os.listdir(b.root))
    for spec in ({"type": "thing"}, {"type": "note"}, {"type": "note", "title": "x", "id": "1"}, {"type": "note", "title": "x", "slug": "y"},
                 {"type": "note", "title": "x", "impl": "ghost"}, {"type": "task", "title": "x", "status": "nonsense"}):
        with pytest.raises(StoreError) as e:
            store.create(v, spec)
        assert e.value.code in ("invalid",)
    assert sorted(os.listdir(b.root)) == before and not os.path.exists(b.path("notes")) and not os.path.exists(b.path("tasks"))


def test_create_rolls_back_a_file_that_fails_validation(b, v):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], required: true }\n", path="tasks/gtd/{slug}.md")
    with pytest.raises(StoreError) as e:
        store.create(b.vault(), {"type": "task", "title": "x", "impl": "gtd"})
    assert "context" in json.dumps(e.value.to_dict()) and not os.path.exists(b.path("tasks/gtd/x.md"))


# ---- update -----------------------------------------------------------------------------------------------------------

def test_update_edits_only_the_changed_lines(b, v):
    r = store.create(v, {"type": "task", "title": "Draft"})
    path = b.path(r["path"])
    text = open(path).read().replace("status: open\n", "# a comment\nstatus: open\ncustom: keep me\n")
    open(path, "w").write(text)
    sync_mod.sync(b.vault(), refresh=True)
    store.update(b.vault(), r["ref"], {"set": {"status": "done"}})
    new = open(path).read()
    assert "# a comment\nstatus: done\ncustom: keep me\n" in new                          # comment, neighbours and order survive
    f = front(b, r["path"])
    assert f["status"] == "done" and f["completed"] and f["updated"] >= f["created"]


def test_update_status_back_to_open_clears_completed(b, v):
    r = store.create(v, {"type": "task", "title": "T", "status": "done"})
    store.update(v, r["ref"], {"set": {"status": "open"}})
    assert "completed" not in front(b, r["path"])


def test_update_noop_leaves_the_file_alone(b, v):
    r = store.create(v, {"type": "note", "title": "N"})
    before = b.read(r["path"])
    out = store.update(v, r["ref"], {"set": {"title": "N"}})
    assert out["changed"] == [] and b.read(r["path"]) == before


def test_update_body_relations_unset_and_tags(b, v):
    area = store.create(v, {"type": "area", "title": "Work"})
    r = store.create(v, {"type": "note", "title": "N", "body": "old\n", "tags": {"a": "1"}})
    out = store.update(v, r["ref"], {"set": {"about": area["ref"], "tags": ["x"]}, "body": "new\n"})
    f = front(b, r["path"])
    assert f["about"] == [area["ref"]] and f["tags"] == {"x": ""} and b.read(r["path"]).endswith("---\nnew\n")
    assert set(out["changed"]) == {"about", "tags", "body"}
    store.update(v, r["ref"], {"unset": ["about"]})
    assert "about" not in front(b, r["path"]) and lint(b) == []


def test_update_conflict_and_forbidden_keys(b, v):
    r = store.create(v, {"type": "note", "title": "N"})
    with pytest.raises(StoreError) as e:
        store.update(v, r["ref"], {"set": {"title": "M"}, "revision": "0" * 40})
    assert e.value.code == "conflict"
    for key in ("slug", "id", "created", "updated", "impl", "completed"):
        with pytest.raises(StoreError) as e:
            store.update(v, r["ref"], {"set": {key: "x"}})
        assert e.value.code == "invalid"
    assert front(b, r["path"])["title"] == "N"
    with pytest.raises(StoreError) as e:
        store.update(v, "note:NOPE", {"set": {"title": "x"}})
    assert e.value.code == "not_found"


def test_update_moves_the_file_when_the_path_changes_and_rolls_back_invalid_changes(b, v):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], default: work }\n", path="tasks/gtd/{context}/{slug}.md")
    r = store.create(b.vault(), {"type": "task", "title": "Plan", "impl": "gtd"})
    assert r["path"] == "tasks/gtd/work/plan.md"
    out = store.update(b.vault(), r["ref"], {"set": {"context": "home"}})
    assert out["moved"] and out["path"] == "tasks/gtd/home/plan.md" and not os.path.exists(b.path("tasks/gtd/work/plan.md"))
    with pytest.raises(StoreError):
        store.update(b.vault(), r["ref"], {"set": {"context": "mars"}})
    assert os.path.exists(b.path("tasks/gtd/home/plan.md")) and front(b, "tasks/gtd/home/plan.md")["context"] == "home"
    assert sync_mod.sync(b.vault())["events"] == []


# ---- archive, unarchive, delete ---------------------------------------------------------------------------------------

def test_archive_and_unarchive_round_trip(b, v):
    r = store.create(v, {"type": "note", "title": "Old note", "body": "keep\n"})
    a = store.archive(v, r["ref"])
    assert a["path"].startswith("archive/note/default-note/old-note") and not os.path.exists(b.path(r["path"]))
    f = front(b, a["path"])
    assert f["archive"] == "archive:archive" and f["archived_at"] and lint(b) == []
    back = store.unarchive(v, r["ref"])
    assert back["path"] == r["path"] and "archive" not in front(b, back["path"]) and b.read(back["path"]).endswith("---\nkeep\n")
    assert sync_mod.sync(b.vault())["events"] == []


def test_system_items_cannot_be_archived_or_deleted(b, v):
    with pytest.raises(StoreError):
        store.archive(v, "area:inbox")
    with pytest.raises(StoreError):
        store.delete(v, "area:inbox", "permanent")


def test_delete_needs_confirmation_and_reports_referrers(b, v):
    project = store.create(v, {"type": "project", "title": "P"})
    task = store.create(v, {"type": "task", "title": "T", "belongs_to": project["ref"]})
    with pytest.raises(StoreError):
        store.delete(v, project["ref"], None)
    assert os.path.exists(b.path(project["path"]))
    out = store.delete(v, project["ref"], "permanent")
    assert out["referenced_by"] == [task["ref"]] and not os.path.exists(b.path(project["path"]))


# ---- convert ----------------------------------------------------------------------------------------------------------

def _gtd(b):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], required: true }\n    priority: { type: enum, values: [low, med, high], default: med }\n",
           path="tasks/gtd/{slug}.md")


def test_convert_plan_reports_missing_and_filled_by_default(b, v):
    _gtd(b)
    r = store.create(b.vault(), {"type": "task", "title": "Plan"})
    plan = store.convert_plan(b.vault(), r["ref"], "gtd")
    assert plan["missing"] == [{"field": "context", "type": "enum"}] and plan["filled_by_default"] == {"priority": "med"}
    assert plan["needs_resolution"] and "title" in plan["carried"] and "status" in plan["carried"]


def test_convert_apply_needs_every_resolution_then_moves_the_item(b, v):
    _gtd(b)
    r = store.create(b.vault(), {"type": "task", "title": "Plan"})
    with pytest.raises(StoreError) as e:
        store.convert_apply(b.vault(), r["ref"], "gtd", {})
    assert "context" in e.value.message and os.path.exists(b.path(r["path"]))
    out = store.convert_apply(b.vault(), r["ref"], "gtd", {"fill": {"context": "work"}})
    f = front(b, out["path"])
    assert out["path"] == "tasks/gtd/plan.md" and f["impl"] == "gtd" and f["context"] == "work" and f["priority"] == "med"
    assert f["id"] == r["ref"].split(":")[1] and not os.path.exists(b.path(r["path"]))
    assert lint(b) == [] and sync_mod.sync(b.vault())["events"] == []


def test_convert_drops_unmapped_fields_and_slug_when_the_target_has_none(b, v):
    b.impl("note", "rich", fields="    summary: { type: string }\n", path="rich/{slug}.md")
    b.impl("note", "bare", path="bare/{id}.md")
    r = store.create(b.vault(), {"type": "note", "title": "N", "impl": "rich", "summary": "s"})
    plan = store.convert_plan(b.vault(), r["ref"], "bare")
    assert plan["unmapped"] == [{"field": "summary", "value": "s"}] and plan["dropped"] == ["slug"]
    out = store.convert_apply(b.vault(), r["ref"], "bare", {"drop": ["summary"]})
    f = front(b, out["path"])
    assert "summary" not in f and "slug" not in f and out["path"] == f"bare/{f['id']}.md"


def test_failed_source_delete_leaves_a_marker_that_finish_clears(b, v, monkeypatch):
    _gtd(b)
    r = store.create(b.vault(), {"type": "task", "title": "Plan"})
    real = store._remove
    def flaky(path):
        if path.endswith("tasks/plan.md"):
            raise OSError("disk says no")
        real(path)
    monkeypatch.setattr(store, "_remove", flaky)
    with pytest.raises(StoreError) as e:
        store.convert_apply(b.vault(), r["ref"], "gtd", {"fill": {"context": "home"}})
    assert e.value.code == "internal" and os.path.exists(b.path(".brain/conversions/" + r["ref"].replace(":", "-") + ".json"))
    assert any(f["code"] == "duplicate-ref" for f in lint(b))
    monkeypatch.setattr(store, "_remove", real)
    store.finish_conversion(b.vault(), r["ref"])
    assert lint(b) == [] and not os.listdir(b.path(".brain/conversions"))


# ---- operations, pending, log -----------------------------------------------------------------------------------------

def test_operations(b, v):
    area = store.create(v, {"type": "area", "title": "Work"})
    n = store.create(v, {"type": "note", "title": "N"})
    pending.apply_operation(v, {"op": "add_relation", "ref": n["ref"], "relation": "about", "target": area["ref"]})
    pending.apply_operation(v, {"op": "add_relation", "ref": n["ref"], "relation": "about", "target": area["ref"]})          # idempotent
    assert front(b, n["path"])["about"] == [area["ref"]]
    pending.apply_operation(v, {"op": "set_field", "ref": n["ref"], "field": "tags", "value": {"topic": "mobile"}})
    pending.apply_operation(v, {"op": "set_relation", "ref": n["ref"], "relation": "about", "value": []})
    assert "about" not in front(b, n["path"]) and front(b, n["path"])["tags"] == {"topic": "mobile"}
    made = pending.apply_operation(v, {"op": "create_item", "type": "note", "fields": {"title": "Made"}, "place": area["ref"]})
    assert front(b, made["path"])["about"] == [area["ref"]]
    with pytest.raises(StoreError):
        pending.apply_operation(v, {"op": "convert", "ref": n["ref"]})


def _event(ref):
    return {"id": "ev_1", "trigger": "capture", "ref": ref, "origin": "external/note/default-note", "depth": 0}


def test_pending_add_list_apply(b, v):
    n = store.create(v, {"type": "note", "title": "N"})
    ops = [{"op": "set_field", "ref": n["ref"], "field": "tags", "value": {"topic": "mobile"}}]
    added = pending.add(v, {"rule": "note/default-note/suggest", "event": _event(n["ref"]), "instruction": "tag it", "rationale": "mobile", "operations": ops})
    assert added["path"].startswith(".brain/automation/pending/") and pending.list_entries(v)["entries"][0]["state"] == "fresh"
    entry = json.load(open(b.path(added["path"])))
    assert entry["revision"] and entry["status"] == "pending" and entry["event"]["id"] == "ev_1"
    assert pending.apply(v, added["id"])["applied"] == 1
    assert front(b, n["path"])["tags"] == {"topic": "mobile"} and not os.path.exists(b.path(added["path"]))
    last = [json.loads(l) for l in open(b.path(".brain/automation/log.jsonl"))][-1]
    assert last["outcome"] == "approved-applied" and last["pending"] == added["id"]
    assert not [f for f in validate.validate(b.vault()) if f["code"].startswith("log-")]


def test_pending_goes_stale_when_the_item_changes_and_can_be_rejected_or_expire(b, v):
    n = store.create(v, {"type": "note", "title": "N"})
    ops = [{"op": "set_field", "ref": n["ref"], "field": "tags", "value": {"a": "b"}}]
    spec = {"rule": "note/default-note/r", "event": _event(n["ref"]), "rationale": "why", "operations": ops}
    stale = pending.add(v, spec)
    store.update(v, n["ref"], {"body": "changed\n"})
    assert pending.list_entries(v)["entries"][0]["state"] == "stale"
    with pytest.raises(StoreError) as e:
        pending.apply(v, stale["id"])
    assert e.value.code == "conflict" and "tags" not in front(b, n["path"])
    assert pending.reject(v, stale["id"])["rejected"] and pending.list_entries(v)["count"] == 0
    old = pending.add(v, dict(spec, expires_days=0))
    path = b.path(old["path"])
    entry = json.load(open(path))
    entry["expires"] = "2020-01-01T00:00:00Z"
    open(path, "w").write(json.dumps(entry))
    assert pending.list_entries(v)["entries"][0]["state"] == "expired"
    assert pending.list_entries(v, prune=True)["count"] == 0 and not os.path.exists(path)


def test_pending_add_validates_the_proposal(b, v):
    n = store.create(v, {"type": "note", "title": "N"})
    base = {"rule": "note/default-note/r", "event": _event(n["ref"]), "rationale": "why", "operations": [{"op": "archive", "ref": n["ref"]}]}
    for bad in (dict(base, operations=[]), dict(base, operations=[{"op": "convert", "ref": n["ref"]}]), dict(base, rationale=""),
                dict(base, event={"ref": n["ref"]}), dict(base, rule="nope")):
        with pytest.raises(StoreError):
            pending.add(v, bad)


def test_log_lines_use_the_vocabulary(b, v):
    pending.append_log(v, {"rule": "vault/r", "trigger": "manual", "outcome": "skipped", "reason": "exists"})
    for bad in ({"outcome": "weird"}, {"outcome": "skipped"}, {"outcome": "failed"}):
        with pytest.raises(StoreError):
            pending.append_log(v, bad)
    line = json.loads(open(b.path(".brain/automation/log.jsonl")).read().splitlines()[-1])
    assert line["outcome"] == "skipped" and line["reason"] == "exists" and line["rule"] == "vault/r" and line["ts"]


def test_create_item_unless_exists_and_place(b, v):
    b.impl("note", "journal", path="journal/{slug}.md")
    op = {"op": "create_item", "type": "note", "impl": "journal", "title": "2026-11-06",
          "unless_exists": {"type": "note", "impl": "journal", "where": {"title": "2026-11-06"}},
          "place": {"find": {"type": "area", "where": {"title": "Journals"}}, "create_if_missing": True}}
    first = pending.apply_operation(b.vault(), op)
    assert first["path"] == "journal/2026-11-06.md" and first["created_placement"].startswith("area:")
    area = first["created_placement"]
    assert front(b, first["path"])["about"] == [area] and front(b, "areas/journals.md")["title"] == "Journals"
    second = pending.apply_operation(b.vault(), op)                                      # idempotent: skipped, nothing created
    assert second["skipped"] == "exists" and second["ref"] == first["ref"]
    assert sorted(os.listdir(b.path("journal"))) == ["2026-11-06.md"] and sorted(os.listdir(b.path("areas"))) == ["inbox.md", "journals.md"]
    third = pending.apply_operation(b.vault(), dict(op, title="2026-11-07", unless_exists={"type": "note", "impl": "journal", "where": {"title": "2026-11-07"}}))
    assert front(b, third["path"])["about"] == [area] and "created_placement" not in third          # the existing area is found, not duplicated
    assert lint(b) == []


def test_place_errors(b, v):
    with pytest.raises(StoreError) as e:
        pending.apply_operation(v, {"op": "create_item", "type": "note", "title": "x", "place": {"find": {"type": "area", "where": {"title": "Nope"}}}})
    assert e.value.code == "not_found" and not os.path.exists(b.path("notes"))
    with pytest.raises(StoreError) as e:
        pending.apply_operation(v, {"op": "create_item", "type": "area", "title": "x", "place": "area:inbox"})
    assert e.value.code == "invalid"
    store.create(v, {"type": "area", "title": "Dup"})
    store.create(v, {"type": "area", "title": "Dup"})
    with pytest.raises(StoreError) as e:
        pending.apply_operation(v, {"op": "create_item", "type": "note", "title": "x", "place": {"find": {"type": "area", "where": {"title": "Dup"}}}})
    assert e.value.code == "conflict"


def test_op_accepts_a_rule_action_as_written(b, v):
    made = pending.apply_operation(v, {"action": "create_item", "type": "note", "title": "From a rule"})
    assert made["path"] == "notes/from-a-rule.md"
