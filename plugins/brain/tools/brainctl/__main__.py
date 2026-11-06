"""Command line: python -m brainctl [--vault PATH] <command> ...   (run from .brain/python; the vault is found by walking up)."""
import argparse
import json
import os
import sys

from . import __version__, approval, client as client_mod, ids, sync as sync_mod, util, validate as validate_mod
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


def cmd_approve_hash(args):
    vault = _vault(args)
    print(approval.approval_hash(vault.path(".brain/python"), args.script))
    return EXIT_OK


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
    s = sub.add_parser("adapter", help="call one operation of a script implementation's adapter (needs the script approved)")
    s.add_argument("impl")
    s.add_argument("op", choices=adapter_ops())
    s.add_argument("--args", help="JSON object of arguments")
    s.set_defaults(fn=cmd_adapter)
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
