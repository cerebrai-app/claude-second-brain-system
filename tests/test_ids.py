"""ULIDs and slugs (plugins/brain/tools/brainctl/ids.py)."""

import pytest

from brainctl import ids


# ---- ULIDs ------------------------------------------------------------------------------------------------------------

def test_ulid_shape():
    u = ids.ulid()
    assert len(u) == 26
    assert set(u) <= set(ids._ALPHABET)


def test_ulid_zero_timestamp_prefix():
    assert ids.ulid(0).startswith("0" * 10)


def test_ulid_sorts_by_time():
    assert ids.ulid(1_000_000) < ids.ulid(1_000_001)


def test_ulid_monotonic_within_a_millisecond():
    xs = [ids.ulid(5_000_000) for _ in range(200)]
    assert xs == sorted(xs)
    assert len(set(xs)) == 200


def test_ulid_timestamp_out_of_range():
    with pytest.raises(ValueError):
        ids.ulid(1 << 48)


# ---- slugs ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("title, expected", [
    ("Draft Q4 plan", "draft-q4-plan"),
    ("2026-11-06", "2026-11-06"),                  # a date title is its own slug (journal file names)
    ("  Hello,   World!! ", "hello-world"),
    ("Café Münster", "café-münster"),              # Unicode letters are kept
    ("買い物 リスト", "買い物-リスト"),
    ("!!!", "untitled"),
    ("", "untitled"),
    ("Meeting 2", "meeting-2"),                    # numbers in a title are left as written
])
def test_slugify(title, expected):
    assert ids.slugify(title) == expected


def test_slugify_truncates_at_a_word_boundary():
    s = ids.slugify("word " * 30)
    assert len(s) <= 60
    assert not s.endswith("-")
    assert s.startswith("word-word")


def test_slugify_hard_cut_without_dashes():
    assert len(ids.slugify("x" * 100)) == 60


def test_unique_slug_suffixes_are_zero_padded():
    assert ids.unique_slug("a", set()) == "a"
    assert ids.unique_slug("a", {"a"}) == "a-02"
    assert ids.unique_slug("a", {"a", "a-02", "A-03"}) == "a-04"      # compared case-insensitively


def test_unique_slug_names_sort_alphabetically():
    taken, names = {"a"}, ["a"]
    for _ in range(12):
        s = ids.unique_slug("a", taken)
        taken.add(s)
        names.append(s)
    assert names == sorted(names)
    assert names[-1] == "a-13"


def test_stems_and_directory_collisions(tmp_path):
    for n in ("draft-q4-plan.md", "draft-q4-plan-02.md", "other.txt"):
        (tmp_path / n).write_text("")
    assert ids.stems(str(tmp_path)) == {"draft-q4-plan", "draft-q4-plan-02"}
    assert ids.unique_slug("draft-q4-plan", ids.stems(str(tmp_path))) == "draft-q4-plan-03"


def test_stems_of_a_missing_directory_is_empty():
    assert ids.stems("/nonexistent-dir-xyz") == set()


def test_cli_prints_ids_and_slugs(capsys):
    assert ids.main(["ids.py", "ulid", "-n", "2"]) == 0
    assert len(capsys.readouterr().out.split()) == 2
    assert ids.main(["ids.py", "slug", "Draft Q4 plan", "--taken", "draft-q4-plan"]) == 0
    assert capsys.readouterr().out.strip() == "draft-q4-plan-02"
