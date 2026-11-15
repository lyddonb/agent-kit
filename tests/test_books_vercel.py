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
    if isinstance(cost, str):  # a literal such as 3.1e-11, written as a JSON number
        raw = raw.replace(json.dumps(cost), cost)
    return raw


def days(first, n):
    return [first + timedelta(days=i) for i in range(n)]


SERVICES = ("Function Storage", "Edge Requests")


def grid(first, n, *extra):
    """n whole days from `first`, the way Vercel sends them: every series has a row each day, $0 unless `extra`
    (more FOCUS lines) says otherwise. The series are the two SERVICES plus every series `extra` mentions."""
    given = books.read_focus("\n".join(extra)) if extra else []
    templates = {(svc, "", "", "{}") for svc in SERVICES} | {r.series for r in given if r.category != "Purchase"}
    covered = {(r.series, r.day) for r in given if r.category != "Purchase"}
    lines = []
    for series in sorted(templates):
        fields = {"ServiceName": series[0], "Tags": json.loads(series[3])}
        fields.update({k: v for k, v in (("SkuId", series[1]), ("RegionId", series[2])) if v})
        lines += [focus(d, "0", **fields) for d in days(first, n) if (series, d) not in covered]
    return lines + list(extra)


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
        return json.loads(out) if expect in (0, 1) else out

    def mine(self, result):
        return {r["evidence"]: (r["billed_cost"], r["service"]) for r in result["rows"]}

    def ledger(self):
        return (self.dir / books.LEDGER).read_text()


class MappingTest(Case):
    def week(self, *lines):
        # one whole week, closed by THROUGH
        return grid(W41, 7, *lines)

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

    def test_week_the_input_starts_inside_is_incomplete(self):
        wednesday = W41 + timedelta(days=2)
        r = self.vercel(grid(wednesday, 12, *[focus(d, "1.00", "gizmo-app") for d in days(wednesday, 12)]), expect=1)  # Wed W41 to Sun W42
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W42:gizmo": ("7.00", "Vercel usage")})
        self.assertEqual(r["rows_outside_weeks"], 15)  # 5 days of 3 rows
        self.assertEqual(r["incomplete_weeks"], ["2026-W41"])

    def test_week_the_input_stops_inside_is_incomplete(self):
        r = self.vercel(grid(W41, 10, *[focus(d, "1.00", "gizmo-app") for d in days(W41, 10)]), expect=1)  # Mon W41 to Wed W42
        self.assertEqual(list(self.mine(r)), ["vercel-focus:2026-W41:gizmo"])
        self.assertEqual(r["incomplete_weeks"], ["2026-W42"])

    def test_input_of_only_purchase_rows_is_an_error(self):
        self.vercel([focus(d, "20.00", category="Purchase", ServiceName="Pro Plan") for d in days(W41, 7)], expect=2)

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
        r = self.vercel(grid(W41, 7, *[focus(W41 + timedelta(days=i), "0.0000000003", "widget-site") for i in range(7)]))
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:shared": ("0.00", "usage read")})
        self.assertEqual(r["below_one_cent"], [{"week": "2026-W41", "project": "widget", "cost": "0.0000000021"}])

    def test_a_week_with_one_project_above_a_cent_drops_the_sub_cent_ones(self):
        r = self.vercel(grid(W41, 7, focus(W41, "0.004", "widget-site"), focus(W41, "0.50", "gizmo-app")))
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("0.50", "Vercel usage")})
        self.assertEqual(r["below_one_cent"], [{"week": "2026-W41", "project": "widget", "cost": "0.004"}])

    def test_below_one_cent_lists_non_zero_costs_either_sign_and_never_zeros(self):
        r = self.vercel(grid(W41, 7, focus(W41, "-0.004", "widget-site"), focus(W41, "0.0049", "gizmo-app"),
                             focus(W41, "0.50", "stray")))
        self.assertEqual(r["below_one_cent"], [{"week": "2026-W41", "project": "gizmo", "cost": "0.0049"},
                                               {"week": "2026-W41", "project": "widget", "cost": "-0.004"}])
        self.assertEqual(self.vercel(grid(W41, 7))["below_one_cent"], [])  # an exact zero is not a loss

    def test_dst_week_with_07z_and_08z_starts_stays_in_its_pacific_week(self):
        # PDT ends 2026-11-01: days before start at 07:00Z, days after at 08:00Z
        mon, sun = date(2026, 10, 26), date(2026, 11, 1)
        lines = [focus(mon + timedelta(days=i), "1.00", "widget-site", hour=7) for i in range(7)]
        lines += [focus(date(2026, 11, 2) + timedelta(days=i), "2.00", "widget-site", hour=8) for i in range(7)]
        r = self.vercel(grid(mon, 14, *lines), through="2026-11-10")
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W44:widget": ("7.00", "Vercel usage"),
                                        "vercel-focus:2026-W45:widget": ("14.00", "Vercel usage")})
        self.assertEqual(sun.isocalendar()[1], 44)

    def test_open_weeks_are_not_written(self):
        r = self.vercel(grid(W41, 10, *[focus(W41 + timedelta(days=i), "1.00", "gizmo-app") for i in range(10)]), through="2026-10-14")  # ends Wednesday
        self.assertEqual(list(self.mine(r)), ["vercel-focus:2026-W41:gizmo"])
        self.assertEqual((r["rows_outside_weeks"], r["incomplete_weeks"]), (9, []))

    def test_a_week_closes_only_two_days_after_its_sunday(self):
        # Sunday Pacific ends Monday 07:00Z or 08:00Z, so a UTC "today" of Monday may still be inside it
        lines = grid(W41, 14)
        for through, weeks in (("2026-10-12", []), ("2026-10-13", ["2026-W41"]), ("2026-10-19", ["2026-W41"]),
                               ("2026-10-20", ["2026-W41", "2026-W42"])):
            with self.subTest(through):
                self.assertEqual(self.vercel(lines, "--dry-run", through=through)["weeks"], weeks)

    def test_a_week_with_no_input_rows_inside_the_range_is_incomplete_not_zero(self):
        lines = grid(W41, 7) + grid(W41 + timedelta(days=14), 7)  # nothing for W42
        r = self.vercel(lines, expect=1)  # the weekly run must notice
        self.assertEqual((r["weeks"], r["incomplete_weeks"]), (["2026-W41", "2026-W43"], ["2026-W42"]))
        self.assertEqual(sorted(self.mine(r)), ["vercel-focus:2026-W41:shared", "vercel-focus:2026-W43:shared"])
        self.assertNotIn("W42", self.ledger())

    def test_a_fetch_cut_off_mid_block_books_no_row_for_the_weeks_it_lost(self):
        # the real file: sorted by service, each service one block per region (and tag set), each block one row a day
        lines = [focus(d, "1.00", "gizmo-app", ServiceName=s, RegionId=r)
                 for s in ("Function Storage", "Edge Requests") for r in ("iad1", "sfo1", "fra1") for d in days(W41, 28)]  # W41-W44
        cut = lines[:5 * 28 + 10]  # the last region of the last service stops on day 10
        r = self.vercel(cut, expect=1)
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("42.00", "Vercel usage")})
        self.assertEqual(r["incomplete_weeks"], ["2026-W42", "2026-W43", "2026-W44"])
        path = self.tmp / "focus.jsonl"
        code, out = run("vercel", str(self.dir), str(path), "--through", THROUGH, "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("INCOMPLETE", out)
        self.assertIn("2026-W42, 2026-W43, 2026-W44", out)

    def test_a_cut_at_a_service_boundary_is_not_detected(self):
        # the known gap: a whole service missing leaves no trace in the file, so only the exit status of the fetch can tell
        lines = [focus(d, "1.00", ServiceName=s) for s in ("Function Storage", "Edge Requests", "Blob") for d in days(W41, 7)]
        self.assertEqual(self.vercel(lines[:14])["weeks"], ["2026-W41"])  # Blob never arrived

    def test_a_negative_week_total_is_booked_as_usage(self):
        r = self.vercel(grid(W41, 7, focus(W41, "-5.005", "gizmo-app"), focus(W41, "-0.004", "widget-site")))
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("-5.01", "Vercel usage")})
        self.assertEqual(r["rows"][0]["charge_type"], "usage")
        self.assertEqual(run("check", str(self.dir))[0], 0)

    def test_rerun_adds_nothing_and_a_recorded_week_is_never_split(self):
        lines = grid(W41, 7, focus(W41, "1.00", "gizmo-app"))
        self.assertEqual(self.vercel(lines)["rows_added"], 1)
        after = self.ledger()
        again = self.vercel(lines)
        self.assertEqual((again["rows_added"], again["rows_skipped"]), (0, 1))
        late = self.vercel(grid(W41, 7, focus(W41, "1.00", "gizmo-app"), focus(W41, "9.00", "widget-site")))
        self.assertEqual(late["rows_added"], 0)
        self.assertEqual(self.ledger(), after)

    def test_dry_run_writes_nothing(self):
        before = self.ledger()
        r = self.vercel(grid(W41, 7, focus(W41, "1.00", "gizmo-app")), "--dry-run")
        self.assertEqual((r["rows_added"], r["dry_run"], self.ledger()), (1, True, before))

    def test_text_report_lists_rows_for_a_dry_run(self):
        path = self.tmp / "f.jsonl"
        path.write_text("\n".join(grid(W41, 7, focus(W41, "1.00", "gizmo-app"))) + "\n")
        code, out = run("vercel", str(self.dir), str(path), "--through", THROUGH, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Rows would add: 1", out)
        self.assertIn("vercel-focus:2026-W41:gizmo", out)

    def test_appended_rows_pass_check(self):
        self.vercel(grid(W41, 7, focus(W41, "1.00", "gizmo-app")))
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
        rows = books.read_focus("\n".join([focus(W41, "0.1"), focus(W41, "0.2"), focus(W41, "3.1e-11")]))
        self.assertEqual([r.cost for r in rows], [Decimal("0.1"), Decimal("0.2"), Decimal("3.1E-11")])
        self.assertEqual(sum((r.cost for r in rows), Decimal(0)), Decimal("0.300000000031"))

    def test_a_float_that_sits_just_under_a_half_cent_still_rounds_up(self):
        # 1.005 is 1.00499999999999989... as a float; as text it is exactly 1.005
        r = self.vercel(grid(W41, 7, focus(W41, "1.005", "gizmo-app")))
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("1.01", "Vercel usage")})

    def test_half_cent_boundary_rounds_up_exactly(self):
        r = self.vercel(grid(W41, 7, focus(W41, "0.0049999999999999999999", "gizmo-app"),
                             focus(W41, "0.0000000000000000000001", "gizmo-app")))
        self.assertEqual(self.mine(r), {"vercel-focus:2026-W41:gizmo": ("0.01", "Vercel usage")})

    def test_no_team_or_project_ids_reach_the_output(self):
        r = self.vercel(grid(W41, 7, focus(W41, "1", "gizmo-app", SubAccountId="team_secret",
                                           Tags={"ProjectName": "gizmo-app", "ProjectId": "prj_secret"})))
        self.assertNotIn("secret", json.dumps(r) + self.ledger())


class PropertyTest(Case):
    """Random FOCUS files against an independent model. Each file is a full grid (every series a row
    every day, sorted by series then day like the real one), sometimes cut off. The model decides
    which weeks are complete and closed from the data alone, and prices them half-up."""

    NAMES = ["widget-site", "widget-docs", "gizmo-app", "stray-one", "stray-two", None]
    MAPPED = {"widget-site": "widget", "widget-docs": "widget", "gizmo-app": "gizmo"}
    SERIES = [("Function Storage", "sku_fs", "iad1"), ("Edge Requests", "sku_er", ""), ("Edge Requests", "", "sfo1"),
              ("Edge Requests", "", "iad1"), ("Blob", "", "")]

    def generate(self, rng):
        first = date(2026, 9, 1) + timedelta(days=rng.randrange(0, 10))
        last = first + timedelta(days=rng.randrange(3, 40))
        entries = []  # (series or None for a Purchase, day, project key, cost, line)
        for series in rng.sample(self.SERIES, rng.randrange(1, 5)):
            name = rng.choice(self.NAMES)  # a series carries one tag set for the whole file
            for day in days(first, (last - first).days + 1):
                cost = Decimal(rng.randrange(-5, 40)) / Decimal(10 ** rng.randrange(0, 6)) * rng.choice([1, 1, 1, Decimal("0.0001")])
                extra = {"ServiceName": series[0], **({"SkuId": series[1]} if series[1] else {}),
                         **({"RegionId": series[2]} if series[2] else {})}
                key = "shared" if name is None else self.MAPPED.get(name, "unassigned")
                entries.append((series, day, key, cost, focus(day, format(cost, "f"), name, "Usage", 7 if day <= date(2026, 11, 1) else 8, **extra)))
        for _ in range(rng.randrange(0, 3)):
            day = rng.choice(days(first, (last - first).days + 1))
            entries.append((None, day, None, Decimal(20), focus(day, "20.00", category="Purchase", ServiceName="Pro Plan")))
        if rng.random() < 0.5:
            entries = entries[:rng.randrange(1, len(entries))]
        return entries

    def expected(self, entries, through):
        first, last = min(e[1] for e in entries if e[0]), max(e[1] for e in entries if e[0])
        series = {e[0] for e in entries if e[0]}
        present = {(e[0], e[1]) for e in entries if e[0]}
        out, incomplete = {}, []
        monday = first - timedelta(days=first.weekday())  # the week the first usage row is in, whole or not
        while monday <= last:
            sunday = monday + timedelta(days=6)
            week = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
            if through >= sunday + timedelta(days=2):
                if first <= monday and sunday <= last and all((s, monday + timedelta(days=i)) in present for s in series for i in range(7)):
                    totals = {}
                    for s, day, key, cost, _ in entries:
                        if s and monday <= day <= sunday:
                            totals[key] = totals.get(key, Decimal(0)) + cost
                    kept = {k: v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for k, v in totals.items()}
                    kept = {k: v for k, v in kept.items() if abs(v) >= Decimal("0.01")}
                    out[week] = kept or {"shared": Decimal("0.00")}
                else:
                    incomplete.append(week)
            monday += timedelta(days=7)
        return out, incomplete

    def test_random_files_match_the_model(self):
        rng = random.Random(20261115)
        cut = 0
        for case in range(150):
            entries = self.generate(rng)
            first, last = min(e[1] for e in entries), max(e[1] for e in entries)
            through = first + timedelta(days=rng.randrange(0, (last - first).days + 6))
            fresh = self.tmp / f"books{case}"
            shutil.copytree(BOOKS, fresh)
            (fresh / "projects.yaml").write_text(PROJECTS)
            path = self.tmp / f"focus{case}.jsonl"
            path.write_text("\n".join(e[4] for e in entries) + "\n")
            args = ("vercel", str(fresh), str(path), "--through", through.isoformat(), "--json")
            want, want_incomplete = self.expected(entries, through)
            cut += bool(want_incomplete)
            code, out = run(*args)
            self.assertEqual(code, 1 if want_incomplete else 0, f"case {case}: {out}")
            result = json.loads(out)
            got = {}
            for row in result["rows"]:
                _, week, project = row["evidence"].split(":")
                got.setdefault(week, {})[project] = Decimal(row["billed_cost"])
            self.assertEqual(got, want, f"case {case}")
            self.assertEqual(result["incomplete_weeks"], want_incomplete, f"case {case}")
            once = (fresh / books.LEDGER).read_bytes()
            code, out = run(*args)
            self.assertEqual((code, json.loads(out)["rows_added"], (fresh / books.LEDGER).read_bytes()),
                             (1 if want_incomplete else 0, 0, once), f"case {case}")
            shutil.rmtree(fresh)
        self.assertGreater(cut, 8, "the generator must truncate often enough to test it")


if __name__ == "__main__":
    unittest.main()
