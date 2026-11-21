"""Tests for verify-work's checklist.py: the items whose trigger matches a diff, and no others."""
import contextlib
import datetime
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/verify-work/scripts/checklist.py"
spec = importlib.util.spec_from_file_location("checklist", SCRIPT)
checklist = importlib.util.module_from_spec(spec)
sys.modules["checklist"] = checklist
spec.loader.exec_module(checklist)

TODAY = datetime.date(2026, 11, 21)


def item(item_id, paths, pattern=None, check=None, **over):
    trigger = {"paths": paths}
    if pattern is not None:
        trigger["pattern"] = pattern
    return {"id": item_id, "trigger": trigger, "check": check or {"command": "make test"},
            "source": "made up", "added": "2026-11-01", "review_by": "2027-02-01", **over}


ITEMS = [
    item("layout", ["src/books.py"], r"^\s*SCHEMA\s*="),
    item("plugins", ["plugins/**"]),
    item("cli-call", ["src/**", "docs/*.md"], r"^\s*tool\s+[a-z]|\btool login\b",
         check={"question": "Does it work signed out?", "probe": "Run it with no login."}),
]


class Repo(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        self.write("src/books.py", 'SCHEMA = ("a", "b")\nprint(1)\n')
        self.write("docs/guide.md", "# Guide\n")
        self.write("plugins/p/skills/s/SKILL.md", "---\nname: s\n---\n")
        self.write(".agents/checklist.json", json.dumps({"version": 1, "items": ITEMS}))
        self.commit("base")
        self.git("checkout", "-q", "-b", "change")

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo,
                              check=True, capture_output=True, text=True).stdout

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def run_cli(self, *args, today=TODAY):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = checklist.main(["--root", str(self.repo), *args], today=today)
        return code, out.getvalue(), err.getvalue()

    def fired(self, *args):
        code, out, err = self.run_cli("--base", "main", "--json", *args)
        self.assertEqual(code, 0, err)
        return {f["id"]: f["fired"] for f in json.loads(out)}


class MatchingTest(Repo):
    def test_a_docs_only_change_prints_nothing(self):
        self.write("docs/guide.md", "# Guide\n\nMore words.\n")
        self.commit("docs")
        code, out, err = self.run_cli("--base", "main")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("0 of 3 items match", err)

    def test_a_pattern_item_fires_on_a_changed_line_and_says_where(self):
        self.write("src/books.py", 'SCHEMA = ("a", "c")\nprint(1)\n')
        self.commit("layout")
        fired = self.fired()
        self.assertEqual(list(fired), ["layout"])
        self.assertEqual(fired["layout"]["path"], "src/books.py")
        self.assertEqual(fired["layout"]["line"], 1)

    def test_a_pattern_item_stays_quiet_when_its_file_changes_elsewhere(self):
        self.write("src/books.py", 'SCHEMA = ("a", "b")\nprint(2)\n')
        self.commit("other line")
        self.assertEqual(self.fired(), {})

    def test_a_removed_line_fires_a_pattern(self):
        self.write("src/books.py", "print(1)\n")
        self.commit("drop the schema")
        self.assertEqual(self.fired()["layout"]["sign"], "-")

    def test_a_pattern_is_not_matched_outside_the_items_paths(self):
        self.write("notes.txt", "tool login\n")
        self.commit("elsewhere")
        self.assertEqual(self.fired(), {})

    def test_a_command_at_the_start_of_a_line_fires_and_a_mention_in_prose_does_not(self):
        self.write("docs/guide.md", "# Guide\n\nDownload it (`tool fetch` gives a folder).\n")
        self.commit("prose")
        self.assertEqual(self.fired(), {})
        self.write("docs/guide.md", "# Guide\n\n```sh\ntool fetch\n```\n")
        self.commit("command")
        self.assertEqual(self.fired()["cli-call"]["text"], "tool fetch")

    def test_a_paths_item_fires_on_any_file_under_the_glob_and_counts_the_rest(self):
        self.write("plugins/p/skills/s/SKILL.md", "---\nname: s\n---\nbody\n")
        self.write("plugins/p/plugin.json", "{}\n")
        self.commit("plugin")
        self.assertEqual(self.fired()["plugins"], {"path": "plugins/p/plugin.json", "more_paths": 1})

    def test_the_working_tree_counts_uncommitted_and_untracked_files(self):
        self.write("src/books.py", 'SCHEMA = ("a", "c")\nprint(1)\n')
        self.write("src/new.py", "import os\ntool login\n")
        fired = self.fired()
        self.assertEqual(set(fired), {"layout", "cli-call"})
        self.assertEqual((fired["cli-call"]["path"], fired["cli-call"]["line"]), ("src/new.py", 2))

    def test_head_reads_that_commit_and_not_the_working_tree(self):
        self.write("docs/guide.md", "# Guide\n\nwords\n")
        self.commit("docs")
        self.write("src/books.py", 'SCHEMA = ("a", "c")\n')
        self.assertEqual(self.fired("--head", "HEAD"), {})
        self.assertEqual(set(self.fired()), {"layout"})

    def test_commits_that_landed_on_the_base_since_the_branch_do_not_count(self):
        self.git("checkout", "-q", "main")
        self.write("plugins/p/plugin.json", "{}\n")
        self.commit("someone else's work")
        self.git("checkout", "-q", "change")
        self.assertEqual(self.fired(), {})

    def test_a_removed_line_that_looks_like_a_file_header_is_read_as_a_line(self):
        self.write("src/q.sql", "-- tool login\nselect 1;\n")
        self.commit("sql")
        self.git("branch", "-f", "main", "HEAD")
        self.write("src/q.sql", "select 1;\n")
        self.commit("drop the comment")
        self.assertEqual(self.fired()["cli-call"], {"path": "src/q.sql", "more_paths": 0, "line": 1, "sign": "-",
                                                     "text": "-- tool login"})


class OutputTest(Repo):
    def test_text_output_carries_the_check_the_source_and_the_dates(self):
        self.write("src/new.py", "tool login\n")
        code, out, _ = self.run_cli("--base", "main")
        self.assertEqual(code, 0)
        self.assertEqual(out, "cli-call\n"
                              "  fired on: src/new.py:1: +tool login\n"
                              "  question: Does it work signed out?\n"
                              "  probe: Run it with no login.\n"
                              "  source: made up\n"
                              "  added 2026-11-01, review by 2027-02-01\n")

    def test_an_item_past_its_review_date_says_so(self):
        self.write("plugins/p/x", "x\n")
        _, out, _ = self.run_cli("--base", "main", today=datetime.date(2027, 2, 2))
        self.assertIn("review by 2027-02-01 (overdue: confirm it still earns its place, or delete it)", out)
        _, out, _ = self.run_cli("--base", "main", today=datetime.date(2027, 2, 1))
        self.assertNotIn("overdue", out)

    def test_a_matched_line_cannot_write_control_characters_to_the_terminal(self):
        self.write("src/new.py", "tool login \x1b[2J" + "x" * 400 + "\n")
        _, out, _ = self.run_cli("--base", "main")
        self.assertNotIn("\x1b", out)
        self.assertLess(max(len(row) for row in out.splitlines()), 220)


class RefusalTest(Repo):
    def refused(self, *args):
        code, out, err = self.run_cli(*args)
        self.assertEqual((code, out), (2, ""), err)
        return err

    def test_a_repo_with_no_checklist_is_not_an_error(self):
        (self.repo / ".agents/checklist.json").unlink()
        code, out, err = self.run_cli("--base", "main")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("this repo has no checklist", err)

    def test_a_folder_inside_the_repo_is_refused_and_not_read_as_a_repo_with_no_checklist(self):
        code, out, err = self.run_cli("--base", "main", "--root", str(self.repo / "src"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("run it from the repo root", err)

    def test_a_folder_outside_any_repo_is_refused(self):
        code, out, err = self.run_cli("--base", "main", "--root", tempfile.mkdtemp())
        self.assertEqual((code, out), (2, ""))
        self.assertIn("is not inside a git repo", err)

    def test_a_named_file_that_is_missing_is_refused(self):
        self.assertIn("no checklist file at nope.json", self.refused("--base", "main", "--file", "nope.json"))

    def test_an_unknown_ref_is_refused_with_gits_words(self):
        self.assertIn("merge-base", self.refused("--base", "no-such-ref"))

    def test_a_ref_that_is_an_option_is_refused(self):
        self.assertIn("is not a ref", self.refused("--base=--output=/tmp/x"))

    def broken(self, doc):
        self.write(".agents/checklist.json", doc if isinstance(doc, str) else json.dumps(doc))
        return self.refused("--base", "main")

    def test_a_file_that_is_not_json_names_the_line(self):
        self.assertIn(".agents/checklist.json:2:", self.broken('{"version": 1,\n "items": [}'))

    def test_format_problems_name_the_item_and_the_key(self):
        cases = {
            "unknown key 'trigers'": item("a", ["x"], trigers={}),
            "item 1 (a): trigger: `paths` must be a non-empty list": item("a", []),
            "`pattern` is not a regular expression": item("a", ["x"], "("),
            'must be either {"command"} or {"question", "probe"}': item("a", ["x"], check={"question": "q"}),
            "`added` must be a date like 2026-11-21": item("a", ["x"], added="21 Nov"),
            "`review_by` is before `added`": item("a", ["x"], review_by="2026-10-01"),
            "`id` must be lowercase words joined by hyphens": item("Not An Id", ["x"]),
        }
        for message, bad in cases.items():
            with self.subTest(message):
                self.assertIn(message, self.broken({"version": 1, "items": [bad]}))
        self.assertIn("`id` is used twice", self.broken({"version": 1, "items": [item("a", ["x"]), item("a", ["y"])]}))
        self.assertIn("missing `review_by`", self.broken({"version": 1, "items": [
            {k: v for k, v in item("a", ["x"]).items() if k != "review_by"}]}))
        self.assertIn("`version` must be 1", self.broken({"version": 2, "items": []}))


class GlobTest(unittest.TestCase):
    def test_globs(self):
        cases = [("plugins/**", "plugins/a/b/c.md", True), ("plugins/**", "plugin/a", False),
                 ("plugins/*/SKILL.md", "plugins/a/SKILL.md", True), ("plugins/*/SKILL.md", "plugins/a/b/SKILL.md", False),
                 ("**/SKILL.md", "SKILL.md", True), ("**/SKILL.md", "a/b/SKILL.md", True),
                 ("docs/*.md", "docs/a.md", True), ("docs/*.md", "docs/a/b.md", False),
                 ("a.b", "aXb", False), ("**", "anything/at/all", True), ("a/**/*.md", "a/b.md", True)]
        for glob, path, want in cases:
            with self.subTest(glob=glob, path=path):
                self.assertEqual(bool(checklist.glob_regex(glob).fullmatch(path)), want)


class SeededChecklistTest(unittest.TestCase):
    """agent-kit's own checklist parses, and each item's globs still name a file in the repo."""

    def test_it_parses_and_no_trigger_is_dead(self):
        items = checklist.parse_checklist((ROOT / ".agents/checklist.json").read_text(), ".agents/checklist.json")
        self.assertEqual([i.id for i in items],
                         ["books-layout", "phase-spec-format", "plugins-in-step", "gh-call", "skill-description"])
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True, capture_output=True,
                                 text=True).stdout.split("\0")
        for i in items:
            for glob in i.trigger.paths:
                with self.subTest(item=i.id, glob=glob):
                    self.assertTrue(any(checklist.glob_regex(glob).fullmatch(p) for p in tracked),
                                    f"{i.id}: no tracked file matches {glob}")


if __name__ == "__main__":
    unittest.main()
