"""The client side of script adapters (docs/plans/03 and 12): run a registered workspace script once per operation.

    client = ScriptClient.for_impl(vault, impl)       # raises ClientError unless the script is registered and approved
    client.call("read", ref="task:01J...")            # -> the result, or raises ClientError(code, message)
    client.list_all(query)                            # follows cursors; every envelope

Rules: the script must be in registry.yml and approved for its current hash; it runs in the workspace virtualenv (`.brain/python/.venv`, never another interpreter) with a scrubbed environment holding only
its `requires_env`; each call has a timeout; a `rate_limited` error is retried once after a minute, and a second one fails.
"""
import json
import os
import subprocess
import time

from . import adapter as adapter_mod, approval, util

RETRY_DELAY = 60          # seconds before the single retry after rate_limited (tests set this to 0)
DEFAULT_TIMEOUT = 30
PAGE = 200
BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "TEMP", "TMP")


class ClientError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


def venv_python(vault):
    """The workspace's own interpreter. Scripts never run under any other Python (no system or calling interpreter)."""
    python = vault.path(".brain/python/.venv/bin/python")
    if not os.path.isfile(python):
        raise ClientError("unavailable", "the Python workspace has no environment at .brain/python/.venv; sync it with the workspace tool "
                          "(for example `uv sync --frozen`, or `poetry install` with in-project virtualenvs) and try again")
    return python


def registry(vault):
    data = util.load_yaml_file(vault.path(".brain/python/registry.yml")) if os.path.isfile(vault.path(".brain/python/registry.yml")) else None
    return {s.get("name"): s for s in ((data or {}).get("scripts") or []) if isinstance(s, dict)}


class ScriptClient:
    def __init__(self, vault, name, entry, settings=None, timeout=None, python=None):
        self.vault = vault
        self.name = name
        self.entry = entry
        self.settings = settings or {}
        self.timeout = timeout or entry.get("timeout") or DEFAULT_TIMEOUT
        self.py_dir = vault.path(".brain/python")
        self.python = python or venv_python(vault)

    @classmethod
    def for_impl(cls, vault, impl):
        command = impl.storage.get("command")
        if not isinstance(command, str) or not command.startswith("python:"):
            raise ClientError("unsupported", f"command {command!r} is not a python:<name> workspace script")
        name = command[len("python:"):]
        entry = registry(vault).get(name)
        if entry is None:
            raise ClientError("unsupported", f"{command} is not in the Python workspace registry")
        settings = dict(impl.storage.get("settings") or {})
        timeout = impl.storage.get("timeout_seconds")
        return cls(vault, name, entry, settings, timeout, python=venv_python(vault))

    # ---- approval ---------------------------------------------------------------------------------------------------
    def check_approved(self):
        path = self.entry.get("path")
        if not path or not os.path.isfile(os.path.join(self.py_dir, path)):
            raise ClientError("unsupported", f"python:{self.name} has no script file at {path!r}")
        approved = (self.entry.get("approved") or {}).get("sha256")
        if not approved:
            raise ClientError("unauthorized", f"python:{self.name} has not been approved; it cannot run until the user approves it")
        if approved != approval.approval_hash(self.py_dir, path):
            raise ClientError("unauthorized", f"python:{self.name} changed since it was approved; show the diff and ask again")

    # ---- running ----------------------------------------------------------------------------------------------------
    def _environment(self):
        env = {k: os.environ[k] for k in BASE_ENV if k in os.environ}
        for name in self.entry.get("requires_env") or []:
            if name in os.environ:
                env[name] = os.environ[name]
        env["PYTHONPATH"] = self.py_dir          # brainctl.adapter and lib/ import from the workspace
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def _run_once(self, op, args):
        request = {"protocol": adapter_mod.PROTOCOL, "op": op, "settings": self.settings, "args": args}
        script = os.path.join(self.py_dir, self.entry["path"])
        try:
            proc = subprocess.run([self.python, script], input=json.dumps(request), capture_output=True, text=True,
                                  timeout=self.timeout, cwd=self.py_dir, env=self._environment())
        except subprocess.TimeoutExpired:
            raise ClientError("unavailable", f"python:{self.name} {op} timed out after {self.timeout}s", retryable=True) from None
        except OSError as exc:
            raise ClientError("internal", f"could not start python:{self.name}: {exc}") from None
        out = proc.stdout.strip()
        try:
            response = json.loads(out.splitlines()[-1]) if out else None
        except ValueError:
            response = None
        if not isinstance(response, dict) or "ok" not in response:
            tail = (proc.stderr or out or "no output").strip().splitlines()[-3:]
            raise ClientError("internal", f"python:{self.name} {op} gave no valid response (exit {proc.returncode}): " + " | ".join(tail))
        if response["ok"]:
            return response.get("result")
        error = response.get("error") or {}
        code = error.get("code") if error.get("code") in adapter_mod.ERROR_CODES else "internal"
        raise ClientError(code, error.get("message") or code, bool(error.get("retryable")))

    def call(self, op, **args):
        self.check_approved()
        try:
            return self._run_once(op, args)
        except ClientError as err:
            if err.code != "rate_limited":
                raise
        time.sleep(RETRY_DELAY)
        return self._run_once(op, args)          # a second rate_limited in a row fails

    def describe(self):
        return self.call("describe")

    def list_all(self, query=None):
        items, cursor = [], None
        while True:
            page = self.call("list", query=query or {}, limit=PAGE, cursor=cursor)
            items.extend(page.get("items") or [])
            cursor = page.get("cursor")
            if not cursor:
                return items


def envelope_to_front(env):
    """A storage envelope as the flat front-matter-like mapping the rest of the helper works on."""
    ident = env["ref"].split(":", 1)[1]
    front = {"id": ident, "type": env.get("type"), "impl": env.get("impl")}
    front.update(env.get("fields") or {})
    front.update(env.get("relations") or {})
    for key in ("created", "updated", "archive", "archived_at"):
        if env.get(key) is not None:
            front[key] = env[key]
    return front
