"""Stand-in for the deterministic parts of `brainctl` (docs/plans/11-brainctl-helper.md) while the real helper is unwritten.

It implements, for the markdown adapter only: listing items across bindings (keyed by ref AND binding, so duplicates show),
`validate` (duplicate refs, half-converted markers, dangling relations), and `sync` (ref-level matching across bindings,
hand-written file adoption, seen state). Needs PyYAML. This is a test tool, not the product.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "plugins", "brain", "tools", "brainctl"))
import ids  # noqa: E402

REL_KEYS = ("belongs_to", "assigned_to", "blocked_by", "about", "links", "area", "owner", "parent")


def parse(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return None, text
    return (yaml.safe_load(m.group(1)) or {}), m.group(2)


class Vault:
    def __init__(self, root):
        self.root = root

    # ----- bindings and items -------------------------------------------------
    def bindings(self):
        out = []
        for f in sorted(glob.glob(f"{self.root}/.brain/impls/*/*.md")):
            fm, _ = parse(f)
            out.append((fm["extends"], fm["impl"], fm["storage"]["path"]))
        return out

    def _files(self, template):
        return sorted(glob.glob(os.path.join(self.root, re.sub(r"\{[^}]+\}", "*", template))))

    def revision(self, path):
        return subprocess.check_output(["git", "-C", self.root, "hash-object", path]).decode().strip()

    def listing(self):
        """Return (items, unadopted). items: list of dicts, one per (ref, binding)."""
        items, unadopted = [], []
        for typ, impl, tpl in self.bindings():
            for f in self._files(tpl):
                fm, body = parse(f)
                if fm is None or not all(k in fm for k in ("id", "type", "impl")):
                    unadopted.append((typ, impl, f))
                    continue
                if fm["type"] != typ or fm["impl"] != impl:
                    continue
                items.append(dict(ref=f"{typ}:{fm['id']}", type=typ, impl=impl, fm=fm, body=body, path=f, rev=self.revision(f)))
        return items, unadopted

    # ----- validate -------------------------------------------------------------
    def validate(self):
        items, unadopted = self.listing()
        probs = []
        seen = {}
        for it in items:
            if it["ref"] in seen:
                probs.append(("error", it["ref"], f"exists in two bindings: {seen[it['ref']]} and {it['impl']}"))
            seen[it["ref"]] = it["impl"]
        for f in sorted(glob.glob(f"{self.root}/.brain/conversions/*.json")):
            probs.append(("warn", os.path.basename(f), "half-converted marker"))
        for _, _, f in unadopted:
            probs.append(("warn", os.path.relpath(f, self.root), "unadopted file"))
        refs = {i["ref"] for i in items} | {"area:inbox"}
        for it in items:
            for k in REL_KEYS:
                for t in it["fm"].get(k) or []:
                    if t not in refs:
                        probs.append(("warn", it["ref"], f"dangling {k} -> {t}"))
        return probs

    # ----- sync -----------------------------------------------------------------
    def _seen_path(self, typ, impl):
        return f"{self.root}/.brain/automation/seen/{typ}/{impl}.json"

    @staticmethod
    def _snapshot(it):
        fm = it["fm"]
        rel = {k: v for k, v in fm.items() if k in REL_KEYS}
        fields = {k: str(v) for k, v in fm.items() if k not in rel and k not in ("id", "type", "impl")}
        return dict(revision=it["rev"], fields=fields, relations=rel)

    def adopt(self, typ, impl, path):
        """Add only the missing identity fields. Never rename the file; never touch the body or existing keys."""
        text = open(path, encoding="utf-8").read()
        m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
        existing = (yaml.safe_load(m.group(1)) or {}) if m else {}
        body = m.group(2) if m else text
        if m:
            front = m.group(1)
        else:
            front = ""
        stem = os.path.splitext(os.path.basename(path))[0]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mtime = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path)))
        heading = re.search(r"^#\s+(.+)$", body, re.M)
        add = {}
        if "id" not in existing:
            add["id"] = ids.ulid()
        if "type" not in existing:
            add["type"] = typ
        if "impl" not in existing:
            add["impl"] = impl
        if "slug" not in existing:
            add["slug"] = stem
        if "title" not in existing:
            add["title"] = heading.group(1) if heading else stem.replace("-", " ")
        if "created" not in existing:
            add["created"] = mtime
        if "updated" not in existing:
            add["updated"] = now
        lines = "".join(f"{k}: {json.dumps(v) if k == 'title' else v}\n" for k, v in add.items())
        open(path, "w", encoding="utf-8").write("---\n" + lines + (front + "\n" if front else "") + "---\n" + body)
        return add["id"] if "id" in add else existing["id"]

    def sync(self, adopt=True):
        """Return (events, report). Matches by ref across bindings; updates the seen state."""
        items, unadopted = self.listing()
        report = dict(adopted=[], unadopted=[os.path.relpath(f, self.root) for _, _, f in unadopted])
        if adopt:
            for typ, impl, f in unadopted:
                self.adopt(typ, impl, f)
                report["adopted"].append(os.path.relpath(f, self.root))
            items, _ = self.listing()
        old = {}  # ref -> (impl, snapshot) across ALL bindings of seen state
        baseline = True
        for typ, impl, _ in self.bindings():
            p = self._seen_path(typ, impl)
            if os.path.exists(p):
                baseline = False
                for ref, snap in json.load(open(p))["entries"].items():
                    old[ref] = (impl, snap)
        new = {}
        for it in items:
            new[it["ref"]] = (it["impl"], self._snapshot(it))
        events = []
        if not baseline:
            for ref, (impl, snap) in new.items():
                if ref not in old:
                    events.append(("create", ref, impl))
                    if self._in_inbox(ref, items):
                        events.append(("capture", ref, impl))
                else:
                    oimpl, osnap = old[ref]
                    if oimpl != impl:
                        events.append(("update", ref, f"changed: impl {oimpl} -> {impl}"))
                    elif osnap["revision"] != snap["revision"]:
                        events.append(("update", ref, "changed"))
            for ref in old:
                if ref not in new:
                    events.append(("missing", ref, ""))
        for typ, impl, _ in self.bindings():
            p = self._seen_path(typ, impl)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump({"impl": impl, "entries": {r: s for r, (i, s) in new.items() if i == impl}}, open(p, "w"), indent=1)
        report["baseline"] = baseline
        return events, report

    def _in_inbox(self, ref, items):
        it = next(i for i in items if i["ref"] == ref)
        placement = {"task": "belongs_to", "note": "about", "project": "area"}.get(it["type"])
        if not placement:
            return False  # areas and persons are top-level
        targets = [t for t in it["fm"].get(placement) or [] if not t.startswith("person:")]
        return not targets or targets == ["area:inbox"]


if __name__ == "__main__":
    v = Vault(os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "."))
    if sys.argv[1] == "validate":
        for p in v.validate():
            print(*p)
    elif sys.argv[1] == "sync":
        ev, rep = v.sync()
        print(rep)
        for e in ev:
            print("EVENT", *e)
