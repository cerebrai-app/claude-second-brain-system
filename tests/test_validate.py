"""`brainctl validate`: one test per check (docs/plans/11, the `validate` skill)."""
import pytest

from brainctl import validate
from conftest import codes


def run(b, ref=None):
    return validate.validate(b.vault(), ref)


def has(findings, code, severity=None, subject=None):
    return any(f["code"] == code and (severity is None or f["severity"] == severity) and (subject is None or subject in f["subject"]) for f in findings)


# ---- a clean vault ----------------------------------------------------------------------------------------------------

def test_fresh_vault_is_clean(b):
    assert run(b) == []


def test_a_populated_valid_vault_is_clean(b):
    b.trait("colleague")
    area, _ = b.item("area", "default-area", "areas", "Work")
    project, _ = b.item("project", "default-project", "projects", "Q4 planning", f"status: open\narea: [area:{area}]\n")
    b.item("task", "default-task", "tasks", "Draft Q4 plan", f"status: open\nbelongs_to: [project:{project}]\n")
    b.item("note", "default-note", "notes", "An idea", f"about: [project:{project}]\ntags:\n  ux: ''\n  review: later\n")
    b.item("person", "default-person", "people", "Alex Rivera", name_block="name:\n  given: Alex\n  family: Rivera\n", extra="traits: [colleague]\ncolleague:\n  employer: Acme\n")
    assert run(b) == []


# ---- the vault itself -------------------------------------------------------------------------------------------------

def test_not_a_vault(tmp_path):
    from brainctl.model import Vault
    assert has(validate.validate(Vault(str(tmp_path))), "not-a-vault", "error")


def test_missing_manifest_means_setup_did_not_finish(b):
    b.remove(".brain/manifest.yml")
    assert has(run(b), "manifest-missing", "error")


def test_missing_config(b):
    b.remove(".brain/config.yml")
    assert has(run(b), "config-missing", "error")


def test_invalid_config_yaml(b):
    b.write(".brain/config.yml", "version: [1\n")
    assert has(run(b), "config-invalid", "error")


def test_archive_must_be_configured(b):
    b.write(".brain/config.yml", "version: 1\nname: x\n")
    assert has(run(b), "archive-config", "error")


def test_core_version_behind_is_a_warning_and_ahead_an_error(b):
    b.edit(".brain/manifest.yml", "core_version: 1", "core_version: 0")
    assert has(run(b), "migration-available", "warning")
    b.edit(".brain/manifest.yml", "core_version: 0", "core_version: 9")
    assert has(run(b), "core-version-ahead", "error")


def test_manifest_index_must_match_the_definitions(b):
    b.edit(".brain/manifest.yml", "  task/default-task: { version: 1 }\n", "  task/ghost: { version: 1 }\n")
    found = run(b)
    assert has(found, "manifest-index", "warning", ".brain/manifest.yml")
    assert len([f for f in found if f["code"] == "manifest-index"]) == 2


def test_inbox_missing_or_not_system(b):
    b.edit("areas/inbox.md", "system: true\n", "")
    assert has(run(b), "inbox-system", "error")
    b.remove("areas/inbox.md")
    assert has(run(b), "inbox-missing", "error")


# ---- implementation definitions ---------------------------------------------------------------------------------------

def test_impl_name_and_extends_must_match(b):
    b.write(".brain/impls/note/odd.md", "---\nimpl: other\nextends: task\nversion: 1\nstorage:\n  adapter: markdown\n  path: \"x/{slug}.md\"\n---\n")
    found = run(b)
    assert has(found, "impl-name", "error") and has(found, "impl-extends", "error")


@pytest.mark.parametrize("path, code", [("tasks/fixed.md", "storage-path"), ("", "storage-path")])
def test_markdown_path_must_make_one_file_per_item(b, path, code):
    b.impl("task", "bad", path=path)
    assert has(run(b), code, "error")


def test_script_storage_needs_a_command(b):
    b.write(".brain/impls/task/remote.md", "---\nimpl: remote\nextends: task\nversion: 1\nstorage:\n  adapter: script\n---\n")
    assert has(run(b), "storage-command", "error")


def test_schema_field_problems_are_reported(b):
    b.impl("task", "gtd", fields="    Bad.Name: { type: date }\n    title: { type: string }\n    when: { type: moment }\n")
    c = codes(run(b), "error")
    assert {"field-name", "field-reserved", "field-type"} <= set(c)


def test_custom_status_values_must_map_to_core_values(b):
    b.impl("task", "gtd", extra="status_values:\n  waiting: open\n  done: done\n  odd: maybe\n")
    found = run(b)
    assert len([f for f in found if f["code"] == "status-values"]) == 2        # duplicates a core value; bad target


def test_exactly_one_active_person_implementation(b):
    b.impl("person", "second", path="people2/{slug}.md")
    assert has(run(b), "person-impl", "error")
    b.write(".brain/impls/person/second.md", b.read(".brain/impls/person/second.md").replace("version: 1\n", "version: 1\nmigration_target: true\n"))
    assert not has(run(b), "person-impl")
    b.impl("person", "third", path="people3/{slug}.md", extra="migration_target: true\n")
    assert has(run(b), "person-impl", "error")


# ---- traits -----------------------------------------------------------------------------------------------------------

def test_trait_name_rules(b):
    b.trait("title")                                 # reserved
    b.write(".brain/traits/Bad-Name.md", "---\ntrait: Bad-Name\nversion: 1\n---\n")
    found = run(b)
    assert len([f for f in found if f["code"] == "trait-name"]) >= 2


def test_person_with_unknown_trait_or_stray_trait_fields(b):
    b.trait("colleague")
    b.item("person", "default-person", "people", "Alex", name_block="name:\n  given: Alex\n", extra="traits: [ghost]\n")
    b.item("person", "default-person", "people", "Bo", name_block="name:\n  given: Bo\n", extra="colleague:\n  employer: Acme\n")
    found = run(b)
    assert has(found, "trait-unknown", "error") and has(found, "trait-fields", "error")


def test_trait_fields_are_validated(b):
    b.trait("colleague", fields="    level: { type: integer, min: 1 }\n")
    b.item("person", "default-person", "people", "Alex", name_block="name:\n  given: Alex\n", extra="traits: [colleague]\ncolleague:\n  level: 0\n")
    assert has(run(b), "field-value", "error")


# ---- items ------------------------------------------------------------------------------------------------------------

def test_required_fields_and_status(b):
    b.item("task", "default-task", "tasks", "No status")
    b.item("task", "default-task", "tasks", "Bad status", "status: maybe\n")
    b.write("notes/empty-title.md", "---\nid: 01M6Q8N7BV24V6C5AF3B8Q4R1H\nslug: empty-title\ntype: note\nimpl: default-note\ntitle: ''\ncreated: 2026-11-06T00:00:00Z\nupdated: 2026-11-06T00:00:00Z\n---\n")
    found = run(b)
    assert has(found, "required-field", "error") and has(found, "status-invalid", "error")
    assert len([f for f in found if f["code"] == "required-field"]) == 2


def test_custom_status_value_is_valid_and_completed_follows_the_category(b):
    b.impl("task", "gtd", extra="status_values:\n  waiting: open\n  shipped: done\n")
    b.item("task", "gtd", "tasks/gtd", "Waiting", "status: waiting\n")
    b.item("task", "gtd", "tasks/gtd", "Shipped, no completed", "status: shipped\n")
    b.item("task", "gtd", "tasks/gtd", "Open but completed", "status: open\ncompleted: 2026-11-06T00:00:00Z\n")
    found = run(b)
    assert not has(found, "status-invalid")
    assert has(found, "completed-missing", "warning") and has(found, "completed-stale", "warning")


def test_ids_slugs_and_timestamps(b):
    b.item("note", "default-note", "notes", "Bad id", ident="not-a-ulid")
    b.write("notes/no-times.md", "---\nid: 01M6Q8N7BV24V6C5AF3B8Q4R1H\ntype: note\nimpl: default-note\ntitle: No times\n---\n")
    b.write("notes/wrong-slug.md", "---\nid: 01M6Q8N7BV24V6C5AF3B8Q4R1J\nslug: other\ntype: note\nimpl: default-note\ntitle: Wrong\ncreated: 2026-11-06T00:00:00Z\nupdated: 2026-11-06T00:00:00Z\n---\n")
    found = run(b)
    assert {"id-format", "slug-missing", "created-missing", "updated-missing", "slug-mismatch"} <= set(codes(found, "warning"))


def test_schema_field_values_are_checked_on_items(b):
    b.impl("task", "gtd", fields="    context: { type: enum, values: [work, home], required: true }\n    due: { type: date }\n")
    b.item("task", "gtd", "tasks/gtd", "No context", "status: open\n")
    b.item("task", "gtd", "tasks/gtd", "Bad due", "status: open\ncontext: work\ndue: next week\n")
    found = run(b)
    assert has(found, "required-field", "error") and has(found, "field-value", "error")


def test_unknown_and_misplaced_keys(b):
    b.item("note", "default-note", "notes", "Odd", "mood: happy\nstatus: open\n")
    found = run(b)
    assert has(found, "unknown-field", "warning") and has(found, "misplaced-key", "error")


def test_tags(b):
    b.item("note", "default-note", "notes", "Good", "tags:\n  Urgent: ''\n  review: later\n")
    b.item("note", "default-note", "notes", "Bad list value", "tags:\n  a: [x]\n")
    b.item("note", "default-note", "notes", "Spaces", "tags:\n  'two words': x\n")
    b.item("note", "default-note", "notes", "Shorthand", "tags: [a, b]\n")
    found = run(b)
    assert has(found, "tags-name", "warning")              # 'Urgent' will be lowercased
    assert len([f for f in found if f["code"] == "tags" and f["severity"] == "error"]) == 2
    assert has(found, "tags-shorthand", "warning")


def test_person_name_must_be_structured(b):
    b.item("person", "default-person", "people", "x", name_block="name: Alex Rivera\n")
    b.item("person", "default-person", "people", "y", name_block="name:\n  given: ' '\n")
    assert len([f for f in run(b) if f["code"] == "required-field"]) == 2


def test_defaults_on_areas_and_projects(b):
    b.item("area", "default-area", "areas", "Bad defaults", "defaults:\n  person: default-person\n  task: ghost\n")
    b.item("project", "default-project", "projects", "Bad project defaults", "status: open\ndefaults:\n  area: default-area\n")
    found = run(b)
    assert len([f for f in found if f["code"] == "defaults"]) == 3


def test_only_the_inbox_may_be_a_system_area(b):
    b.item("area", "default-area", "areas", "Pretend inbox", "system: true\n")
    assert has(run(b), "system-flag", "error")


def test_task_completed_on_a_note_is_misplaced(b):
    b.item("note", "default-note", "notes", "n", "completed: 2026-11-06T00:00:00Z\n")
    assert has(run(b), "misplaced-key", "error")


# ---- relations --------------------------------------------------------------------------------------------------------

def test_relation_targets_cardinality_and_dangling(b):
    area, _ = b.item("area", "default-area", "areas", "Work")
    proj, _ = b.item("project", "default-project", "projects", "P", "status: open\n")
    b.item("task", "default-task", "tasks", "Two homes", f"status: open\nbelongs_to: [project:{proj}, area:{area}]\n")
    b.item("task", "default-task", "tasks", "Wrong type", f"status: open\nassigned_to: [project:{proj}]\n")
    b.item("task", "default-task", "tasks", "Dangling", "status: open\nbelongs_to: [project:01M6Q8N7BV24V6C5AF3B8Q4R1K]\n")
    b.item("task", "default-task", "tasks", "Bad ref", "status: open\nblocked_by: [nonsense]\n")
    found = run(b)
    assert has(found, "relation-cardinality", "error") and has(found, "relation-target", "error")
    assert has(found, "dangling-ref", "warning") and has(found, "relation-ref", "error")


def test_note_about_allows_one_project_or_area_and_any_persons(b):
    a1, _ = b.item("area", "default-area", "areas", "A1")
    a2, _ = b.item("area", "default-area", "areas", "A2")
    pers, _ = b.item("person", "default-person", "people", "Pat", name_block="name:\n  given: Pat\n")
    b.item("note", "default-note", "notes", "ok", f"about: [area:{a1}, person:{pers}]\n")
    assert run(b) == []
    b.item("note", "default-note", "notes", "too many", f"about: [area:{a1}, area:{a2}]\n")
    assert has(run(b), "relation-cardinality", "error")


def test_the_inbox_is_a_valid_relation_target_and_archived_targets_warn(b):
    b.item("task", "default-task", "tasks", "In the inbox", "status: open\nbelongs_to: [area:inbox]\n")
    assert run(b) == []
    arch, _ = b.item("project", "default-project", "archive/project/default-project", "Old", "status: done\ncompleted: 2026-11-06T00:00:00Z\narchive: archive:archive\narchived_at: 2026-11-06T00:00:00Z\n")
    b.item("task", "default-task", "tasks", "Points at archive", f"status: open\nbelongs_to: [project:{arch}]\n")
    assert has(run(b), "archived-target", "warning")


def test_area_parent_cycle_is_an_error_and_blocked_by_cycle_a_warning(b):
    a, _ = b.item("area", "default-area", "areas", "A", )
    c, _ = b.item("area", "default-area", "areas", "C", f"parent: [area:{a}]\n")
    b.add_front("areas/a.md", f"parent: [area:{c}]\n")
    t1, _ = b.item("task", "default-task", "tasks", "T1", "status: open\n")
    t2, _ = b.item("task", "default-task", "tasks", "T2", f"status: open\nblocked_by: [task:{t1}]\n")
    b.add_front("tasks/t1.md", f"blocked_by: [task:{t2}]\n")
    found = run(b)
    assert has(found, "parent-cycle", "error") and has(found, "blocked-cycle", "warning")


def test_person_named_relations_are_checked_like_any_ref(b):
    pers, _ = b.item("person", "default-person", "people", "Pat", name_block="name:\n  given: Pat\n")
    b.item("person", "default-person", "people", "Quinn", name_block="name:\n  given: Quinn\n", extra=f"works_with: [person:{pers}, person:01M6Q8N7BV24V6C5AF3B8Q4R1K]\n")
    found = run(b)
    assert has(found, "dangling-ref", "warning")
    assert not has(found, "unknown-field")                      # a list of refs is a named relation, not an unknown field


# ---- scan problems and duplicates -------------------------------------------------------------------------------------

def test_unparseable_and_unadopted_files(b):
    b.write("notes/broken.md", "---\ntitle: [x\n---\n")
    b.write("notes/by-hand.md", "# By hand\n")
    found = run(b)
    assert has(found, "unparseable-file", "error") and has(found, "unadopted-file", "warning")


def test_the_same_ref_in_two_bindings_is_an_error(b):
    b.impl("task", "gtd", path="tasks/gtd/{slug}.md")
    i, _ = b.item("task", "default-task", "tasks", "Moved", "status: open\n")
    text = b.read("tasks/moved.md").replace("impl: default-task", "impl: gtd")
    b.write("tasks/gtd/moved.md", text)
    assert has(run(b), "duplicate-ref", "error", f"task:{i}")


def test_half_converted_marker(b):
    b.write(".brain/conversions/task-01M6Q8N7BV24V6C5AF3B8Q4R1H.json", "{}")
    assert has(run(b), "half-converted", "warning")


# ---- git ignore -------------------------------------------------------------------------------------------------------

def test_a_committed_path_that_git_ignores_is_an_error(b):
    b.write(".gitignore", ".venv\nlib/\n.brain/index/\n.brain/cache/\n.brain/automation/seen/\n.brain/automation/pending/\n.brain/automation/log.jsonl\n.brain/conversions/\n.brain/python/outputs/\n")
    found = run(b)
    assert has(found, "gitignored-path", "error", ".brain/python/lib")


def test_missing_ignore_for_derived_state_is_a_warning(b):
    b.write(".gitignore", "!.brain/python/lib/\nlib/\n")
    found = run(b)
    assert has(found, "gitignore-missing", "warning", ".brain/automation/seen")


# ---- the Python workspace ---------------------------------------------------------------------------------------------

def test_workspace_is_required(b):
    import shutil
    shutil.rmtree(b.path(".brain/python"))
    assert has(run(b), "workspace-missing", "error")


def test_workspace_files(b):
    b.remove(".brain/python/pyproject.toml")
    b.remove(".brain/python/uv.lock")
    found = run(b)
    assert has(found, "workspace-project", "error") and has(found, "workspace-lock", "error")


def test_script_approval_states(b):
    from brainctl import approval
    b.write(".brain/python/scripts/a.py", "print(1)\n")
    h = approval.approval_hash(b.path(".brain/python"), "scripts/a.py")
    b.write(".brain/python/scripts/b.py", "print(2)\n")
    b.write(".brain/python/registry.yml", f"""scripts:
  - {{ name: ok, path: scripts/a.py, approved: {{ sha256: "{h}" }} }}
  - {{ name: new, path: scripts/b.py }}
  - {{ name: stale, path: scripts/a.py, approved: {{ sha256: "0000" }} }}
  - {{ name: gone, path: scripts/none.py }}
""")
    found = run(b)
    assert has(found, "script-unapproved", "warning", "python:new")
    assert has(found, "script-changed", "warning", "python:stale")
    assert has(found, "script-missing", "error", "python:gone")
    assert not has(found, "script-changed", subject="python:ok")


# ---- automation -------------------------------------------------------------------------------------------------------

def rule_impl(b, rules):
    b.impl("task", "gtd", fields="    due: { type: date }\n",
           extra="sorts:\n  pinned:\n    rule: x\n    keys:\n      - { name: due, type: date }\n  loose:\n    rule: y\nfilters:\n  today:\n    rule: z\n" + rules)


def test_rules_that_use_schedule_or_unknown_triggers(b):
    rule_impl(b, "automation:\n  - id: a\n    on: { schedule: '0 8 * * *' }\n    do: []\n  - id: b\n    on: sometimes\n    do: []\n")
    found = run(b)
    assert has(found, "schedule-unsupported", "error") and has(found, "rule-trigger", "error")


def test_rule_ids_must_be_unique(b):
    rule_impl(b, "automation:\n  - id: a\n    on: manual\n    do: []\n  - id: a\n    on: manual\n    do: []\n")
    assert has(run(b), "rule-id", "error")


def test_surface_must_name_defined_filters_and_pinned_sorts(b):
    rule_impl(b, "automation:\n  - id: ok\n    on: manual\n    do:\n      - { action: surface, filter: today, sort: pinned }\n"
                 "  - id: bad\n    on: manual\n    do:\n      - { action: surface, filter: nope, sort: loose }\n"
                 "  - id: missing-sort\n    on: manual\n    do:\n      - { action: surface, sort: nope }\n")
    found = run(b)
    assert not any(f["subject"].endswith("/ok") for f in found)
    assert has(found, "sort-unpinned", "error", "/bad")
    assert len([f for f in found if f["code"] == "rule-blocked"]) == 2


def test_hooks_must_be_registered_workspace_scripts(b):
    rule_impl(b, "automation:\n  - id: h\n    on: update\n    do:\n      - { action: hook, run: 'python:ghost' }\n")
    assert has(run(b), "hook-unregistered", "error")


def test_creating_a_placed_item_without_place_is_a_warning(b):
    rule_impl(b, "automation:\n  - id: c\n    on: manual\n    do:\n      - { action: create_item, type: task }\n      - { action: create_item, type: task, place: 'area:inbox' }\n")
    found = run(b)
    assert len([f for f in found if f["code"] == "rule-unplaced"]) == 1


def vault_rules(b, text):
    b.write(".brain/automation.yml", text)


def test_vault_rules_must_be_manual_and_declare_what_they_require(b):
    b.impl("note", "journal", path="journal/{slug}.md")
    vault_rules(b, """automation:
  - id: ok
    requires: [ { type: note, impl: journal } ]
    on: manual
    do: []
  - id: event
    requires: [ { type: note, impl: journal } ]
    on: create
    do: []
  - id: undeclared
    on: manual
    do: []
""")
    found = run(b)
    assert not any(f["subject"] == "vault/ok" for f in found)
    assert has(found, "vault-trigger", "error", "vault/event") and has(found, "rule-requires", "error", "vault/undeclared")


def test_vault_rule_blocked_by_a_missing_or_old_implementation(b):
    b.impl("note", "journal", path="journal/{slug}.md", version=1)
    vault_rules(b, "automation:\n  - id: r\n    requires: [ { type: note, impl: journal, min_version: 2 }, { type: task, impl: ghost } ]\n    on: manual\n    do: []\n")
    assert len([f for f in run(b) if f["code"] == "rule-blocked"]) == 2


def test_vault_rule_closed_world_and_place(b):
    b.impl("note", "journal", path="journal/{slug}.md")
    vault_rules(b, """automation:
  - id: r
    requires: [ { type: note, impl: journal } ]
    on: manual
    do:
      - action: write_body
        target:
          find: { type: note, impl: journal, where: { title: today } }
          create_if_missing: true
          place: { find: { type: area, where: { title: Journals } }, create_if_missing: true }
""")
    found = run(b)
    assert has(found, "rule-undeclared-impl", "error")              # `place` finds an area, but no area implementation is required
    vault_rules(b, b.read(".brain/automation.yml").replace("requires: [ { type: note, impl: journal } ]", "requires: [ { type: note, impl: journal }, { type: area, impl: default-area } ]"))
    assert not has(run(b), "rule-undeclared-impl")


def test_vault_rule_without_place_warns(b):
    b.impl("note", "journal", path="journal/{slug}.md")
    vault_rules(b, "automation:\n  - id: r\n    requires: [ { type: note, impl: journal } ]\n    on: manual\n    do:\n      - action: write_body\n        target: { find: { type: note, impl: journal }, create_if_missing: true }\n")
    assert has(run(b), "rule-unplaced", "warning")


def test_invalid_vault_automation_yaml(b):
    vault_rules(b, "automation: [\n")
    assert has(run(b), "automation-invalid", "error")


# ---- filtering ------------------------------------------------------------------------------------------------------

def test_ref_filter_limits_the_findings(b):
    i, _ = b.item("task", "default-task", "tasks", "No status")
    b.item("task", "default-task", "tasks", "Bad status", "status: maybe\n")
    only = run(b, f"task:{i}")
    assert only and all(f["subject"].startswith(f"task:{i}") for f in only)


def test_an_unquoted_date_slug_or_title_is_read_as_a_date_and_reported(b):
    b.write("notes/2026-11-06.md", "---\nid: 01M6Q8N7BV24V6C5AF3B8Q4R1H\nslug: 2026-11-06\ntype: note\nimpl: default-note\ntitle: 2026-11-06\ncreated: 2026-11-06T00:00:00Z\nupdated: 2026-11-06T00:00:00Z\n---\n")
    found = run(b)
    assert has(found, "slug-type", "warning") and has(found, "title-type", "error")


# ---- script (backend) implementations ---------------------------------------------------------------------------------

SCRIPT_IMPL = "---\nimpl: remote\nextends: task\nversion: 1\nstorage:\n  adapter: script\n  command: python:remote\n{extra}---\n"


def test_script_impl_must_point_at_a_registered_workspace_script(b):
    b.write(".brain/impls/task/remote.md", SCRIPT_IMPL.format(extra=""))
    assert has(run(b), "command-unregistered", "error")
    b.write(".brain/python/scripts/remote.py", "print(1)\n")
    b.write(".brain/python/registry.yml", "scripts:\n  - { name: remote, path: scripts/remote.py }\n")
    assert not has(run(b), "command-unregistered")


def test_script_impl_without_a_backend_spec_warns_until_one_exists(b):
    b.write(".brain/python/scripts/remote.py", "print(1)\n")
    b.write(".brain/python/registry.yml", "scripts:\n  - { name: remote, path: scripts/remote.py }\n")
    b.write(".brain/impls/task/remote.md", SCRIPT_IMPL.format(extra=""))
    assert has(run(b), "backend-spec-missing", "warning")
    b.write(".brain/backends/remote.md", "# remote backend\n")
    assert not has(run(b), "backend-spec-missing")


def test_script_impl_timeout_must_be_a_positive_integer(b):
    b.write(".brain/impls/task/remote.md", SCRIPT_IMPL.format(extra="  timeout_seconds: 0\n").replace("  timeout_seconds: 0\n---", "  timeout_seconds: 0\n---"))
    assert has(run(b), "storage-timeout", "error")


# ---- idempotent creation and tag instructions -------------------------------------------------------------------------

def test_unless_exists_needs_a_type_and_a_where(b):
    b.impl("note", "journal", path="journal/{slug}.md")
    for bad in ("{ type: note }", "{ where: { title: x } }", "{ type: spaceship, where: { title: x } }", "[ title ]"):
        vault_rules(b, f"automation:\n  - id: r\n    requires: [ {{ type: note, impl: journal }}, {{ type: area, impl: default-area }} ]\n    on: manual\n    do:\n      - {{ action: create_item, type: note, impl: journal, place: 'area:inbox', unless_exists: {bad} }}\n")
        assert has(run(b), "unless-exists", "error"), bad
    vault_rules(b, "automation:\n  - id: r\n    requires: [ { type: note, impl: journal }, { type: area, impl: default-area } ]\n    on: manual\n    do:\n      - { action: create_item, type: note, impl: journal, place: 'area:inbox', unless_exists: { type: note, impl: journal, where: { title: x } } }\n")
    assert not has(run(b), "unless-exists") and not has(run(b), "rule-undeclared-impl")


def test_unless_exists_in_a_vault_rule_must_name_a_required_impl(b):
    b.impl("note", "journal", path="journal/{slug}.md")
    b.impl("note", "other", path="other/{slug}.md")
    vault_rules(b, "automation:\n  - id: r\n    requires: [ { type: note, impl: journal } ]\n    on: manual\n    do:\n      - { action: create_item, type: note, impl: journal, place: 'area:inbox', unless_exists: { type: note, impl: other, where: { title: x } } }\n")
    assert has(run(b), "rule-undeclared-impl", "error")


def test_an_instruction_asking_for_several_tags_warns(b):
    for text, warned in (("Propose up to two tags (key 'topic') for the note.", True), ("Suggest 3 tags for it.", True),
                         ("Propose tags with distinct keys, up to two tags.", False), ("Propose one tag.", False)):
        rule_impl(b, f"automation:\n  - id: t\n    on: capture\n    do:\n      - {{ action: claude, instruction: \"{text}\" }}\n")
        assert has(run(b), "tags-one-per-key", "warning") is warned, text


def test_slug_is_an_ordinary_field_only_implementations_that_declare_it_have_one(b):
    # no slug field: a {id} path is fine, an item needs no slug, and a {slug} path is rejected
    b.impl("note", "plain", path="plain/{id}.md")
    b.write("plain/01M6Q8N7BV24V6C5AF3B8Q4R1H.md", "---\nid: 01M6Q8N7BV24V6C5AF3B8Q4R1H\ntype: note\nimpl: plain\ntitle: Hi\ncreated: 2026-11-06T00:00:00Z\nupdated: 2026-11-06T00:00:00Z\n---\n")
    assert run(b) == []
    b.write(".brain/impls/note/bad.md", "---\nimpl: bad\nextends: note\nversion: 1\nstorage:\n  adapter: markdown\n  path: \"bad/{slug}.md\"\n---\n")
    assert has(run(b), "storage-path", "error", "bad")


def test_conversion_marker_shape(b):
    good = '{"ref": "task:01M6Q8N7BV24V6C5AF3B8Q4R1H", "from": {"impl": "default-task", "path": "tasks/a.md"}, "to": {"impl": "gtd", "path": "tasks/gtd/a.md"}, "at": "2026-11-06T00:00:00Z"}'
    b.write(".brain/conversions/task-good.json", good)
    b.write(".brain/conversions/task-bad.json", '{"ref": "nope"}')
    found = run(b)
    assert has(found, "half-converted", "warning", "task-good") and not has(found, "conversion-marker", subject="task-good")
    assert has(found, "conversion-marker", "warning", "task-bad")
