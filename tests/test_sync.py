"""`brainctl sync`: detection by ref across bindings, adoption of hand-written files, seen state (docs/plans/05)."""
import json
import os

from brainctl import sync as sync_mod, util


def run(b, **kw):
    return sync_mod.sync(b.vault(), **kw)


def triggers(result, ref=None):
    return [(e["trigger"], e["ref"]) for e in result["events"] if ref is None or e["ref"] == ref]


def of(result, trigger):
    return [e for e in result["events"] if e["trigger"] == trigger]


# ---- baseline ---------------------------------------------------------------------------------------------------------

def test_first_sync_builds_a_silent_baseline(b):
    b.item("task", "default-task", "tasks", "One", "status: open\n")
    b.item("note", "default-note", "notes", "Two")
    result = run(b)
    assert result["report"]["baseline"] is True and result["events"] == []
    assert os.path.exists(b.path(".brain/automation/seen/task/default-task.json"))


def test_a_second_sync_is_quiet(b):
    b.item("task", "default-task", "tasks", "One", "status: open\n")
    run(b)
    again = run(b)
    assert again["report"]["baseline"] is False and again["events"] == []


def test_seen_state_file_shape(b):
    i, _ = b.item("task", "default-task", "tasks", "One", "status: open\n")
    run(b)
    data = json.load(open(b.path(".brain/automation/seen/task/default-task.json")))
    entry = data["entries"][f"task:{i}"]
    assert data["impl"] == "default-task" and "revision" in entry and entry["fields"]["title"] == "One"
    assert "body" not in entry and "body_sha" in entry                      # no body, only its hash


def test_dry_run_writes_nothing(b):
    b.item("task", "default-task", "tasks", "One", "status: open\n")
    b.write("notes/by-hand.md", "# By hand\n")
    result = run(b, dry_run=True)
    assert result["report"]["adopted"] == [] and result["report"]["unadopted"] == ["notes/by-hand.md"]
    assert not os.path.exists(b.path(".brain/automation/seen"))
    assert b.read("notes/by-hand.md") == "# By hand\n"


# ---- events -----------------------------------------------------------------------------------------------------------

def test_new_items_fire_create_and_capture_only_in_the_inbox(b):
    run(b)
    t, _ = b.item("task", "default-task", "tasks", "Inbox task", "status: open\n")
    a, _ = b.item("area", "default-area", "areas", "Work")
    n, _ = b.item("note", "default-note", "notes", "Placed note", f"about: [area:{a}]\n")
    pers, _ = b.item("person", "default-person", "people", "Pat", name_block="name:\n  given: Pat\n")
    result = run(b)
    assert ("create", f"task:{t}") in triggers(result) and ("capture", f"task:{t}") in triggers(result)
    assert ("capture", f"area:{a}") not in triggers(result)                  # areas are top-level
    assert ("capture", f"note:{n}") not in triggers(result)                  # placed under an area
    assert ("capture", f"person:{pers}") not in triggers(result)             # persons are top-level
    assert all(e["origin"].startswith("external/") and e["depth"] == 0 for e in result["events"])
    assert [e["origin"] for e in of(result, "create") if e["ref"] == f"task:{t}"] == ["external/task/default-task"]


def test_update_lists_what_changed(b):
    i, _ = b.item("task", "default-task", "tasks", "Draft", "status: open\n")
    run(b)
    b.edit("tasks/draft.md", "status: open", "status: done")
    result = run(b)
    (event,) = of(result, "update")
    assert event["ref"] == f"task:{i}" and event["changed"] == ["status"]
    assert event["before"]["fields"]["status"] == "open" and event["after"]["fields"]["status"] == "done"


def test_body_changes_are_reported_as_body(b):
    b.item("note", "default-note", "notes", "Idea", body="one\n")
    run(b)
    b.edit("notes/idea.md", "one\n", "two\n")
    (event,) = of(run(b), "update")
    assert event["changed"] == ["body"]


def test_relation_changes_also_fire_a_relation_event(b):
    a1, _ = b.item("area", "default-area", "areas", "A1")
    a2, _ = b.item("area", "default-area", "areas", "A2")
    t, _ = b.item("task", "default-task", "tasks", "T", f"status: open\nbelongs_to: [area:{a1}]\n")
    run(b)
    b.edit("tasks/t.md", f"belongs_to: [area:{a1}]", f"belongs_to: [area:{a2}]")
    result = run(b)
    (rel,) = of(result, "relation")
    assert rel["relation"] == "belongs_to" and rel["added"] == [f"area:{a2}"] and rel["removed"] == [f"area:{a1}"]
    assert of(result, "update")[0]["changed"] == ["belongs_to"]


def test_a_missing_item_is_reported_not_an_event(b):
    i, _ = b.item("task", "default-task", "tasks", "Gone", "status: open\n")
    run(b)
    b.remove("tasks/gone.md")
    result = run(b)
    assert result["events"] == [] and result["report"]["missing"] == [f"task:{i}"]


def test_archive_and_unarchive_events(b):
    i, _ = b.item("note", "default-note", "notes", "Old")
    run(b)
    text = b.read("notes/old.md").replace("created:", "archive: archive:archive\narchived_at: 2026-11-06T00:00:00Z\ncreated:")
    b.remove("notes/old.md")
    b.write("archive/note/default-note/old.md", text)
    result = run(b)
    assert [e["trigger"] for e in result["events"]] == ["archive"] and result["report"]["missing"] == []
    b.remove("archive/note/default-note/old.md")
    b.write("notes/old.md", text.replace("archive: archive:archive\narchived_at: 2026-11-06T00:00:00Z\n", ""))
    assert [e["trigger"] for e in run(b)["events"]] == ["unarchive"]


# ---- conversions: matching by ref across bindings --------------------------------------------------------------------

def test_a_conversion_is_one_update_with_the_impl_changed(b):
    b.impl("task", "gtd", path="tasks/gtd/{slug}.md")
    i, _ = b.item("task", "default-task", "tasks", "Draft", "status: open\n")
    run(b)
    text = b.read("tasks/draft.md").replace("impl: default-task", "impl: gtd")
    b.remove("tasks/draft.md")
    b.write("tasks/gtd/draft.md", text)
    result = run(b)
    assert triggers(result) == [("update", f"task:{i}")]
    assert "impl" in result["events"][0]["changed"] and result["events"][0]["impl"] == "gtd"
    assert result["report"]["missing"] == []
    assert run(b)["events"] == []


def test_an_interrupted_conversion_does_not_hide_the_duplicate(b):
    b.impl("task", "gtd", path="tasks/gtd/{slug}.md")
    i, _ = b.item("task", "default-task", "tasks", "Draft", "status: open\n")
    run(b)
    b.write("tasks/gtd/draft.md", b.read("tasks/draft.md").replace("impl: default-task", "impl: gtd"))
    result = run(b)                                               # source still exists: both bindings hold the ref
    assert len([e for e in result["events"] if e["ref"] == f"task:{i}"]) <= 2
    from brainctl import validate
    assert any(f["code"] == "duplicate-ref" for f in validate.validate(b.vault()))


# ---- adoption ---------------------------------------------------------------------------------------------------------

def test_a_hand_written_file_is_adopted_additively(b):
    run(b)
    original = "# Idea from the bus\nWhat if triage had a mobile view?\n"
    b.write("notes/idea-from-the-bus.md", original)
    result = run(b)
    assert result["report"]["adopted"] == ["notes/idea-from-the-bus.md"]
    text = b.read("notes/idea-from-the-bus.md")
    assert text.endswith(original)                                           # body untouched, name unchanged
    front = util.ParsedFile(text).front
    assert front["type"] == "note" and front["impl"] == "default-note" and front["slug"] == "idea-from-the-bus"
    assert front["title"] == "Idea from the bus" and len(front["id"]) == 26
    assert {"created", "updated"} <= set(front)
    ref = f"note:{front['id']}"
    assert (("create", ref) in triggers(result)) and (("capture", ref) in triggers(result))
    assert run(b)["events"] == []


def test_adoption_keeps_existing_keys_and_order(b):
    run(b)
    b.write("notes/mine.md", "---\ntitle: Mine\ntags:\n  a: ''\nmood: calm\n---\ntext\n")
    run(b)
    text = b.read("notes/mine.md")
    assert text.index("title: Mine") < text.index("tags:") < text.index("mood: calm")
    front = util.ParsedFile(text).front
    assert front["title"] == "Mine" and front["mood"] == "calm" and "id" in front


def test_adoption_fills_status_and_schema_defaults(b):
    b.impl("task", "gtd", fields="    priority: { type: enum, values: [low, med], default: med }\n", path="tasks/gtd/{slug}.md")
    run(b)
    b.write("tasks/gtd/call-dentist.md", "# Call the dentist\n")
    run(b)
    front = util.ParsedFile(b.read("tasks/gtd/call-dentist.md")).front
    assert front["status"] == "open" and front["priority"] == "med" and front["title"] == "Call the dentist"


def test_a_file_that_cannot_be_valid_is_not_adopted(b):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], required: true }\n", path="tasks/gtd/{slug}.md")
    run(b)
    b.write("tasks/gtd/needs-context.md", "# Needs context\n")
    result = run(b)
    assert b.read("tasks/gtd/needs-context.md") == "# Needs context\n"
    assert result["report"]["adopted"] == [] and result["report"]["invalid"][0]["path"] == "tasks/gtd/needs-context.md"


def test_ambiguous_directories_adopt_nothing(b):
    b.impl("note", "twin", path="notes/{slug}.md")
    run(b)
    b.write("notes/mine.md", "text\n")
    result = run(b)
    assert b.read("notes/mine.md") == "text\n"
    assert [p["code"] for p in result["report"]["problems"]] == ["ambiguous-file"]


def test_no_adopt_flag_reports_only(b):
    run(b)
    b.write("notes/mine.md", "text\n")
    result = run(b, adopt=False)
    assert result["report"]["unadopted"] == ["notes/mine.md"] and b.read("notes/mine.md") == "text\n"


def test_person_adoption_uses_a_display_name(b):
    run(b)
    b.write("people/pat-jones.md", "# Pat Jones\n")
    run(b)
    front = util.ParsedFile(b.read("people/pat-jones.md")).front
    assert front["name"] == {"display": "Pat Jones"} and front["type"] == "person"


def test_a_file_in_the_wrong_directory_is_not_adopted_as_something_else(b):
    run(b)
    b.write("notes/claims-task.md", "---\ntype: task\n---\ntext\n")
    result = run(b)
    assert result["report"]["adopted"] == [] and result["report"]["invalid"]


# ---- invalid external changes -----------------------------------------------------------------------------------------

def test_an_invalid_external_change_runs_no_rules_and_is_reported_until_fixed(b):
    b.impl("task", "gtd", fields="    due: { type: date }\n", path="tasks/gtd/{slug}.md")
    i, _ = b.item("task", "gtd", "tasks/gtd", "Draft", "status: open\n")
    run(b)
    b.add_front("tasks/gtd/draft.md", "due: someday\n")
    result = run(b)
    assert result["events"] == [] and result["report"]["invalid"][0]["ref"] == f"task:{i}"
    again = run(b)                                       # still reported: the seen state was not advanced
    assert again["report"]["invalid"] and again["events"] == []
    b.edit("tasks/gtd/draft.md", "due: someday", "due: 2026-12-01")
    assert triggers(run(b)) == [("update", f"task:{i}")]


# ---- bindings the helper cannot read yet ----------------------------------------------------------------------------

def test_script_bindings_are_reported_incomplete(b):
    b.write(".brain/impls/task/remote.md", "---\nimpl: remote\nextends: task\nversion: 1\nstorage:\n  adapter: script\n  command: python:remote\n---\n")
    result = run(b)
    assert result["report"]["incomplete"] == [{"binding": "task/remote", "reason": "adapter 'script' is not supported by this helper yet"}]


# ---- refresh ----------------------------------------------------------------------------------------------------------

def test_refresh_accepts_the_plugins_own_writes_without_events(b):
    b.item("task", "default-task", "tasks", "One", "status: open\n")
    run(b)
    b.edit("tasks/one.md", "status: open", "status: done")          # a write the plugin made itself
    refreshed = run(b, refresh=True)
    assert refreshed["events"] == [] and refreshed["report"]["refreshed"] >= 2
    assert run(b)["events"] == []                                    # not reported as an outside change later


def test_refresh_does_not_adopt_and_does_not_hide_hand_written_files(b):
    run(b)
    b.write("notes/by-hand.md", "# By hand\n")
    result = run(b, refresh=True)
    assert result["report"]["unadopted"] == ["notes/by-hand.md"] and b.read("notes/by-hand.md") == "# By hand\n"
    assert run(b)["report"]["adopted"] == ["notes/by-hand.md"]
