"""Tests for `quality.py sweep` (plugins/bstack/skills/qualitydirector/scripts/quality.py).

Every repo, path and sha here is made up. The books watch two public repos and one private one, and GitHub is the fake `gh` of
test_quality_fetch, which serves canned answers and logs every call. Nothing reads the network or the clock.
"""
import json
import os
import stat
import unittest.mock

import test_quality_fetch as tf
import test_quality_visibility as tv

quality = tf.quality
SECRET, OPEN, PLAIN = ("secret-app", "acme/secret-app"), ("open-lib", "acme/open-lib"), ("plain-lib", "acme/plain-lib")
STAMP = "2026-11-20T10:00:00Z"
SHA_NOW, SHA_THEN = "a" * 40, "b" * 40
PRIVATE_LINE = ("1 private watched repo was not checked and is not named here. "
                "Check with --with-private, and keep that answer out of public text.")


def listing(*paths: str, sha: str = SHA_NOW, truncated: bool = False) -> dict:
    return {"sha": sha, "truncated": truncated, "tree": [{"path": p, "type": "blob"} for p in paths]}


class SweepCase(tv.TempCase):
    def setUp(self):
        super().setUp()
        self.builder = tv.Builder(SECRET, OPEN, PLAIN)
        for (repo, slug), value in ((SECRET, "private"), (OPEN, "public"), (PLAIN, "public")):
            self.builder.visibility(STAMP, repo, slug, value)
        self.builder.write(self.books)
        self.data = self.tmp / "data"
        (self.data / "api").mkdir(parents=True)
        gh = self.tmp / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text(tf.FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        patcher = unittest.mock.patch.dict(os.environ, {"QUALITY_GH": str(gh), "FAKE_GH_DATA": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tree("acme/open-lib", listing("README.md", "docs/phases/P1-core.md", "docs/phases/P2-sync.md", "docs/phases/notes/draft.md",
                                           ".agents/skills/verify-open-lib/SKILL.md", ".agents/skills/other/SKILL.md"))
        self.tree("acme/plain-lib", listing("README.md", "docs/REVIEW.md"))
        self.tree("acme/secret-app", listing("docs/phases/P1-hidden.md", "REVIEW.md"))

    def put(self, endpoint: str, value, suffix: str = "json") -> None:
        data = value if isinstance(value, str) else tf.dumps(value)
        (self.data / "api" / (endpoint.replace("/", "__") + "." + suffix)).write_text(data)

    def tree(self, slug: str, value, ref: str = "HEAD") -> None:
        self.put(f"repos/{slug}/git/trees/{ref}", value)

    def endpoints(self) -> list[str]:
        log = self.data / "calls.log"
        return [json.loads(line)[-1] for line in log.read_text().splitlines()] if log.exists() else []

    def sweep(self, *argv) -> tuple[int, str]:
        return tf.cli("sweep", self.books, *argv)


class PublicListTest(SweepCase):
    def test_it_lists_the_public_repo_that_holds_one_and_says_which_holds_none(self):
        self.assertEqual(self.sweep("phase-spec"), (0, "\n".join((
            "sweep phase-spec: 1 of 2 public watched repos held docs/phases/*.md on the default branch today",
            "- acme/open-lib: docs/phases/P1-core.md, docs/phases/P2-sync.md",
            "none: acme/plain-lib",
            PRIVATE_LINE)) + "\n"))

    def test_each_kind_matches_only_where_its_generator_writes(self):
        code, out = self.sweep("verify-skill")
        self.assertEqual((code, out.splitlines()[1]), (0, "- acme/open-lib: .agents/skills/verify-open-lib/SKILL.md"))
        code, out = self.sweep("review-guide")
        self.assertEqual((code, out.splitlines()[:3]), (0, [
            "sweep review-guide: 0 of 2 public watched repos held REVIEW.md on the default branch today",
            "none: acme/open-lib", "none: acme/plain-lib"]))

    def test_more_paths_than_are_shown_are_counted(self):
        self.tree("acme/open-lib", listing(*(f"docs/phases/P{n}-x.md" for n in range(1, 6))))
        self.assertIn("- acme/open-lib: docs/phases/P1-x.md, docs/phases/P2-x.md, docs/phases/P3-x.md and 2 more\n", self.sweep("phase-spec")[1])

    def test_json_holds_every_path(self):
        code, out = self.sweep("phase-spec", "--json")
        report = json.loads(out)
        self.assertEqual((code, report["private_not_checked"], report["with_private"], report["at"]), (0, 1, False, None))
        self.assertEqual(report["repos"], [
            {"github": "acme/open-lib", "state": "holds", "paths": ["docs/phases/P1-core.md", "docs/phases/P2-sync.md"], "commit": SHA_NOW, "why": ""},
            {"github": "acme/plain-lib", "state": "none", "paths": [], "commit": SHA_NOW, "why": ""}])

    def test_an_unknown_kind_is_a_usage_error(self):
        self.assertEqual(self.sweep("changelog")[0], 2)
        self.assertEqual(self.endpoints(), [])


class PrivateRepoTest(SweepCase):
    """The list goes into a PR on a public repo: a private repo is not asked about and nothing of it is printed."""

    def assert_nothing_private(self, out: str) -> None:
        for word in ("secret", "hidden"):
            self.assertNotIn(word, out.lower())

    def test_a_private_repo_is_never_asked_about_or_named(self):
        for flags in ((), ("--json",), ("--at", "2026-11-16")):
            self.put("repos/acme/open-lib/commits", [{"sha": SHA_THEN}])
            self.put("repos/acme/plain-lib/commits", [])
            self.tree("acme/open-lib", listing(sha=SHA_THEN), ref=SHA_THEN)
            _, out = self.sweep("phase-spec", *flags)
            self.assert_nothing_private(out)
        self.assert_nothing_private("\n".join(self.endpoints()))

    def test_nothing_private_is_printed_when_every_call_fails(self):
        for slug in ("acme/open-lib", "acme/plain-lib", "acme/secret-app"):
            self.put(f"repos/{slug}/git/trees/HEAD", f"gh: could not reach {slug}", suffix="error")
        code, out = self.sweep("phase-spec")
        self.assertEqual(code, 1)
        self.assert_nothing_private(out)

    def test_a_repo_with_no_visibility_row_or_a_failed_lookup_counts_as_private(self):
        for rows in ([(OPEN, "public")], [(OPEN, "public"), (PLAIN, "unknown")], [(OPEN, "public"), (PLAIN, "private"), (PLAIN, "public")]):
            builder = tv.Builder(OPEN, PLAIN)
            for n, ((repo, slug), value) in enumerate(rows):
                builder.visibility(f"2026-11-2{n}T10:00:00Z", repo, slug, value)
            builder.write(self.books)
            (self.data / "calls.log").unlink(missing_ok=True)
            code, out = self.sweep("phase-spec")
            self.assertEqual((code, out.splitlines()[0]), (0, "sweep phase-spec: 1 of 1 public watched repos held docs/phases/*.md on the default branch today"))
            self.assertNotIn("plain-lib", out + "\n".join(self.endpoints()))

    def test_books_without_visibility_are_refused_before_any_call(self):
        (self.books / quality.REPOS).unlink()
        code, out = self.sweep("phase-spec")
        self.assertEqual(code, 2)
        self.assertIn("sweep needs books/repos.csv", out)
        self.assertEqual(self.endpoints(), [])

    def test_with_private_names_them_under_a_warning(self):
        code, out = self.sweep("phase-spec", "--with-private")
        self.assertEqual((code, out.splitlines()), (0, [
            quality.SWEEP_PRIVATE_BANNER,
            "sweep phase-spec: 2 of 3 watched repos held docs/phases/*.md on the default branch today",
            "- acme/open-lib: docs/phases/P1-core.md, docs/phases/P2-sync.md",
            "- acme/secret-app (private): docs/phases/P1-hidden.md",
            "none: acme/plain-lib"]))
        report = json.loads(self.sweep("phase-spec", "--with-private", "--json")[1])
        self.assertEqual([(r["github"], r["private"]) for r in report["repos"]],
                         [("acme/open-lib", False), ("acme/plain-lib", False), ("acme/secret-app", True)])


class UnknownIsNotNoneTest(SweepCase):
    def test_a_failed_call_is_could_not_check_and_exits_1(self):
        self.put("repos/acme/plain-lib/git/trees/HEAD", "gh: Server Error (HTTP 502)", suffix="error")
        code, out = self.sweep("phase-spec")
        self.assertEqual(code, 1)
        self.assertIn("- acme/open-lib: docs/phases/P1-core.md", out)
        self.assertIn("could not check: acme/plain-lib (gh api repos/acme/plain-lib/git/trees/HEAD failed: gh: Server Error (HTTP 502))", out)
        self.assertNotIn("none:", out)

    def test_a_file_list_cut_short_with_no_match_is_could_not_check(self):
        self.tree("acme/plain-lib", listing("README.md", truncated=True))
        code, out = self.sweep("phase-spec")
        self.assertEqual(code, 1)
        self.assertIn("could not check: acme/plain-lib (GitHub cut the file list short, so a missing match proves nothing)", out)

    def test_a_file_list_cut_short_with_a_match_still_holds(self):
        self.tree("acme/open-lib", listing("docs/phases/P1-core.md", truncated=True))
        code, out = self.sweep("phase-spec")
        self.assertEqual(code, 0)
        self.assertIn("- acme/open-lib: docs/phases/P1-core.md\n", out)

    def test_an_answer_that_is_not_a_file_list_is_could_not_check(self):
        for answer in ("not json", [], {"sha": SHA_NOW}, {"tree": [], "truncated": False}):
            self.tree("acme/plain-lib", answer)
            code, out = self.sweep("phase-spec")
            self.assertEqual(code, 1, answer)
            self.assertIn("could not check: acme/plain-lib", out)

    def test_books_that_fail_check_are_refused(self):
        with open(self.books / quality.REPOS, "a") as f:
            f.write("not,a,row\n")
        self.assertEqual(self.sweep("phase-spec")[0], 2)
        self.assertEqual(self.endpoints(), [])


class AtADayTest(SweepCase):
    """`--at DAY` replays a past change: the tree of the last commit by the end of that day, not today's."""

    def setUp(self):
        super().setUp()
        self.put("repos/acme/open-lib/commits", [{"sha": SHA_THEN}])
        self.tree("acme/open-lib", listing("docs/phases/P1-core.md", sha=SHA_THEN), ref=SHA_THEN)
        self.put("repos/acme/plain-lib/commits", [])

    def test_it_reads_the_commit_of_that_day_and_names_it(self):
        self.assertEqual(self.sweep("phase-spec", "--at", "2026-11-16"), (0, "\n".join((
            "sweep phase-spec: 1 of 2 public watched repos held docs/phases/*.md on the default branch on 2026-11-16",
            "- acme/open-lib: docs/phases/P1-core.md (commit bbbbbbb)",
            "none: acme/plain-lib (no commit by 2026-11-16)",
            PRIVATE_LINE)) + "\n"))
        self.assertEqual(self.endpoints(), [
            "repos/acme/open-lib/commits?until=2026-11-16T23:59:59Z&per_page=1", f"repos/acme/open-lib/git/trees/{SHA_THEN}?recursive=1",
            "repos/acme/plain-lib/commits?until=2026-11-16T23:59:59Z&per_page=1"])

    def test_a_commit_listing_that_names_no_commit_is_could_not_check(self):
        for answer in ({"sha": SHA_THEN}, [{"sha": "HEAD"}], [7]):
            self.put("repos/acme/open-lib/commits", answer)
            code, out = self.sweep("phase-spec", "--at", "2026-11-16")
            self.assertEqual(code, 1, answer)
            self.assertIn("could not check: acme/open-lib", out)

    def test_a_day_that_is_not_a_date_is_a_usage_error(self):
        self.assertEqual(self.sweep("phase-spec", "--at", "last week")[0], 2)


class GlobTest(unittest.TestCase):
    def test_a_star_stays_inside_one_folder(self):
        for path, glob, expected in (("docs/phases/P1-a.md", "docs/phases/*.md", True), ("docs/phases/old/P1-a.md", "docs/phases/*.md", False),
                                     ("docs/phases", "docs/phases/*.md", False), ("sub/REVIEW.md", "REVIEW.md", False),
                                     ("docs/Phases/P1-a.md", "docs/phases/*.md", False),
                                     (".claude/skills/verify-x/SKILL.md", ".claude/skills/verify-*/SKILL.md", True)):
            self.assertEqual(quality.glob_segments_match(path, glob), expected, (path, glob))


if __name__ == "__main__":
    unittest.main()
