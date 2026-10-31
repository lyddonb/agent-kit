"""Tests for the CFO books checker (plugins/cfo/skills/cfo-books/scripts/books.py)."""
import importlib.util
import json
import os
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

    def write_q(self, text):
        # junk to probe the content checks, followed by the headings the questions check needs
        self.write("questions.md", text + "\n## Open\n\n## Answered\n")

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

    def test_project_check_stays_on_when_projects_unreadable(self):
        self.write("projects.yaml", "version: 1\nprojects: &x\n  a: 1\n")
        line = self.append_row(project="nope")
        self.assertFlags("projects.yaml", 2, "unsupported YAML")
        self.assertFlags(books.LEDGER, line, "project 'nope'")


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
            "  three\n"
            "after: 2\n"
            "tree:\n"
            "  leaf:\n"
            "    deep: [a, \"b, c\", [1, 2.5]]\n"
            "list:\n"
            "  - plain\n"
            "  - {k: v, n: [x, y], z: null}\n"
            "  - key: value here; with a semicolon\n"
            "inline: {a: 1, b: {c: [d]}}\n")
        self.assertEqual(doc, {
            "version": 1, "ratio": 0.5, "nothing": None, "empty": None, "flag": True,
            "name": "has # hash", "note": "it's fine", "date": "2026-04-26",
            "folded": "one two # not a comment three", "after": 2,
            "tree": {"leaf": {"deep": ["a", "b, c", [1, 2.5]]}},
            "list": ["plain", {"k": "v", "n": ["x", "y"], "z": None}, {"key": "value here; with a semicolon"}],
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
        self.write_q("ok\nAccount 123456789012 is ours\n")
        self.assertFlags("questions.md", 2, "account ID")

    def test_dashed_without_hash_flagged(self):
        self.write_q("Account 1234-5678-9012 here\n")
        self.assertFlags("questions.md", 1, "account ID")

    def test_dashed_with_hash_not_flagged(self):
        self.write_q("Receipt #1234-5678-9012 here\n")
        self.assertClean()

    def test_longer_runs_not_flagged_as_account(self):
        self.write_q("ticket 1234567890123 and 12345678901\n")
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
                self.write_q(f"x\nkey {token} end\n")
                self.assertFlags("questions.md", 2, "secret")
                self.assertFalse(any(token in p for p in self.problems()))

    def test_too_short_not_flagged(self):
        for token in ("AKIA" + "ABCDEFGHIJKLMNO", "ghp_" + self.BODY[:35], "xoxb-12345", "sk-short",
                      "AIza" + self.BODY[:34]):
            with self.subTest(token):
                self.write_q(f"key {token} end\n")
                self.assertClean()

    def test_bare_prefix_in_prose_not_flagged(self):
        self.write_q("A key starting with sk-ant- or AKIA, ghp_, github_pat_, xoxb- or AIza.\n")
        self.assertClean()

    def test_word_boundary(self):
        self.write_q("the task-" + "a" * 30 + " thing\n")
        self.assertClean()


class SkipTest(Case):
    def test_binary_file_is_a_problem(self):
        (self.dir / "blob.bin").write_bytes(b"\0\1\2 4242424242424242")
        self.assertFlags("blob.bin", 1, "binary file")

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


class NoSilentSkipTest(Case):
    def test_utf16_with_bom_is_scanned(self):
        (self.dir / "notes.txt").write_bytes(b"\xff\xfe" + "ok\n4242424242424242\n".encode("utf-16-le"))
        self.assertFlags("notes.txt", 2, "card number")

    def test_utf8_bom_ledger_is_clean(self):
        path = self.dir / books.LEDGER
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assertClean()

    def test_empty_projects_file_fails_and_keeps_project_rule(self):
        self.write("projects.yaml", "# nothing\n")
        self.write("budgets.yaml", "")
        line = self.append_row(project="no-such-project")
        self.assertFlags("projects.yaml", 1, "empty file")
        self.assertFlags("budgets.yaml", 1, "empty file")
        self.assertFlags(books.LEDGER, line, "project 'no-such-project'")

    def test_broken_git_index_is_a_problem(self):
        git(self.dir, "init", "-q")
        (self.dir / ".git/index").write_bytes(b"garbage")
        self.assertTrue(any("git ls-files" in p for p in self.problems()), self.problems())

    def test_unreadable_file_is_a_problem(self):
        import os
        if os.geteuid() == 0:
            self.skipTest("root can read anything")
        path = self.dir / "secret.txt"
        path.write_text("x\n")
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        self.assertFlags("secret.txt", 1, "unreadable")

    def test_file_name_is_scanned(self):
        self.write("4242424242424242.txt", "hello\n")
        self.assertFlags("4242424242424242.txt", 1, "file name")

    def test_multi_line_row_is_a_problem(self):
        with open(self.dir / books.LEDGER, "a") as f:
            f.write(GOOD_ROW.replace("Pro plan", '"Pro\nplan"') + "\n")
        self.assertFlags(books.LEDGER, 5, "more than one line")


class CardHardeningTest(Case):
    def test_tail_after_16_digits(self):
        for i, text in enumerate(("card 4111 1111 1111 1111 123", "4111 1111 1111 1111 12/28",
                                  "4111-1111-1111-1111-99"), 1):
            with self.subTest(text):
                self.write("notes.txt", text + "\n")
                self.assertFlags("notes.txt", 1, "card number")

    def test_other_separators(self):
        for text in ("4111.1111.1111.1111", "4111\u20111111\u20111111\u20111111", "4111\u00a01111\u00a01111\u00a01111",
                     "4111-1111 1111-1111", "3782.822463.10005", "4111\u20151111\u20151111\u20151111"):
            with self.subTest(text):
                self.write("notes.txt", text + "\n")
                self.assertFlags("notes.txt", 1, "card number")

    def test_dates_still_not_flagged(self):
        self.write("notes.txt", "2026-10-01 2026.10.01 2026-10-01 2026-10-31\n")
        self.assertClean()


class HistoryTest(Case):
    def setUp(self):
        super().setUp()
        git(self.dir, "init", "-q")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "base")

    def commit_text(self, rel, text):
        self.write(rel, text)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "change")

    def test_card_added_then_removed_still_fails(self):
        original = (self.dir / "questions.md").read_text()
        self.commit_text("questions.md", original + "\ncard 4242424242424242\n")
        line = len((self.dir / "questions.md").read_text().split("\n")) - 1
        self.commit_text("questions.md", original)
        self.assertFlags("questions.md", line, "in commit", "HEAD~2")
        self.assertTrue(any("card number" in p and "in commit" in p for p in self.problems("HEAD~2")))
        self.assertClean()  # no --base, no history scan

    def test_clean_history_is_fine(self):
        self.commit_text("questions.md", "fine\n\n## Open\n\n## Answered\n")
        self.assertClean("HEAD~1")

    def test_empty_range_is_fine(self):
        self.assertClean("HEAD")

    def test_evidence_exemption_for_12_digits_in_history(self):
        self.append_row(evidence="Invoice 123456789012")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "row")
        self.assertClean("HEAD~1")
        self.append_row(service="123456789012")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "row2")
        self.assertFlags(books.LEDGER, 6, "in commit", "HEAD~1")


class YamlStrictTest(unittest.TestCase):
    def rejects(self, text, line=1):
        with self.assertRaises(books.YamlError, msg=text) as cm:
            books.parse_yaml(text)
        self.assertEqual(cm.exception.line, line, text)

    def test_flow_punctuation(self):
        for text in ('a: ["a" "b"]', "a: {x: 1 y: 2}", "a: [1 2]", "a: [1,,2]", "a: {x: 1, x: 2}",
                     "a: {x: 1,, y: 2}"):
            with self.subTest(text):
                self.rejects(text + "\n")

    def test_flow_trailing_comma_ok(self):
        self.assertEqual(books.parse_yaml("a: [1, 2,]\n"), {"a": [1, 2]})

    def test_escapes(self):
        self.rejects('a: "x\\qy"\n')
        self.rejects('a: "x\\u0041y"\n')
        self.assertEqual(books.parse_yaml('a: "x\\ny\\"z\\\\"\n'), {"a": 'x\ny"z\\'})

    def test_plain_scalar_shapes(self):
        for text in ("a: x: y", "a: x:", "a: - x", "a: ]x", "a: }x", "a: ,x", "- - x", "a:\n  - - x"):
            with self.subTest(text):
                with self.assertRaises(books.YamlError):
                    books.parse_yaml(text + "\n")

    def test_block_scalars(self):
        self.rejects("a: >-\n  one\n\n  two\nb: 1\n", 1)
        self.rejects("a: |\n  one\n    deeper\nb: 1\n", 1)
        self.assertEqual(books.parse_yaml("a: >-\n  one\n  two\n\nb: 1\n"), {"a": "one two", "b": 1})

    def test_leading_zero_is_a_string(self):
        self.assertEqual(books.parse_yaml("a: 012\nb: 0\nc: 10\nd: 0.5\ne: 007.5\n"),
                         {"a": "012", "b": 0, "c": 10, "d": 0.5, "e": "007.5"})


class AccountHardeningTest(Case):
    def flagged(self, text, kind="account ID"):
        self.write_q(text + "\n")
        self.assertFlags("questions.md", 1, kind)

    def clean(self, text):
        self.write_q(text + "\n")
        self.assertClean()

    def test_space_grouped(self):
        self.flagged("Account 1234 5678 9012 here")

    def test_hash_exemption_unless_account_nearby(self):
        self.clean("Receipt #1234-5678-9012 here")
        self.flagged("AWS account #1234-5678-9012 here")
        self.flagged("acct #1234-5678-9012 here")

    def test_decimal_fraction_not_flagged(self):
        self.clean("billed 0.123456789012 USD")
        self.flagged("billed 123456789012 USD")

    def test_secret_variants(self):
        body = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
        for token in ("ghs_" + body[:36], "gho_" + body[:36], "ghp_" + body, "ASIA" + "ABCDEFGHIJKLMNOP",
                      "xoxe-" + "1234567890-ab", "sk_live_" + body[:24], "sk_test_" + body[:24],
                      "OPENAI-sk-" + body[:24], "X_sk-ant-" + body[:24]):
            with self.subTest(token):
                self.flagged("key " + token + " end", "secret")

    def test_words_not_flagged(self):
        self.clean("task-" + "a" * 30 + " and risk-" + "b" * 30)

    def test_append_only_compares_bytes(self):
        git(self.dir, "init", "-q")
        path = self.dir / books.LEDGER
        path.write_bytes(path.read_bytes() + b"\xff junk\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "base")
        path.write_bytes(path.read_bytes().replace(b"\xff junk", b"\xfe junk"))
        self.assertFlags(books.LEDGER, 5, "changed since HEAD", "HEAD")


class CliTest(Case):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT)] + list(args), capture_output=True, text=True)

    def test_clean_books(self):
        r = self.run_cli("check", str(self.dir))
        self.assertEqual((r.returncode, r.stdout), (0, "ok, 3 rows, 0 problems\n"))

    def test_problems_sorted_with_count(self):
        self.write_q("4242424242424242\n")
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


class AppendTest(Case):
    HEADER = "evidence,charge_date,period_start,provider,service,charge_type,billed_cost,currency,project,status,source"

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT)] + list(args), capture_output=True, text=True)

    def rows_file(self, text):
        path = Path(self._tmp.name) / "rows.csv"
        path.write_text(text)
        return str(path)

    def new_row(self, evidence, **kw):
        c = dict(evidence=evidence, charge_date="2026-03-01", period_start="2026-03-01", provider="Acme Cloud",
                 service="Pro plan", charge_type="subscription", billed_cost="20.00", currency="USD",
                 project="shared", status="verified", source="gmail-receipt")
        c.update(kw)
        return ",".join(c[h] for h in self.HEADER.split(","))

    def ledger(self):
        return (self.dir / books.LEDGER).read_bytes()

    def append(self, *rows, header=None):
        text = (header or self.HEADER) + "\n" + "".join(r + "\n" for r in rows)
        return self.run_cli("append", str(self.dir), self.rows_file(text))

    def test_adds_rows_in_schema_order_and_keeps_old_bytes(self):
        before = self.ledger()
        r = self.append(self.new_row("Acme receipt A1"), self.new_row("Acme receipt A2"))
        self.assertEqual((r.returncode, r.stdout), (0, "added 2, skipped 0 (evidence already in the ledger)\n"))
        after = self.ledger()
        self.assertTrue(after.startswith(before))
        self.assertEqual(after[len(before):].decode(),
                         "2026-03-01,2026-03-01,,Acme Cloud,Pro plan,subscription,20.00,USD,,shared,verified,gmail-receipt,Acme receipt A1\n"
                         "2026-03-01,2026-03-01,,Acme Cloud,Pro plan,subscription,20.00,USD,,shared,verified,gmail-receipt,Acme receipt A2\n")
        self.assertClean()

    def test_skips_evidence_already_in_the_ledger(self):
        r = self.append(self.new_row("  Acme receipt #1000-2000-3000 "), self.new_row("Acme receipt B1"))
        self.assertEqual(r.stdout, "added 1, skipped 1 (evidence already in the ledger)\n")
        self.assertEqual(self.ledger().count(b"Acme receipt #1000-2000-3000"), 1)

    def test_skips_duplicate_evidence_inside_the_input(self):
        r = self.append(self.new_row("Acme receipt C1"), self.new_row("Acme receipt C1", billed_cost="21.00"))
        self.assertEqual(r.stdout, "added 1, skipped 1 (evidence already in the ledger)\n")

    def test_nothing_to_add_leaves_the_file_untouched(self):
        path = self.dir / books.LEDGER
        os.utime(path, (1_000_000_000, 1_000_000_000))
        before = (self.ledger(), path.stat().st_mtime_ns)
        r = self.append(self.new_row("Acme receipt #1000-2000-3000"))
        self.assertEqual((r.returncode, r.stdout), (0, "added 0, skipped 1 (evidence already in the ledger)\n"))
        self.assertEqual((self.ledger(), path.stat().st_mtime_ns), before)

    def test_columns_not_given_stay_empty(self):
        r = self.run_cli("append", str(self.dir), self.rows_file(
            "evidence,charge_date,period_start,provider,service,charge_type,currency,project,status\n"
            "Acme invoice D1,2026-03-02,2026-03-01,Acme Cloud,Metered usage,usage,USD,unassigned,unknown\n"))
        self.assertEqual(r.returncode, 0, r.stdout)
        last = self.ledger().decode().splitlines()[-1]
        self.assertEqual(last, "2026-03-02,2026-03-01,,Acme Cloud,Metered usage,usage,,USD,,unassigned,unknown,,Acme invoice D1")

    def test_unknown_column_is_an_error_and_writes_nothing(self):
        before = self.ledger()
        r = self.append("E1,5", header="evidence,price")
        self.assertEqual(r.returncode, 2)
        self.assertIn("price", r.stderr)
        self.assertEqual(self.ledger(), before)

    def test_evidence_column_is_required(self):
        r = self.append("2026-03-01", header="charge_date")
        self.assertEqual(r.returncode, 2)

    def test_refused_by_check_leaves_file_identical(self):
        before = self.ledger()
        r = self.append(self.new_row("Acme receipt F1", service="card 4242 4242 4242 4242"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("forbidden content", r.stdout)
        self.assertTrue(r.stdout.endswith("refused, ledger unchanged\n"))
        self.assertNotIn("4242 4242", r.stdout)
        self.assertEqual(self.ledger(), before)

    def test_refused_when_a_new_row_breaks_a_rule(self):
        before = self.ledger()
        r = self.append(self.new_row("Acme receipt G1", status="verified", billed_cost=""))
        self.assertEqual(r.returncode, 1)
        self.assertIn("billed_cost is empty", r.stdout)
        self.assertEqual(self.ledger(), before)

    def test_existing_problem_blocks_append(self):
        self.append_row(status="maybe")
        before = self.ledger()
        r = self.append(self.new_row("Acme receipt H1"))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.endswith("refused, ledger unchanged\n"))
        self.assertEqual(self.ledger(), before)

    def test_existing_problem_blocks_even_when_nothing_to_add(self):
        self.append_row(status="maybe")
        r = self.append(self.new_row("Acme receipt #1000-2000-3000"))
        self.assertEqual(r.returncode, 1)

    def test_missing_trailing_newline_is_added(self):
        path = self.dir / books.LEDGER
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        r = self.append(self.new_row("Acme receipt I1"))
        self.assertEqual(r.returncode, 0, r.stdout)
        lines = self.ledger().decode().split("\n")
        self.assertEqual(len(lines), 6)  # header, 3 old rows, 1 new, trailing empty
        self.assertTrue(lines[4].endswith("Acme receipt I1"))
        self.assertClean()

    def test_no_temp_file_left_behind(self):
        self.append(self.new_row("Acme receipt J1"))
        self.assertEqual(sorted(p.name for p in (self.dir / "ledger").iterdir()), ["charges.csv"])


class SummaryTest(Case):
    # The fixture ledger holds January 2026: Acme Pro 20.00 (shared), Example AI credits 10.50
    # (widget, API-equivalent 12.25) and one unknown Acme usage row dated February. Envelope is 100, warning at 80%.
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT)] + list(args), capture_output=True, text=True)

    def summary(self, month="2026-01", as_of="2026-01-06"):
        r = self.run_cli("summary", str(self.dir), "--month", month, "--as-of", as_of, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_cash_by_provider_and_project(self):
        cash = self.summary()["cash"]
        self.assertEqual(cash, {"total": "30.50", "by_provider": {"Acme Cloud": "20.00", "Example AI": "10.50"},
                                "by_project": {"shared": "20.00", "widget": "10.50"}, "rows": 2})

    def test_unknown_row_is_listed_and_not_cash(self):
        s = self.summary(month="2026-02", as_of="2026-02-01")
        self.assertEqual(s["cash"]["total"], "0.00")
        self.assertEqual(s["unknown"], [{"line": 4, "charge_date": "2026-02-01", "provider": "Acme Cloud",
                                         "service": "Metered usage",
                                         "evidence": "Acme invoice 99887 (amount is in the PDF; not yet read)"}])
        self.assertEqual(self.summary()["unknown"][0]["line"], 4)  # open in every month's view

    def test_adjustment_can_be_negative(self):
        self.append_row(charge_date="2026-01-20", charge_type="adjustment", billed_cost="-5.00",
                        evidence="Acme credit note 7")
        self.assertEqual(self.summary()["cash"]["total"], "25.50")

    def test_usage_equivalent_is_not_cash(self):
        self.append_row(charge_date="2026-01-21", charge_type="usage-equivalent", billed_cost="99.00",
                        api_equivalent_cost="99.00", evidence="Acme log 1")
        s = self.summary()
        self.assertEqual(s["cash"]["total"], "30.50")
        self.assertEqual(s["api_equivalent"]["total"], "111.25")

    def test_api_equivalent_is_separate_and_by_project(self):
        self.assertEqual(self.summary()["api_equivalent"], {"total": "12.25", "by_project": {"widget": "12.25"}})

    def test_envelope_percentage(self):
        env = self.summary()["envelope"]
        self.assertEqual(env, {"usd": "100.00", "status": "proposed", "spent": "30.50", "pct": "30.5",
                               "warning_pct": 80, "over_warning": False, "over_envelope": False})

    def test_over_warning_flips_past_the_share(self):
        self.append_row(charge_date="2026-01-25", billed_cost="49.50", evidence="Acme receipt at80")
        env = self.summary()["envelope"]
        self.assertEqual((env["pct"], env["over_warning"]), ("80.0", False))  # exactly at the share is not past it
        self.append_row(charge_date="2026-01-26", billed_cost="0.01", evidence="Acme receipt over80")
        env = self.summary()["envelope"]
        self.assertEqual((env["pct"], env["over_warning"], env["over_envelope"]), ("80.0", True, False))
        self.append_row(charge_date="2026-01-27", billed_cost="30.00", evidence="Acme receipt over100")
        self.assertTrue(self.summary()["envelope"]["over_envelope"])

    def test_missing_envelope_is_null(self):
        self.write("budgets.yaml", "version: 1\nmonthly_envelope: {}\nalerts: {}\n")
        self.assertIsNone(self.summary()["envelope"])

    def test_yearly_charge_is_cash_once_and_a_monthly_equivalent(self):
        self.append_row(charge_date="2026-01-20", period_start="2026-01-20", period_end="2027-01-19",
                        service="Pro yearly", billed_cost="100.00", evidence="Acme receipt yearly")
        s = self.summary()
        self.assertEqual(s["cash"]["total"], "130.50")
        self.assertEqual(s["monthly_equivalent"]["lines"],
                         [{"provider": "Acme Cloud", "service": "Pro yearly", "billed_cost": "100.00",
                           "period_start": "2026-01-20", "period_end": "2027-01-19", "months": 12, "monthly": "8.33"}])
        self.assertEqual(s["monthly_equivalent"]["total"], "28.33")  # 20.00 monthly plan + 8.33
        self.assertEqual(self.summary(month="2026-09")["monthly_equivalent"]["total"], "8.33")  # mid-year
        self.assertEqual(self.summary(month="2027-02")["monthly_equivalent"]["total"], "0.00")  # lapsed

    def test_renewed_monthly_plan_counts_once_in_the_run_rate(self):
        self.append_row(charge_date="2026-02-04", period_start="2026-02-04", period_end="2026-03-05",
                        evidence="Acme receipt renew")
        self.assertEqual(self.summary(month="2026-02")["monthly_equivalent"]["total"], "20.00")

    def test_renewals_window_includes_day_30_and_excludes_day_31(self):
        self.assertEqual(self.summary(as_of="2026-01-06")["renewals"],
                         [{"vendor": "Acme Cloud", "plan": "Pro", "amount_usd": "20.00", "cadence": "monthly",
                           "next": "2026-02-05", "days": 30}])
        self.assertEqual(self.summary(as_of="2026-01-05")["renewals"], [])
        self.assertEqual(self.summary(as_of="2026-02-05")["renewals"][0]["days"], 0)
        self.assertEqual(self.summary(as_of="2026-02-06")["renewals"], [])

    def test_undated_renewal_is_listed_apart(self):
        self.assertEqual(self.summary()["renewals_undated"], [{"vendor": "Example AI", "plan": "unknown"}])

    def test_json_keys_and_string_money(self):
        s = self.summary()
        self.assertEqual(list(s), ["month", "as_of", "currency", "cash", "envelope", "monthly_equivalent",
                                   "renewals", "renewals_undated", "unknown", "api_equivalent"])
        self.assertEqual((s["month"], s["as_of"], s["currency"]), ("2026-01", "2026-01-06", "USD"))
        for value in (s["cash"]["total"], s["envelope"]["usd"], s["monthly_equivalent"]["total"],
                      s["api_equivalent"]["total"], *s["cash"]["by_provider"].values()):
            self.assertIsInstance(value, str)

    def test_rounds_half_up_only_at_output(self):
        for i in range(3):
            self.append_row(charge_date="2026-01-2%d" % i, billed_cost="0.005", evidence=f"Acme receipt tiny{i}")
        self.assertEqual(self.summary()["cash"]["total"], "30.52")  # 30.515 rounds up, not 3 x 0.01

    def test_text_output_sections_in_order(self):
        r = self.run_cli("summary", str(self.dir), "--month", "2026-01", "--as-of", "2026-01-06")
        self.assertEqual(r.returncode, 0, r.stderr)
        heads = ["Cash for 2026-01: $30.50", "  By provider:", "  By project:",
                 "Envelope: $30.50 of $100.00 (30.5%), warning at 80%, status proposed",
                 "Monthly equivalent", "Renewals in the next 30 days", "Unknown amounts", "API-equivalent"]
        at = [r.stdout.find(h) for h in heads]
        self.assertNotIn(-1, at, r.stdout)
        self.assertEqual(at, sorted(at))

    def test_refuses_on_a_broken_ledger(self):
        self.append_row(status="maybe")
        r = self.run_cli("summary", str(self.dir), "--month", "2026-01")
        self.assertEqual(r.returncode, 1)
        self.assertIn("status 'maybe'", r.stdout)
        self.assertNotIn("Cash for", r.stdout)

    def test_bad_month_and_as_of_are_usage_errors(self):
        self.assertEqual(self.run_cli("summary", str(self.dir), "--month", "2026-13").returncode, 2)
        self.assertEqual(self.run_cli("summary", str(self.dir), "--month", "2026-01", "--as-of", "soon").returncode, 2)


if __name__ == "__main__":
    unittest.main()
