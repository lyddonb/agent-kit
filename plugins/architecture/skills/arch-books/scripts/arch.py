#!/usr/bin/env python3
"""Check and summarize the Head of Architecture's risk register.

    uv run --python 3.12 arch.py check BOOKS [--base REF]
    uv run --python 3.12 arch.py summary BOOKS [--json]

Exit 0 when clean, 1 when the books have problems, 2 when an input is missing or unusable.
Python 3.10 or later, standard library only, no network.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, NamedTuple

RISKS = "risks.csv"
RUBRIC = "rubric.csv"
RISK_COLUMNS = ("risk_id", "date", "event", "component", "failure_mode", "consequence",
                "likelihood", "detection", "evidence", "question", "note")
RUBRIC_COLUMNS = ("failure_mode", "consequence", "likelihood", "detection", "why")
SCORE_COLUMNS = ("consequence", "likelihood", "detection")
MAX_CELL = 1000
MAX_FILE_BYTES = 5_000_000
MAX_NAME = 64
RECEIPT = "receipt:"

UNSEEN = "unseen"
STATES = (UNSEEN, "observed", "open", "proposed", "accepted", "declined", "mitigating", "closed")
EVENTS = ("observe", "open", "rescore", "propose", "accept", "decline", "mitigate", "close", "reopen")

TRANSITIONS = {
    (UNSEEN, "observe"): "observed",
    ("observed", "open"): "open",
    ("open", "rescore"): "open",
    ("open", "propose"): "proposed",
    ("proposed", "rescore"): "proposed",
    ("proposed", "accept"): "accepted",
    ("proposed", "decline"): "declined",
    ("accepted", "rescore"): "accepted",
    ("accepted", "mitigate"): "mitigating",
    ("declined", "rescore"): "declined",
    ("declined", "reopen"): "open",
    ("mitigating", "rescore"): "mitigating",
    ("mitigating", "close"): "closed",
    ("closed", "reopen"): "open",
}

SCORED_EVENTS = ("open", "rescore")
EVIDENCE_EVENTS = ("observe", "rescore", "accept", "decline", "mitigate", "close", "reopen")
QUESTION_EVENTS = ("propose", "rescore", "accept", "decline")
ANSWER_EVENTS = ("accept", "decline")
LIVE_STATES = ("open", "proposed", "accepted", "mitigating")
BAD_CATEGORIES = ("Cc", "Cf", "Co", "Cs", "Zl", "Zp")
TIERS = ("P0", "P1", "P2", "P3")

_ID = re.compile(r"A[1-9][0-9]*")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_QUESTION = re.compile(r"Q[1-9][0-9]*")
_SCORE = re.compile(r"[1-4]")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_FORMULA_FIRST = "=+-@＝＋－＠"


class Unusable(Exception):
    pass


class Problem(NamedTuple):
    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.message}"


class Row(NamedTuple):
    line: int
    cells: dict


@dataclass
class BaseView:
    old_lines: int = 0
    rubric: dict | None = None


@dataclass
class Risk:
    risk_id: str
    state: str
    component: str
    failure_mode: str
    scores: tuple | None
    question: str | None
    first_date: str
    last_date: str
    events: int


def score(consequence: int, likelihood: int, detection: int) -> int:
    return consequence * likelihood * detection


def tier(consequence: int, likelihood: int, total: int) -> str:
    if (consequence == 4 and likelihood >= 2) or total >= 36:
        return "P0"
    if total >= 18:
        return "P1"
    if total >= 8:
        return "P2"
    return "P3"


def text_problem(value: str) -> str | None:
    if any(unicodedata.category(char) in BAD_CATEGORIES for char in value):
        return "contains a control or invisible character (a spreadsheet or a terminal would act on it, or it hides what the text says)"
    if value != value.strip():
        return "has leading or trailing whitespace"
    if value and value[0] in _FORMULA_FIRST:
        return "starts with = + - or @ (a spreadsheet would run it as a formula)"
    if len(value) > MAX_CELL:
        return f"is longer than {MAX_CELL} characters"
    return None


def name_problem(value: str) -> bool:
    return not (_NAME.fullmatch(value) and len(value) <= MAX_NAME)


def receipt(evidence: str) -> bool:
    return evidence.startswith(RECEIPT) and bool(evidence[len(RECEIPT):].strip())


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def valid_date(text: str) -> bool:
    match = _DATE.fullmatch(text)
    if not match:
        return False
    try:
        date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return False
    return True


def read_table(name: str, data: bytes, columns: tuple) -> tuple[list[Row], list[Problem]]:
    problems: list[Problem] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return [], [Problem(name, 1, f"is not valid UTF-8 ({error.reason} at byte {error.start})")]
    if text and not text.endswith("\n"):
        problems.append(Problem(name, text.count("\n") + 1, "the file must end with a newline"))
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows: list[Row] = []
    previous_end = 0
    while True:
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as error:
            problems.append(Problem(name, previous_end + 1, f"is not valid CSV ({error})"))
            return [], problems
        start, previous_end = previous_end + 1, reader.line_num
        if start == 1:
            if tuple(record) != columns:
                problems.append(Problem(name, 1, "header must be exactly " + ",".join(columns)))
                return [], problems
            continue
        if not record:
            problems.append(Problem(name, start, "empty line"))
            continue
        if len(record) != len(columns):
            problems.append(Problem(name, start, f"has {len(record)} cells, expected {len(columns)}"))
            continue
        cells = dict(zip(columns, record))
        bad = False
        for column, value in cells.items():
            why = text_problem(value)
            if why:
                problems.append(Problem(name, start, f"{column} {why}"))
                bad = True
        if not bad:
            rows.append(Row(start, cells))
    if not text:
        problems.append(Problem(name, 1, "header must be exactly " + ",".join(columns)))
    return rows, problems


def read_rubric(data: bytes) -> tuple[dict, list[Problem]]:
    rows, problems = read_table(RUBRIC, data, RUBRIC_COLUMNS)
    rubric: dict = {}
    for row in rows:
        cells = row.cells
        mode = cells["failure_mode"]
        if not mode:
            problems.append(Problem(RUBRIC, row.line, "failure_mode is empty"))
            continue
        if name_problem(mode):
            problems.append(Problem(RUBRIC, row.line, f"failure_mode must be lowercase letters, digits and hyphens, starting with a letter or digit, at most {MAX_NAME} characters"))
            continue
        if mode in rubric:
            problems.append(Problem(RUBRIC, row.line, f"failure_mode {mode} is listed twice"))
            continue
        scores = []
        for column in SCORE_COLUMNS:
            if not _SCORE.fullmatch(cells[column]):
                problems.append(Problem(RUBRIC, row.line, f"{column} must be an integer from 1 to 4"))
            else:
                scores.append(int(cells[column]))
        if len(scores) == len(SCORE_COLUMNS):
            rubric[mode] = tuple(scores)
    return rubric, problems


def parse_scores(cells: dict) -> tuple[tuple | None, list[str]]:
    given = [cells[column] for column in SCORE_COLUMNS]
    if not any(given):
        return None, []
    issues = []
    for column in SCORE_COLUMNS:
        if cells[column] and not _SCORE.fullmatch(cells[column]):
            issues.append(f"{column} must be an integer from 1 to 4")
    if issues:
        return None, issues
    if not all(given):
        return None, ["the three scores come together: consequence, likelihood and detection"]
    return tuple(int(value) for value in given), []


def fold(rows: list[Row], rubric: dict, view: BaseView | None = None) -> tuple[dict, list[Problem]]:
    view = view or BaseView()
    problems: list[Problem] = []
    risks: dict = {}
    states: dict = {}
    for row in rows:
        cells = row.cells

        def report(message: str) -> None:
            problems.append(Problem(RISKS, row.line, message))

        risk_id, event = cells["risk_id"], cells["event"]
        if not _ID.fullmatch(risk_id):
            report("risk_id must be A followed by digits with no leading zero, like A12")
            continue
        if event not in EVENTS:
            report(f"event must be one of {', '.join(EVENTS)}")
            continue
        when = cells["date"]
        dated = valid_date(when)
        if not dated:
            report("date must be a real date like 2026-11-27")
        elif when > (utc_today() + timedelta(days=1)).isoformat():
            report(f"date {when} is in the future")
        for column in ("component", "failure_mode"):
            if cells[column] and name_problem(cells[column]):
                report(f"{column} must be lowercase letters, digits and hyphens, starting with a letter or digit, at most {MAX_NAME} characters")
        scores, score_issues = parse_scores(cells)
        for issue in score_issues:
            report(issue)
        if cells["question"] and not _QUESTION.fullmatch(cells["question"]):
            report("question must look like Q3")
        known = risks.get(risk_id)
        current = states.get(risk_id, UNSEEN)
        moved = TRANSITIONS.get((current, event))
        if moved is None:
            report(f"illegal move: {event} from {current}")
        if known is None and event == "observe":
            component, failure_mode = cells["component"], cells["failure_mode"]
        elif known is not None:
            component, failure_mode = known.component, known.failure_mode
            for column in ("component", "failure_mode"):
                if cells[column] and cells[column] != getattr(known, column):
                    report(f"{column} is fixed by the observe row; leave it empty or repeat it")
        else:
            component = failure_mode = ""
        if event == "observe":
            for column in ("component", "failure_mode"):
                if not cells[column]:
                    report(f"observe needs {column}")
            if failure_mode and row.line > view.old_lines and failure_mode not in (view.rubric or {}) and failure_mode not in rubric:
                report(f"failure_mode {failure_mode} is not in {RUBRIC}")
        if event in SCORED_EVENTS:
            if scores is None and not score_issues:
                report(f"{event} needs consequence, likelihood and detection")
            expected = (view.rubric or {}).get(failure_mode, rubric.get(failure_mode))
            if event == "open" and row.line > view.old_lines and scores is not None and expected is not None and scores != expected:
                report(f"open scores must equal the {RUBRIC} row for {failure_mode}")
        elif scores is not None or any(cells[column] for column in SCORE_COLUMNS):
            report(f"{event} does not carry scores")
        if event in EVIDENCE_EVENTS and not cells["evidence"]:
            report(f"{event} needs evidence")
        if event == "close" and cells["evidence"] and not receipt(cells["evidence"]):
            report(f"close evidence must start with {RECEIPT} and say what the receipt is")
        if event in QUESTION_EVENTS and not cells["question"]:
            report(f"{event} needs question")
        if event not in QUESTION_EVENTS and cells["question"]:
            report(f"{event} does not carry a question")
        if event in ANSWER_EVENTS and cells["question"] and known is not None and known.question and cells["question"] != known.question:
            report(f"{event} question must equal the propose question ({known.question})")
        if known is not None and dated and valid_date(known.last_date) and when < known.last_date:
            report(f"date {when} is earlier than this risk's previous row ({known.last_date})")
        if known is None and event == "observe" and moved is not None:
            risks[risk_id] = Risk(risk_id, moved, component, failure_mode, None, None,
                                  when, when, 1)
            states[risk_id] = moved
            continue
        if known is None:
            continue
        known.events += 1
        if dated and when > known.last_date:
            known.last_date = when
        if moved is not None:
            known.state = states[risk_id] = moved
            if scores is not None and event in SCORED_EVENTS:
                known.scores = scores
            if cells["question"] and event == "propose":
                known.question = cells["question"]
    return risks, problems


def read_books(books_dir: str) -> tuple[bytes, bytes]:
    root = Path(books_dir)
    if not root.is_dir():
        raise Unusable(f"not a directory: {books_dir}")
    out = []
    for name in (RISKS, RUBRIC):
        path = root / name
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                raise Unusable(f"{path} is {size} bytes, over the {MAX_FILE_BYTES} byte limit")
            out.append(path.read_bytes())
        except OSError as error:
            raise Unusable(f"cannot read {path}: {error.strerror or error}") from error
    return out[0], out[1]


def _git(books_dir: str, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items()
           if key not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    return subprocess.run(["git", "-C", books_dir, *args], capture_output=True, env=env)


def _lines(data: bytes) -> list[bytes]:
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts.pop()
    return parts


def read_base(books_dir: str, ref: str) -> tuple[list[Problem], dict]:
    def cannot(why: str) -> list[Problem]:
        return [Problem(RISKS, 1, f"cannot check against {ref}: {why}")]

    if ref.startswith("-"):
        return cannot("a ref cannot start with a dash"), {}
    shown: dict = {}
    try:
        if _git(books_dir, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode != 0:
            return cannot("not a commit here (is this a git repo, and is the ref fetched?)"), {}
        top = _git(books_dir, "rev-parse", "--show-toplevel")
        top_dir = os.fsdecode(top.stdout).rstrip("\n")
        if top.returncode != 0 or os.path.realpath(top_dir) != os.path.realpath(books_dir):
            return cannot("the books folder must be the top level of its git work tree"), {}
        for name in (RISKS, RUBRIC):
            listed = _git(books_dir, "ls-tree", "--name-only", ref, "--", name)
            if listed.returncode != 0:
                return cannot("git ls-tree failed"), {}
            if not listed.stdout.strip():
                continue
            content = _git(books_dir, "show", f"{ref}:./{name}")
            if content.returncode != 0:
                return cannot("git show failed"), {}
            shown[name] = content.stdout
    except OSError as error:
        return cannot(f"git could not run ({error.strerror or error})"), {}
    return [], shown


def append_only_problems(ref: str, base_risks: bytes | None, current: bytes) -> Iterator[Problem]:
    old, new = _lines(base_risks or b""), _lines(current)
    for index, line in enumerate(old):
        if index >= len(new) or new[index] != line:
            yield Problem(RISKS, index + 1, f"a past row was edited or deleted (line {index + 1} differs from {ref})")
            return


def load(books_dir: str, base: str | None = None) -> tuple[dict, int, list[Problem]]:
    risks_data, rubric_data = read_books(books_dir)
    rubric, problems = read_rubric(rubric_data)
    view = BaseView()
    base_problems: list[Problem] = []
    if base is not None:
        base_problems, shown = read_base(books_dir, base)
        if RISKS in shown:
            view.old_lines = len(_lines(shown[RISKS]))
        if RUBRIC in shown:
            view.rubric = read_rubric(shown[RUBRIC])[0]
        if not base_problems:
            base_problems = list(append_only_problems(base, shown.get(RISKS), risks_data))
    rows, table_problems = read_table(RISKS, risks_data, RISK_COLUMNS)
    risks, row_problems = fold(rows, rubric, view)
    all_problems = problems + sorted(table_problems + row_problems, key=lambda p: p.line) + base_problems
    return risks, len(rows), all_problems


def risk_record(risk: Risk) -> dict:
    scores = risk.scores
    consequence, likelihood, detection = scores if scores else (None, None, None)
    total = score(*scores) if scores else None
    return {
        "risk_id": risk.risk_id,
        "state": risk.state,
        "live": risk.state in LIVE_STATES,
        "component": risk.component,
        "failure_mode": risk.failure_mode,
        "consequence": consequence,
        "likelihood": likelihood,
        "detection": detection,
        "score": total,
        "tier": tier(consequence, likelihood, total) if scores else None,
        "first_date": risk.first_date,
        "last_date": risk.last_date,
        "question": risk.question,
        "events": risk.events,
    }


def rank_key(record: dict) -> tuple:
    group = 0 if record["live"] else 1 if record["state"] == "observed" else 2
    rank = TIERS.index(record["tier"]) if record["tier"] else len(TIERS)
    return group, rank, -(record["score"] or 0), int(record["risk_id"][1:])


def summarize(risks: dict) -> dict:
    records = sorted((risk_record(risk) for risk in risks.values()), key=rank_key)
    by_state = {state: 0 for state in STATES if state != UNSEEN}
    by_tier = {name: 0 for name in TIERS}
    live = 0
    for record in records:
        by_state[record["state"]] += 1
        if record["live"]:
            live += 1
            by_tier[record["tier"]] += 1
    return {"version": 1, "risks": records, "counts": {"by_state": by_state, "by_tier": by_tier, "live": live}}


def render_json(summary: dict) -> str:
    return json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_text(summary: dict) -> str:
    lines = []
    for record in summary["risks"]:
        lines.append("  ".join([
            record["risk_id"], record["tier"] or "--", str(record["score"] if record["score"] is not None else "--"),
            record["state"], record["component"], record["failure_mode"]]))
    counts = summary["counts"]
    lines.append("states: " + ", ".join(f"{k} {v}" for k, v in counts["by_state"].items()))
    lines.append(f"live {counts['live']}; live tiers: " + ", ".join(f"{k} {v}" for k, v in counts["by_tier"].items()))
    return "\n".join(lines) + "\n"


def cmd_check(args: argparse.Namespace) -> int:
    try:
        _, count, problems = load(args.books, args.base)
    except Unusable as error:
        print(f"arch.py: {error}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} problems")
        return 1
    print(f"ok, {count} rows, 0 problems")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    try:
        risks, _, problems = load(args.books, args.base)
    except Unusable as error:
        print(f"arch.py: {error}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"arch.py: refusing to summarize books with {len(problems)} problems; run check", file=sys.stderr)
        return 1
    summary = summarize(risks)
    sys.stdout.write(render_json(summary) if args.json else render_text(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arch.py", description="Work with the Head of Architecture's books.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate the register")
    check.add_argument("books", metavar="BOOKS")
    check.add_argument("--base", metavar="REF", help="fail if a row of risks.csv at REF was edited or deleted; rows from REF are not re-judged by the rubric")
    check.set_defaults(func=cmd_check)
    summary = sub.add_parser("summary", help="fold the register into states, scores and tiers")
    summary.add_argument("books", metavar="BOOKS")
    summary.add_argument("--json", action="store_true")
    summary.add_argument("--base", metavar="REF", help="refuse books whose rows at REF were edited or deleted; judge rows by the rubric at REF")
    summary.set_defaults(func=cmd_summary)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
