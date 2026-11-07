"""Field type vocabulary and constraints (docs/plans/08, "Field types")."""
import datetime as dt

import pytest

from brainctl import schema


def problems(spec, value):
    return [m for _sev, m in schema.check_value("f", spec, value)]


# ---- values -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("spec, value", [
    ({"type": "string"}, "hello"),
    ({"type": "text"}, "line one\nline two"),
    ({"type": "integer"}, 3),
    ({"type": "number"}, 2.5),
    ({"type": "number"}, 2),
    ({"type": "boolean"}, False),
    ({"type": "date"}, dt.date(2026, 11, 6)),
    ({"type": "date"}, "2026-11-06"),
    ({"type": "datetime"}, "2026-11-06T09:30:00Z"),
    ({"type": "datetime"}, dt.datetime(2026, 11, 6, 9, 30)),
    ({"type": "enum", "values": ["a", "b"]}, "a"),
    ({"type": "list", "of": "string"}, ["x", "y"]),
    ({"type": "list", "of": {"type": "enum", "values": ["a", "b"]}}, ["a", "b"]),
    ({"type": "integer", "min": 0, "max": 10}, 10),
    ({"type": "string", "pattern": "[A-Z]{2}-[0-9]+"}, "AB-12"),
])
def test_valid_values(spec, value):
    assert problems(spec, value) == []


@pytest.mark.parametrize("spec, value", [
    ({"type": "string"}, "two\nlines"),
    ({"type": "text"}, 5),
    ({"type": "integer"}, 1.5),
    ({"type": "integer"}, True),                    # a boolean is not an integer
    ({"type": "integer"}, 2 ** 53),
    ({"type": "number"}, float("inf")),
    ({"type": "boolean"}, "true"),
    ({"type": "date"}, "11/06/2026"),
    ({"type": "date"}, "2026-13-40"),
    ({"type": "datetime"}, "yesterday"),
    ({"type": "enum", "values": ["a", "b"]}, "c"),
    ({"type": "list", "of": "string"}, "not a list"),
    ({"type": "list", "of": "integer"}, [1, "two"]),
    ({"type": "integer", "min": 0}, -1),
    ({"type": "integer", "max": 5}, 6),
    ({"type": "date", "min": "2026-01-01"}, "2025-12-31"),
    ({"type": "string", "min_length": 3}, "ab"),
    ({"type": "string", "max_length": 3}, "abcd"),
    ({"type": "list", "of": "string", "max_length": 1}, ["a", "b"]),
    ({"type": "string", "pattern": "[a-z]+"}, "abc1"),     # the pattern must match the whole value
])
def test_invalid_values(spec, value):
    assert problems(spec, value)


def test_a_non_string_scalar_in_a_string_field_is_only_a_warning():
    result = schema.check_value("f", {"type": "string"}, 10)
    assert [sev for sev, _ in result] == ["warning"]


# ---- definitions ------------------------------------------------------------------------------------------------------

def codes(name, spec):
    return {c for c, _ in schema.check_spec(name, spec)}


def test_valid_definition():
    assert schema.check_spec("priority", {"type": "enum", "values": ["low", "med"], "default": "med"}) == []


@pytest.mark.parametrize("name, spec, code", [
    ("Due", {"type": "date"}, "field-name"),
    ("a.b", {"type": "date"}, "field-name"),
    ("title", {"type": "string"}, "field-reserved"),
    ("x", {"type": "map"}, "field-type"),
    ("x", {"type": "string", "min": 1}, "field-constraint"),        # min does not apply to a string
    ("x", {"type": "string", "bogus": 1}, "field-constraint"),
    ("x", {"type": "enum"}, "field-enum"),
    ("x", {"type": "enum", "values": ["a", "a"]}, "field-enum"),
    ("x", {"type": "list"}, "field-list"),
    ("x", {"type": "list", "of": "list"}, "field-list"),
    ("x", {"type": "string", "pattern": "(?<=a)b"}, "field-pattern"),      # no lookbehind
    ("x", {"type": "string", "pattern": "(a)\\1"}, "field-pattern"),       # no backreferences
    ("x", {"type": "string", "pattern": "("}, "field-pattern"),
    ("x", {"type": "enum", "values": ["a"], "default": "z"}, "field-default"),
    ("x", "not a mapping", "field-spec"),
])
def test_invalid_definitions(name, spec, code):
    assert code in codes(name, spec)


def test_check_fields_required_and_defaults():
    fields = {"context": {"type": "enum", "values": ["work", "home"], "required": True},
              "priority": {"type": "enum", "values": ["low", "med"], "default": "med", "required": True}}
    out = schema.check_fields({}, fields)
    assert [c for _s, c, m in out] == ["required-field"]            # a required field with a default is not missing
    assert schema.defaults_for(fields, {}) == {"priority": "med"}
    assert schema.defaults_for(fields, {"priority": "low"}) == {}   # never overwrites a value
