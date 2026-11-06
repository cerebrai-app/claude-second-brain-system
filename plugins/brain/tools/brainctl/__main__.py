"""Command line: python -m brainctl [--vault PATH] <command> ...   (run from .brain/python; the vault is found by walking up)."""
import argparse
import json
import os
import sys

from . import __version__, approval, client as client_mod, ids, pending as pending_mod, store, sync as sync_mod, templates, util, validate as validate_mod
from .model import Vault

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


def _vault(args):
    vault = Vault(args.vault) if args.vault else Vault.discover(".")
    if vault is None:
        print(util.dumps({"ok": False, "error": "not_found", "message": "no .brain directory found from here upwards"}))
        sys.exit(EXIT_USAGE)
    return vault


def cmd_id(args):
    for _ in range(args.n):
        print(ids.ulid())
    return EXIT_OK


def cmd_slug(args):
    taken = set(args.taken.split(",")) if args.taken else set()
    if args.dir:
        taken |= ids.stems(args.dir, args.ext)
    print(ids.unique_slug(ids.slugify(args.title), taken))
    return EXIT_OK


def cmd_validate(args):
    vault = _vault(args)
    findings = validate_mod.validate(vault, args.ref)
    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    if args.text:
        for f in findings:
            print(f"{f['severity']:7} {f['code']:22} {f['subject']}: {f['message']}")
        print(f"{errors} error(s), {warnings} warning(s)")
    else:
        print(util.dumps({"ok": errors == 0, "errors": errors, "warnings": warnings, "findings": findings}))
    return EXIT_FINDINGS if errors else EXIT_OK


def cmd_sync(args):
    vault = _vault(args)
    if args.refresh and (args.dry_run or args.no_adopt):
        print(util.dumps({"ok": False, "error": "invalid", "message": "--refresh cannot be combined with --dry-run or --no-adopt"}))
        return EXIT_USAGE
    result = sync_mod.sync(vault, adopt=not args.no_adopt, dry_run=args.dry_run, refresh=args.refresh)
    if args.text:
        rep = result["report"]
        print(f"baseline: {rep['baseline']}  adopted: {len(rep['adopted'])}  invalid: {len(rep['invalid'])}  missing: {len(rep['missing'])}")
        for e in result["events"]:
            print(f"EVENT {e['trigger']:9} {e['ref']}" + (f"  changed={e['changed']}" if "changed" in e else ""))
    else:
        print(util.dumps({"ok": True, **result}))
    return EXIT_OK


def cmd_list(args):
    vault = _vault(args)
    scan = vault.scan()
    rows = [{"ref": i.ref, "impl": i.impl, "path": i.relpath, "archived": i.archived, "title": i.title, "revision": i.revision} for i in scan.items]
    print(util.dumps({"ok": True, "items": rows, "incomplete": [{"binding": f"{t}/{n}", "reason": r} for t, n, r in scan.skipped]}))
    return EXIT_OK


def cmd_read(args):
    vault = _vault(args)
    matches = [i for i in vault.scan().items if i.ref == args.ref]
    if not matches:
        print(util.dumps({"ok": False, "error": "not_found", "ref": args.ref}))
        return EXIT_FINDINGS
    out = [{"ref": i.ref, "impl": i.impl, "path": i.relpath, "archived": i.archived, "revision": i.revision, "front": i.front, "body": i.body} for i in matches]
    print(util.dumps({"ok": True, "items": out}))
    return EXIT_OK


def cmd_adapter(args):
    """Call one operation of an implementation's script adapter: the same path sync and list use."""
    vault = _vault(args)
    impl = next((i for (t, n), i in vault.impls.items() if n == args.impl and not i.error), None)
    if impl is None or impl.adapter != "script":
        print(util.dumps({"ok": False, "error": {"code": "invalid", "message": f"{args.impl!r} is not a script implementation"}}))
        return EXIT_USAGE
    try:
        call_args = json.loads(args.args) if args.args else {}
        if not isinstance(call_args, dict):
            raise ValueError("--args must be a JSON object")
        result = client_mod.ScriptClient.for_impl(vault, impl).call(args.op, **call_args)
    except ValueError as exc:
        print(util.dumps({"ok": False, "error": {"code": "invalid", "message": str(exc)}}))
        return EXIT_USAGE
    except client_mod.ClientError as err:
        print(util.dumps({"ok": False, "error": {"code": err.code, "message": err.message, "retryable": err.retryable}}))
        return EXIT_FINDINGS
    print(util.dumps({"ok": True, "result": result}))
    return EXIT_OK


def _dig(front, dotted):
    node = front
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def cmd_find(args):
    """Items matching a type, an optional impl and field equalities: the structural check behind `unless_exists`."""
    vault = _vault(args)
    wanted = {}
    for pair in args.where or []:
        if "=" not in pair:
            print(util.dumps({"ok": False, "error": "invalid", "message": f"--where needs field=value, got {pair!r}"}))
            return EXIT_USAGE
        key, value = pair.split("=", 1)
        wanted[key] = value
    scan = vault.scan()
    rows = []
    for item in scan.items:
        if item.type != args.type or (args.impl and item.impl != args.impl) or (item.archived and not args.include_archived):
            continue
        if all(_same(_title_aware(item, k), v) for k, v in wanted.items()):
            rows.append({"ref": item.ref, "impl": item.impl, "path": item.relpath, "archived": item.archived, "title": item.title})
    print(util.dumps({"ok": True, "count": len(rows), "items": rows, "incomplete": [{"binding": f"{t}/{n}", "reason": r} for t, n, r in scan.skipped]}))
    return EXIT_OK if rows else EXIT_FINDINGS


def _title_aware(item, key):
    return item.title if key == "title" and item.type == "person" else _dig(item.front, key)


def _same(actual, wanted):
    if actual is None:
        return False
    return str(util.jsonable(actual)).strip() == wanted if not isinstance(actual, (dict, list)) else util.dumps(util.jsonable(actual)) == wanted


def cmd_approve_hash(args):
    vault = _vault(args)
    print(approval.approval_hash(vault.path(".brain/python"), args.script))
    return EXIT_OK


def cmd_approve(args):
    from . import approval
    vault = _vault(args)
    if bool(args.script) == bool(args.all):
        print("give a script name or --all (not both)", file=sys.stderr)
        return EXIT_USAGE
    by = (args.by or "").strip()
    if not by:
        print("--by is required: name the person who approved (their name or email), not the tool or the git identity", file=sys.stderr)
        return EXIT_USAGE
    try:
        done = approval.approve(vault.path(".brain/python"), None if args.all else [args.script], by, util.now_iso())
    except (approval.ApprovalError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(util.dumps({"approved": [{"name": n, "sha256": h} for n, h in done], "by": by}))
    return EXIT_OK


def cmd_render(args):
    """Resolve `{{ name }}` templates (built-ins `today` and `now`, plus --vars bindings). Prints text, or JSON with --json."""
    import datetime as dt
    vault = Vault(args.vault) if args.vault else Vault.discover(".")
    try:
        now = None
        if args.now:
            now = dt.datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        variables = templates.builtins(vault.config_get("timezone") if vault else None, now)
        if args.vars:
            text = sys.stdin.read() if args.vars == "-" else (open(args.vars[1:], encoding="utf-8").read() if args.vars.startswith("@") else args.vars)
            bound = json.loads(text)
            if not isinstance(bound, dict):
                raise templates.TemplateError("--vars must be a JSON object of name to value")
            variables.update(bound)
        for pair in args.var or []:
            if "=" not in pair:
                raise templates.TemplateError(f"--var needs name=value, got {pair!r}")
            key, value = pair.split("=", 1)
            variables[key] = value
        if args.json:
            data = json.loads(args.template if args.template is not None else sys.stdin.read())
            print(util.dumps(templates.resolve(data, variables)))
        else:
            if args.template is None:
                raise templates.TemplateError("give a template string (or --json with data)")
            print(templates.render(args.template, variables))
    except (templates.TemplateError, ValueError, OSError) as exc:
        print(util.dumps({"ok": False, "error": "template", "message": str(exc)}))
        return EXIT_USAGE
    return EXIT_OK


def _json_input(args):
    """The command's JSON argument: --json '<json>', --json @FILE, or --json - for stdin. Nothing is read from stdin unless asked, so a
    command run from a shell with an open pipe cannot hang. {} when there is no input."""
    text = args.json
    if text == "-":
        text = sys.stdin.read()
    elif text and text.startswith("@"):
        with open(text[1:], encoding="utf-8") as fh:
            text = fh.read()
    if not text or not text.strip():
        return {}
    value = json.loads(text)
    if not isinstance(value, (dict, list)):
        raise ValueError("the JSON input must be an object")
    return value


def _store_command(args, fn):
    """Run a write command: print its JSON result (exit 0), or {ok: false, error} and exit 1 for a storage error, 2 for bad input."""
    vault = _vault(args)
    try:
        result = fn(vault)
    except store.StoreError as err:
        print(util.dumps({"ok": False, "error": err.to_dict()}))
        return EXIT_FINDINGS
    except (ValueError, KeyError, OSError) as exc:
        print(util.dumps({"ok": False, "error": {"code": "invalid", "message": f"bad input: {exc}"}}))
        return EXIT_USAGE
    print(util.dumps(result))
    return EXIT_OK


def cmd_create(args):
    return _store_command(args, lambda v: store.create(v, _json_input(args)))


def cmd_update(args):
    return _store_command(args, lambda v: store.update(v, args.ref, _json_input(args)))


def cmd_archive(args):
    return _store_command(args, lambda v: store.archive(v, args.ref))


def cmd_unarchive(args):
    return _store_command(args, lambda v: store.unarchive(v, args.ref))


def cmd_delete(args):
    return _store_command(args, lambda v: store.delete(v, args.ref, args.confirm))


def cmd_convert(args):
    if args.action == "plan":
        return _store_command(args, lambda v: store.convert_plan(v, args.ref, args.to))
    if args.action == "apply":
        return _store_command(args, lambda v: store.convert_apply(v, args.ref, args.to, _json_input(args)))
    return _store_command(args, lambda v: store.finish_conversion(v, args.ref))


def cmd_op(args):
    return _store_command(args, lambda v: pending_mod.apply_operation(v, _json_input(args)))


def cmd_log(args):
    return _store_command(args, lambda v: pending_mod.append_log(v, _json_input(args)))


def cmd_pending(args):
    if args.action == "add":
        return _store_command(args, lambda v: pending_mod.add(v, _json_input(args)))
    if args.action == "list":
        return _store_command(args, lambda v: pending_mod.list_entries(v, prune=args.prune))
    if not args.id:
        print("give the pending entry id", file=sys.stderr)
        return EXIT_USAGE
    if args.action == "apply":
        def run(v):
            edited = _json_input(args)
            return pending_mod.apply(v, args.id, edited.get("operations") if isinstance(edited, dict) and edited else None)
        return _store_command(args, run)
    return _store_command(args, lambda v: pending_mod.reject(v, args.id))


def adapter_ops():
    from .adapter import OPERATIONS
    return OPERATIONS


def build_parser():
    p = argparse.ArgumentParser(prog="brainctl", description="Deterministic helper for a second-brain vault.")
    p.add_argument("--vault", help="vault root (default: found by walking up from the working directory)")
    p.add_argument("--version", action="version", version=f"brainctl {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("id", help="new ULID(s)")
    s.add_argument("-n", type=int, default=1)
    s.set_defaults(fn=cmd_id)
    s = sub.add_parser("slug", help="a unique slug for a title")
    s.add_argument("title")
    s.add_argument("--taken", help="comma-separated names already in use")
    s.add_argument("--dir", help="directory whose file stems are in use")
    s.add_argument("--ext", default=".md")
    s.set_defaults(fn=cmd_slug)
    s = sub.add_parser("validate", help="check the vault (read-only)")
    s.add_argument("--ref", help="only findings for this ref or path prefix")
    s.add_argument("--text", action="store_true", help="human-readable output instead of JSON")
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("sync", help="detect outside changes, adopt hand-written files, update the seen state")
    s.add_argument("--no-adopt", action="store_true", help="report unadopted files without editing them")
    s.add_argument("--dry-run", action="store_true", help="write nothing: no adoption and no seen state")
    s.add_argument("--refresh", action="store_true", help="accept the current state as seen: no events, no adoption (use after the plugin's own writes)")
    s.add_argument("--text", action="store_true")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("list", help="list items across bindings and the Archive")
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser("read", help="read an item by ref")
    s.add_argument("ref")
    s.set_defaults(fn=cmd_read)
    s = sub.add_parser("find", help="find items by type, impl and field values (exit 1 when none match)")
    s.add_argument("--type", required=True)
    s.add_argument("--impl")
    s.add_argument("--where", action="append", metavar="FIELD=VALUE", help="field equality; repeatable; dotted paths reach nested fields")
    s.add_argument("--include-archived", action="store_true")
    s.set_defaults(fn=cmd_find)
    s = sub.add_parser("adapter", help="call one operation of a script implementation's adapter (needs the script approved)")
    s.add_argument("impl")
    s.add_argument("op", choices=adapter_ops())
    s.add_argument("--args", help="JSON object of arguments")
    s.set_defaults(fn=cmd_adapter)
    def writer(name, help_, fn, **kw):
        s = sub.add_parser(name, help=help_)
        for flag, kwargs in kw.get("args", []):
            s.add_argument(flag, **kwargs)
        if kw.get("json", True):
            s.add_argument("--json", help="the JSON input: the JSON itself, @FILE, or - to read stdin (stdin is never read otherwise)")
        s.set_defaults(fn=fn)
        return s

    writer("create", "create an item (JSON: type, impl?, title or name, fields, relations, tags, body); assigns id, slug, timestamps, defaults", cmd_create)
    writer("update", "change an item (JSON: set, unset, body, revision?); sets updated and completed, moves the file when the path changes", cmd_update,
           args=[("ref", {})])
    writer("archive", "move an item to the Archive", cmd_archive, args=[("ref", {})], json=False)
    writer("unarchive", "restore an archived item", cmd_unarchive, args=[("ref", {})], json=False)
    writer("delete", "permanently delete an item (needs --confirm permanent)", cmd_delete, args=[("ref", {}), ("--confirm", {})], json=False)
    s = writer("convert", "convert an item to another implementation of its type: plan | apply (JSON resolutions: drop, rename, fill) | finish", cmd_convert,
               args=[("action", {"choices": ["plan", "apply", "finish"]}), ("ref", {})])
    s.add_argument("--to", help="the target implementation id (plan, apply)")
    writer("op", "apply one rule operation (set_field, set_relation, add_relation, archive, unarchive, create_item) from JSON", cmd_op)
    writer("log", "append a rule-run line to the automation log (JSON: rule, trigger, event, actions, outcome, ...)", cmd_log)
    s = writer("pending", "the pending-approval queue: add (JSON proposal) | list [--prune] | apply ID [JSON: edited operations] | reject ID", cmd_pending,
               args=[("action", {"choices": ["add", "list", "apply", "reject"]}), ("id", {"nargs": "?"})])
    s.add_argument("--prune", action="store_true", help="list: drop expired entries")
    s = sub.add_parser("approve", help="record the current approval hash of a registered script, or of every unapproved or changed one (--all); show the user the diff first")
    s.add_argument("script", nargs="?")
    s.add_argument("--all", action="store_true")
    s.add_argument("--by", help="who approved: the user's name or email (required)")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("render", help="resolve {{ today }}, {{ now }} and bound variables in a template string, or in the strings of a JSON value (--json)")
    s.add_argument("template", nargs="?", help="the template (with --json: a JSON value; omit to read it from stdin)")
    s.add_argument("--json", action="store_true", help="the input is JSON; every string in it is resolved and the JSON is printed")
    s.add_argument("--vars", help="JSON object of bindings (name to value, for example a surface result set); @FILE reads a file, - reads stdin")
    s.add_argument("--var", action="append", metavar="NAME=VALUE", help="a string binding; repeatable")
    s.add_argument("--now", help="resolve against this instant (ISO 8601) instead of the current time, for tests")
    s.set_defaults(fn=cmd_render)
    s = sub.add_parser("approve-hash", help="the workspace approval hash of a script (path relative to .brain/python)")
    s.add_argument("script")
    s.set_defaults(fn=cmd_approve_hash)
    return p


def environment_problem(package_dir=None, prefix=None):
    """An installed copy (inside <vault>/.brain/python) must run in that workspace's virtualenv, and nowhere else."""
    package_dir = os.path.realpath(package_dir or os.path.dirname(os.path.abspath(__file__)))
    workspace = os.path.dirname(package_dir)
    if os.path.basename(workspace) != "python" or os.path.basename(os.path.dirname(workspace)) != ".brain":
        return None                      # running from the plugin source (development, tests): no workspace to enforce
    expected = os.path.join(workspace, ".venv")
    if os.path.realpath(prefix or sys.prefix) != os.path.realpath(expected):
        return (f"brainctl must run in the workspace environment ({expected}), not {prefix or sys.prefix}. "
                "Run it through the workspace tool from .brain/python, for example `uv run --frozen python -m brainctl ...`.")
    return None


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    problem = environment_problem()
    if problem:
        print(util.dumps({"ok": False, "error": "wrong_environment", "message": problem}))
        sys.exit(EXIT_USAGE)
    sys.exit(main())
