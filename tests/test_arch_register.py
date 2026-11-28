"""Tests for the Head of Architecture's risk register (plugins/architecture/skills/arch-books)."""
import ast
import contextlib
import csv
import datetime
import importlib.util
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "plugins/architecture/skills/arch-books"
SCRIPT = SKILL / "scripts/arch.py"
SPEC = SKILL / "references/risk-lifecycle.md"
MACHINE_CHECKER = ROOT / "plugins/bstack/skills/state-machines/scripts/check-machine.py"

spec = importlib.util.spec_from_file_location("arch", SCRIPT)
arch = importlib.util.module_from_spec(spec)
sys.modules["arch"] = arch
spec.loader.exec_module(arch)

RUBRIC = (
    "failure_mode,consequence,likelihood,detection,why\n"
    "single-host,4,2,2,one machine runs it\n"
    "stale-pin,2,2,2,an old pin\n"
    "quiet-job,3,3,4,a job stopped without a sign\n"
    "slow-restore,3,3,2,restores take long\n"
    "tiny,1,2,3,small and loud\n"
)
RUBRIC_SCORES = {"single-host": (4, 2, 2), "stale-pin": (2, 2, 2), "quiet-job": (3, 3, 4),
                 "slow-restore": (3, 3, 2), "tiny": (1, 2, 3)}
HEADER = ",".join(arch.RISK_COLUMNS)
DAY = "2026-11-01"


def row(risk_id="A1", date=DAY, event="observe", **cells):
    values = {column: "" for column in arch.RISK_COLUMNS}
    values.update(risk_id=risk_id, date=date, event=event)
    values.update(cells)
    return ",".join(_cell(values[column]) for column in arch.RISK_COLUMNS)


def _cell(text):
    return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n\r') else text


def legal_row(event, risk_id="A1", date=DAY, failure_mode="single-host", component="web-app"):
    if event == "observe":
        return row(risk_id, date, event, component=component, failure_mode=failure_mode, evidence="seen in review")
    if event in arch.SCORED_EVENTS:
        c, l, d = RUBRIC_SCORES[failure_mode]
        return row(risk_id, date, event, consequence=str(c), likelihood=str(l), detection=str(d),
                   evidence="" if event == "open" else "the user's answer", question="" if event == "open" else "Q3")
    if event == "propose":
        return row(risk_id, date, event, question="Q3")
    if event in ("accept", "decline"):
        return row(risk_id, date, event, evidence="evidence for " + event, question="Q3")
    if event == "close":
        return row(risk_id, date, event, evidence="receipt: probe failed before, passes now")
    return row(risk_id, date, event, evidence="evidence for " + event)


def shortest_paths():
    paths = {arch.UNSEEN: []}
    queue = deque([arch.UNSEEN])
    while queue:
        state = queue.popleft()
        for (source, event), target in arch.TRANSITIONS.items():
            if source == state and target not in paths:
                paths[target] = paths[state] + [event]
                queue.append(target)
    return paths


PATHS = shortest_paths()


class Books:
    def __init__(self, test, rows=(), rubric=RUBRIC):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(self.cleanup)
        self.write_rubric(rubric)
        self.write_rows(rows)

    def cleanup(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_rubric(self, text):
        (self.dir / "rubric.csv").write_text(text)

    def write_rows(self, rows):
        (self.dir / "risks.csv").write_text("\n".join([HEADER, *rows]) + "\n")

    def run(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = arch.main([args[0], str(self.dir), *args[1:]])
        return code, out.getvalue(), err.getvalue()

    def summary(self):
        code, out, err = self.run("summary", "--json")
        return code, (json.loads(out) if out else None), err


def life(risk_id="A1", failure_mode="single-host", events=None, date=DAY):
    events = PATHS["closed"] if events is None else events
    return [legal_row(e, risk_id, date, failure_mode) for e in events]


class Case(unittest.TestCase):
    def books(self, rows=(), rubric=RUBRIC):
        return Books(self, rows, rubric)

    def assertProblem(self, books, text, step, *args):
        code, out, _ = books.run("check", *args)
        self.assertEqual(code, 1, f"{step}: check should fail\n{out}")
        self.assertIn(text, out, f"{step}: check should say {text!r}\n{out}")
        return out


class LifecycleTests(Case):
    def test_full_legal_life_folds_to_closed(self):
        books = self.books(life(events=["observe", "open", "propose", "accept", "mitigate", "close"]))
        code, out, _ = books.run("check")
        self.assertEqual((code, out), (0, "ok, 6 rows, 0 problems\n"), "a legal full life passes check")
        _, summary, _ = books.summary()
        self.assertEqual(summary["risks"][0]["state"], "closed", "observe..close with a receipt folds to closed")
        self.assertEqual(summary["risks"][0]["events"], 6, "the summary counts every event")

    def test_close_needs_a_receipt(self):
        prefix = life(events=["observe", "open", "propose", "accept", "mitigate"])
        for evidence in ("merged in PR 12", "Receipt: yes", "receipt:"):
            books = self.books(prefix + [row("A1", DAY, "close", evidence=evidence)])
            self.assertProblem(books, "close evidence must start with receipt:", f"close with evidence {evidence!r}")
        books = self.books(prefix + [row("A1", DAY, "close")])
        self.assertProblem(books, "close needs evidence", "close with no evidence")

    def test_close_from_any_other_state_fails(self):
        for state, path in PATHS.items():
            if state == "mitigating":
                continue
            books = self.books(life(events=path) + [legal_row("close")])
            self.assertProblem(books, f"illegal move: close from {state}", f"close from {state}")

    def test_every_illegal_pair_fails_with_exactly_that_problem(self):
        illegal = [(s, e) for s in arch.STATES for e in arch.EVENTS if (s, e) not in arch.TRANSITIONS]
        self.assertGreater(len(illegal), 50, "the table leaves most pairs illegal")
        for state, event in illegal:
            books = self.books(life(events=PATHS[state]) + [legal_row(event)])
            code, out, _ = books.run("check")
            self.assertEqual(code, 1, f"{event} from {state} must fail check")
            problems = [line for line in out.splitlines() if line.startswith("risks.csv:")]
            self.assertEqual(len(problems), 1, f"{event} from {state} fails for one reason only:\n{out}")
            self.assertIn(f"illegal move: {event} from {state}", problems[0], f"{event} from {state} names the move")

    def test_every_legal_pair_passes(self):
        for (state, event), target in arch.TRANSITIONS.items():
            books = self.books(life(events=PATHS[state]) + [legal_row(event)])
            code, out, _ = books.run("check")
            self.assertEqual(code, 0, f"{event} from {state} is legal:\n{out}")
            self.assertEqual(books.summary()[1]["risks"][0]["state"], target, f"{event} from {state} lands in {target}")

    def test_code_table_matches_the_spec(self):
        done = subprocess.run([sys.executable, str(MACHINE_CHECKER), str(SPEC), "--json"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, f"the spec passes the state-machines checker:\n{done.stderr}")
        machine = json.loads(done.stdout[done.stdout.index("{"):])
        self.assertEqual(tuple(machine["states"]), arch.STATES, "spec and code list the same states in order")
        self.assertEqual(tuple(machine["events"]), arch.EVENTS, "spec and code list the same events in order")
        self.assertEqual(machine["initial"], arch.UNSEEN, "the spec starts at unseen")
        moves = {(t["state"], t["event"]): t["next"] for t in machine["transitions"] if t["next"] in arch.STATES}
        self.assertEqual(moves, arch.TRANSITIONS, "the spec's moves are the code's TRANSITIONS")

    def test_only_close_reaches_closed(self):
        reaching = {event for (_, event), target in arch.TRANSITIONS.items() if target == "closed"}
        self.assertEqual(reaching, {"close"}, "no event but close moves a risk to closed")


class RandomSequenceTests(Case):
    def test_random_sequences_never_crash_or_split_a_risk(self):
        rng = random.Random(20261127)
        books = self.books()
        passed = failed = 0
        for _ in range(600):
            rows, state = [], {}
            for _ in range(rng.randint(1, 14)):
                risk_id = f"A{rng.randint(1, 3)}"
                current = state.get(risk_id, arch.UNSEEN)
                legal = [e for e in arch.EVENTS if (current, e) in arch.TRANSITIONS]
                event = rng.choice(legal) if legal and rng.random() < 0.8 else rng.choice(arch.EVENTS)
                line = legal_row(event, risk_id)
                if rng.random() < 0.12:
                    line = self.corrupt(rng, line)
                rows.append(line)
                state[risk_id] = arch.TRANSITIONS.get((current, event), current)
            books.write_rows(rows)
            code, out, _ = books.run("check")
            self.assertIn(code, (0, 1), "check exits 0 or 1 on any rows")
            scode, summary, _ = books.summary()
            if code == 0:
                passed += 1
                self.assertEqual(scode, 0, "books that pass check can be summarized")
                ids = [r["risk_id"] for r in summary["risks"]]
                self.assertEqual(len(ids), len(set(ids)), "a risk appears once, in one state")
                self.assertEqual({r["risk_id"]: r["state"] for r in summary["risks"]}, state,
                                 "each risk folds to the state its legal moves led to")
                self.assertTrue(all(r["state"] in arch.STATES for r in summary["risks"]), "every state is legal")
            else:
                failed += 1
                self.assertEqual((scode, summary), (1, None), "books that fail check are not summarized")
        self.assertGreaterEqual(passed, 100, "the generator reaches passing books often enough to mean something")
        self.assertGreaterEqual(failed, 100, "the generator reaches failing books often enough to mean something")

    @staticmethod
    def corrupt(rng, line):
        return rng.choice([
            line.replace(",2026-", ",2025-", 1),
            line.replace("A", "B", 1),
            line + ",extra",
            line.replace(",open,", ",opn,", 1),
            "=" + line,
            line.replace("single-host", "unknown-mode"),
        ])


class SummaryTests(Case):
    def test_summary_is_byte_identical_across_runs_and_hash_seeds(self):
        books = self.books(life("A1") + life("A2", "stale-pin", PATHS["open"]) + life("A10", "quiet-job", PATHS["observed"]))
        outputs = []
        for seed in ("1", "2", "3"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            done = subprocess.run([sys.executable, str(SCRIPT), "summary", str(books.dir), "--json"],
                                  capture_output=True, env=env)
            self.assertEqual(done.returncode, 0, f"summary runs with hash seed {seed}: {done.stderr!r}")
            outputs.append(done.stdout)
        self.assertEqual(len(set(outputs)), 1, "summary --json gives the same bytes on every run")
        self.assertEqual(books.run("summary", "--json")[1].encode(), outputs[0], "in-process and subprocess runs agree")

    def test_summary_shape_and_ranking(self):
        books = self.books(
            life("A2", "stale-pin", PATHS["open"]) + life("A10", "single-host", PATHS["open"])
            + life("A3", "quiet-job", PATHS["open"]) + life("A1", "tiny", PATHS["observed"])
            + life("A4", "tiny", PATHS["open"]))
        _, summary, _ = books.summary()
        self.assertEqual(summary["version"], 1, "the summary says its version")
        ranked = [(r["risk_id"], r["tier"], r["score"]) for r in summary["risks"]]
        self.assertEqual(ranked, [("A3", "P0", 36), ("A10", "P0", 16), ("A2", "P2", 8), ("A4", "P3", 6), ("A1", None, None)],
                         "risks sort by tier, then score descending, then id numerically, observed last")
        self.assertEqual(summary["counts"]["by_state"]["open"], 4, "counts by state")
        self.assertEqual(summary["counts"]["by_state"]["closed"], 0, "states with no risk count zero")
        self.assertEqual(summary["counts"]["by_tier"], {"P0": 2, "P1": 0, "P2": 1, "P3": 1}, "observed risks have no tier")
        self.assertEqual(summary["counts"]["live"], 4, "four risks are live")
        first = summary["risks"][-1]
        self.assertEqual((first["score"], first["tier"], first["consequence"]), (None, None, None), "observed is unscored")
        for record in summary["risks"]:
            self.assertTrue(all(isinstance(v, (int, str, type(None))) for v in record.values()), "integers and strings only")

    def test_summary_refuses_books_that_fail_the_row_rules(self):
        books = self.books(life(events=["observe", "propose"]))
        code, out, err = books.run("summary", "--json")
        self.assertEqual((code, out), (1, ""), "summary prints nothing for bad books")
        self.assertIn("illegal move: propose from observed", err, "summary says why on stderr")

    def test_tier_boundaries(self):
        self.assertEqual(arch.tier(4, 2, 8), "P0", "(4,2,1) is P0 by the consequence rule")
        self.assertEqual(arch.tier(4, 1, 16), "P2", "consequence 4 with likelihood 1 is not P0 by itself")
        self.assertEqual(arch.tier(3, 3, 36), "P0", "score 36 is P0")
        self.assertEqual(arch.tier(3, 3, 35), "P1", "score 35 is P1")
        self.assertEqual(arch.tier(3, 3, 18), "P1", "score 18 is P1")
        self.assertEqual(arch.tier(3, 3, 17), "P2", "score 17 is P2")
        self.assertEqual(arch.tier(2, 2, 8), "P2", "score 8 is P2")
        self.assertEqual(arch.tier(2, 2, 7), "P3", "score 7 is P3")

    def test_tier_boundaries_through_the_summary(self):
        cases = [("single-host", "P0", 16), ("quiet-job", "P0", 36), ("slow-restore", "P1", 18),
                 ("stale-pin", "P2", 8), ("tiny", "P3", 6)]
        rows = []
        for number, (mode, _, _) in enumerate(cases, 1):
            rows += life(f"A{number}", mode, PATHS["open"])
        _, summary, _ = self.books(rows).summary()
        got = {r["failure_mode"]: (r["tier"], r["score"]) for r in summary["risks"]}
        self.assertEqual(got, {mode: (t, s) for mode, t, s in cases}, "the rubric's scores give these tiers")

    def test_open_scores_must_equal_the_rubric(self):
        for scores in ((4, 2, 1), (3, 2, 2), (4, 2, 3)):
            c, l, d = scores
            books = self.books([legal_row("observe"), row("A1", DAY, "open", consequence=str(c), likelihood=str(l), detection=str(d))])
            self.assertProblem(books, "open scores must equal the rubric.csv row for single-host", f"open with {scores}")

    def test_rescore_with_evidence_changes_the_scores(self):
        books = self.books(life(events=["observe", "open"]))
        before = books.summary()[1]["risks"][0]
        books.write_rows(life(events=["observe", "open"])
                         + [row("A1", DAY, "rescore", consequence="1", likelihood="1", detection="1", evidence="the user says it moved", question="Q4")])
        self.assertEqual(books.run("check")[0], 0, "a rescore with evidence passes")
        after = books.summary()[1]["risks"][0]
        self.assertEqual((before["score"], before["tier"]), (16, "P0"), "the rubric scores before the rescore")
        self.assertEqual((after["score"], after["tier"], after["state"]), (1, "P3", "open"), "later rows use the rescored values")
        books.write_rows(life(events=["observe", "open"]) + [row("A1", DAY, "rescore", consequence="1", likelihood="1", detection="1", question="Q4")])
        self.assertProblem(books, "rescore needs evidence", "rescore without evidence")

    def test_propose_records_the_question_and_reopen_keeps_scores(self):
        books = self.books(life(events=["observe", "open", "propose", "decline", "reopen"]))
        record = books.summary()[1]["risks"][0]
        self.assertEqual((record["state"], record["question"], record["score"]), ("open", "Q3", 16),
                         "a reopened risk keeps its question and scores")


class RowRuleTests(Case):
    def test_each_malformed_row_is_reported_with_its_line(self):
        observe = legal_row("observe", "A9")
        cases = {
            "risk_id must be A followed by digits": row("a1", DAY, "observe", component="x", failure_mode="tiny", evidence="e"),
            "leading zero": row("A01", DAY, "observe", component="x", failure_mode="tiny", evidence="e"),
            "date must be a real date": row("A1", "2026-02-30", "observe", component="x", failure_mode="tiny", evidence="e"),
            "date must be a real date like": row("A1", "20261127", "observe", component="x", failure_mode="tiny", evidence="e"),
            "event must be one of": row("A1", DAY, "ignore"),
            "failure_mode nope is not in rubric.csv": row("A1", DAY, "observe", component="x", failure_mode="nope", evidence="e"),
            "observe needs component": row("A1", DAY, "observe", failure_mode="tiny", evidence="e"),
            "observe needs evidence": row("A1", DAY, "observe", component="x", failure_mode="tiny"),
            "consequence must be an integer from 1 to 4": row("A1", DAY, "open", consequence="5", likelihood="1", detection="1"),
            "the three scores come together": row("A1", DAY, "open", consequence="1"),
            "question must look like Q3": row("A1", DAY, "propose", question="3"),
        }
        for message, bad in cases.items():
            books = self.books([observe, bad])
            out = self.assertProblem(books, message, f"row rule {message!r}")
            self.assertIn("risks.csv:3:", out, f"{message!r} is reported on line 3")

    def test_scores_only_where_the_event_carries_them(self):
        books = self.books(life(events=["observe", "open"]) + [row("A1", DAY, "propose", question="Q1", consequence="1", likelihood="1", detection="1")])
        self.assertProblem(books, "propose does not carry scores", "scores on propose")
        books = self.books(life(events=["observe", "open"]) + [row("A1", DAY, "propose", question="Q1"), row("A1", DAY, "accept", evidence="x", question="Q3"), row("A1", DAY, "mitigate", evidence="x", question="Q3")])
        self.assertProblem(books, "mitigate does not carry a question", "question on mitigate")

    def test_component_and_failure_mode_are_fixed_by_observe(self):
        later = life(events=["observe", "open"])
        for column, value in (("component", "other-app"), ("failure_mode", "tiny")):
            books = self.books(later + [row("A1", DAY, "rescore", consequence="1", likelihood="1", detection="1", evidence="e", question="Q4", **{column: value})])
            self.assertProblem(books, f"{column} is fixed by the observe row", f"{column} changed on a later row")
        books = self.books(later + [row("A1", DAY, "rescore", consequence="1", likelihood="1", detection="1", evidence="e", question="Q4",
                                        component="web-app", failure_mode="single-host")])
        self.assertEqual(books.run("check")[0], 0, "repeating them is fine")

    def test_dates_never_go_back_within_a_risk(self):
        books = self.books([legal_row("observe", date="2026-11-05"), legal_row("open", date="2026-11-04")])
        self.assertProblem(books, "earlier than this risk's previous row", "an earlier date")
        books = self.books([legal_row("observe", "A1", "2026-11-05"), legal_row("observe", "A2", "2026-11-01")])
        self.assertEqual(books.run("check")[0], 0, "another risk may have an earlier date")

    def test_header_files_and_encoding(self):
        books = self.books()
        (books.dir / "risks.csv").write_text("risk_id,date\n")
        self.assertProblem(books, "header must be exactly risk_id,date,event", "a wrong header")
        (books.dir / "risks.csv").write_bytes(b"")
        self.assertProblem(books, "header must be exactly", "an empty file")
        (books.dir / "risks.csv").write_bytes(b"\xef\xbb\xbf" + HEADER.encode() + b"\n")
        self.assertProblem(books, "header must be exactly", "a byte order mark")
        (books.dir / "risks.csv").write_bytes(HEADER.encode() + b"\n" + b"A1,\xff\n")
        self.assertProblem(books, "not valid UTF-8", "bytes that are not UTF-8")
        (books.dir / "risks.csv").write_text(HEADER + "\n" + legal_row("observe"))
        self.assertProblem(books, "must end with a newline", "no final newline")
        (books.dir / "risks.csv").write_text(HEADER + '\n"A1,2026\n')
        self.assertProblem(books, "", "an unterminated quote")
        books.write_rows(["", legal_row("observe")])
        self.assertProblem(books, "empty line", "a blank line")
        books.write_rows([legal_row("observe") + ",extra"])
        self.assertProblem(books, "has 12 cells, expected 11", "a long row")

    def test_missing_input_exits_two(self):
        books = self.books()
        for command in ("check", "summary"):
            (books.dir / "rubric.csv").unlink()
            code, _, err = books.run(command)
            self.assertEqual(code, 2, f"{command} with no rubric.csv exits 2")
            self.assertIn("rubric.csv", err, "and names the file")
            books.write_rubric(RUBRIC)
            (books.dir / "risks.csv").unlink()
            self.assertEqual(books.run(command)[0], 2, f"{command} with no risks.csv exits 2")
            books.write_rows([])
        code, _, _ = arch_main_with(["check", str(books.dir / "nowhere")])
        self.assertEqual(code, 2, "a missing books folder exits 2")

    def test_rubric_rules(self):
        for text, message in (
            ("failure_mode,consequence\n", "header must be exactly failure_mode,consequence,likelihood,detection,why"),
            (RUBRIC + "tiny,1,1,1,again\n", "failure_mode tiny is listed twice"),
            (RUBRIC + "wide,5,1,1,too big\n", "consequence must be an integer from 1 to 4"),
            (RUBRIC + ",1,1,1,no name\n", "failure_mode is empty"),
            (RUBRIC + "=cmd,1,1,1,formula\n", "starts with ="),
        ):
            self.assertProblem(self.books(rubric=text), message, f"rubric {message!r}")


def arch_main_with(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = arch.main(argv)
    return code, out.getvalue(), err.getvalue()


class TextHygieneTests(Case):
    def test_cells_a_spreadsheet_would_run_fail(self):
        for start in ("=", "+", "-", "@", "\uff1d", "\uff0b"):
            books = self.books([legal_row("observe"), row("A1", DAY, "open", consequence="4", likelihood="2", detection="2", note=start + "SUM(A1)")])
            self.assertProblem(books, "starts with = + - or @", f"a note starting with {start!r}")
        books = self.books([legal_row("observe").replace("seen in review", "=cmd|' /C calc'!A0")])
        self.assertProblem(books, "evidence starts with", "a formula in evidence")

    def test_control_characters_fail(self):
        for bad in ("\x07", "\x1b[31m", "\x00", "\x7f", "\x85", "\u202e", "\u200b", "\ufeff", "a\nb", "a\tb", "a\rb",
                    "\u00ad", "\u061c", "\u200e", "\u200f", "\u2060", "\ue000", "\u2028", "\u2029"):
            books = self.books([row("A1", DAY, "observe", component="x", failure_mode="tiny", evidence="seen" + bad + "here")])
            self.assertProblem(books, "control or invisible character", f"evidence containing {bad!r}")

    def test_cell_length_limit(self):
        ok = self.books([row("A1", DAY, "observe", component="x", failure_mode="tiny", evidence="e" * 1000)])
        self.assertEqual(ok.run("check")[0], 0, "1000 characters is allowed")
        long = self.books([row("A1", DAY, "observe", component="x", failure_mode="tiny", evidence="e" * 1001)])
        self.assertProblem(long, "longer than 1000 characters", "1001 characters")

    def test_a_minus_inside_a_cell_is_fine(self):
        books = self.books([row("A1", DAY, "observe", component="web-app", failure_mode="single-host", evidence="seen - twice, in a=b")])
        self.assertEqual(books.run("check")[0], 0, "only the first character counts")


class AppendOnlyTests(Case):
    def git(self, books, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        return subprocess.run(["git", "-C", str(books.dir), "-c", "user.name=t", "-c", "user.email=t@example.com",
                               "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, env=env)

    def committed(self):
        books = self.books(life(events=["observe", "open", "propose"]) + life("A2", "stale-pin", ["observe"]))
        self.git(books, "init", "-q")
        self.git(books, "add", ".")
        self.git(books, "commit", "-q", "-m", "books")
        return books

    def test_unchanged_and_appended_rows_pass(self):
        books = self.committed()
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "an unchanged register passes")
        with open(books.dir / "risks.csv", "a") as handle:
            handle.write(legal_row("accept") + "\n" + legal_row("open", "A2", failure_mode="stale-pin") + "\n")
        self.assertEqual(books.run("check", "--base", "HEAD")[1], "ok, 6 rows, 0 problems\n", "appended rows pass")

    def test_editing_one_character_of_a_past_row_fails(self):
        books = self.committed()
        path = books.dir / "risks.csv"
        path.write_text(path.read_text().replace("seen in review", "seen in reviev", 1))
        out = self.assertProblem(books, "a past row was edited or deleted", "one character edited", "--base", "HEAD")
        self.assertIn("risks.csv:2:", out, "it names the edited row's line")

    def test_deleting_a_past_row_fails(self):
        books = self.committed()
        path = books.dir / "risks.csv"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:2] + lines[3:]) + "\n")
        self.assertProblem(books, "a past row was edited or deleted", "a middle row deleted", "--base", "HEAD")
        path.write_text("\n".join(lines[:-1]) + "\n")
        self.assertProblem(books, "a past row was edited or deleted", "the last row deleted", "--base", "HEAD")

    def test_a_row_inserted_before_a_past_row_fails(self):
        books = self.committed()
        path = books.dir / "risks.csv"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:2] + [legal_row("observe", "A9")] + lines[2:]) + "\n")
        self.assertProblem(books, "a past row was edited or deleted", "a row inserted into history", "--base", "HEAD")

    def test_a_base_that_is_not_usable_is_a_problem(self):
        books = self.committed()
        self.assertProblem(books, "cannot check against nope", "an unknown ref", "--base", "nope")
        self.assertProblem(books, "cannot check against --help", "a ref that looks like a flag", "--base=--help")
        nested = Path(books.dir) / "inner"
        nested.mkdir()
        (nested / "risks.csv").write_text(HEADER + "\n")
        (nested / "rubric.csv").write_text(RUBRIC)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = arch.main(["check", str(nested), "--base", "HEAD"])
        self.assertEqual(code, 1, "a books folder inside a bigger repo cannot be checked against a ref")
        self.assertIn("top level of its git work tree", out.getvalue(), "and says why")

    def test_a_file_new_since_the_base_passes(self):
        books = self.committed()
        self.git(books, "rm", "-q", "--cached", "risks.csv")
        self.git(books, "commit", "-q", "-m", "drop")
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "no risks.csv at the base means nothing to compare")


class ScriptTests(Case):
    def test_exit_codes_from_the_command_line(self):
        books = self.books(life())
        run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, text=True)
        self.assertEqual(run("check", str(books.dir)).returncode, 0, "a clean register exits 0")
        books.write_rows([legal_row("close")])
        self.assertEqual(run("check", str(books.dir)).returncode, 1, "a bad register exits 1")
        self.assertEqual(run("check", str(books.dir / "none")).returncode, 2, "a missing folder exits 2")
        self.assertEqual(run().returncode, 2, "no command exits 2")

    def test_script_imports_nothing_that_can_reach_the_network(self):
        banned = {"urllib", "http", "socket", "requests", "ssl", "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio", "importlib"}
        tree = ast.parse(SCRIPT.read_text())
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0])
            elif isinstance(node, ast.Name) and node.id == "__import__":
                found.add("__import__")
        self.assertEqual(found & (banned | {"__import__"}), set(), "arch.py imports no network module")

    def test_script_needs_only_the_standard_library(self):
        tree = ast.parse(SCRIPT.read_text())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertTrue(modules <= set(sys.stdlib_module_names), f"non-stdlib imports: {modules - set(sys.stdlib_module_names)}")


def git_in(books, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", str(books.dir), "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, env=env)


def rubric_text(*rows):
    return "failure_mode,consequence,likelihood,detection,why\n" + "".join(f"{m},{c},{l},{d},why\n" for m, c, l, d in rows)


def open_row(risk_id, scores, date=DAY):
    c, l, d = scores
    return row(risk_id, date, "open", consequence=str(c), likelihood=str(l), detection=str(d))


LRM = chr(0x200E)
INVISIBLE = [chr(code) for code in (0xAD, 0x61C, 0x200E, 0x200F, 0x2060, 0xE000)]
NO_BREAK_SPACE = chr(0xA0)


class RubricHistoryTests(Case):
    def committed(self, rubric, rows):
        books = self.books(rows, rubric_text(*rubric))
        git_in(books, "init", "-q")
        git_in(books, "add", ".")
        git_in(books, "commit", "-q", "-m", "books")
        return books

    def observe(self, mode="single-host", risk_id="A1"):
        return legal_row("observe", risk_id, failure_mode=mode)

    def test_a_changed_rubric_row_does_not_fail_old_rows(self):
        books = self.committed([("single-host", 4, 2, 2)], [self.observe(), open_row("A1", (4, 2, 2))])
        books.write_rubric(rubric_text(("single-host", 3, 2, 2)))
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "old rows are not re-judged by a changed rubric")
        self.assertProblem(books, "open scores must equal the rubric.csv row", "without --base every row is judged by today's rubric")

    def test_a_removed_or_renamed_mode_does_not_fail_old_rows(self):
        books = self.committed([("single-host", 4, 2, 2)], [self.observe(), open_row("A1", (4, 2, 2))])
        books.write_rubric(rubric_text(("other-mode", 1, 1, 1)))
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "a removed or renamed mode leaves history alone")
        self.assertProblem(books, "failure_mode single-host is not in rubric.csv", "without --base the old row fails")

    def test_a_new_row_is_judged_by_the_rubric_at_the_base(self):
        books = self.committed([("single-host", 4, 2, 2)], [self.observe()])
        books.write_rubric(rubric_text(("single-host", 1, 1, 1)))
        with open(books.dir / "risks.csv", "a") as handle:
            handle.write(open_row("A1", (1, 1, 1)) + "\n")
        out = self.assertProblem(books, "open scores must equal the rubric.csv row", "a rubric edited in the same change as the open", "--base", "HEAD")
        self.assertIn("risks.csv:3:", out, "the new row is the one reported")
        books.write_rows([self.observe(), open_row("A1", (4, 2, 2))])
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "the rubric at the base scores pass")

    def test_a_mode_added_and_used_in_the_same_change_is_judged_by_the_working_rubric(self):
        books = self.committed([("single-host", 4, 2, 2)], [self.observe()])
        books.write_rubric(rubric_text(("single-host", 4, 2, 2), ("new-mode", 2, 3, 1)))
        books.write_rows([self.observe(), self.observe("new-mode", "A2"), open_row("A2", (2, 3, 1))])
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "a new mode and its first rows pass together")
        books.write_rows([self.observe(), self.observe("new-mode", "A2"), open_row("A2", (2, 3, 2))])
        self.assertProblem(books, "open scores must equal the rubric.csv row for new-mode", "a new mode with the wrong scores", "--base", "HEAD")

    def test_a_rubric_missing_at_the_base_falls_back_to_the_working_tree(self):
        books = self.books([self.observe(), open_row("A1", (4, 2, 2))], rubric_text(("single-host", 4, 2, 2)))
        (books.dir / ".gitignore").write_text("rubric.csv\n")
        git_in(books, "init", "-q")
        git_in(books, "add", ".")
        git_in(books, "commit", "-q", "-m", "books without the rubric")
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "the working rubric judges when the base has none")
        books.write_rows([self.observe(), open_row("A1", (4, 2, 2)), self.observe("single-host", "A2"), open_row("A2", (3, 3, 3))])
        self.assertProblem(books, "open scores must equal the rubric.csv row", "and it still judges new rows", "--base", "HEAD")

    def test_rows_that_were_already_in_the_base_are_not_judged_by_any_rubric(self):
        books = self.committed([("single-host", 4, 2, 2)], [self.observe("gone-mode"), self.observe("single-host", "A2"), open_row("A2", (3, 3, 3))])
        self.assertEqual(books.run("check", "--base", "HEAD")[0], 0, "history that disagrees with the base rubric is left alone")
        self.assertEqual(books.run("check")[0], 1, "without --base the same books fail")

    def test_other_rules_still_apply_to_old_rows(self):
        books = self.committed([("single-host", 4, 2, 2)], [self.observe(), legal_row("close")])
        self.assertProblem(books, "illegal move: close from observed", "the state machine judges old rows too", "--base", "HEAD")

    def test_summary_with_a_base_refuses_edited_or_deleted_history(self):
        books = self.committed([("single-host", 4, 2, 2)], [self.observe(), open_row("A1", (4, 2, 2))])
        (books.dir / "risks.csv").write_text(HEADER + "\n")
        code, out, err = books.run("summary", "--json")
        self.assertEqual((code, json.loads(out)["risks"]), (0, []), "without --base a truncated register summarizes to nothing")
        code, out, err = books.run("summary", "--json", "--base", "HEAD")
        self.assertEqual((code, out), (1, ""), "with --base a truncated register is refused")
        self.assertIn("a past row was edited or deleted", err, "and says why")
        git_in(books, "checkout", "-q", "--", "risks.csv")
        self.assertEqual(books.run("summary", "--json", "--base", "HEAD")[0], 0, "an untouched history summarizes")
        books.write_rubric(rubric_text(("single-host", 1, 1, 1)))
        self.assertEqual(books.run("summary", "--json", "--base", "HEAD")[0], 0, "a changed rubric does not stop the summary")


class ProvenanceTests(Case):
    def test_answers_carry_the_question(self):
        base = life(events=["observe", "open", "propose"])
        for event, extra in (("rescore", dict(consequence="1", likelihood="1", detection="1")), ("accept", {}), ("decline", {})):
            books = self.books(base + [row("A1", DAY, event, evidence="the answer", **extra)])
            self.assertProblem(books, f"{event} needs question", f"{event} without a question")

    def test_accept_and_decline_must_answer_the_proposed_question(self):
        base = life(events=["observe", "open", "propose"])
        for event in ("accept", "decline"):
            wrong = self.books(base + [row("A1", DAY, event, evidence="the answer", question="Q9")])
            self.assertProblem(wrong, f"{event} question must equal the propose question (Q3)", f"{event} answering another question")
            right = self.books(base + [row("A1", DAY, event, evidence="the answer", question="Q3")])
            self.assertEqual(right.run("check")[0], 0, f"{event} answering the proposed question passes")

    def test_a_rescore_may_answer_any_question_and_other_events_carry_none(self):
        books = self.books(life(events=["observe", "open"]) + [row("A1", DAY, "rescore", consequence="1", likelihood="1", detection="1", evidence="e", question="Q8")])
        self.assertEqual(books.run("check")[0], 0, "a rescore carries the question it answers")
        before = {"observe": "unseen", "open": "observed", "mitigate": "accepted", "close": "mitigating", "reopen": "closed"}
        for event, state in before.items():
            cells = next(csv.reader([legal_row(event)]))
            cells[arch.RISK_COLUMNS.index("question")] = "Q1"
            books = self.books(life(events=PATHS[state]) + [",".join(_cell(c) for c in cells)])
            self.assertProblem(books, f"{event} does not carry a question", f"a question on {event}")

    def test_a_reproposed_risk_is_answered_by_the_latest_question(self):
        rows = life(events=["observe", "open", "propose", "decline", "reopen"]) + [row("A1", DAY, "propose", question="Q7"), row("A1", DAY, "accept", evidence="e", question="Q7")]
        self.assertEqual(self.books(rows).run("check")[0], 0, "the answer matches the latest propose")


class IdentityAndTextTests(Case):
    def test_names_are_plain_lowercase_ascii(self):
        for bad in ("Web-App", "web_app", "web app", "cafe" + chr(0x301), "w" * 65, "a.b"):
            books = self.books([row("A1", DAY, "observe", component=bad, failure_mode="single-host", evidence="e")])
            self.assertIn("component must be lowercase letters, digits and hyphens", books.run("check")[1], f"component {bad!r} is refused")
            books = self.books(rubric=rubric_text((bad, 1, 1, 1)))
            self.assertIn("failure_mode must be lowercase letters, digits and hyphens", books.run("check")[1], f"rubric failure_mode {bad!r} is refused")
        for good in ("web-app", "9lives", "w" * 64):
            books = self.books([row("A1", DAY, "observe", component=good, failure_mode="single-host", evidence="e")])
            self.assertEqual(books.run("check")[0], 0, f"component {good!r} is fine")
        books = self.books([row("A1", DAY, "observe", component="web-app", failure_mode="Single-Host", evidence="e")])
        self.assertIn("failure_mode must be lowercase letters, digits and hyphens", books.run("check")[1], "a risk's failure_mode follows the same rule")

    def test_invisible_characters_and_padding_fail(self):
        for bad in INVISIBLE:
            books = self.books([row("A1", DAY, "observe", component="x", failure_mode="tiny", evidence="a" + bad + "b")])
            self.assertProblem(books, "invisible character", f"evidence with {bad!r}")
        for padded in (" e", "e ", NO_BREAK_SPACE + "e", " "):
            books = self.books([row("A1", DAY, "observe", component="x", failure_mode="tiny", evidence=padded)])
            self.assertProblem(books, "leading or trailing whitespace", f"evidence {padded!r}")

    def test_a_receipt_needs_visible_content(self):
        prefix = life(events=["observe", "open", "propose", "accept", "mitigate"])
        for evidence in ("receipt:" + LRM, "receipt: " + LRM, "receipt: "):
            self.assertProblem(self.books(prefix + [row("A1", DAY, "close", evidence=evidence)]), "evidence", f"close evidence {evidence!r}")
        self.assertEqual(self.books(prefix + [row("A1", DAY, "close", evidence="receipt: probe passes")]).run("check")[0], 0, "a real receipt passes")


class DateAndSizeTests(Case):
    def setUp(self):
        self.original = arch.utc_today
        arch.utc_today = lambda: datetime.date(2026, 11, 27)
        self.addCleanup(setattr, arch, "utc_today", self.original)

    def test_a_date_more_than_a_day_ahead_fails(self):
        ok = self.books([row("A1", "2026-11-28", "observe", component="x", failure_mode="tiny", evidence="e")])
        self.assertEqual(ok.run("check")[0], 0, "tomorrow is allowed for a clock a day off")
        late = self.books([row("A1", "2026-11-29", "observe", component="x", failure_mode="tiny", evidence="e")])
        self.assertProblem(late, "date 2026-11-29 is in the future", "two days ahead")

    def test_a_file_over_five_million_bytes_is_refused_before_it_is_read(self):
        for name in ("risks.csv", "rubric.csv"):
            books = self.books()
            (books.dir / name).write_bytes(b"x" * 5_000_001)
            for command in ("check", "summary"):
                code, out, err = books.run(command)
                self.assertEqual((code, out), (2, ""), f"{command} exits 2 on an oversized {name}")
                self.assertIn("over the 5000000 byte limit", err, "and says the limit")


class SummaryOrderTests(Case):
    def test_equal_tier_and_score_sort_by_numeric_id(self):
        rows = life("A10", "single-host", PATHS["open"]) + life("A2", "single-host", PATHS["open"]) + life("A9", "single-host", PATHS["open"])
        ids = [r["risk_id"] for r in self.books(rows).summary()[1]["risks"]]
        self.assertEqual(ids, ["A2", "A9", "A10"], "ids tie-break numerically, not as strings")

    def test_dates_are_compared_to_the_latest_row_not_the_first(self):
        rows = [legal_row("observe", date="2026-11-01"), legal_row("open", date="2026-11-05"),
                row("A1", "2026-11-03", "rescore", consequence="1", likelihood="1", detection="1", evidence="e", question="Q1")]
        out = self.assertProblem(self.books(rows), "earlier than this risk's previous row (2026-11-05)", "a third row older than the second")
        self.assertIn("risks.csv:4:", out, "it is the third row that fails")

    def test_live_risks_rank_first_and_closed_ones_leave_the_tier_counts(self):
        rows = (life("A1", "single-host") + life("A2", "slow-restore", PATHS["open"])
                + life("A3", "tiny", PATHS["observed"]) + life("A4", "tiny", ["observe", "open", "propose", "decline"]))
        _, summary, _ = self.books(rows).summary()
        self.assertEqual([r["risk_id"] for r in summary["risks"]], ["A2", "A3", "A1", "A4"],
                         "the live P1 first, then observed, then closed and declined by tier and score")
        self.assertEqual([r["live"] for r in summary["risks"]], [True, False, False, False], "only the open one is live")
        self.assertEqual(summary["counts"]["by_tier"], {"P0": 0, "P1": 1, "P2": 0, "P3": 0}, "a closed P0 is not counted")
        self.assertEqual(summary["counts"]["live"], 1, "one live risk")
        closed = summary["risks"][2]
        self.assertEqual((closed["state"], closed["tier"], closed["score"]), ("closed", "P0", 16), "a closed risk keeps its last score and tier")


if __name__ == "__main__":
    unittest.main()
