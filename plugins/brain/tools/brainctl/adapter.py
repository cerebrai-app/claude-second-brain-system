"""Base class for script adapters: the process boundary of docs/plans/03 ("`script` adapter") in one place.

A backend adapter is a script in the vault's Python workspace that subclasses `BrainAdapter`, implements the storage operations
for one service, and ends with `MyAdapter().main()`. The plugin calls it once per operation: a JSON request on stdin, a JSON
response on stdout, a non-zero exit code on failure. Typical use:

    from brainctl.adapter import BrainAdapter, NotFound, Conflict

    class TodoistTasks(BrainAdapter):
        name = "todoist-tasks"
        requires_env = ["TODOIST_TOKEN"]
        supports_body = True
        tags = "labels"
        query = ["types", "fields_eq"]

        def read(self, ref, native_id=None):
            ...                      # return an envelope or raise NotFound

    if __name__ == "__main__":
        TodoistTasks().main()

Request:   {"protocol": 1, "op": "read", "settings": {...}, "args": {"ref": "task:01J..."}}
Response:  {"ok": true, "result": {...}}   or   {"ok": false, "error": {"code": "not_found", "message": "...", "retryable": false}}
"""
import inspect
import json
import os
import sys
import traceback

from . import util

PROTOCOL = 1
OPERATIONS = ("describe", "create", "read", "update", "archive", "unarchive", "delete", "list", "resolve")
ERROR_CODES = ("not_found", "conflict", "invalid", "unauthorized", "rate_limited", "unavailable", "unsupported", "internal")


# ---- errors: raise these; they become the error response ------------------------------------------------------------

class AdapterError(Exception):
    code = "internal"
    retryable = False

    def __init__(self, message="", retryable=None, **extra):
        super().__init__(message)
        self.message = message or self.code
        if retryable is not None:
            self.retryable = retryable
        self.extra = extra

    def to_dict(self):
        out = {"code": self.code, "message": self.message, "retryable": self.retryable}
        out.update(self.extra)
        return out


class NotFound(AdapterError):
    code = "not_found"


class Conflict(AdapterError):
    """The id already exists (create) or the stored revision differs from the one sent (update, delete)."""
    code = "conflict"


class Invalid(AdapterError):
    code = "invalid"


class Unauthorized(AdapterError):
    code = "unauthorized"


class RateLimited(AdapterError):
    """Pass `retry_after` (seconds) when the service says how long to wait."""
    code = "rate_limited"
    retryable = True


class Unavailable(AdapterError):
    code = "unavailable"
    retryable = True


class Unsupported(AdapterError):
    code = "unsupported"


class Internal(AdapterError):
    code = "internal"


# ---- helpers for adapter authors -------------------------------------------------------------------------------------

def make_ref(type_, ident):
    return f"{type_}:{ident}"


def split_ref(ref):
    """'task:01J...' -> ('task', '01J...'). Raises Invalid for anything else."""
    if not isinstance(ref, str) or ":" not in ref:
        raise Invalid(f"not a ref: {ref!r}")
    type_, ident = ref.split(":", 1)
    if not type_ or not ident:
        raise Invalid(f"not a ref: {ref!r}")
    return type_, ident


def envelope(type_, ident, impl, fields=None, relations=None, body="", created=None, updated=None, archive=None, archived_at=None,
             revision=None, **extra):
    """Build the envelope every operation returns (docs/plans/03, "Item envelope")."""
    out = {
        "ref": make_ref(type_, ident),
        "type": type_,
        "impl": impl,
        "fields": dict(fields or {}),
        "relations": {k: list(v) for k, v in (relations or {}).items()},
        "body": body or "",
        "created": created,
        "updated": updated,
        "archive": archive,
        "archived_at": archived_at,
        "revision": revision,
    }
    out.update(extra)
    return out


def paginate(items, limit=None, cursor=None, max_page=200):
    """Offset pagination over an already filtered list: returns {"items": [...], "cursor": next or None}."""
    size = max(1, min(int(limit or max_page), max_page))
    try:
        start = int(cursor) if cursor not in (None, "") else 0
    except ValueError as exc:
        raise Invalid(f"bad cursor {cursor!r}") from exc
    page = items[start:start + size]
    nxt = start + size
    return {"items": page, "cursor": str(nxt) if nxt < len(items) else None}


def matches_query(item, query):
    """Apply the structural query (docs/plans/03, `query`) to an envelope, for backends that must filter locally."""
    query = query or {}
    if query.get("types") and item["type"] not in query["types"]:
        return False
    if query.get("impls") and item["impl"] not in query["impls"]:
        return False
    for name, want in (query.get("fields_eq") or {}).items():
        if item["fields"].get(name) != want:
            return False
    for name, target in (query.get("relations_include") or {}).items():
        if target not in item["relations"].get(name, []):
            return False
    since = query.get("updated_since")
    if since and (item.get("updated") or "") < since:
        return False
    archived = item.get("archive") is not None
    if archived and not query.get("include_archived") and not query.get("archived_only"):
        return False
    if query.get("archived_only") and not archived:
        return False
    return True


# ---- the base class --------------------------------------------------------------------------------------------------

class BrainAdapter:
    """Subclass, set the class attributes that describe the backend, and implement the operations it supports.

    Operations you do not implement answer `unsupported`. Raise `AdapterError` subclasses for expected failures; anything else
    becomes `internal` (the traceback goes to stderr, which the plugin shows to the user).
    """

    # --- what `describe` reports (docs/plans/03, "Capabilities") ---
    name = "adapter"
    requires_env = []                 # environment variables the script needs; declare them in registry.yml too
    settings_schema = {}              # e.g. {"project": {"type": "string", "required": True}}
    query = []                        # query keys honored natively: types, impls, fields_eq, relations_include, updated_since, include_archived
    max_page = 200
    supports_body = False
    preserves_unknown_fields = False
    supports_traits = False
    tags = "labels"                   # "map": key/value tags natively; "labels": names only (then keep values in storage.tag_values_field)
    native_ids = False                # True if the backend has its own ids (the plugin then passes native_id back)
    hard_delete = False
    archive_adapter = False
    transactions = False

    settings = None                   # set from each request

    # --- credentials and settings ---
    def env(self, name, default=None, required=True):
        """Read a credential from the environment. Raises Unauthorized (never logs the value) when it is required and missing."""
        value = os.environ.get(name, default)
        if required and not value:
            raise Unauthorized(f"environment variable {name} is not set")
        return value

    def setting(self, name, default=None, required=False):
        value = (self.settings or {}).get(name, default)
        if required and value in (None, ""):
            raise Invalid(f"setting {name!r} is required")
        return value

    # --- operations (override the ones the backend supports) ---
    def describe(self):
        return {
            "protocol": PROTOCOL,
            "adapter": self.name,
            "capabilities": {
                "query": list(self.query),
                "archive_adapter": self.archive_adapter,
                "hard_delete": self.hard_delete,
                "native_ids": self.native_ids,
                "transactions": self.transactions,
                "supports_body": self.supports_body,
                "preserves_unknown_fields": self.preserves_unknown_fields,
                "supports_traits": self.supports_traits,
                "tags": self.tags,
                "max_page": self.max_page,
            },
            "settings_schema": dict(self.settings_schema),
            "requires_env": list(self.requires_env),
        }

    def create(self, envelope, **_):
        raise Unsupported("create is not supported")

    def read(self, ref, **_):
        raise Unsupported("read is not supported")

    def update(self, envelope, **_):
        raise Unsupported("update is not supported")

    def archive(self, ref, revision=None, **_):
        raise Unsupported("archive is not supported natively; the plugin archives through the Archive adapter")

    def unarchive(self, ref, revision=None, **_):
        raise Unsupported("unarchive is not supported natively")

    def delete(self, ref, revision=None, confirm=None, **_):
        raise Unsupported("permanent delete is not supported")

    def list(self, query=None, limit=None, cursor=None, **_):
        raise Unsupported("list is not supported")

    def resolve(self, ref, **_):
        """Default: a cheap existence check built on read()."""
        try:
            self.read(ref)
            return {"binding": self.name, "found": True}
        except NotFound:
            return {"binding": self.name, "found": False}

    # --- dispatch ---
    def handle(self, request):
        """Run one request dict and return the response dict. Never raises."""
        try:
            if not isinstance(request, dict):
                raise Invalid("request must be a JSON object")
            if request.get("protocol", PROTOCOL) != PROTOCOL:
                raise Invalid(f"unsupported protocol {request.get('protocol')!r}; this adapter speaks {PROTOCOL}")
            op = request.get("op")
            if op not in OPERATIONS:
                raise Unsupported(f"unknown operation {op!r}")
            self.settings = request.get("settings") or {}
            args = request.get("args") or {}
            if not isinstance(args, dict):
                raise Invalid("args must be an object")
            result = self._invoke(getattr(self, op), args)
            return {"ok": True, "result": util.jsonable(self._shape(op, result))}
        except AdapterError as exc:
            return {"ok": False, "error": exc.to_dict()}
        except Exception as exc:  # a bug in the adapter: report it, keep the traceback for stderr
            traceback.print_exc(file=sys.stderr)
            return {"ok": False, "error": Internal(f"{type(exc).__name__}: {exc}").to_dict()}

    @staticmethod
    def _invoke(method, args):
        signature = inspect.signature(method)
        params = signature.parameters
        if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            args = {k: v for k, v in args.items() if k in params}      # unknown args are ignored (forward compatibility)
        try:
            signature.bind(**args)
        except TypeError as exc:                                         # a missing required argument is the caller's mistake
            raise Invalid(f"{method.__name__}: {exc}") from exc
        return method(**args)

    @staticmethod
    def _shape(op, result):
        if op == "delete" and result is None:
            return {"ok": True}
        if op == "list":
            if not isinstance(result, dict) or "items" not in result:
                raise Internal("list must return {'items': [...], 'cursor': ...}")
            result.setdefault("cursor", None)
        return result

    # --- the process boundary ---
    def main(self, argv=None, stdin=None, stdout=None, stderr=None):
        """Read one request from stdin, write one response to stdout, return the exit code (also used as sys.exit's argument)."""
        stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
        try:
            request = json.load(stdin)
        except ValueError as exc:
            response = {"ok": False, "error": Invalid(f"request is not valid JSON: {exc}").to_dict()}
        else:
            response = self.handle(request)
        json.dump(response, stdout, ensure_ascii=False)
        stdout.write("\n")
        if not response["ok"]:
            stderr.write(f"{response['error']['code']}: {response['error']['message']}\n")
            return 1
        return 0

    @classmethod
    def run(cls):
        """For the last line of a script: `if __name__ == "__main__": MyAdapter.run()`."""
        sys.exit(cls().main())
