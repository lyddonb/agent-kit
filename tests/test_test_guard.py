"""Tests for verify-work's test_guard.py: a diff that weakens a Python test is reported, and nothing else is."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/verify-work/scripts/test_guard.py"
spec = importlib.util.spec_from_file_location("test_guard", SCRIPT)
test_guard = importlib.util.module_from_spec(spec)
sys.modules["test_guard"] = test_guard
spec.loader.exec_module(test_guard)

BASE = '''
import unittest


def helper(case):
    case.assertEqual(1, 1)
    case.assertTrue(True)


class BooksTest(unittest.TestCase):
    def setUp(self):
        self.n = 1

    def test_rows(self):
        self.assertEqual(self.n, 1)
        self.assertEqual(len("ab"), 2)

    def test_slow(self):
        run(timeout=5)
        self.assertAlmostEqual(0.1, 0.1, delta=0.01)
        self.assertAlmostEqual(0.1, 0.1, places=7)

    def test_error(self):
        with self.assertRaisesRegex(ValueError, "bad row"):
            parse("x")
'''


class Repo(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        self.write("tests/test_books.py", BASE)
        self.write("src/books.py", "print(1)\n")
        self.write("README.md", "# Books\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "change")

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo,
                              check=True, capture_output=True, text=True).stdout

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def edit(self, rel, old, new):
        path = self.repo / rel
        text = path.read_text()
        self.assertIn(old, text, f"fixture edit: {old!r} is not in {rel}")
        path.write_text(text.replace(old, new))

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def run_guard(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = test_guard.main(["--root", str(self.repo), *args])
        return code, out.getvalue().splitlines(), err.getvalue()

    def findings(self, *args):
        code, lines, err = self.run_guard("--base", "main", *args)
        self.assertEqual(code, 0, f"the guard should run: {err}")
        return lines


class RemovalTest(Repo):
    def test_a_deleted_test_is_reported_by_name(self):
        self.edit("tests/test_books.py", "    def test_rows(self):\n        self.assertEqual(self.n, 1)\n"
                  "        self.assertEqual(len(\"ab\"), 2)\n", "")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_rows: removed"])

    def test_a_rename_says_which_tests_the_file_gained(self):
        self.edit("tests/test_books.py", "def test_rows(", "def test_each_row(")
        self.assertEqual(self.findings(), [
            "tests/test_books.py: BooksTest.test_rows: removed",
            "tests/test_books.py: gains 1 tests: BooksTest.test_each_row",
        ])

    def test_a_test_moved_to_another_changed_file_says_where(self):
        self.edit("tests/test_books.py", "class BooksTest(", "class OtherTest(")
        self.write("tests/test_more.py", "import unittest\n\nclass BooksTest(unittest.TestCase):\n"
                   "    def test_rows(self):\n        self.assertEqual(1, 1)\n")
        lines = self.findings()
        self.assertIn("tests/test_books.py: BooksTest.test_rows: moved to tests/test_more.py", lines)

    def test_deleting_the_file_reports_every_test_in_it(self):
        (self.repo / "tests/test_books.py").unlink()
        self.assertEqual(self.findings(), [
            "tests/test_books.py: BooksTest.test_error: removed",
            "tests/test_books.py: BooksTest.test_rows: removed",
            "tests/test_books.py: BooksTest.test_slow: removed",
        ])

    def test_a_renamed_file_that_lost_a_test_is_read_under_its_new_name(self):
        self.git("mv", "tests/test_books.py", "tests/test_ledger.py")
        self.edit("tests/test_ledger.py", "    def test_error(self):\n", "    def helper_error(self):\n")
        self.commit("rename")
        self.assertIn("tests/test_ledger.py: BooksTest.test_error: removed", self.findings())

    def test_a_file_renamed_out_of_the_test_pattern_is_still_compared(self):
        self.git("mv", "tests/test_books.py", "src/books_cases.py")
        self.edit("src/books_cases.py", "    def test_error(self):\n", "    def case_error(self):\n")
        self.commit("rename out")
        self.assertIn("src/books_cases.py: BooksTest.test_error: removed", self.findings())


class WeakeningTest(Repo):
    def test_a_skip_decorator_is_reported(self):
        self.edit("tests/test_books.py", "    def test_rows(", "    @unittest.skip('later')\n    def test_rows(")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_rows: gains a skip"])

    def test_a_skip_call_inside_the_test_is_reported(self):
        self.edit("tests/test_books.py", "        self.assertEqual(self.n, 1)\n",
                  "        self.skipTest('flaky')\n        self.assertEqual(self.n, 1)\n")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_rows: gains a skip"])

    def test_a_skip_on_the_class_is_reported_on_the_class(self):
        self.edit("tests/test_books.py", "class BooksTest(", "@unittest.skipIf(True, 'ci')\nclass BooksTest(")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest: gains a skip"])

    def test_a_helper_module_under_tests_is_compared_too(self):
        self.write("tests/support.py", "def check_row(case, row):\n    case.assertEqual(row, 1)\n    case.assertTrue(row)\n")
        self.commit("support")
        self.git("branch", "-f", "main", "HEAD")
        self.edit("tests/support.py", "    case.assertTrue(row)\n", "")
        self.assertEqual(self.findings(), ["tests/support.py: check_row: assertions 2 -> 1"])

    def test_a_retry_is_reported(self):
        self.edit("tests/test_books.py", "    def test_rows(", "    @pytest.mark.flaky(reruns=3)\n    def test_rows(")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_rows: gains a retry"])

    def test_a_wider_timeout_is_reported(self):
        self.edit("tests/test_books.py", "run(timeout=5)", "run(timeout=30)")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_slow: timeout 5 -> 30"])

    def test_a_wider_delta_and_fewer_places_are_reported(self):
        self.edit("tests/test_books.py", "delta=0.01", "delta=0.5")
        self.edit("tests/test_books.py", "places=7", "places=2")
        self.assertEqual(self.findings(), [
            "tests/test_books.py: BooksTest.test_slow: delta 0.01 -> 0.5",
            "tests/test_books.py: BooksTest.test_slow: places 7 -> 2",
        ])

    def test_a_dropped_assertion_is_reported(self):
        self.edit("tests/test_books.py", "        self.assertEqual(len(\"ab\"), 2)\n", "")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_rows: assertions 2 -> 1"])

    def test_a_dropped_assertion_in_a_helper_is_reported(self):
        self.edit("tests/test_books.py", "    case.assertTrue(True)\n", "")
        self.assertEqual(self.findings(), ["tests/test_books.py: helper: assertions 2 -> 1"])

    def test_an_exact_check_traded_for_a_weaker_one_is_reported(self):
        self.edit("tests/test_books.py", "self.assertEqual(self.n, 1)", "self.assertIn(self.n, (0, 1))")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_rows: trades assertEqual for assertIn"])

    def test_a_message_check_traded_for_a_type_check_is_reported(self):
        self.edit("tests/test_books.py", 'self.assertRaisesRegex(ValueError, "bad row")', "self.assertRaises(ValueError)")
        self.assertEqual(self.findings(),
                         ["tests/test_books.py: BooksTest.test_error: trades assertRaisesRegex for assertRaises"])


class QuietTest(Repo):
    def test_a_docs_and_source_change_reports_nothing(self):
        self.edit("README.md", "# Books", "# The books")
        self.edit("src/books.py", "print(1)", "print(2)")
        self.commit("docs")
        code, lines, err = self.run_guard("--base", "main", "--head", "HEAD")
        self.assertEqual((code, lines), (0, []))
        self.assertIn("0 findings", err)

    def test_adding_tests_and_assertions_reports_nothing(self):
        self.edit("tests/test_books.py", "        self.assertEqual(self.n, 1)\n",
                  "        self.assertEqual(self.n, 1)\n        self.assertGreater(self.n, 0)\n")
        self.write("tests/test_new.py", "def test_new():\n    assert 1\n")
        self.assertEqual(self.findings(), [])

    def test_tests_main_gained_after_the_branch_point_are_not_reported_as_removed(self):
        self.git("checkout", "-q", "main")
        self.edit("tests/test_books.py", "    def test_error(self):\n",
                  "    def test_later(self):\n        self.assertTrue(1)\n\n    def test_error(self):\n")
        self.commit("main moves on")
        self.git("checkout", "-q", "change")
        self.edit("README.md", "# Books", "# Branch")
        self.commit("branch work")
        self.assertEqual(self.findings("--head", "HEAD"), [])


class ModesTest(Repo):
    def test_without_head_it_reads_uncommitted_edits(self):
        self.edit("tests/test_books.py", "        self.assertEqual(len(\"ab\"), 2)\n", "")
        self.assertEqual(self.findings(), ["tests/test_books.py: BooksTest.test_rows: assertions 2 -> 1"])
        self.assertEqual(self.findings("--head", "HEAD"), [], "with --head only the commit is read")

    def test_a_head_this_python_cannot_parse_is_a_finding_not_a_silence(self):
        self.edit("tests/test_books.py", "class BooksTest(", "class BooksTest((")
        lines = self.findings()
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], r"^tests/test_books\.py: Python 3\.\d+ cannot parse it at the head "
                                   r"\(line \d+: .+\); its tests were not compared$")

    def test_json_gives_path_name_and_what(self):
        self.edit("tests/test_books.py", "run(timeout=5)", "run(timeout=30)")
        code, lines, _ = self.run_guard("--base", "main", "--json")
        self.assertEqual((code, json.loads("\n".join(lines))),
                         (0, [{"path": "tests/test_books.py", "name": "BooksTest.test_slow", "what": "timeout 5 -> 30"}]))

    def test_a_bad_ref_exits_2(self):
        code, lines, err = self.run_guard("--base", "no-such-ref")
        self.assertEqual((code, lines), (2, []))
        self.assertIn("test-guard:", err)

    def test_an_option_given_as_a_ref_exits_2(self):
        code, _, err = self.run_guard("--base=--output=x")
        self.assertEqual(code, 2, err)

    def test_a_folder_below_the_top_exits_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = test_guard.main(["--root", str(self.repo / "tests"), "--base", "main"])
        self.assertEqual(code, 2)
        self.assertIn("is not the top of a git work tree", err.getvalue())


class HistoryTest(unittest.TestCase):
    def setUp(self):
        found = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", "990c84f^{commit}"], capture_output=True)
        self.assertEqual(found.returncode, 0, "these tests replay agent-kit's history: clone it in full (fetch-depth: 0)")

    def guard(self, sha):
        return [f.text() for f in test_guard.guard(ROOT, f"{sha}^", sha)]

    def test_990c84f_reports_the_three_tests_it_renamed_or_replaced(self):
        removed = [line for line in self.guard("990c84f") if line.endswith(": removed")]
        self.assertEqual(removed, [
            "tests/test_quality.py: FileProblemsTest.test_row_with_an_embedded_newline: removed",
            "tests/test_quality.py: WeeklyRulesTest.test_p50_equal_to_max_is_fine: removed",
            "tests/test_quality.py: WeeklyRulesTest.test_p50_more_than_max: removed",
        ])

    def test_a_docs_only_commit_reports_nothing(self):
        self.assertEqual(self.guard("cb5299b"), [])


if __name__ == "__main__":
    unittest.main()
