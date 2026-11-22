"""Tests for beau-mode's sweep.py: which watched repos hold an artifact the kit generated.

sweep.py asks GitHub through the `gh` CLI. These tests give it a fake `gh` (a script that serves canned answers
keyed by the endpoint, and logs every call), selected through SWEEP_GH. Repo names are made up. Nothing here
touches the network.
"""
import base64
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/beau-mode/scripts/sweep.py"

FAKE_GH = f'''#!{sys.executable}
import json, os, sys
data = os.environ["FAKE_GH_DATA"]
args = sys.argv[1:]
with open(os.path.join(data, "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:1] != ["api"] or len(args) != 2:
    sys.stderr.write("fake gh only does `gh api ENDPOINT`\\n")
    sys.exit(2)
answers = json.load(open(os.path.join(data, "answers.json")))
answer = answers.get(args[1])
if answer is None:
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
if "error" in answer:
    sys.stderr.write(answer["error"])
    sys.exit(1)
sys.stdout.write(answer["raw"] if "raw" in answer else json.dumps(answer["out"]))
'''

HEADS = {"acme/widgets": "main", "acme/gadgets": "trunk", "acme/hidden": "main", "acme/empty": "main"}
SHAS = {slug: f"{i:040x}" for i, slug in enumerate(HEADS, 1)}
OLD_SHAS = {slug: f"{i + 100:040x}" for i, slug in enumerate(HEADS, 1)}


def blob(path):
    return {"path": path, "type": "blob"}


def repo_answers(slug, files, truncated=False, at=None):
    """The answers for one repo: its info, its head commit when asked `at`, and the tree at the commit read."""
    ref = HEADS[slug] if at is None else OLD_SHAS[slug]
    out = {f"repos/{slug}": {"out": {"default_branch": HEADS[slug]}},
           f"repos/{slug}/git/trees/{ref}?recursive=1": {"out": {"tree": [blob(p) for p in files], "truncated": truncated}}}
    if at is not None:
        out[f"repos/{slug}/commits?sha={HEADS[slug]}&until={at}T23:59:59Z&per_page=1"] = {"out": [{"sha": OLD_SHAS[slug]}]}
    return out


def content(slug, path, text, ref=None):
    ref = ref or HEADS[slug]
    return {f"repos/{slug}/contents/{path}?ref={ref}": {"out": {"type": "file", "encoding": "base64",
                                                               "content": base64.b64encode(text.encode()).decode()}}}


WIDGET_FILES = ["docs/phases/p1.md", "docs/phases/p2.md", "docs/phases/notes/deep.md", "README.md",
                ".claude/skills/verify-widgets/SKILL.md", ".claude/skills/other/SKILL.md", "REVIEW.md"]
GADGET_FILES = ["docs/phases/p1.md", ".agents/skills/verify-gadgets/SKILL.md", "src/REVIEW.md"]


class SweepCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.books = self.dir / "books-dir"
        (self.books / "books").mkdir(parents=True)
        self.data = self.dir / "gh-data"
        self.data.mkdir()
        gh = self.dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.gh = str(gh)
        self.answers = {}
        self.write_books({"widgets": "acme/widgets", "gadgets": "acme/gadgets", "hidden": "acme/hidden", "empty": "acme/empty"},
                         {"widgets": "public", "gadgets": "public", "hidden": "private", "empty": "public"})

    def write_books(self, watched, visibility, extra_repos_rows=()):
        (self.books / "books/watched.csv").write_text(
            "repo,github,workflow\n" + "".join(f"{r},{g},ci\n" for r, g in watched.items()))
        if visibility is not None:
            (self.books / "books/repos.csv").write_text(
                "seen,repo,github,visibility\n"
                + "".join(f"2026-11-01T00:00:00Z,{r},{watched[r]},{v}\n" for r, v in visibility.items())
                + "".join(f"{row}\n" for row in extra_repos_rows))

    def serve(self, *answer_sets):
        for a in answer_sets:
            self.answers.update(a)

    def standard(self):
        self.serve(repo_answers("acme/widgets", WIDGET_FILES), repo_answers("acme/gadgets", GADGET_FILES),
                   repo_answers("acme/hidden", ["docs/phases/secret-plan.md", "REVIEW.md"]), repo_answers("acme/empty", ["README.md"]))

    def run_sweep(self, *args, gh=None, path=None):
        (self.data / "answers.json").write_text(json.dumps(self.answers))
        (self.data / "calls.log").write_text("")
        env = {**os.environ, "FAKE_GH_DATA": str(self.data), "SWEEP_GH": gh or self.gh}
        if path is not None:
            env["PATH"] = path
            env.pop("SWEEP_GH", None)
        done = subprocess.run([sys.executable, str(SCRIPT), str(self.books), *args], capture_output=True, env=env, timeout=60)
        self.calls = [json.loads(line) for line in (self.data / "calls.log").read_text().splitlines()]
        return done.returncode, done.stdout.decode(), done.stderr.decode()


class HoldersTest(SweepCase):
    def test_each_artifact_is_found_by_its_globs(self):
        self.standard()
        code, out, err = self.run_sweep("--artifact", "phase-spec")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "widgets (acme/widgets): phase-spec: 2 file(s): docs/phases/p1.md, docs/phases/p2.md",
            "gadgets (acme/gadgets): phase-spec: 1 file(s): docs/phases/p1.md",
            "hidden (acme/hidden): phase-spec: 1 file(s): docs/phases/secret-plan.md",
            "sweep: 3 of 4 watched repos hold phase-spec"])
        _, out, _ = self.run_sweep("--artifact", "verify-skill")
        self.assertEqual(out.splitlines(), [
            "widgets (acme/widgets): verify-skill: 1 file(s): .claude/skills/verify-widgets/SKILL.md",
            "gadgets (acme/gadgets): verify-skill: 1 file(s): .agents/skills/verify-gadgets/SKILL.md",
            "sweep: 2 of 4 watched repos hold verify-skill"])
        _, out, _ = self.run_sweep("--artifact", "review")
        self.assertEqual(out.splitlines(), [
            "widgets (acme/widgets): review: 1 file(s): REVIEW.md",
            "hidden (acme/hidden): review: 1 file(s): REVIEW.md",
            "sweep: 2 of 4 watched repos hold review"])

    def test_several_artifacts_make_a_line_each_and_a_repo_counts_once(self):
        self.standard()
        _, out, _ = self.run_sweep("--artifact", "review", "--artifact", "verify-skill")
        self.assertEqual(out.splitlines()[:3], [
            "widgets (acme/widgets): review: 1 file(s): REVIEW.md",
            "widgets (acme/widgets): verify-skill: 1 file(s): .claude/skills/verify-widgets/SKILL.md",
            "gadgets (acme/gadgets): verify-skill: 1 file(s): .agents/skills/verify-gadgets/SKILL.md"])
        self.assertEqual(out.splitlines()[-1], "sweep: 3 of 4 watched repos hold review, verify-skill")

    def test_a_repo_with_none_is_not_listed(self):
        self.standard()
        _, out, _ = self.run_sweep("--artifact", "phase-spec")
        self.assertNotIn("empty", out)

    def test_it_reads_no_file_content_without_containing(self):
        self.standard()
        self.run_sweep("--artifact", "phase-spec")
        self.assertEqual([c for c in self.calls if "/contents/" in c[1]], [])

    def test_it_never_calls_gh_auth(self):
        self.standard()
        self.run_sweep("--artifact", "phase-spec")
        self.assertTrue(self.calls)
        self.assertTrue(all(c[0] == "api" for c in self.calls), self.calls)

    def test_json_prints_the_holders_as_a_list(self):
        self.standard()
        code, out, err = self.run_sweep("--artifact", "review", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [
            {"repo": "widgets", "github": "acme/widgets", "artifact": "review", "count": 1, "files": ["REVIEW.md"]},
            {"repo": "hidden", "github": "acme/hidden", "artifact": "review", "count": 1, "files": ["REVIEW.md"]}])
        self.assertIn("sweep: 2 of 4 watched repos hold review", err)


class ContainingTest(SweepCase):
    def test_only_files_whose_content_matches_are_kept(self):
        self.standard()
        self.serve(content("acme/widgets", "docs/phases/p1.md", "# P1\n\n## Acceptance\n- [ ] a\n"),
                   content("acme/widgets", "docs/phases/p2.md", "# P2\n\n## Done\n"),
                   content("acme/gadgets", "docs/phases/p1.md", "## Ideal state\n"),
                   content("acme/hidden", "docs/phases/secret-plan.md", "## Acceptance\n"))
        code, out, _ = self.run_sweep("--artifact", "phase-spec", "--containing", "^## Acceptance")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "widgets (acme/widgets): phase-spec: 1 file(s): docs/phases/p1.md",
            "hidden (acme/hidden): phase-spec: 1 file(s): docs/phases/secret-plan.md",
            "sweep: 2 of 4 watched repos hold phase-spec"])
        fetched = [c[1] for c in self.calls if "/contents/" in c[1]]
        self.assertEqual(len(fetched), 4)
        self.assertFalse(any("README" in f or "other" in f for f in fetched))

    def test_a_file_gh_cannot_return_fails_the_repo_not_silently_partial(self):
        self.standard()
        self.serve(content("acme/widgets", "docs/phases/p1.md", "## Acceptance\n"))
        self.answers["repos/acme/widgets/contents/docs/phases/p2.md?ref=main"] = {"out": {"type": "file", "encoding": "none", "content": ""}}
        code, out, err = self.run_sweep("--artifact", "phase-spec", "--containing", "Acceptance")
        self.assertEqual(code, 1)
        self.assertNotIn("widgets (", out)
        self.assertIn("FAILED widgets:", err)


class AtTest(SweepCase):
    def test_at_reads_the_newest_commit_by_the_end_of_that_day(self):
        self.serve(repo_answers("acme/widgets", ["docs/phases/old.md"], at="2026-11-16"))
        self.answers["repos/acme/widgets/git/trees/main?recursive=1"] = {"out": {"tree": [blob("docs/phases/new.md")]}}
        self.write_books({"widgets": "acme/widgets"}, {"widgets": "public"})
        code, out, _ = self.run_sweep("--artifact", "phase-spec", "--at", "2026-11-16")
        self.assertEqual(code, 0)
        self.assertIn("docs/phases/old.md", out)
        self.assertNotIn("new.md", out)
        self.assertIn(["api", "repos/acme/widgets/commits?sha=main&until=2026-11-16T23:59:59Z&per_page=1"], self.calls)

    def test_a_repo_with_no_commit_by_that_day_holds_nothing_and_is_not_a_failure(self):
        self.serve(repo_answers("acme/widgets", ["docs/phases/new.md"], at="2026-11-16"))
        self.answers["repos/acme/widgets/commits?sha=main&until=2026-11-16T23:59:59Z&per_page=1"] = {"out": []}
        self.write_books({"widgets": "acme/widgets"}, {"widgets": "public"})
        code, out, err = self.run_sweep("--artifact", "phase-spec", "--at", "2026-11-16")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "sweep: 0 of 1 watched repos hold phase-spec\n")


class PublicOnlyTest(SweepCase):
    def test_a_private_repo_is_never_named_and_none_of_its_paths_print(self):
        self.standard()
        code, out, err = self.run_sweep("--artifact", "phase-spec", "--public-only")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "widgets (acme/widgets): phase-spec: 2 file(s): docs/phases/p1.md, docs/phases/p2.md",
            "gadgets (acme/gadgets): phase-spec: 1 file(s): docs/phases/p1.md",
            "sweep: 2 of 3 public watched repos hold phase-spec",
            "1 private repo(s) hold one; run without --public-only to see them"])
        for text in (out, err):
            self.assertNotIn("hidden", text)
            self.assertNotIn("secret-plan", text)

    def test_json_keeps_private_repos_out_too(self):
        self.standard()
        code, out, err = self.run_sweep("--artifact", "phase-spec", "--public-only", "--json")
        self.assertEqual(code, 0)
        self.assertEqual({h["repo"] for h in json.loads(out)}, {"widgets", "gadgets"})
        self.assertNotIn("hidden", out + err)
        self.assertIn("1 private repo(s) hold one", err)

    def test_a_private_repos_failure_line_does_not_name_it(self):
        self.standard()
        self.answers["repos/acme/hidden"] = {"error": "gh: Not Found for acme/hidden (HTTP 404)\n"}
        code, out, err = self.run_sweep("--artifact", "phase-spec", "--public-only")
        self.assertEqual(code, 1)
        self.assertNotIn("hidden", out + err)
        self.assertIn("FAILED a private repo", err)
        code, _, err = self.run_sweep("--artifact", "phase-spec")
        self.assertIn("FAILED hidden:", err)

    def test_it_needs_repos_csv(self):
        self.standard()
        (self.books / "books/repos.csv").unlink()
        code, out, err = self.run_sweep("--artifact", "phase-spec", "--public-only")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("books/repos.csv", err)
        code, _, _ = self.run_sweep("--artifact", "phase-spec")
        self.assertEqual(code, 0)

    def test_the_rule_is_quality_pys(self):
        """No row, an `unknown` latest row, a row that once said private, and two slugs for one name are all private."""
        self.write_books({"a": "acme/widgets", "b": "acme/gadgets", "c": "acme/hidden", "d": "acme/empty", "e": "acme/other"},
                         {"a": "public", "b": "public", "c": "public", "d": "public"},
                         extra_repos_rows=["2026-11-02T00:00:00Z,b,acme/gadgets,unknown", "2026-11-03T00:00:00Z,b,acme/gadgets,public",
                                           "2026-11-02T00:00:00Z,c,acme/hidden,private", "2026-11-03T00:00:00Z,c,acme/hidden,public"])
        (self.books / "books/runs.csv").write_text(
            "started,repo,sha,event,workflow,python,tests,failed,skipped,wall_ms,exit_code,evidence\n"
            "2026-11-01T00:00:00Z,d,abc,push,ci,3.12,1,0,0,1,0,https://github.com/acme/elsewhere/actions/runs/1/attempts/1\n")
        self.serve(*(repo_answers(s, ["REVIEW.md"]) for s in ("acme/widgets", "acme/gadgets", "acme/hidden", "acme/empty")),
                   {"repos/acme/other": {"out": {"default_branch": "main"}},
                    "repos/acme/other/git/trees/main?recursive=1": {"out": {"tree": [blob("REVIEW.md")]}}})
        code, out, _ = self.run_sweep("--artifact", "review", "--public-only")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "a (acme/widgets): review: 1 file(s): REVIEW.md")
        self.assertEqual(out.splitlines()[1], "b (acme/gadgets): review: 1 file(s): REVIEW.md")
        self.assertIn("sweep: 2 of 2 public watched repos hold review", out)
        self.assertIn("3 private repo(s) hold one", out)


class FailureTest(SweepCase):
    def test_a_failed_lookup_exits_1_and_the_others_are_still_listed(self):
        self.standard()
        self.answers["repos/acme/gadgets"] = {"error": "gh: Server Error (HTTP 500)\n"}
        code, out, err = self.run_sweep("--artifact", "review")
        self.assertEqual(code, 1)
        self.assertEqual(err, "FAILED gadgets: gh api failed: gh: Server Error (HTTP 500)\n")
        self.assertIn("widgets (acme/widgets): review", out)
        self.assertNotIn("gadgets (", out)

    def test_a_truncated_tree_is_a_failure_not_a_partial_answer(self):
        self.standard()
        self.serve(repo_answers("acme/widgets", WIDGET_FILES, truncated=True))
        code, out, err = self.run_sweep("--artifact", "review")
        self.assertEqual(code, 1)
        self.assertIn("FAILED widgets: the file tree is too big", err)
        self.assertNotIn("widgets (", out)

    def test_answers_of_the_wrong_shape_fail_the_repo_without_a_traceback(self):
        self.standard()
        self.answers["repos/acme/widgets"] = {"raw": "not json"}
        self.answers["repos/acme/gadgets"] = {"out": ["a list"]}
        self.answers["repos/acme/hidden/git/trees/main?recursive=1"] = {"out": {"tree": [None, 5, {"path": 7, "type": "blob"}, blob("REVIEW.md")]}}
        code, out, err = self.run_sweep("--artifact", "review")
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertIn("FAILED widgets: gh api did not answer with JSON", err)
        self.assertIn("FAILED gadgets: gh did not name a default branch", err)
        self.assertIn("hidden (acme/hidden): review", out)


class UsageTest(SweepCase):
    def test_missing_books_files(self):
        self.standard()
        (self.books / "books/watched.csv").unlink()
        code, out, err = self.run_sweep("--artifact", "review")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("books/watched.csv", err)
        self.books = self.dir / "nowhere"
        code, out, err = self.run_sweep("--artifact", "review")
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err)

    def test_a_watched_file_with_the_wrong_header_is_refused(self):
        (self.books / "books/watched.csv").write_text("repo,workflow\nwidgets,ci\n")
        code, _, err = self.run_sweep("--artifact", "review")
        self.assertEqual(code, 2)
        self.assertIn("header", err)

    def test_bad_arguments_exit_2(self):
        self.standard()
        for args in ([], ["--artifact", "nonesuch"], ["--artifact", "review", "--at", "2026-13-01"],
                     ["--artifact", "review", "--at", "yesterday"], ["--artifact", "review", "--containing", "("],
                     ["--artifact", "review", "--nonesuch"]):
            with self.subTest(args=args):
                code, out, err = self.run_sweep(*args)
                self.assertEqual((code, out), (2, ""))
                self.assertNotIn("Traceback", err)
                self.assertTrue(err)

    def test_no_gh_exits_2(self):
        self.standard()
        code, out, err = self.run_sweep("--artifact", "review", path=str(self.dir / "empty-path"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cannot find the gh CLI", err)


class HostileInputTest(SweepCase):
    def test_control_characters_in_paths_and_errors_never_reach_the_output(self):
        evil = "docs/phases/a\x1b[31mred\x1b]0;title\x07‮evil\nline.md"
        self.standard()
        self.serve(repo_answers("acme/widgets", [evil, "docs/phases/ok.md"]))
        self.answers["repos/acme/gadgets"] = {"error": "boom \x1b[2J\x00 forged\nFAILED other: x\n"}
        code, out, err = self.run_sweep("--artifact", "phase-spec")
        self.assertEqual(code, 1)
        for text in (out, err):
            self.assertIsNone(re.search("[\x00-\x09\x0b-\x1f\x7f-\x9f‮]", text), repr(text))
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn("2 file(s)", out)
        code, out, _ = self.run_sweep("--artifact", "phase-spec", "--json")
        self.assertIsNone(re.search("[\x00-\x09\x0b-\x1f\x7f-\x9f‮]", out))

    def test_a_huge_listing_is_capped_in_the_output(self):
        files = [f"docs/phases/p{i}.md" for i in range(1500)]
        self.write_books({"widgets": "acme/widgets"}, {"widgets": "public"})
        self.serve(repo_answers("acme/widgets", files))
        _, out, _ = self.run_sweep("--artifact", "phase-spec")
        first = out.splitlines()[0]
        self.assertIn("1000 file(s)", first)
        self.assertIn("and 980 more", first)

    def test_an_invalid_slug_in_the_books_is_never_passed_to_gh(self):
        self.write_books({"widgets": "acme/widgets/../../user"}, {"widgets": "public"})
        code, _, err = self.run_sweep("--artifact", "review")
        self.assertEqual(code, 1)
        self.assertIn("FAILED widgets: the books name no valid OWNER/NAME", err)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
