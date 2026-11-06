#!/usr/bin/env python3
"""Reproduce the deterministic part of the rehearsal on a fresh scratch vault and assert the expected results.

    python3 tests/rehearsal/scenario.py [--vault DIR] [--workspace] [--keep]

--vault DIR    use DIR (must not exist) instead of a temporary directory
--workspace    also build and exercise the Python workspace (needs `uv`, network)
--keep         do not delete the temporary vault afterwards

The steps that need Claude (following the skills) are listed in TESTING.md; this script covers the mechanical ones with
`brainsim.py` standing in for `brainctl`. Needs PyYAML.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import brainsim  # noqa: E402
from brainsim import ids  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sh(*cmd, cwd=None, check_=True):
    return subprocess.run(cmd, cwd=cwd, check=check_, capture_output=True, text=True)


def write(vault, rel, text):
    path = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)
    return path


def item(vault, typ, impl, directory, title, extra="", slug=None, body=""):
    """Create an item the way the skills describe: ULID id, unique zero-padded slug, frontmatter file."""
    d = os.path.join(vault, directory)
    s = ids.unique_slug(slug or ids.slugify(title), ids.stems(d))
    i, t = ids.ulid(), now()
    quoted = f'"{title}"' if title[:1].isdigit() else title
    write(vault, f"{directory}/{s}.md",
          f"---\nid: {i}\nslug: {s}\ntype: {typ}\nimpl: {impl}\ntitle: {quoted}\n{extra}created: {t}\nupdated: {t}\n---\n{body}")
    return i, s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault")
    ap.add_argument("--workspace", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    vault = a.vault or tempfile.mkdtemp(prefix="brain-vault-")
    if a.vault:
        os.makedirs(vault)
    print(f"vault: {vault}\n")

    # ---- setup (docs/plans/06) ---------------------------------------------------
    sh("git", "init", "-q", cwd=vault)
    sh("git", "config", "user.email", "test@example.com", cwd=vault)
    sh("git", "config", "user.name", "Test", cwd=vault)
    # A Python-template .gitignore ignores `lib/`: the case that bit the first rehearsal.
    write(vault, ".gitignore", "__pycache__/\n.venv\nlib/\n")
    for t in ("task", "note", "project", "area", "person"):
        shutil.copy(f"{REPO}/plugins/brain/starters/{t}/default-{t}.md", os.path.join(vault, ".brain/impls", t, f"default-{t}.md")) \
            if os.path.isdir(os.path.join(vault, ".brain/impls", t)) else (
            os.makedirs(os.path.join(vault, ".brain/impls", t)),
            shutil.copy(f"{REPO}/plugins/brain/starters/{t}/default-{t}.md", os.path.join(vault, ".brain/impls", t, f"default-{t}.md")))
    write(vault, ".brain/config.yml", "version: 1\nname: scratch\narchive:\n  adapter: markdown\n  path: \"archive/{type}/{impl}/{slug}.md\"\nimpls: .brain/impls\npython:\n  tool: uv\ncapture:\n  type_by_source: {}\n")
    t0 = now()
    write(vault, "areas/inbox.md", f"---\nid: inbox\nslug: inbox\ntype: area\nimpl: default-area\ntitle: Inbox\nsystem: true\ndefaults:\n  task: default-task\n  note: default-note\n  project: default-project\n  area: default-area\ncreated: {t0}\nupdated: {t0}\n---\n")
    write(vault, ".brain/manifest.yml", "core_version: 1\nmigrations: []\nimplementations:\n  task/default-task: { version: 1 }\n  note/default-note: { version: 1 }\n  project/default-project: { version: 1 }\n  area/default-area: { version: 1 }\n  person/default-person: { version: 1 }\ntraits: {}\n")
    ignored = sh("git", "check-ignore", "-q", ".brain/python/lib/x.py", cwd=vault, check_=False).returncode == 0
    check("template .gitignore ignores .brain/python/lib/ (reproduces the first-rehearsal bug)", ignored)
    with open(os.path.join(vault, ".gitignore"), "a") as g:
        g.write("!.brain/python/lib/\n")
    ignored = sh("git", "check-ignore", "-q", ".brain/python/lib/x.py", cwd=vault, check_=False).returncode == 0
    check("a negation line un-ignores it", not ignored)

    if a.workspace:
        py = os.path.join(vault, ".brain/python")
        os.makedirs(py)
        sh("uv", "init", "--bare", "--name", "brain-workspace", "--python", ">=3.12", cwd=py)
        sh("uv", "lock", cwd=py)
        sh("uv", "sync", "--frozen", cwd=py)
        r = subprocess.run(["env", "-i", f"PATH={os.environ['PATH']}", "uv", "run", "--frozen", "python", "-c", "print('ok')"], cwd=py, capture_output=True, text=True)
        check("workspace runs a script with a scrubbed environment", r.stdout.strip() == "ok", r.stderr[-200:])

    v = brainsim.Vault(vault)
    events, report = v.sync()
    check("first sync builds a silent baseline", report["baseline"] and events == [])

    # ---- capture (docs/plans/06, 08) -------------------------------------------------
    n1, s1 = item(vault, "note", "default-note", "notes", "Look into spaced repetition")
    n2, s2 = item(vault, "note", "default-note", "notes", "Look into spaced repetition")
    check("slug is human readable", s1 == "look-into-spaced-repetition", s1)
    check("collision gets a zero-padded suffix", s2 == "look-into-spaced-repetition-02", s2)
    for _ in range(9):
        item(vault, "note", "default-note", "notes", "Look into spaced repetition")
    names = sorted((n[:-3] for n in os.listdir(os.path.join(vault, "notes"))))  # sort by stem
    expected = ["look-into-spaced-repetition"] + [f"look-into-spaced-repetition-{n:02d}" for n in range(2, 12)]
    check("suffixes are zero-padded and sort alphabetically by stem through -11", names == expected, names)
    # keep the base and -02; drop the rest so later checks stay readable
    for n in names[2:]:
        os.remove(os.path.join(vault, "notes", n + ".md"))
    jid, js = item(vault, "note", "journal", "journal", time.strftime("%Y-%m-%d", time.gmtime()))
    check("a date title gives a date file name", js == time.strftime("%Y-%m-%d", time.gmtime()), js)

    tid, ts = item(vault, "task", "default-task", "tasks", "Draft Q4 plan", "status: open\n")
    aid, _ = item(vault, "area", "default-area", "areas", "Work")
    pid, _ = item(vault, "project", "default-project", "projects", "Q4 planning", "status: open\ndefaults:\n  task: gtd-task\n")
    write(vault, ".brain/impls/task/gtd-task.md",
          "---\nimpl: gtd-task\nextends: task\nversion: 1\nschema:\n  fields:\n    context: { type: enum, values: [work, home, errands], required: true }\n    priority: { type: enum, values: [low, med, high], default: med }\nstorage:\n  adapter: markdown\n  path: \"tasks/gtd/{slug}.md\"\n---\n")
    write(vault, ".brain/impls/note/journal.md", "---\nimpl: journal\nextends: note\nversion: 1\nstorage:\n  adapter: markdown\n  path: \"journal/{slug}.md\"\n---\n")
    events, _ = v.sync()
    refs = {e[1] for e in events if e[0] == "create"}
    check("sync reports the new items as creates", {f"task:{tid}", f"note:{n1}", f"area:{aid}", f"project:{pid}"} <= refs, events)
    caps = {e[1] for e in events if e[0] == "capture"}
    check("tasks, notes and projects fire capture; areas do not", f"task:{tid}" in caps and f"area:{aid}" not in caps, caps)

    # ---- hand-written file adoption (docs/plans/05) -----------------------------------
    hand = write(vault, "notes/idea-from-the-bus.md", "# Idea from the bus\nWhat if triage had a mobile view?\n")
    events, report = v.sync()
    text = open(hand).read()
    check("hand-written file is adopted", report["adopted"] == ["notes/idea-from-the-bus.md"] and "id: " in text, report)
    check("adoption keeps the file name and body", os.path.exists(hand) and text.rstrip().endswith("What if triage had a mobile view?"))
    adopted_id = [l.split(": ", 1)[1] for l in text.splitlines() if l.startswith("id: ")][0]
    check("adoption emits create and capture for the adopted note", ("create", f"note:{adopted_id}", "default-note") in events and ("capture", f"note:{adopted_id}", "default-note") in events, events)
    events, _ = v.sync()
    check("a second sync is quiet", events == [], events)

    # ---- triage: placement and a conversion with a half-converted failure ----------------
    # (the third-party edits below are what `brainctl update` would do, including refreshing the seen state)
    def rewrite(path, add_lines):
        s = open(path).read().replace("\nupdated:", "\n" + add_lines + "updated:", 1)
        open(path, "w").write(s)
    rewrite(os.path.join(vault, "notes", s1 + ".md"), f"about: [project:{pid}]\n")
    rewrite(os.path.join(vault, "projects", "q4-planning.md"), f"area: [area:{aid}]\n")
    v.sync()
    # conversion default-task -> gtd-task: required `context` is missing, `priority` is filled by default
    src = os.path.join(vault, "tasks", ts + ".md")
    dst = os.path.join(vault, "tasks/gtd", ts + ".md")
    os.makedirs(os.path.dirname(dst))
    created = [l for l in open(src).read().splitlines() if l.startswith("created:")][0]
    write(vault, f"tasks/gtd/{ts}.md",
          f"---\nid: {tid}\nslug: {ts}\ntype: task\nimpl: gtd-task\ntitle: Draft Q4 plan\nstatus: open\ncontext: work\npriority: med\nbelongs_to: [project:{pid}]\n{created}\nupdated: {now()}\n---\n")
    write(vault, f".brain/conversions/task-{tid}.json", f'{{"ref":"task:{tid}","at":"{now()}"}}\n')
    probs = v.validate()
    check("validate reports the item in two bindings", any(p[0] == "error" and "two bindings" in p[2] for p in probs), probs)
    check("validate reports the half-converted marker", any("half-converted" in p[2] for p in probs), probs)
    os.remove(src)
    os.remove(os.path.join(vault, f".brain/conversions/task-{tid}.json"))
    check("finishing the conversion clears validate", [p for p in v.validate() if p[0] == "error"] == [], v.validate())
    events, _ = v.sync()
    mine = [e for e in events if e[1] == f"task:{tid}"]
    check("sync sees the conversion as ONE update with the impl changed", mine == [("update", f"task:{tid}", "changed: impl default-task -> gtd-task")], mine)

    # ---- approval hash (docs/plans/11) --------------------------------------------------
    if a.workspace:
        py = os.path.join(vault, ".brain/python")
        os.makedirs(os.path.join(py, "scripts"), exist_ok=True)
        os.makedirs(os.path.join(py, "lib"), exist_ok=True)
        write(vault, ".brain/python/scripts/hello.py", "print('hi')\n")
        h = lambda: subprocess.run([sys.executable, "-I", f"{HERE}/approval_hash.py", "scripts/hello.py"], cwd=py, capture_output=True, text=True).stdout.strip()
        h1 = h()
        with open(os.path.join(py, "pyproject.toml"), "a") as f:
            f.write("# touched\n")
        check("approval hash changes when pyproject.toml changes", h1 != h() and len(h1) == 64)

    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    if not (a.keep or a.vault):
        shutil.rmtree(vault)
    else:
        print(f"vault kept at {vault}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
