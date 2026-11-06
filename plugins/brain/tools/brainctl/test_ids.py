import os, tempfile, unittest
import ids


class UlidTests(unittest.TestCase):
    def test_shape(self):
        u = ids.ulid()
        self.assertEqual(len(u), 26)
        self.assertTrue(set(u) <= set(ids._ALPHABET))

    def test_known_timestamp_prefix(self):
        # 0 ms -> ten zero characters of timestamp
        self.assertTrue(ids.ulid(0).startswith("0" * 10))

    def test_sorts_by_time(self):
        a, b = ids.ulid(1_000_000), ids.ulid(1_000_001)
        self.assertLess(a, b)

    def test_monotonic_within_millisecond(self):
        xs = [ids.ulid(5_000_000) for _ in range(200)]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(set(xs)), 200)

    def test_range(self):
        with self.assertRaises(ValueError):
            ids.ulid(1 << 48)


class SlugTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(ids.slugify("Draft Q4 plan"), "draft-q4-plan")

    def test_date_title_is_itself(self):
        self.assertEqual(ids.slugify("2026-11-06"), "2026-11-06")

    def test_punctuation_and_spaces(self):
        self.assertEqual(ids.slugify("  Hello,   World!! "), "hello-world")

    def test_unicode_kept(self):
        self.assertEqual(ids.slugify("Café Münster"), "café-münster")
        self.assertEqual(ids.slugify("買い物 リスト"), "買い物-リスト")

    def test_empty_becomes_untitled(self):
        self.assertEqual(ids.slugify("!!!"), "untitled")
        self.assertEqual(ids.slugify(""), "untitled")

    def test_truncation(self):
        s = ids.slugify("word " * 30)
        self.assertLessEqual(len(s), 60)
        self.assertFalse(s.endswith("-"))
        self.assertTrue(s.startswith("word-word"))

    def test_truncation_without_dash(self):
        s = ids.slugify("x" * 100)
        self.assertEqual(len(s), 60)

    def test_unique(self):
        self.assertEqual(ids.unique_slug("a", set()), "a")
        self.assertEqual(ids.unique_slug("a", {"a"}), "a-02")
        self.assertEqual(ids.unique_slug("a", {"a", "a-02", "A-03"}), "a-04")

    def test_unique_sorts_alphabetically(self):
        taken = {"a"}
        names = ["a"]
        for _ in range(12):
            s = ids.unique_slug("a", taken)
            taken.add(s)
            names.append(s)
        self.assertEqual(names, sorted(names))
        self.assertEqual(names[-1], "a-13")

    def test_directory_stems(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("draft-q4-plan.md", "draft-q4-plan-02.md", "other.txt"):
                open(os.path.join(d, n), "w").close()
            self.assertEqual(ids.stems(d), {"draft-q4-plan", "draft-q4-plan-02"})
            self.assertEqual(ids.unique_slug("draft-q4-plan", ids.stems(d)), "draft-q4-plan-03")
        self.assertEqual(ids.stems("/nonexistent-dir-xyz"), set())


if __name__ == "__main__":
    unittest.main()
