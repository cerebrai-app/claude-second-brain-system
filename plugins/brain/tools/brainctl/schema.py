"""Field types and constraints (docs/plans/08, "Field types"): validating schema definitions and values."""
import datetime as _dt
import math
import re

from . import model

SCALARS = ("string", "text", "integer", "number", "boolean", "date", "datetime", "enum")
APPLICABLE = {
    "required": set(model.FIELD_TYPES),
    "default": set(model.FIELD_TYPES),
    "min": {"integer", "number", "date", "datetime"},
    "max": {"integer", "number", "date", "datetime"},
    "min_length": {"string", "text", "list"},
    "max_length": {"string", "text", "list"},
    "pattern": {"string"},
    "values": {"enum"},
    "of": {"list"},
}
MAX_SAFE_INT = 2 ** 53 - 1
_NON_PORTABLE = re.compile(r"\(\?<[=!]|\\[1-9]|\(\?P=|\(\?\(")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_date(value):
    if isinstance(value, _dt.datetime):
        return None
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_datetime(value):
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _naive(value):
    return value.replace(tzinfo=None) if isinstance(value, _dt.datetime) else value


def check_spec(name, spec):
    """Problems with one field definition: [(code, message)]."""
    out = []
    if not isinstance(name, str) or not model.NAME_RE.match(name):
        out.append(("field-name", f"field name {name!r} must match [a-z][a-z0-9_]* (no dots)"))
    elif name in model.RESERVED:
        out.append(("field-reserved", f"field name {name!r} is reserved"))
    if not isinstance(spec, dict):
        return out + [("field-spec", f"field {name!r}: definition must be a mapping")]
    type_ = spec.get("type")
    if type_ not in model.FIELD_TYPES:
        return out + [("field-type", f"field {name!r}: unknown type {type_!r}")]
    for key in spec:
        if key == "type":
            continue
        if key not in APPLICABLE:
            out.append(("field-constraint", f"field {name!r}: unknown constraint {key!r}"))
        elif type_ not in APPLICABLE[key]:
            out.append(("field-constraint", f"field {name!r}: constraint {key!r} does not apply to type {type_!r}"))
    if type_ == "enum":
        values = spec.get("values")
        if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values) or len(set(values)) != len(values):
            out.append(("field-enum", f"field {name!r}: enum needs a non-empty list of unique string values"))
    if type_ == "list":
        of = spec.get("of")
        inner = {"type": of} if isinstance(of, str) else of
        if not isinstance(inner, dict) or inner.get("type") not in SCALARS:
            out.append(("field-list", f"field {name!r}: list needs `of` set to a scalar type"))
        else:
            for code, msg in check_spec(f"{name}[]", inner):
                if code not in ("field-name", "field-reserved"):
                    out.append((code, msg))
    if "pattern" in spec:
        pattern = spec["pattern"]
        if not isinstance(pattern, str) or _NON_PORTABLE.search(pattern):
            out.append(("field-pattern", f"field {name!r}: pattern must be a string without lookbehind or backreferences"))
        else:
            try:
                re.compile(pattern)
            except re.error as exc:
                out.append(("field-pattern", f"field {name!r}: invalid pattern ({exc})"))
    if "default" in spec and not out:
        problems = check_value(name, spec, spec["default"])
        if problems:
            out.append(("field-default", f"field {name!r}: default is not valid ({problems[0][1]})"))
    return out


def check_value(name, spec, value):
    """Problems with a value against a field definition: [(severity, message)]."""
    type_ = spec.get("type")
    out = []
    if type_ in ("string", "text"):
        if not isinstance(value, str):
            if isinstance(value, (bool, int, float, _dt.date)) and type_ == "string":
                return [("warning", f"{name}: expected a string but found a {type(value).__name__} (hand edit?); it will be read as text")]
            return [("error", f"{name}: expected {type_}, found {type(value).__name__}")]
        if type_ == "string" and ("\n" in value or "\r" in value):
            out.append(("error", f"{name}: a string must be a single line (use type text)"))
        if "min_length" in spec and len(value) < spec["min_length"]:
            out.append(("error", f"{name}: shorter than {spec['min_length']} characters"))
        if "max_length" in spec and len(value) > spec["max_length"]:
            out.append(("error", f"{name}: longer than {spec['max_length']} characters"))
        if "pattern" in spec and isinstance(spec["pattern"], str) and not re.fullmatch(spec["pattern"], value):
            out.append(("error", f"{name}: does not match pattern {spec['pattern']!r}"))
        return out
    if type_ == "integer":
        if not _is_int(value):
            return [("error", f"{name}: expected integer, found {type(value).__name__}")]
        if abs(value) > MAX_SAFE_INT:
            out.append(("error", f"{name}: outside the safe integer range"))
    elif type_ == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            return [("error", f"{name}: expected a finite number")]
    elif type_ == "boolean":
        if not isinstance(value, bool):
            return [("error", f"{name}: expected true or false")]
        return out
    elif type_ == "date":
        parsed = _parse_date(value)
        if parsed is None:
            return [("error", f"{name}: expected a date (YYYY-MM-DD)")]
        value = parsed
    elif type_ == "datetime":
        parsed = _parse_datetime(value)
        if parsed is None:
            return [("error", f"{name}: expected a datetime (ISO 8601)")]
        value = parsed
    elif type_ == "enum":
        if not isinstance(value, str) or value not in (spec.get("values") or []):
            return [("error", f"{name}: {value!r} is not one of {spec.get('values')}")]
        return out
    elif type_ == "list":
        if not isinstance(value, list):
            return [("error", f"{name}: expected a list")]
        if "min_length" in spec and len(value) < spec["min_length"]:
            out.append(("error", f"{name}: fewer than {spec['min_length']} items"))
        if "max_length" in spec and len(value) > spec["max_length"]:
            out.append(("error", f"{name}: more than {spec['max_length']} items"))
        of = spec.get("of")
        inner = {"type": of} if isinstance(of, str) else (of or {})
        for index, element in enumerate(value):
            out += check_value(f"{name}[{index}]", inner, element)
        return out
    else:
        return [("error", f"{name}: unknown type {type_!r}")]
    # ordered comparisons for integer, number, date, datetime
    for bound, op in (("min", lambda a, b: a < b), ("max", lambda a, b: a > b)):
        if bound in spec:
            limit = spec[bound]
            if type_ == "date":
                limit = _parse_date(limit)
            elif type_ == "datetime":
                limit = _parse_datetime(limit)
            if limit is None:
                continue
            a, b = (_naive(value), _naive(limit)) if type_ in ("date", "datetime") else (value, limit)
            if op(a, b):
                out.append(("error", f"{name}: {'below' if bound == 'min' else 'above'} the {bound} {spec[bound]!r}"))
    return out


def check_fields(front, fields, skip=()):
    """Validate the schema fields of an item: [(severity, code, message)]."""
    out = []
    for name, spec in fields.items():
        if name in skip or not isinstance(spec, dict):
            continue
        if name not in front or front[name] is None:
            if spec.get("required") and "default" not in spec:
                out.append(("error", "required-field", f"required field {name!r} is missing"))
            continue
        for severity, message in check_value(name, spec, front[name]):
            out.append((severity, "field-value", message))
    return out


def defaults_for(fields, front):
    """Schema defaults for fields that are absent in `front` (applied when an item is created or adopted)."""
    return {name: spec["default"] for name, spec in fields.items()
            if isinstance(spec, dict) and "default" in spec and (name not in front or front[name] is None)}
