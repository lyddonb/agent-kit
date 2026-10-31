"""Tests for `books.py claude-code` and the pricing-age warning (synthetic logs only)."""
import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/cfo/skills/cfo-books/scripts/books.py"
BOOKS = ROOT / "tests/fixtures/books"
CC = ROOT / "tests/fixtures/claude-code"

spec = importlib.util.spec_from_file_location("books", SCRIPT)
books = importlib.util.module_from_spec(spec)
sys.modules["books"] = books
spec.loader.exec_module(books)

PROJECTS = """version: 1
projects:
  shared:
    state: active
  widget:
    state: proposed
  gizmo:
    state: proposed
  alpha:
    state: active
    paths: [/work/alpha]
  deep:
    state: active
    paths:
      - /work/alpha/deep
"""


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = books.main(list(argv))
    return code, out.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "books"
        shutil.copytree(BOOKS, self.dir)
        (self.dir / "projects.yaml").write_text(PROJECTS)
        self.logs = CC / "logs"
        saved = books.PRICING_FILE
        books.PRICING_FILE = CC / "pricing.json"
        self.addCleanup(setattr, books, "PRICING_FILE", saved)

    def cc(self, *extra, since="2026-10-19", until="2026-10-30", logs=None):
        code, out = run("claude-code", str(self.dir), "--since", since, "--until", until,
                        "--logs", str(logs or self.logs), "--json", *extra)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def totals(self, result):
        return {(t["week"], t["project"]): t for t in result["totals"]}

    def ledger(self):
        return (self.dir / books.LEDGER).read_text()


class PricingTest(Case):
    def test_price_math_per_project(self):
        t = self.totals(self.cc("--dry-run"))
        # alpha: m1 0.0825 (5m and 1h priced apart) + m2 0.0325 (unsplit write at 5m) + m6 fast 2 * 10.00
        self.assertEqual(t[("2026-W43", "alpha")]["api_equivalent_cost"], "20.12")  # 20.115 rounds half up
        # deep: m4 2.00 + 0.80, m7 fast on a model with no fast price stays at 2.00
        self.assertEqual(t[("2026-W43", "deep")]["api_equivalent_cost"], "4.80")
        # unassigned: m3 1.00 (/work/alphabet is not under /work/alpha) + m10 1.00
        self.assertEqual(t[("2026-W43", "unassigned")]["api_equivalent_cost"], "2.00")

    def test_token_sums_by_kind(self):
        k = self.totals(self.cc("--dry-run"))[("2026-W43", "alpha")]["tokens"]
        self.assertEqual(k, {"input": 1003000, "output": 500, "cache_write_5m": 2000,
                             "cache_write_1h": 2000, "cache_read": 10000})

    def test_duplicate_lines_count_once(self):
        r = self.cc("--dry-run")
        self.assertEqual(r["duplicates_dropped"], 1)
        self.assertEqual(r["messages_counted"], 8)  # m1..m7 and m10; the synthetic and user lines are not messages

    def test_partial_streamed_line_loses_to_the_final_one(self):
        with tempfile.TemporaryDirectory() as d:
            lines = []
            for out_tokens in (10, 400, 40):
                lines.append(json.dumps({"timestamp": "2026-10-20T10:00:00Z", "cwd": "/x", "requestId": "r",
                                         "message": {"id": "m", "model": "model-a",
                                                     "usage": {"input_tokens": 0, "output_tokens": out_tokens}}}))
            (Path(d) / "a.jsonl").write_text("\n".join(lines) + "\n")
            r = self.cc("--dry-run", logs=Path(d))
        self.assertEqual(r["totals"][0]["tokens"]["output"], 400)
        self.assertEqual(r["duplicates_dropped"], 2)

    def test_fast_priced_with_multiplier_and_reported_when_it_cannot_be(self):
        r = self.cc("--dry-run")
        self.assertEqual(r["speeds"], {"fast": 2, "standard": 6})
        self.assertEqual(r["nonstandard_speed_priced_at_standard"], 1)

    def test_unknown_model_is_listed_and_excluded(self):
        r = self.cc("--dry-run")
        self.assertEqual(r["unpriced_models"], {"model-unknown": {
            "input": 7, "output": 9, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0}})
        self.assertEqual(sum(Decimal(t["api_equivalent_cost"]) for t in r["totals"]), Decimal("26.92"))
        code, text = run("claude-code", str(self.dir), "--since", "2026-10-19", "--until", "2026-10-30",
                         "--logs", str(self.logs), "--dry-run")
        self.assertIn("model-unknown: input 7, output 9", text)
        self.assertIn("EXCLUDED", text)


class WeeksTest(Case):
    def test_partial_current_week_is_not_emitted(self):
        r = self.cc("--dry-run")
        self.assertEqual(r["weeks"], ["2026-W43"])
        self.assertEqual(r["messages_outside_weeks"], 2)  # m8 in W44, m9 in W42
        # W44 ends Sunday 2026-11-01: it is written only when --until is after that day
        self.assertEqual(self.cc("--dry-run", until="2026-11-01")["weeks"], ["2026-W43"])
        self.assertEqual(self.cc("--dry-run", until="2026-11-02")["weeks"], ["2026-W43", "2026-W44"])

    def test_since_rounds_down_to_monday(self):
        mid = self.cc("--dry-run", since="2026-10-22")  # a Thursday
        self.assertEqual(mid["totals"], self.cc("--dry-run", since="2026-10-19")["totals"])
        self.assertEqual(self.cc("--dry-run", since="2026-10-14")["weeks"], ["2026-W42", "2026-W43"])  # a Wednesday

    def test_offset_timestamp_is_read_in_utc(self):
        # m10 is 2026-10-26T01:00+02:00, which is Sunday 23:00 UTC, so week 43
        t = self.totals(self.cc("--dry-run"))
        self.assertEqual(t[("2026-W43", "unassigned")]["tokens"]["output"], 50000)


class RowsTest(Case):
    def test_dry_run_writes_nothing_and_shows_rows(self):
        before = self.ledger()
        code, out = run("claude-code", str(self.dir), "--since", "2026-10-19", "--until", "2026-10-30",
                        "--logs", str(self.logs), "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(self.ledger(), before)
        self.assertIn("Rows would add: 3", out)
        self.assertIn("claude-code:2026-W43:alpha", out)

    def test_rows_have_the_schema_values(self):
        self.cc()
        rows = {r.cells["project"]: r.cells for r in books.load(self.dir).rows if r.cells["source"] == "claude-code-logs"}
        self.assertEqual(rows["alpha"], {
            "charge_date": "2026-10-25", "period_start": "2026-10-19", "period_end": "2026-10-25",
            "provider": "Anthropic", "service": "Claude Code (API-equivalent)", "charge_type": "usage-equivalent",
            "billed_cost": "0", "currency": "USD", "api_equivalent_cost": "20.12", "project": "alpha",
            "status": "verified", "source": "claude-code-logs", "evidence": "claude-code:2026-W43:alpha"})
        self.assertEqual(books.run_checks(books.load(self.dir)), [])

    def test_rerun_adds_nothing(self):
        self.cc()
        once = self.ledger()
        r = self.cc()
        self.assertEqual((r["rows_added"], r["rows_skipped"]), (0, 3))
        self.assertEqual(self.ledger(), once)

    def test_no_log_text_reaches_the_ledger(self):
        self.cc()
        added = self.ledger().replace((BOOKS / "ledger/charges.csv").read_text(), "")
        for forbidden in ("/work", "synthetic text", "model-", "r1", '"m1"'):
            self.assertNotIn(forbidden, added)

    def test_refuses_when_the_books_are_not_clean(self):
        (self.dir / "projects.yaml").write_text(PROJECTS.replace("[/work/alpha]", "/work/alpha"))
        code, out = run("claude-code", str(self.dir), "--since", "2026-10-19", "--logs", str(self.logs))
        self.assertEqual(code, 1)
        self.assertIn("'paths' must be a list", out)


class ProjectMappingTest(Case):
    def test_longest_prefix_wins_on_component_boundaries(self):
        pairs = books.project_paths(books.load(self.dir))
        self.assertEqual(books.project_for("/work/alpha/deep/x", pairs), "deep")
        self.assertEqual(books.project_for("/work/alpha/deeper", pairs), "alpha")
        self.assertEqual(books.project_for("/work/alpha", pairs), "alpha")
        self.assertEqual(books.project_for("/work/alphabet", pairs), "unassigned")
        self.assertEqual(books.project_for("", pairs), "unassigned")

    def test_tilde_expands(self):
        (self.dir / "projects.yaml").write_text(PROJECTS.replace("/work/alpha]", "~/code/x]"))
        pairs = books.project_paths(books.load(self.dir))
        home = str(Path("~").expanduser())
        self.assertEqual(books.project_for(home + "/code/x/y", pairs), "alpha")


class PricingWarningTest(Case):
    def check(self, today):
        return run("check", str(self.dir), "--today", today)

    def test_fresh_pricing_has_no_warning(self):
        code, out = self.check("2026-12-30")  # 90 days after 2026-10-01
        self.assertEqual(code, 0)
        self.assertNotIn("warning", out)
        self.assertTrue(out.rstrip().endswith("0 problems"), out)

    def test_stale_pricing_warns_and_still_exits_zero(self):
        code, out = self.check("2026-12-31")  # 91 days
        self.assertEqual(code, 0)
        self.assertIn("scripts/pricing.json:3: warning: pricing is from 2026-10-01, 91 days old", out)
        self.assertTrue(out.rstrip().endswith("0 problems, 1 warning"), out)

    def test_warning_is_not_a_problem(self):
        books_loaded = books.load(self.dir)
        self.assertEqual(books.run_checks(books_loaded), [])
        self.assertEqual(len(books.run_warnings(books_loaded, date(2027, 6, 1))), 1)

    def test_unreadable_pricing_date_warns(self):
        books.PRICING_FILE = self.dir / "missing.json"
        code, out = self.check("2026-11-01")
        self.assertEqual(code, 0)
        self.assertIn("warning: cannot read the pricing date", out)

    def test_shipped_pricing_is_loadable_and_covers_the_models_in_use(self):
        p = books.load_pricing(ROOT / "plugins/cfo/skills/cfo-books/scripts/pricing.json")
        for model in ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"):
            self.assertIn(model, p.models)
        self.assertTrue(p.source.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
