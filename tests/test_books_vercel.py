"""Tests for `books.py vercel` (synthetic FOCUS data only: invented projects, no real ids or amounts)."""
import contextlib
import importlib.util
import io
import json
import random
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/cfo/skills/cfo-books/scripts/books.py"
BOOKS = ROOT / "tests/fixtures/books"

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
    resources: ["vercel:widget-site", "vercel:widget-docs"]
  gizmo:
    state: proposed
    resources: [vercel:gizmo-app]
"""


def focus(day, cost, project=None, category="Usage", hour=7, currency="USD", **extra):
    """One FOCUS JSON line for the Pacific day that starts at `hour`:00Z on `day` (a date)."""
    start = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
    obj = {"BilledCost": cost, "ChargePeriodStart": start.isoformat().replace("+00:00", ".000Z"),
           "ChargePeriodEnd": (start + timedelta(days=1)).isoformat().replace("+00:00", ".000Z"),
           "BillingCurrency": currency, "ChargeCategory": category, "ServiceName": "Function Storage",
           "SubAccountId": "team_synthetic", "Tags": {"ProjectName": project} if project else {}}
    obj.update(extra)
    raw = json.dumps(obj)
    if isinstance(cost, str):  # a literal such as 5.7e-10, written as a JSON number
        raw = raw.replace(json.dumps(cost), cost)
    return raw


def days(first, n):
    return [first + timedelta(days=i) for i in range(n)]


W41 = date(2026, 10, 5)  # Monday; Sunday is 2026-10-11
W42 = date(2026, 10, 12)
THROUGH = "2026-11-09"


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = books.main(list(argv))
    return code, out.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.dir = self.tmp / "books"
        shutil.copytree(BOOKS, self.dir)
        (self.dir / "projects.yaml").write_text(PROJECTS)

    def vercel(self, lines, *extra, through=THROUGH, expect=0):
        path = self.tmp / "focus.jsonl"
        path.write_text("\n".join(lines) + "\n")
        code, out = run("vercel", str(self.dir), str(path), "--through", through, "--json", *extra)
        self.assertEqual(code, expect, out)
        return json.loads(out) if expect == 0 else out

    def mine(self, result):
        return {r["evidence"]: (r["billed_cost"], r["service"]) for r in result["rows"]}

    def ledger(self):
        return (self.dir / books.LEDGER).read_text()


class MappingTest(Case):
    def week(self, *lines):
        # a full week plus the next Monday, so the week is closed
        return list(lines) + [focus(W42, "0", "widget-site")]

    def test_mapped_project_sums_exactly_and_rounds_half_up(self):
        r = self.vercel(self.week(focus(W41, "1.0025", "widget-site"), focus(W41 + timedelta(days=2), "1.0000", "widget-docs"),
                                  focus(W41 + timedelta(days=6), "0.0025", "widget-site")))
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:widget": ("2.01", "Vercel usage")})  # 2.005 up
        row = r["rows"][0]
        self.assertEqual((row["charge_date"], row["period_start"], row["period_end"]), ("2026-10-11", "2026-10-05", "2026-10-11"))
        self.assertEqual((row["provider"], row["charge_type"], row["currency"], row["api_equivalent_cost"]),
                         ("Vercel", "usage", "USD", ""))
        self.assertEqual((row["status"], row["source"]), ("verified", "vercel-focus"))

    def test_empty_tags_go_to_shared_and_unknown_project_to_unassigned(self):
        r = self.vercel(self.week(focus(W41, "3.00"), focus(W41, "4.00", "mystery"), focus(W41, "5.00", "gizmo-app")))
        self.assertEqual(self.mine(r), {
            "vercel-focus:2026-W41:gizmo": ("5.00", "Vercel usage"),
            "vercel-focus:2026-W41:shared": ("3.00", "Vercel usage"),
            "vercel-focus:2026-W41:unassigned": ("4.00", "Vercel usage")})
        self.assertEqual(r["unmapped_projects"], ["mystery"])

    def test_tags_without_a_project_name_are_team_level(self):
        r = self.vercel(self.week(focus(W41, "3.00", Tags={"Environment": "production"})))
        self.assertEqual(list(self.mine(r)), ["vercel-focus:2026-W41:shared"])

    def test_purchase_rows_are_skipped_and_counted(self):
        r = self.vercel(self.week(focus(W41, "20.00", category="Purchase"), focus(W41, "2.00", "gizmo-app")))
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("2.00", "Vercel usage")})
        self.assertEqual(r["purchase_rows_skipped"], 1)

    def test_a_project_listed_under_two_books_projects_is_an_error(self):
        (self.dir / "projects.yaml").write_text(PROJECTS.replace("vercel:gizmo-app", "vercel:widget-site"))
        with self.assertRaisesRegex(books.UsageError, "listed under both"):
            books.vercel_projects(books.load(self.dir))
        self.vercel(self.week(focus(W41, "1")), expect=2)


class WeekTest(Case):
    def test_sub_cent_week_is_one_usage_read_row(self):
        r = self.vercel([focus(W41 + timedelta(days=i), "0.0000000003", "widget-site") for i in range(7)] + [focus(W42, "0")])
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:shared": ("0.00", "usage read")})
        self.assertEqual(r["below_one_cent"], [])  # sub-cent, not a loss: it rounds to 0.00

    def test_a_week_with_one_project_above_a_cent_drops_the_sub_cent_ones(self):
        r = self.vercel([focus(W41, "0.004", "widget-site"), focus(W41, "0.50", "gizmo-app"), focus(W42, "0")])
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("0.50", "Vercel usage")})

    def test_dst_week_with_07z_and_08z_starts_stays_in_its_pacific_week(self):
        # PDT ends 2026-11-01: days before start at 07:00Z, days after at 08:00Z
        mon, sun = date(2026, 10, 26), date(2026, 11, 1)
        lines = [focus(mon + timedelta(days=i), "1.00", "widget-site", hour=7) for i in range(7)]
        lines += [focus(date(2026, 11, 2) + timedelta(days=i), "2.00", "widget-site", hour=8) for i in range(7)]
        r = self.vercel(lines)
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W44:widget": ("7.00", "Vercel usage"),
                                        "vercel-focus:2026-W45:widget": ("14.00", "Vercel usage")})
        self.assertEqual(sun.isocalendar()[1], 44)

    def test_open_weeks_are_not_written(self):
        full = [focus(W41 + timedelta(days=i), "1.00", "gizmo-app") for i in range(7)]
        partial = [focus(W42 + timedelta(days=i), "1.00", "gizmo-app") for i in range(3)]  # input ends Wednesday
        r = self.vercel(full + partial)
        self.assertEqual(list(self.mine(r)), ["vercel-focus:2026-W41:gizmo"])
        self.assertEqual(r["rows_outside_weeks"], 3)

    def test_week_not_before_through_is_open(self):
        lines = [focus(W41 + timedelta(days=i), "1.00", "gizmo-app") for i in range(14)]
        self.assertEqual(list(self.mine(self.vercel(lines, through="2026-10-18"))), ["vercel-focus:2026-W41:gizmo"])
        self.assertEqual(len(self.mine(self.vercel(lines, through="2026-10-19"))), 1)  # W42 already recorded below
        self.assertEqual(self.vercel(lines, through="2026-10-11")["weeks"], [])

    def test_a_week_with_no_input_rows_inside_the_range_is_still_read(self):
        r = self.vercel([focus(W41, "1.00", "gizmo-app"), focus(W41 + timedelta(days=14, hours=0), "1.00", "gizmo-app"),
                         focus(date(2026, 10, 25), "0")])
        self.assertEqual(r["weeks"], ["2026-W41", "2026-W42", "2026-W43"])
        self.assertEqual(self.mine(r)["vercel-focus:2026-W42:shared"], ("0.00", "usage read"))

    def test_rerun_adds_nothing_and_a_recorded_week_is_never_split(self):
        lines = [focus(W41, "1.00", "gizmo-app"), focus(W42, "0")]
        self.assertEqual(self.vercel(lines)["rows_added"], 1)
        after = self.ledger()
        again = self.vercel(lines)
        self.assertEqual((again["rows_added"], again["rows_skipped"]), (0, 1))
        late = self.vercel(lines + [focus(W41, "9.00", "widget-site")])
        self.assertEqual(late["rows_added"], 0)
        self.assertEqual(self.ledger(), after)

    def test_dry_run_writes_nothing(self):
        before = self.ledger()
        r = self.vercel([focus(W41, "1.00", "gizmo-app"), focus(W42, "0")], "--dry-run")
        self.assertEqual((r["rows_added"], r["dry_run"], self.ledger()), (1, True, before))

    def test_text_report_lists_rows_for_a_dry_run(self):
        path = self.tmp / "f.jsonl"
        path.write_text(focus(W41, "1.00", "gizmo-app") + "\n" + focus(W42, "0") + "\n")
        code, out = run("vercel", str(self.dir), str(path), "--through", THROUGH, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Rows would add: 1", out)
        self.assertIn("vercel-focus:2026-W41:gizmo", out)

    def test_appended_rows_pass_check(self):
        self.vercel([focus(W41, "1.00", "gizmo-app"), focus(W42, "0")])
        code, out = run("check", str(self.dir))
        self.assertEqual(code, 0, out)


class InputTest(Case):
    def test_bad_currency_names_the_line(self):
        out = self.vercel([focus(W41, "1"), focus(W41, "1", currency="EUR")], expect=2)
        self.assertEqual(out, "")  # the error goes to stderr
        path = self.tmp / "f.jsonl"
        path.write_text(focus(W41, "1") + "\n" + focus(W41, "1", currency="EUR") + "\n")
        with self.assertRaisesRegex(books.UsageError, "line 2: BillingCurrency is 'EUR'"):
            books.read_focus(path.read_text())

    def test_missing_field_names_the_line_and_field(self):
        good = json.loads(focus(W41, "1"))
        del good["ChargePeriodEnd"]
        with self.assertRaisesRegex(books.UsageError, "line 2: missing ChargePeriodEnd"):
            books.read_focus(focus(W41, "1") + "\n" + json.dumps(good))
        self.vercel([json.dumps(good)], expect=2)

    def test_non_json_lines_are_ignored_but_broken_json_is_an_error(self):
        rows = books.read_focus("Vercel CLI 1.2.3\n" + focus(W41, "1") + "\n\n")
        self.assertEqual(len(rows), 1)
        with self.assertRaisesRegex(books.UsageError, "line 1: not valid JSON"):
            books.read_focus('{"BilledCost": 1,')

    def test_empty_input_is_an_error_not_a_zero_week(self):
        self.vercel(["hint line only"], expect=2)

    def test_bad_cost_and_bad_through(self):
        with self.assertRaisesRegex(books.UsageError, "BilledCost is not a number"):
            books.read_focus(focus(W41, "1").replace('"BilledCost": 1', '"BilledCost": "1"'))
        with self.assertRaisesRegex(books.UsageError, "NaN is not a number"):
            books.read_focus(focus(W41, "1").replace('"BilledCost": 1', '"BilledCost": NaN'))
        code, _ = run("vercel", str(self.dir), str(self.tmp / "x"), "--through", "tomorrow")
        self.assertEqual(code, 2)

    def test_float_parsing_is_exact(self):
        rows = books.read_focus("\n".join([focus(W41, "0.1"), focus(W41, "0.2"), focus(W41, "5.7e-10")]))
        self.assertEqual([r.cost for r in rows], [Decimal("0.1"), Decimal("0.2"), Decimal("5.7E-10")])
        self.assertEqual(sum((r.cost for r in rows), Decimal(0)), Decimal("0.30000000057"))

    def test_a_float_that_sits_just_under_a_half_cent_still_rounds_up(self):
        # 1.005 is 1.00499999999999989... as a float; as text it is exactly 1.005
        r = self.vercel([focus(W41, "1.005", "gizmo-app"), focus(W42, "0")])
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("1.01", "Vercel usage")})

    def test_half_cent_boundary_rounds_up_exactly(self):
        r = self.vercel([focus(W41, "0.0049999999999999999999", "gizmo-app"), focus(W41, "0.0000000000000000000001", "gizmo-app"),
                         focus(W42, "0")])
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("0.01", "Vercel usage")})

    def test_no_team_or_project_ids_reach_the_output(self):
        r = self.vercel([focus(W41, "1", "gizmo-app", SubAccountId="team_secret", Tags={"ProjectName": "gizmo-app", "ProjectId": "prj_secret"}),
                         focus(W42, "0")])
        self.assertNotIn("secret", json.dumps(r) + self.ledger())


class PropertyTest(Case):
    """Random FOCUS data against an independent model: each row is its project's week total rounded
    half-up, every closed week has a row, and a second run adds nothing."""

    NAMES = ["widget-site", "widget-docs", "gizmo-app", "stray-one", "stray-two", None]
    MAPPED = {"widget-site": "widget", "widget-docs": "widget", "gizmo-app": "gizmo"}

    def generate(self, rng):
        first = date(2026, 9, 1) + timedelta(days=rng.randrange(0, 10))
        lines, model, row_days = [], {}, []
        last = first + timedelta(days=rng.randrange(3, 40))
        for day in days(first, (last - first).days + 1):
            hour = 7 if day <= date(2026, 11, 1) else 8
            for _ in range(rng.randrange(0, 4)):
                name = rng.choice(self.NAMES)
                cost = Decimal(rng.randrange(0, 40)) / Decimal(10 ** rng.randrange(0, 6)) * rng.choice([1, 1, 1, Decimal("0.0001")])
                category = "Purchase" if rng.random() < 0.05 else "Usage"
                lines.append(focus(day, format(cost, "f"), name, category, hour))
                row_days.append(day)
                if category != "Purchase":
                    key = "shared" if name is None else self.MAPPED.get(name, "unassigned")
                    model[(day, key)] = model.get((day, key), Decimal(0)) + cost
        lines.append(focus(last, "0"))
        return lines, min(row_days + [last]), last, model

    def expected(self, first, last, through, model):
        out, monday = {}, first - timedelta(days=first.weekday())
        while monday + timedelta(days=6) <= last and monday + timedelta(days=6) < through:
            week = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
            totals = {}
            for (day, key), cost in model.items():
                if monday <= day <= monday + timedelta(days=6):
                    totals[key] = totals.get(key, Decimal(0)) + cost
            kept = {k: v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for k, v in totals.items()}
            kept = {k: v for k, v in kept.items() if v >= Decimal("0.01")}
            out[week] = kept or {"shared": Decimal("0.00")}
            monday += timedelta(days=7)
        return out

    def test_random_weeks_match_the_model(self):
        rng = random.Random(20261115)
        for case in range(200):
            lines, first, last, model = self.generate(rng)
            through = date(2026, 11, 9)
            fresh = self.tmp / f"books{case}"
            shutil.copytree(BOOKS, fresh)
            (fresh / "projects.yaml").write_text(PROJECTS)
            path = self.tmp / f"focus{case}.jsonl"
            path.write_text("\n".join(lines) + "\n")
            args = ("vercel", str(fresh), str(path), "--through", through.isoformat(), "--json")
            code, out = run(*args)
            self.assertEqual(code, 0, f"case {case}: {out}")
            got = {}
            for row in json.loads(out)["rows"]:
                _, week, project = row["evidence"].split(":")
                got.setdefault(week, {})[project] = Decimal(row["billed_cost"])
            self.assertEqual(got, self.expected(first, last, through, model), f"case {case}")
            once = (fresh / books.LEDGER).read_bytes()
            code, out = run(*args)
            self.assertEqual((code, json.loads(out)["rows_added"], (fresh / books.LEDGER).read_bytes()), (0, 0, once), f"case {case}")
            shutil.rmtree(fresh)


if __name__ == "__main__":
    unittest.main()
