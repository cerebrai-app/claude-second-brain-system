"""Template resolution (docs/plans/05, "Template variables"): `brainctl render` and the rule checks in `validate`."""
import datetime as dt
import json

import pytest

from brainctl import __main__ as cli, templates
from conftest import codes

NOW = dt.datetime(2026, 11, 6, 23, 30, tzinfo=dt.timezone.utc)
TASKS = [
    {"ref": "task:1", "fields": {"title": "Draft Q4 plan", "status": "open", "due": "2026-11-07"}},
    {"ref": "task:2", "fields": {"title": "Pay | invoice", "status": "done"}},
]


def test_builtins_follow_the_time_zone():
    assert templates.builtins("UTC", NOW) == {"today": "2026-11-06", "now": "2026-11-06T23:30:00Z"}
    assert templates.builtins("Asia/Tokyo", NOW)["today"] == "2026-11-07"          # already tomorrow there
    assert templates.builtins("America/Los_Angeles", NOW)["today"] == "2026-11-06"
    assert templates.builtins(None, NOW)["today"] == "2026-11-06"
    with pytest.raises(templates.TemplateError):
        templates.zone("Mars/Olympus")


def test_render_text_and_whitespace():
    v = templates.builtins("UTC", NOW)
    assert templates.render("Journal {{today}} / {{ today }} at {{ now }}", v) == "Journal 2026-11-06 / 2026-11-06 at 2026-11-06T23:30:00Z"
    assert templates.render("no templates here", v) == "no templates here"


def test_filters_format_item_lists():
    v = {"ts": TASKS}
    assert templates.render("{{ ts | checklist }}", v) == "- [ ] Draft Q4 plan\n- [x] Pay | invoice"
    assert templates.render("{{ ts | bullets }}", v) == "- Draft Q4 plan\n- Pay | invoice"
    assert templates.render("{{ ts | refs }}", v) == "task:1, task:2"
    table = templates.render("{{ ts | table }}", v).splitlines()
    assert table[0] == "| title | status | due |" and table[2] == "| Draft Q4 plan | open | 2026-11-07 |"
    assert table[3] == "| Pay \\| invoice | done |  |"                              # a pipe in a cell is escaped
    assert templates.render("{{ ts | checklist }}", {"ts": []}) == ""


def test_person_titles_use_the_display_name():
    people = [{"ref": "person:1", "fields": {"name": {"display": "Alex Rivera"}}}]
    assert templates.render("{{ p | bullets }}", {"p": people}) == "- Alex Rivera"


@pytest.mark.parametrize("bad", ["{{ nope }}", "{{ today | shout }}", "{{ today", "today }}", "{{ 1x }}", "{{ }}", "{{ today.x }}"])
def test_errors_are_raised_not_guessed(bad):
    with pytest.raises(templates.TemplateError):
        templates.render(bad, templates.builtins("UTC", NOW))


def test_a_list_without_a_filter_is_an_error():
    with pytest.raises(templates.TemplateError):
        templates.render("{{ ts }}", {"ts": TASKS})
    with pytest.raises(templates.TemplateError):
        templates.render("{{ today | checklist }}", templates.builtins("UTC", NOW))


def test_resolve_walks_nested_values_and_leaves_keys_and_non_strings():
    v = templates.builtins("UTC", NOW)
    data = {"title": "{{ today }}", "where": {"title": "{{ today }}", "n": 3}, "tags": ["{{ now }}", "x"], "{{ today }}": True}
    assert templates.resolve(data, v) == {"title": "2026-11-06", "where": {"title": "2026-11-06", "n": 3}, "tags": ["2026-11-06T23:30:00Z", "x"], "{{ today }}": True}


def test_check_reports_scope_problems():
    assert templates.check("{{ today }}", {"today"}) == []
    assert "unknown variable 'tasks'" in templates.check("{{ tasks | checklist }}", {"today"})[0]
    assert templates.check("{{ today | nope }}", {"today"})


# ---- command line -----------------------------------------------------------------------------------------------------

def test_render_command(b, capsys):
    assert cli.main(["--vault", b.root, "render", "J {{ today }}", "--now", "2026-11-06T23:30:00Z"]) == 0
    assert capsys.readouterr().out.strip() == "J 2026-11-06"
    b.write(".brain/config.yml", b.read(".brain/config.yml") + "timezone: Asia/Tokyo\n")
    assert cli.main(["--vault", b.root, "render", "{{ today }}", "--now", "2026-11-06T23:30:00Z"]) == 0
    assert capsys.readouterr().out.strip() == "2026-11-07"
    assert cli.main(["--vault", b.root, "render", "{{ ts | refs }} {{ who }}", "--vars", json.dumps({"ts": TASKS}), "--var", "who=me"]) == 0
    assert capsys.readouterr().out.strip() == "task:1, task:2 me"


def test_render_json_resolves_every_string(b, capsys):
    data = {"title": "{{ today }}", "unless_exists": {"where": {"title": "{{ today }}"}}}
    assert cli.main(["--vault", b.root, "render", "--json", json.dumps(data), "--now", "2026-11-06T10:00:00Z"]) == 0
    assert json.loads(capsys.readouterr().out) == {"title": "2026-11-06", "unless_exists": {"where": {"title": "2026-11-06"}}}


def test_render_errors_exit_two(b, capsys):
    assert cli.main(["--vault", b.root, "render", "{{ nope }}"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "template"
    assert cli.main(["--vault", b.root, "render"]) == 2


# ---- validate ---------------------------------------------------------------------------------------------------------

def _rule(b, do):
    b.write(".brain/automation.yml", "rules:\n  - id: r\n    on: manual\n    requires: [{ type: note, impl: default-note }]\n    do:\n" + do)
    from brainctl import validate
    return validate.validate(b.vault())


def test_validate_checks_template_names_and_scope(b):
    ok = _rule(b, "      - { action: create_item, type: note, impl: default-note, title: '{{ today }}' }\n")
    assert "rule-template" not in codes(ok, "error")
    bad = _rule(b, "      - { action: create_item, type: note, impl: default-note, title: '{{ tomorrow }}' }\n")
    assert "rule-template" in codes(bad, "error")
    # an `as` binding is visible only to the actions after it
    order = _rule(b, "      - { action: write_body, text: '{{ ts | checklist }}' }\n      - { action: surface, impl: default-note, as: ts }\n")
    assert "rule-template" in codes(order, "error")
    fine = _rule(b, "      - { action: surface, impl: default-note, as: ts }\n      - { action: write_body, text: '{{ ts | checklist }}' }\n")
    assert "rule-template" not in codes(fine, "error")


def test_validate_checks_the_configured_time_zone(b):
    from brainctl import validate
    b.write(".brain/config.yml", b.read(".brain/config.yml") + "timezone: Mars/Olympus\n")
    assert "config-timezone" in codes(validate.validate(b.vault()), "error")


def test_the_vault_rules_list_must_be_called_rules(b):
    from brainctl import validate
    b.write(".brain/automation.yml", "automation:\n  - { id: r, on: manual }\n")
    found = validate.validate(b.vault())
    assert any(f["code"] == "automation-invalid" and "`rules:`" in f["message"] for f in found)
