"""Tests for the `questions` check in books.py: the shape of questions.md."""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/cfo/skills/cfo-books/scripts/books.py"
FIXTURE = ROOT / "tests/fixtures/books"

spec = importlib.util.spec_from_file_location("books", SCRIPT)
books = importlib.util.module_from_spec(spec)
sys.modules["books"] = books
spec.loader.exec_module(books)

GOOD = """# Open questions

## Open

- **Q2 (2026-10-31) Envelope.** Proposed 300 a month. Confirm or change.
Answer: yes, 300.

## Answered

- **Q1 (2026-10-01) Vendor.** Which project uses it? **Answered 2026-10-05:** the demo.
"""


class QuestionsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "books"
        shutil.copytree(FIXTURE, self.dir)

    def problems(self, text):
        (self.dir / "questions.md").write_text(text)
        books_ = books.load(self.dir)
        return [f"{p.path}:{p.line}: {p.message}" for p in books.check_questions(books_)]

    def assertProblem(self, text, line, fragment):
        found = self.problems(text)
        self.assertTrue(any(p.startswith(f"questions.md:{line}: ") and fragment in p for p in found),
                        f"expected line {line} {fragment!r} in {found}")

    def test_good_file(self):
        self.assertEqual(self.problems(GOOD), [])

    def test_answer_line_allowed_under_open(self):
        self.assertEqual(self.problems(GOOD.replace("Answer: yes, 300.", "  Answer: yes")), [])

    def test_duplicate_id_across_sections(self):
        text = GOOD.replace("Q1 (2026-10-01)", "Q2 (2026-10-01)")
        self.assertProblem(text, 10, "Q2 is already used on line 5")

    def test_bad_format_missing_date(self):
        self.assertProblem(GOOD.replace("Q2 (2026-10-31) ", "Q2 "), 5, "must start")

    def test_bad_format_title_without_period(self):
        self.assertProblem(GOOD.replace("Envelope.**", "Envelope**"), 5, "must start")

    def test_impossible_date(self):
        self.assertProblem(GOOD.replace("2026-10-31", "2026-13-31"), 5, "not a real date")

    def test_answered_without_date(self):
        self.assertProblem(GOOD.replace("**Answered 2026-10-05:** ", ""), 10, "no '**Answered")

    def test_missing_heading(self):
        found = self.problems(GOOD.replace("## Answered", "## Done"))
        self.assertTrue(any("missing heading '## Answered'" in p for p in found), found)

    def test_missing_file(self):
        (self.dir / "questions.md").unlink()
        found = [p.message for p in books.check_questions(books.load(self.dir))]
        self.assertTrue(any("missing" in m for m in found), found)

    def test_real_books_command_passes_on_good_file(self):
        (self.dir / "questions.md").write_text(GOOD)
        self.assertEqual([p for p in books.run_checks(books.load(self.dir)) if p.path == "questions.md"], [])


if __name__ == "__main__":
    unittest.main()
