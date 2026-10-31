"""Tests for the CFO books checker (plugins/cfo/skills/cfo-books/scripts/books.py)."""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/cfo/skills/cfo-books/scripts/books.py"
FIXTURE = ROOT / "tests/fixtures/books"

spec = importlib.util.spec_from_file_location("books", SCRIPT)
books = importlib.util.module_from_spec(spec)
sys.modules["books"] = books  # dataclasses look the module up by name
spec.loader.exec_module(books)

GOOD_ROW = "2026-03-01,2026-03-01,2026-03-31,Acme Cloud,Pro plan,subscription,20.00,USD,,shared,verified,gmail-receipt,Acme receipt #1000-2000-3001"
FIELDS = list(books.SCHEMA)


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "books"
        shutil.copytree(FIXTURE, self.dir)

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def append_row(self, **overrides):
        cells = dict(zip(FIELDS, GOOD_ROW.split(",")))
        cells.update(overrides)
        with open(self.dir / books.LEDGER, "a") as f:
            f.write(",".join(cells[k] for k in FIELDS) + "\n")
        return len((self.dir / books.LEDGER).read_text().splitlines())  # its line number

    def problems(self, base=None):
        return [str(p) for p in books.run_checks(books.load(self.dir, base))]

    def assertFlags(self, path, line, kind, base=None):
        found = self.problems(base)
        want = f"{path}:{line}: "
        self.assertTrue(any(p.startswith(want) and kind in p for p in found),
                        f"expected {want}...{kind!r} in {found}")

    def assertClean(self, base=None):
        self.assertEqual(self.problems(base), [])


class FixtureTest(Case):
    def test_fixture_is_clean(self):
        self.assertClean()

    def test_good_appended_row_is_clean(self):
        self.append_row()
        self.assertClean()


class HeaderTest(Case):
    def test_wrong_header_names_line_1(self):
        text = (self.dir / books.LEDGER).read_text().replace("evidence", "proof", 1)
        self.write(books.LEDGER, text)
        self.assertFlags(books.LEDGER, 1, "header")

    def test_missing_ledger(self):
        (self.dir / books.LEDGER).unlink()
        self.assertFlags(books.LEDGER, 1, "missing file")


class RowTest(Case):
    def flagged(self, kind, **overrides):
        self.assertFlags(books.LEDGER, self.append_row(**overrides), kind)

    def test_bad_charge_date(self):
        self.flagged("charge_date", charge_date="2026-13-01")

    def test_period_start_required(self):
        self.flagged("period_start", period_start="")

    def test_bad_period_end(self):
        self.flagged("period_end", period_end="soon")

    def test_empty_period_end_is_fine(self):
        self.append_row(period_end="")
        self.assertClean()

    def test_period_order(self):
        self.flagged("after period_end", period_start="2026-04-01", period_end="2026-03-01")

    def test_unknown_charge_type(self):
        self.flagged("charge_type", charge_type="gift")

    def test_unknown_status(self):
        self.flagged("status", status="maybe")

    def test_unknown_currency(self):
        self.flagged("currency", currency="EUR")

    def test_unknown_status_with_amount(self):
        self.flagged("must be empty", status="unknown", billed_cost="5.00")

    def test_verified_without_amount(self):
        self.flagged("billed_cost is empty", billed_cost="")

    def test_unknown_status_without_amount_is_fine(self):
        self.append_row(status="unknown", billed_cost="")
        self.assertClean()

    def test_amount_not_a_number(self):
        self.flagged("billed_cost is not a decimal", billed_cost="twenty")
        self.flagged("billed_cost is not a decimal", billed_cost="NaN")

    def test_api_equivalent_not_a_number(self):
        self.flagged("api_equivalent_cost", api_equivalent_cost="lots")

    def test_empty_evidence(self):
        self.flagged("evidence", evidence="")

    def test_unknown_project(self):
        self.flagged("project", project="nope")

    def test_unassigned_project_is_fine(self):
        self.append_row(project="unassigned")
        self.assertClean()

    def test_wrong_column_count(self):
        with open(self.dir / books.LEDGER, "a") as f:
            f.write("2026-03-01,too,few\n")
        self.assertFlags(books.LEDGER, 5, "columns")


class YamlFileTest(Case):
    def test_missing_key_in_each_file(self):
        for name, key in (("projects.yaml", "projects"), ("budgets.yaml", "alerts"), ("renewals.yaml", "renewals")):
            with self.subTest(name):
                original = (self.dir / name).read_text()
                self.write(name, original.replace("\n" + key + ":", "\nrenamed:", 1))
                self.assertFlags(name, 1, f"missing top-level key '{key}'")
                self.write(name, original)

    def test_unsupported_syntax_names_file_and_line(self):
        self.write("budgets.yaml", "version: 1\nmonthly_envelope: &anchor\n  usd: 1\nalerts: {}\n")
        self.assertFlags("budgets.yaml", 2, "unsupported YAML")

    def test_unterminated_flow_names_line(self):
        self.write("renewals.yaml", "version: 1\nrenewals:\n  - {vendor: Acme\n")
        self.assertFlags("renewals.yaml", 3, "unsupported YAML")

    def test_tab_indentation(self):
        self.write("budgets.yaml", "version: 1\nmonthly_envelope:\n\tusd: 1\nalerts: {}\n")
        self.assertFlags("budgets.yaml", 3, "unsupported YAML")

    def test_missing_yaml_file(self):
        (self.dir / "renewals.yaml").unlink()
        self.assertFlags("renewals.yaml", 1, "missing file")

    def test_project_check_is_skipped_when_projects_unreadable(self):
        self.write("projects.yaml", "version: 1\nprojects: &x\n  a: 1\n")
        self.append_row(project="nope")
        found = self.problems()
        self.assertTrue(any(p.startswith("projects.yaml:") for p in found))
        self.assertFalse(any("project 'nope'" in p for p in found))


class YamlReaderTest(unittest.TestCase):
    def test_subset(self):
        doc = books.parse_yaml(
            "# top comment\n"
            "version: 1\n"
            "ratio: 0.5\n"
            "nothing: null\n"
            "empty:\n"
            "flag: true\n"
            "name: \"has # hash\"   # trailing\n"
            "note: it's fine   # not part of it\n"
            "date: 2026-04-26\n"
            "folded: >-\n"
            "  one two\n"
            "  # not a comment\n"
            "\n"
            "  three\n"
            "after: 2\n"
            "tree:\n"
            "  leaf:\n"
            "    deep: [a, \"b, c\", [1, 2.5]]\n"
            "list:\n"
            "  - plain\n"
            "  - {k: v, n: [x, y], z: null}\n"
            "  - key: value here; with: no space-colon trap\n"
            "inline: {a: 1, b: {c: [d]}}\n")
        self.assertEqual(doc, {
            "version": 1, "ratio": 0.5, "nothing": None, "empty": None, "flag": True,
            "name": "has # hash", "note": "it's fine", "date": "2026-04-26",
            "folded": "one two # not a comment three", "after": 2,
            "tree": {"leaf": {"deep": ["a", "b, c", [1, 2.5]]}},
            "list": ["plain", {"k": "v", "n": ["x", "y"], "z": None}, {"key": "value here; with: no space-colon trap"}],
            "inline": {"a": 1, "b": {"c": ["d"]}},
        })

    def test_unsupported_raises_with_line(self):
        for text, line in (("a: 1\nb: *x\n", 2), ("a: 1\n  b: 2\n", 2), ("a: 1\na: 2\n", 2),
                           ("- a\nb: 1\n", 2), ("a: \"open\n", 1), ("a: {b: 1} junk\n", 1)):
            with self.subTest(text):
                with self.assertRaises(books.YamlError) as cm:
                    books.parse_yaml(text)
                self.assertEqual(cm.exception.line, line)


class CardTest(Case):
    def flagged_card(self, text):
        self.write("notes.txt", f"first line\nnote {text} end\n")
        self.assertFlags("notes.txt", 2, "card number")

    def not_flagged(self, text):
        self.write("notes.txt", f"note {text} end\n")
        self.assertClean()

    def test_contiguous(self):
        self.flagged_card("4242424242424242")

    def test_grouped_spaces_and_dashes(self):
        self.flagged_card("4111 1111 1111 1111")
        self.flagged_card("4111-1111-1111-1111")

    def test_amex_grouping(self):
        self.flagged_card("3782 822463 10005")
        self.flagged_card("378282246310005")

    def test_mixed_separators_not_grouped(self):
        self.not_flagged("4111 1111-1111 1111")

    def test_luhn_invalid_ignored(self):
        self.not_flagged("4242424242424241")
        self.not_flagged("4111 1111 1111 1112")

    def test_dates_and_receipts_not_flagged(self):
        self.not_flagged("2026-10-31 receipt #1234-5678-9012")

    def test_adjacent_digits_not_a_card(self):
        self.not_flagged("424242424242424299999999")

    def test_message_does_not_echo_the_number(self):
        self.write("notes.txt", "4242424242424242\n")
        self.assertFalse(any("4242" in p for p in self.problems()))
        self.assertTrue(any("16 digits" in p for p in self.problems()))


class AccountIdTest(Case):
    def test_12_digits_in_non_evidence_column(self):
        line = self.append_row(service="123456789012")
        self.assertFlags(books.LEDGER, line, "account ID")

    def test_12_digits_in_evidence_not_flagged(self):
        self.append_row(evidence="Invoice 123456789012")
        self.assertClean()

    def test_12_digits_elsewhere_flagged(self):
        self.write("questions.md", "ok\nAccount 123456789012 is ours\n")
        self.assertFlags("questions.md", 2, "account ID")

    def test_dashed_without_hash_flagged(self):
        self.write("questions.md", "Account 1234-5678-9012 here\n")
        self.assertFlags("questions.md", 1, "account ID")

    def test_dashed_with_hash_not_flagged(self):
        self.write("questions.md", "Receipt #1234-5678-9012 here\n")
        self.assertClean()

    def test_longer_runs_not_flagged_as_account(self):
        self.write("questions.md", "ticket 1234567890123 and 12345678901\n")
        self.assertClean()


class SecretTest(Case):
    BODY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"

    def planted(self):
        return {
            "Anthropic": "sk-ant-" + "api03-abcDEF123_-" + "xyzXYZ789",
            "sk-": "sk-proj-" + self.BODY[:24],
            "AWS": "AKIA" + "ABCDEFGHIJKLMNOP",
            "GitHub token": "ghp_" + self.BODY[:36],
            "GitHub fine-grained": "github_pat_" + self.BODY[:30],
            "Slack": "xoxb-" + "1234567890-abcdef",
            "Google": "AIza" + self.BODY[:35],
        }

    def test_each_prefix_flagged_at_full_length(self):
        for label, token in self.planted().items():
            with self.subTest(label):
                self.write("questions.md", f"x\nkey {token} end\n")
                self.assertFlags("questions.md", 2, "secret")
                self.assertFalse(any(token in p for p in self.problems()))

    def test_too_short_not_flagged(self):
        for token in ("AKIA" + "ABCDEFGHIJKLMNO", "ghp_" + self.BODY[:35], "xoxb-12345", "sk-short",
                      "AIza" + self.BODY[:34]):
            with self.subTest(token):
                self.write("questions.md", f"key {token} end\n")
                self.assertClean()

    def test_bare_prefix_in_prose_not_flagged(self):
        self.write("questions.md", "A key starting with sk-ant- or AKIA, ghp_, github_pat_, xoxb- or AIza.\n")
        self.assertClean()

    def test_word_boundary(self):
        self.write("questions.md", "the task-" + "a" * 30 + " thing\n")
        self.assertClean()


class SkipTest(Case):
    def test_binary_files_skipped(self):
        (self.dir / "blob.bin").write_bytes(b"\0\1\2 4242424242424242")
        self.assertClean()

    def test_gitignored_files_skipped_in_a_git_repo(self):
        git(self.dir, "init", "-q")
        self.write(".gitignore", "inbox/\n")
        self.write("inbox/statement.txt", "4242424242424242\n")
        self.assertClean()
        self.write("other.txt", "4242424242424242\n")
        self.assertFlags("other.txt", 1, "card number")


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false"] + list(args), check=True, capture_output=True)


class AppendOnlyTest(Case):
    def setUp(self):
        super().setUp()
        git(self.dir, "init", "-q")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "base")

    def test_appending_is_fine(self):
        self.append_row()
        self.assertClean("HEAD")

    def test_changed_line(self):
        path = self.dir / books.LEDGER
        path.write_text(path.read_text().replace("20.00", "21.00"))
        self.assertFlags(books.LEDGER, 2, "changed since HEAD", "HEAD")
        self.assertFalse(any("changed since" in p for p in self.problems()))  # off without --base

    def test_removed_line(self):
        path = self.dir / books.LEDGER
        path.write_text("\n".join(path.read_text().splitlines()[:2]) + "\n")
        self.assertFlags(books.LEDGER, 3, "removed since HEAD", "HEAD")
        self.assertFlags(books.LEDGER, 4, "removed since HEAD", "HEAD")

    def test_no_ledger_at_base_is_fine(self):
        git(self.dir, "rm", "-q", "-r", "--cached", "ledger")
        git(self.dir, "commit", "-q", "-m", "drop ledger")
        self.assertClean("HEAD")

    def test_bad_ref_is_a_problem_not_a_crash(self):
        self.assertFlags(books.LEDGER, 1, "cannot check against", "no-such-ref")

    def test_not_a_git_repo_is_a_problem_not_a_crash(self):
        shutil.rmtree(self.dir / ".git")
        self.assertFlags(books.LEDGER, 1, "cannot check against", "HEAD")


class CliTest(Case):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT)] + list(args), capture_output=True, text=True)

    def test_clean_books(self):
        r = self.run_cli("check", str(self.dir))
        self.assertEqual((r.returncode, r.stdout), (0, "ok, 3 rows, 0 problems\n"))

    def test_problems_sorted_with_count(self):
        self.write("questions.md", "4242424242424242\n")
        line = self.append_row(status="maybe")
        r = self.run_cli("check", str(self.dir))
        out = r.stdout.splitlines()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(out[0].startswith(f"{books.LEDGER}:{line}: "), out)
        self.assertTrue(out[1].startswith("questions.md:1: "), out)
        self.assertEqual(out[-1], "2 problems")

    def test_missing_dir_is_usage_error(self):
        self.assertEqual(self.run_cli("check", str(self.dir / "nope")).returncode, 2)

    def test_no_subcommand_is_usage_error(self):
        self.assertEqual(self.run_cli().returncode, 2)


if __name__ == "__main__":
    unittest.main()
