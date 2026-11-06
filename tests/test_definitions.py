"""Writing definitions: implementations, rules, traits and the manifest."""
import json
import os

import pytest

from brainctl import definitions, store, sync as sync_mod, util, validate
from brainctl.store import StoreError


def errors(b):
    return [f for f in validate.validate(b.vault()) if f["severity"] == "error"]


def warnings(b):
    return [f for f in validate.validate(b.vault()) if f["severity"] == "warning"]


def manifest(b):
    return util.load_yaml_file(b.path(".brain/manifest.yml"))


def define(b):
    return b.vault()


# ---- implementations --------------------------------------------------------------------------------------------------

def test_impl_add_writes_the_definition_registers_it_and_declares_slug(b):
    out = definitions.impl_add(b.vault(), {
        "type": "task", "impl": "gtd-task", "path": "tasks/gtd/{slug}.md",
        "fields": {"context": {"type": "enum", "values": ["work", "home"], "required": True},
                   "priority": {"type": "enum", "values": ["low", "med", "high"], "default": "med"}}})
    assert out["ref"] == "task/gtd-task" and out["slug_field_added"]
    text = b.read(".brain/impls/task/gtd-task.md")
    assert "slug: {type: string}" in text and 'path: "tasks/gtd/{slug}.md"' in text and "context: {type: enum, values: [work, home], required: true}" in text
    assert "## Slug" in text and "ids-and-slugs.md" in text
    assert manifest(b)["implementations"]["task/gtd-task"] == {"version": 1}
    assert errors(b) == [] and warnings(b) == []
    created = store.create(b.vault(), {"type": "task", "title": "Plan", "impl": "gtd-task", "context": "work"})
    assert created["path"] == "tasks/gtd/plan.md"


def test_impl_add_from_copies_a_variant(b):
    out = definitions.impl_add(b.vault(), {"type": "note", "impl": "zettel", "from": "note/default-note", "path": "zettel/{slug}.md"})
    assert out["ref"] == "note/zettel"
    v = b.vault().impl_for("note", "zettel")
    assert v.path_template == "zettel/{slug}.md" and "slug" in v.fields and v.version == 1
    assert errors(b) == []


def test_impl_add_refuses_bad_input_and_changes_nothing(b):
    before = b.read(".brain/manifest.yml")
    for spec, code in (({"type": "thing", "impl": "x", "path": "x/{slug}.md"}, "invalid"), ({"type": "note", "impl": "Bad Name", "path": "x/{slug}.md"}, "invalid"),
                       ({"type": "note", "impl": "default-note", "path": "x/{slug}.md"}, "conflict"), ({"type": "note", "impl": "nopath"}, "invalid"),
                       ({"type": "note", "impl": "norender", "path": "x/fixed.md"}, "invalid"),
                       ({"type": "note", "impl": "badfield", "path": "x/{slug}.md", "fields": {"n": {"type": "integer", "pattern": "x"}}}, "invalid")):
        with pytest.raises(StoreError) as e:
            definitions.impl_add(b.vault(), spec)
        assert e.value.code == code, spec
    assert b.read(".brain/manifest.yml") == before and not os.path.exists(b.path("x"))
    for name in ("norender", "badfield", "nopath"):
        assert not os.path.exists(b.path(f".brain/impls/note/{name}.md"))


def test_impl_update_keeps_comments_and_can_bump_the_version(b):
    definitions.impl_add(b.vault(), {"type": "task", "impl": "gtd", "path": "tasks/gtd/{slug}.md", "fields": {"context": {"type": "string"}}})
    p = b.path(".brain/impls/task/gtd.md")
    text = open(p).read()
    open(p, "w").write(text.replace("storage:", "# where files live\nstorage:"))
    out = definitions.impl_update(b.vault(), "task/gtd", {"fields": {"priority": {"type": "enum", "values": ["low", "high"], "default": "low"}}, "remove_fields": ["context"], "bump": True})
    text = b.read(".brain/impls/task/gtd.md")
    assert "# where files live" in text and "priority:" in text and "context" not in text and out["version"] == 2
    assert manifest(b)["implementations"]["task/gtd"] == {"version": 2} and errors(b) == []
    definitions.impl_update(b.vault(), "task/gtd", {"set": {"status_values": {"waiting": "open"}}})
    assert b.vault().impl_for("task", "gtd").status_values == {"waiting": "open"} and manifest(b)["implementations"]["task/gtd"] == {"version": 2}


def test_impl_update_rolls_back_what_breaks_the_vault(b):
    definitions.impl_add(b.vault(), {"type": "task", "impl": "gtd", "path": "tasks/gtd/{slug}.md"})
    store.create(b.vault(), {"type": "task", "title": "Plan", "impl": "gtd"})
    before = b.read(".brain/impls/task/gtd.md")
    with pytest.raises(StoreError) as e:                                               # an existing item would lack the new required field
        definitions.impl_update(b.vault(), "task/gtd", {"fields": {"context": {"type": "string", "required": True}}})
    assert e.value.code == "invalid" and b.read(".brain/impls/task/gtd.md") == before
    for patch in ({"set": {"impl": "other"}}, {"set": {"version": 9}}, {"unset": ["extends"]}):
        with pytest.raises(StoreError):
            definitions.impl_update(b.vault(), "task/gtd", patch)
    with pytest.raises(StoreError) as e:
        definitions.impl_update(b.vault(), "task/ghost", {"bump": True})
    assert e.value.code == "not_found"


def test_impl_show(b):
    out = definitions.impl_show(b.vault(), "note/default-note")
    assert out["front"]["storage"]["path"] == "notes/{slug}.md" and out["manifest_version"] == 1
    with pytest.raises(StoreError):
        definitions.impl_show(b.vault(), "note/ghost")


# ---- rules ------------------------------------------------------------------------------------------------------------

JOURNAL_RULE = {"id": "create-today-journal", "on": "manual", "requires": [{"type": "note", "impl": "journal"}, {"type": "area", "impl": "default-area"}],
                "do": [{"action": "create_item", "type": "note", "impl": "journal", "title": "{{ today }}",
                        "unless_exists": {"type": "note", "impl": "journal", "where": {"title": "{{ today }}"}},
                        "place": {"find": {"type": "area", "where": {"title": "Journals"}}, "create_if_missing": True}}]}


def test_vault_rule_add_replace_list_remove(b):
    definitions.impl_add(b.vault(), {"type": "note", "impl": "journal", "path": "journal/{slug}.md"})
    out = definitions.rule_add(b.vault(), {"scope": "vault", "rule": JOURNAL_RULE})
    assert out["path"] == ".brain/automation.yml" and not out["replaced"]
    data = util.load_yaml_file(b.path(".brain/automation.yml"))
    assert list(data) == ["rules"] and data["rules"][0]["do"][0]["title"] == "{{ today }}" and errors(b) == []
    with pytest.raises(StoreError) as e:
        definitions.rule_add(b.vault(), {"scope": "vault", "rule": JOURNAL_RULE})
    assert e.value.code == "conflict"
    again = definitions.rule_add(b.vault(), {"scope": "vault", "rule": dict(JOURNAL_RULE, enabled=False), "replace": True})
    assert again["replaced"] and util.load_yaml_file(b.path(".brain/automation.yml"))["rules"][0]["enabled"] is False
    assert definitions.rule_list(b.vault())["rules"] == [{"scope": "vault", "id": "create-today-journal", "on": "manual", "enabled": False}]
    definitions.rule_remove(b.vault(), "vault", "create-today-journal")
    assert definitions.rule_list(b.vault())["count"] == 0 and errors(b) == []


def test_impl_rule_goes_in_the_automation_list_and_keeps_the_rest(b):
    text = b.read(".brain/impls/note/default-note.md")
    open(b.path(".brain/impls/note/default-note.md"), "w").write(text.replace("storage:", "# keep me\nstorage:"))
    definitions.rule_add(b.vault(), {"scope": "note/default-note", "rule": {"id": "tag", "on": "capture", "do": [{"action": "claude", "instruction": "Propose a tag 'topic'."}]}})
    text = b.read(".brain/impls/note/default-note.md")
    assert "# keep me" in text and "automation:" in text and "id: tag" in text
    assert b.vault().impl_for("note", "default-note").automation[0]["id"] == "tag" and errors(b) == []
    definitions.rule_remove(b.vault(), "note/default-note", "tag")
    assert "automation" not in b.read(".brain/impls/note/default-note.md") and errors(b) == []


def test_bad_rules_are_refused_and_nothing_is_written(b):
    cases = [
        {"scope": "vault", "rule": {"id": "r", "on": "capture", "requires": [], "do": []}},                                    # vault rules are manual only
        {"scope": "vault", "rule": {"id": "r", "on": "manual", "requires": [{"type": "note", "impl": "ghost"}], "do": []}},    # missing implementation
        {"scope": "note/default-note", "rule": {"id": "r", "on": "sometimes", "do": []}},
        {"scope": "note/default-note", "rule": {"id": "r", "on": "manual", "do": [{"action": "create_item", "type": "note", "title": "{{ tomorrow }}"}]}},
        {"scope": "note/default-note", "rule": {"on": "manual"}},
        {"scope": "note/ghost", "rule": {"id": "r", "on": "manual", "do": []}},
    ]
    note = b.read(".brain/impls/note/default-note.md")
    for spec in cases:
        with pytest.raises(StoreError):
            definitions.rule_add(b.vault(), spec)
    assert not os.path.exists(b.path(".brain/automation.yml")) and b.read(".brain/impls/note/default-note.md") == note
    with pytest.raises(StoreError) as e:
        definitions.rule_remove(b.vault(), "vault", "nope")
    assert e.value.code == "not_found"


# ---- traits -----------------------------------------------------------------------------------------------------------

def test_trait_add(b):
    definitions.trait_add(b.vault(), {"name": "colleague", "fields": {"employer": {"type": "string"}}})
    assert "employer: {type: string}" in b.read(".brain/traits/colleague.md") and manifest(b)["traits"]["colleague"] == {"version": 1}
    assert errors(b) == []
    person = store.create(b.vault(), {"type": "person", "name": "Alex", "traits": ["colleague"], "colleague": {"employer": "Acme"}})
    assert person["path"] == "people/alex.md"
    with pytest.raises(StoreError):
        definitions.trait_add(b.vault(), {"name": "colleague"})
    with pytest.raises(StoreError):
        definitions.trait_add(b.vault(), {"name": "Not-Valid"})


def test_definition_writes_leave_no_sync_noise(b):
    sync_mod.sync(b.vault())
    definitions.impl_add(b.vault(), {"type": "note", "impl": "journal", "path": "journal/{slug}.md"})
    definitions.trait_add(b.vault(), {"name": "colleague"})
    assert sync_mod.sync(b.vault())["events"] == []


def test_manifest_edits_touch_only_one_line(b):
    before = b.read(".brain/manifest.yml").split("\n")
    definitions.impl_add(b.vault(), {"type": "note", "impl": "zettel", "path": "zettel/{slug}.md"})
    after = b.read(".brain/manifest.yml").split("\n")
    assert [l for l in after if l not in before] == ["  note/zettel: { version: 1 }"] and [l for l in before if l not in after] == []
    definitions.impl_update(b.vault(), "note/zettel", {"bump": True})
    assert "  note/zettel: { version: 2 }" in b.read(".brain/manifest.yml") and b.read(".brain/manifest.yml").count("note/zettel") == 1
    keys = [l.strip().split(":")[0] for l in b.read(".brain/manifest.yml").split("implementations:")[1].split("traits:")[0].strip().split("\n")]
    assert keys == sorted(keys)
    definitions.trait_add(b.vault(), {"name": "colleague"})                       # traits: {} becomes a block
    assert "traits:\n  colleague: { version: 1 }" in b.read(".brain/manifest.yml") and errors(b) == []
