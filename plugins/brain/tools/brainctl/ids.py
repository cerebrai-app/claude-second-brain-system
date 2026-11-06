#!/usr/bin/env python3
"""Deterministic id and slug helpers for the brain plugin (standard library only).

    python3 -I ids.py ulid [-n N]
    python3 -I ids.py slug "Some Title" [--taken a,b,c] [--dir PATH [--ext .md]]

ulid  -> a 26-character ULID (Crockford base32): 48-bit millisecond timestamp + 80 random bits.
slug  -> a human-readable file-name stem made from a title (docs/plans/08-core-types.md, "Slug"),
         made unique against the names already taken.
"""
import os
import sys
import time
import unicodedata

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_MAX_SLUG = 60
_MIN_WORD_CUT = 20

_last_ms = -1
_last_rand = 0


def ulid(now_ms=None):
    """Return a ULID. Monotonic within one process: ids made in the same millisecond still sort in order."""
    global _last_ms, _last_rand
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    if ms < 0 or ms >= 1 << 48:
        raise ValueError("timestamp out of range")
    if ms == _last_ms:
        _last_rand += 1
        if _last_rand >= 1 << 80:
            raise OverflowError("random component exhausted within one millisecond")
    else:
        _last_ms = ms
        _last_rand = int.from_bytes(os.urandom(10), "big")
        # leave room to increment within the same millisecond
        _last_rand &= (1 << 79) - 1
    n = (ms << 80) | _last_rand
    return "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def slugify(text):
    """Lowercase; keep Unicode letters and digits; every other run becomes one '-'; trim; cut to 60 at a '-' where possible."""
    s = unicodedata.normalize("NFC", text).lower()
    out = []
    pending_dash = False
    for ch in s:
        if ch.isalnum():
            if pending_dash and out:
                out.append("-")
            pending_dash = False
            out.append(ch)
        else:
            pending_dash = True
    slug = "".join(out)
    if len(slug) > _MAX_SLUG:
        head = slug[: _MAX_SLUG + 1]
        cut = head.rfind("-")
        slug = head[:cut] if cut >= _MIN_WORD_CUT else slug[:_MAX_SLUG]
        slug = slug.strip("-")
    return slug or "untitled"


def unique_slug(base, taken):
    """Return base, or base-02, base-03, ... the first not in `taken` (compared case-insensitively).

    The collision number is zero-padded to two digits so names sort alphabetically (base, base-02, ..., base-10).
    """
    used = {t.lower() for t in taken}
    if base.lower() not in used:
        return base
    n = 2
    while f"{base}-{n:02d}".lower() in used:
        n += 1
    return f"{base}-{n:02d}"


def stems(directory, ext=".md"):
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return set()
    return {n[: -len(ext)] for n in names if n.endswith(ext)} if ext else set(names)


def main(argv):
    if len(argv) < 2 or argv[1] not in ("ulid", "slug"):
        print(__doc__, file=sys.stderr)
        return 2
    if argv[1] == "ulid":
        n = 1
        if "-n" in argv:
            n = int(argv[argv.index("-n") + 1])
        for _ in range(n):
            print(ulid())
        return 0
    if len(argv) < 3:
        print("slug needs a title", file=sys.stderr)
        return 2
    taken = set()
    if "--taken" in argv:
        taken |= {t for t in argv[argv.index("--taken") + 1].split(",") if t}
    if "--dir" in argv:
        ext = argv[argv.index("--ext") + 1] if "--ext" in argv else ".md"
        taken |= stems(argv[argv.index("--dir") + 1], ext)
    print(unique_slug(slugify(argv[2]), taken))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
