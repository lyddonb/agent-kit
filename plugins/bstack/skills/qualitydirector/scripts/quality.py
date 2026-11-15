#!/usr/bin/env python3
"""The Quality Director's primitives: record a test run, check the quality books, book recorded
runs into them, and summarize a week.

Usage:
    uv run --python 3.12 quality.py record TESTS_DIR --out FILE --repo NAME [--sha SHA]
    uv run --python 3.12 quality.py check BOOKS_DIR [--base REF]
    uv run --python 3.12 quality.py ingest BOOKS_DIR ARTIFACT_DIR [--dry-run] [--json]
    uv run --python 3.12 quality.py summary BOOKS_DIR [--week YYYY-Www] [--json]

`record` runs `python -m unittest discover -s TESTS_DIR` and writes what happened to FILE as
JSON Lines: a run header, then one line per test with its outcome (pass, fail, error, skip) and
milliseconds. Then it prints `recorded N tests in M ms -> FILE`.

The recorder never shares a process with the tests. The parent checks that FILE can be
written (exit 2 if not), reads the start time and git sha, starts a child (the same Python, the
same flags, directory, environment and stdin/stdout/stderr) that runs the suite, and reads the
child's events from a pipe: one line when a test starts, one when each outcome is known. The
parent builds the rows and the header from those events and writes FILE after the child exits,
so nothing a test does (stubbing `json`, closing `sys.stdout`, emptying PATH, `os._exit`, a
KeyboardInterrupt) can change the file or the exit code. A test that started and never finished
is an `error` row. A module that fails to import and a setUpClass that raises each get an
`error` row too. When unittest's run finishes normally the child sends one last event, and the
header says `"complete": true`; a run cut short (SystemExit, KeyboardInterrupt, `os._exit`, a
signal, a test that closed the event pipe) says `false`.

The header's `exit_code` is the child's exit status as a shell reports it (128+N after signal N).
The recorder exits with the child's status when that is not 0. It exits 1 when the run is not
complete, when no test ran, or when a row is fail or error (this includes a test that ended the
process with `os._exit(0)`). These three cases are the only ones where it differs from plain
unittest: a suite cut short at exit 0 and an empty suite never look green. Exit 2 is bad usage, including an output directory
that is missing or not writable.

A test cannot tell the child from `python -m unittest discover -s TESTS_DIR` except through
`__main__` (the child runs a `-c` bootstrap, so `__main__` is not `unittest.__main__`). The
child imports only what plain unittest imports, and `sys.argv`, `sys.path` and `sys.orig_argv`
match. Interpreter flags (`-O`, `-W`, `-X`, `-E`, `-I`, `-P`, `-b`, `-B`, `-s`, `-S`, `-d`,
`-v`, `-q`) are rebuilt from `sys.flags`, `sys.warnoptions` and `sys._xoptions`. `-u` leaves no
trace in those and is not carried (PYTHONUNBUFFERED is, through the environment). POSIX only.

`--sha SHA` (40 lowercase hex, exit 2 otherwise) sets the header's sha and wins over GITHUB_SHA
and git: on pull_request events GITHUB_SHA is a temporary merge commit, so a workflow passes
`--sha "${{ github.event.pull_request.head.sha || github.sha }}"`.

The books are three CSV files under BOOKS_DIR: books/runs.csv (one row per recorded CI run, append
only), books/failures.csv (one row per failing test in a run, append only) and
books/tests-weekly.csv (per ISO week, repo and test: runs, failed, total and max milliseconds;
rows are updated in place and kept sorted).

`check` validates the three files and prints one `path:line: message` line per problem (path
relative to BOOKS_DIR), then `ok, N rows, 0 problems` or `N problems`. Exit 0 when clean, 1 when
there are problems, 2 on bad usage. With --base REF, runs.csv and failures.csv must be
append-only against REF. It also checks across the files: every failures row belongs to a run,
and a run has exactly as many failures rows as its `failed` says.

`ingest` books every `*.jsonl` recorder file under ARTIFACT_DIR (any depth) into the books. Those
files come from CI that runs pull-request code, so they are untrusted: each is parsed strictly
(see `parse_artifact`), a file that is not valid is named with the reason and skipped, and ingest
exits 1 after booking the good ones. A run whose event is `local` or whose evidence is empty is
skipped with a note. A run already in runs.csv (same evidence and python) is skipped, so a second
ingest changes nothing. The runs.csv `exit_code` is the recorder's verdict recomputed from the
rows (a run cut short at child exit 0 books as 1). The three files are built in memory, checked,
and written only if the result passes, all or none.

`summary` prints the numbers of one ISO week from books that pass `check`: the one place a
report takes its numbers from. With --json it is one object with sorted keys and integer
numbers only. A median of an even count is the lower of the two middle values.

Standard library only; needs Python 3.10 or later (run it through uv).

Shape: `Books` is loaded once (the CSV tables with line numbers). Each entry in `CHECKS`
takes a `Books` and yields `Problem`s. A new check is a new entry in that registry. Ingest
and summary read the checked tables as typed rows (`RunRow`, `FailureRow`, `WeeklyRow`).
"""
import sys

if sys.version_info < (3, 10):
    sys.stderr.write(
        f"quality.py needs Python 3.10 or later (this is {sys.version_info[0]}.{sys.version_info[1]}). "
        "Run it with: uv run --python 3.12 <path to quality.py> ...\n")
    raise SystemExit(2)

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import select
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

RECORD_VERSION = 1
OUTCOMES = ("pass", "skip", "fail", "error")  # ordered by severity; a test keeps its worst
RUN_KEYS = ("v", "repo", "sha", "event", "workflow", "python", "os", "started",
            "wall_ms", "exit_code", "complete", "tests", "failed", "skipped", "evidence")
TEST_KEYS = ("id", "outcome", "ms")

RUNS = "books/runs.csv"
FAILURES = "books/failures.csv"
WEEKLY = "books/tests-weekly.csv"
RUNS_SCHEMA = ("started", "repo", "sha", "event", "workflow", "python",
               "tests", "failed", "skipped", "wall_ms", "exit_code", "evidence")
FAILURES_SCHEMA = ("started", "repo", "sha", "python", "test_id", "outcome", "evidence")
WEEKLY_SCHEMA = ("week", "repo", "test_id", "runs", "failed", "total_ms", "max_ms")
SCHEMAS = {RUNS: RUNS_SCHEMA, FAILURES: FAILURES_SCHEMA, WEEKLY: WEEKLY_SCHEMA}
FAILING = ("fail", "error")  # the outcomes failures.csv holds
SUITE_MEDIAN_THRESHOLD_MS = 300_000  # a suite whose median wall time is above this is over threshold

# ---------------------------------------------------------------------------
# record: the child
# ---------------------------------------------------------------------------

# The child is `python <flags> -c CHILD FD TESTS_DIR ARGV0 [FLAG...]`. It must look to a test
# like `python -m unittest discover -s TESTS_DIR`, so it imports only what that imports
# (runpy comes with `-m`) and encodes events by hand: no json, no codec lookup. `os.write`,
# the clock and the fd are bound once, so a test that stubs them cannot redirect the stream.
# Events, one per line, fields separated by a tab, the id escaped so it holds no tab or newline:
#   S id            a test started
#   O outcome id    the open test reported an outcome (pass, skip, fail, error)
#   E ms id         the open test finished
#   X outcome id    an outcome for something that never started (setUpClass, import failure)
#   C               unittest's run finished normally (it is the last thing the runner does, so
#                   SystemExit, KeyboardInterrupt, os._exit or a signal never get to send it)
# Only the process that started the run writes: a forked copy of it stays silent.
CHILD = r'''
def _quality_child(fd, tests_dir, argv0, flags):
    import os, sys, time
    import runpy
    import unittest
    write, clock, getpid = os.write, time.perf_counter, os.getpid
    owner = getpid()
    os.set_inheritable(fd, False)

    def escape(text):
        out = []
        for ch in str(text):
            n = ord(ch)
            if ch == "\\":
                out.append("\\\\")
            elif " " <= ch <= "~":
                out.append(ch)
            elif n < 0x10000:
                out.append("\\u%04x" % n)
            else:
                out.append("\\U%08x" % n)
        return "".join(out)

    def ident(test):
        try:
            return escape(test.id())
        except Exception:
            return escape(repr(test))

    def emit(*fields):
        if getpid() != owner:
            return
        try:
            # bytes() and not str.encode: under -X dev the codec lookup would import encodings.ascii
            data = bytes(ord(ch) for ch in "\t".join(fields) + "\n")
            while data:
                data = data[write(fd, data):]
        except Exception:
            pass

    class Result(unittest.TextTestResult):
        # A test may run an inner suite against this same result, so starts nest: a stack.
        _open = ()

        def startTest(self, test):
            emit("S", ident(test))
            self._open = self._open + ((test, clock()),)
            super().startTest(test)

        def stopTest(self, test):
            for i in range(len(self._open) - 1, -1, -1):
                if self._open[i][0] is test:
                    started = self._open[i][1]
                    self._open = self._open[:i] + self._open[i + 1:]
                    emit("E", "%d" % max(0, round((clock() - started) * 1000)), ident(test))
                    break
            super().stopTest(test)

        def _mark(self, test, outcome):
            if isinstance(test, unittest.case._SubTest):
                test = test.test_case
            if any(t is test for t, _ in self._open):
                emit("O", outcome, ident(test))
            elif outcome != "pass":
                emit("X", outcome, ident(test))

        def addSuccess(self, test):
            self._mark(test, "pass")
            super().addSuccess(test)

        def addExpectedFailure(self, test, err):
            self._mark(test, "pass")
            super().addExpectedFailure(test, err)

        def addFailure(self, test, err):
            self._mark(test, "fail")
            super().addFailure(test, err)

        def addError(self, test, err):
            self._mark(test, "error")
            super().addError(test, err)

        def addSkip(self, test, reason):
            self._mark(test, "skip")
            super().addSkip(test, reason)

        def addUnexpectedSuccess(self, test):
            self._mark(test, "fail")
            super().addUnexpectedSuccess(test)

        def addSubTest(self, test, subtest, err):
            if err is not None:
                self._mark(test, "fail" if issubclass(err[0], test.failureException) else "error")
            super().addSubTest(test, subtest, err)

    class Runner(unittest.TextTestRunner):
        resultclass = Result

        def run(self, test):
            result = super().run(test)  # returns only after the last test and the module teardown
            emit("C")
            return result

    if not (sys.flags.isolated or getattr(sys.flags, "safe_path", False)):
        sys.path[0] = os.getcwd()
    sys.argv = [os.path.basename(sys.executable) + " -m unittest", "discover", "-s", tests_dir]
    sys.orig_argv = [argv0] + flags + ["-m", "unittest", "discover", "-s", tests_dir]
    unittest.main(module=None, testRunner=Runner)


import sys
_quality_child(int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:])
'''


# (option, sys.flags attribute, the environment variable that sets the same thing)
_ENV_FLAGS = (("-B", "dont_write_bytecode", "PYTHONDONTWRITEBYTECODE"), ("-s", "no_user_site", "PYTHONNOUSERSITE"),
              ("-P", "safe_path", "PYTHONSAFEPATH"), ("-d", "debug", "PYTHONDEBUG"),
              ("-v", "verbose", "PYTHONVERBOSE"), ("-O", "optimize", "PYTHONOPTIMIZE"))


def interpreter_flags() -> list[str]:
    """The command-line options that changed how this interpreter behaves, for the child.

    Built from sys.flags, sys.warnoptions and sys._xoptions. What the environment already
    supplies (PYTHONWARNINGS, PYTHONOPTIMIZE and the like) reaches the child through the
    inherited environment, so it is not repeated: the child's sys.warnoptions and sys.orig_argv
    must equal plain unittest's.
    """
    f = sys.flags
    from_env = not f.ignore_environment
    args: list[str] = []
    if f.isolated:
        args.append("-I")
    else:
        args += ["-E"] * bool(f.ignore_environment)
    for option, attr, var in _ENV_FLAGS:
        if f.isolated and attr in ("no_user_site", "safe_path"):
            continue  # -I implies them
        want = int(getattr(f, attr, 0))
        have = os.environ.get(var, "") if from_env else ""
        have = (int(have) if have.isdecimal() else 1) if have else 0
        if want > have:
            args.append(option[:1] + option[1] * want)
    args += ["-S"] * bool(f.no_site) + ["-" + "q" * f.quiet] * bool(f.quiet)
    args += ["-" + "b" * f.bytes_warning] * bool(f.bytes_warning)
    warn = list(sys.warnoptions)
    if f.dev_mode and warn[:1] == ["default"]:
        warn = warn[1:]  # -X dev (or PYTHONDEVMODE) puts it there itself
    if from_env:
        in_env = [w for w in os.environ.get("PYTHONWARNINGS", "").split(",") if w]
        if warn[:len(in_env)] == in_env:
            warn = warn[len(in_env):]
    if f.bytes_warning:
        tail = "error::BytesWarning" if f.bytes_warning > 1 else "default::BytesWarning"
        if warn[-1:] == [tail]:
            warn = warn[:-1]  # -b / -bb put it there themselves
    for w in warn:
        args += ["-W", w]
    for key, value in sys._xoptions.items():
        args += ["-X", key if value is True else f"{key}={value}"]
    return args


# ---------------------------------------------------------------------------
# record: the parent
# ---------------------------------------------------------------------------


class Tally:
    """Builds the rows from the child's events. It never runs or imports test code.

    Tests nest: a test may run an inner suite against its own result, so a start arrives while
    the outer test is still open. The open tests are a stack. Each keeps the worst outcome
    reported for it, and `E` closes it with the child's own milliseconds. A test closed without
    any outcome (an interrupt) or never closed (os._exit, a crash, a kill) is an `error`, timed
    by this process's clock.
    """

    def __init__(self, clock=time.perf_counter):
        self.rows: list[dict] = []
        self._clock = clock
        self._open: list[list] = []  # [id, when it started, worst outcome so far], innermost last
        self.complete = False  # the child said its run finished normally
        self._handlers = {"S": self._start, "O": self._outcome_of, "E": self._end, "X": self._alone,
                          "C": self._completed}

    def feed(self, line: str) -> None:
        kind, _, rest = line.partition("\t")
        first, _, test_id = rest.partition("\t")
        handler = self._handlers.get(kind)
        if handler is not None:
            handler(first, test_id)

    def _find(self, test_id: str) -> int | None:
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == test_id:
                return i
        return None

    def _start(self, test_id: str, _: str) -> None:
        self._open.append([_unescape(test_id), self._clock(), None])

    def _outcome_of(self, outcome: str, test_id: str) -> None:
        i = self._find(_unescape(test_id))
        if i is not None and outcome in OUTCOMES:
            entry = self._open[i]
            if entry[2] is None or OUTCOMES.index(outcome) > OUTCOMES.index(entry[2]):
                entry[2] = outcome

    def _end(self, ms: str, test_id: str) -> None:
        i = self._find(_unescape(test_id))
        if i is not None and ms.isdecimal():
            while len(self._open) - 1 > i:
                self._close_innermost(self._clock())  # started inside this one and never finished
            entry = self._open.pop()
            self.rows.append({"id": entry[0], "outcome": entry[2] or "error", "ms": int(ms)})

    def _alone(self, outcome: str, test_id: str) -> None:
        if outcome in OUTCOMES:
            self.rows.append({"id": _unescape(test_id), "outcome": outcome, "ms": 0})

    def _completed(self, _: str, __: str) -> None:
        self.complete = True

    def _close_innermost(self, now: float) -> None:
        test_id, began, outcome = self._open.pop()
        worst = max(outcome or "error", "error", key=OUTCOMES.index)
        self.rows.append({"id": test_id, "outcome": worst, "ms": max(0, round((now - began) * 1000))})

    def finish(self) -> None:
        """The child is gone: every test still open never finished."""
        now = self._clock()
        while self._open:
            self._close_innermost(now)


def _unescape(text: str) -> str:
    try:
        return text.encode("ascii").decode("unicode_escape")
    except UnicodeError:
        return text


def exit_code(child_code: int, records: list[dict], complete: bool) -> int:
    """The recorder's verdict, from the child's exit status, the rows and whether the run completed.

    The child's code stands when it is not 0, so a run exits as plain unittest does. Three guards
    only ever turn a 0 into a 1: a run that did not complete is never green (SystemExit(0) or
    `os._exit(0)` in a setUpClass after a passing test), a run with no rows is never green (plain
    unittest says 0 before 3.12 and 5 after), and a fail or error row is never green (a test that
    ended the process with `os._exit(0)` leaves an `error` row).
    """
    if child_code != 0:
        return child_code
    if not complete or not records:
        return 1
    return 1 if any(r["outcome"] in ("fail", "error") for r in records) else 0


def _git_head(cwd: str) -> str:
    try:
        done = subprocess.run(["git", "-C", cwd, "rev-parse", "HEAD"], capture_output=True, text=True)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _evidence(env) -> str:
    keys = ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
    if not all(env.get(k) for k in keys):
        return ""
    server, repo, run, attempt = (env[k] for k in keys)
    return f"{server}/{repo}/actions/runs/{run}/attempts/{attempt}"


def run_header(repo: str, records: list[dict], started: str, wall_ms: int, child_code: int,
               complete: bool, sha: str, env) -> dict:
    return {
        "v": RECORD_VERSION,
        "repo": repo,
        "sha": sha,
        "event": env.get("GITHUB_EVENT_NAME") or "local",
        "workflow": env.get("GITHUB_WORKFLOW") or "",
        "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
        "os": env.get("RUNNER_OS") or sys.platform,
        "started": started,
        "wall_ms": wall_ms,
        "exit_code": child_code,
        "complete": complete,
        "tests": len(records),
        "failed": sum(r["outcome"] in ("fail", "error") for r in records),
        "skipped": sum(r["outcome"] == "skip" for r in records),
        "evidence": _evidence(env),
    }


def _output_problem(out: str) -> str | None:
    """Why FILE (absolute) cannot be written, found before any test runs."""
    folder = os.path.dirname(out)
    if not os.path.isdir(folder):
        return f"output directory does not exist: {folder}"
    if os.path.isdir(out):
        return f"output path is a directory: {out}"
    if os.path.exists(out):
        return None if os.access(out, os.W_OK) else f"output file is not writable: {out}"
    return None if os.access(folder, os.W_OK | os.X_OK) else f"output directory is not writable: {folder}"


def _sha_arg(text: str) -> str:
    if not _SHA.fullmatch(text):
        raise argparse.ArgumentTypeError(f"must be 40 lowercase hex characters, got {text!r}")
    return text


def _shell_code(returncode: int) -> int:
    """subprocess says -N for death by signal N; a shell says 128+N."""
    return returncode if returncode >= 0 else 128 - returncode


def _read_events(fd: int, proc: subprocess.Popen, tally: Tally) -> None:
    """Feed the child's lines to the tally until the pipe closes.

    The pipe closes when the child exits. A test that leaks the write end to a process that
    outlives the run keeps it open, so once the child is gone only what is already buffered is read.
    """
    pending = b""

    def read_some(timeout: float) -> bool | None:  # True: data, False: nothing now, None: closed
        nonlocal pending
        if not select.select([fd], [], [], timeout)[0]:
            return False
        chunk = os.read(fd, 1 << 16)
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            tally.feed(line.decode("ascii", "replace"))
        return True if chunk else None

    while True:
        got = read_some(0.1)
        if got is None:
            return
        if got is False and proc.poll() is not None:
            while read_some(0):
                pass
            return


def _start_child(tests_dir: str, flags: list[str], write_fd: int) -> subprocess.Popen:
    argv0 = getattr(sys, "orig_argv", [sys.executable])[0]
    return subprocess.Popen(
        [sys.executable, *flags, "-c", CHILD, str(write_fd), tests_dir, argv0, *flags],
        pass_fds=(write_fd,))


def _run_child(tests_dir: str, tally: Tally) -> int:
    """Run the suite in a child and return its exit status as a shell reports it."""
    flags = interpreter_flags()
    read_fd, write_fd = os.pipe()
    box: list[subprocess.Popen] = []

    def relay(signum, frame):
        # Ctrl-C reaches the child through the terminal's process group; SIGTERM and SIGHUP only
        # reach this process, so pass them on and still write the file.
        if signum != signal.SIGINT and box:
            box[0].send_signal(signum)

    saved = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            if signal.getsignal(sig) == signal.SIG_IGN:
                continue  # as for plain unittest: under nohup SIGHUP, after `cmd &` in a script SIGINT
            saved[sig] = signal.signal(sig, relay)
        try:
            box.append(_start_child(tests_dir, flags, write_fd))
        except OSError as e:
            print(f"quality.py: cannot start {sys.executable}: {e}", file=sys.stderr)
            return 127
        finally:
            os.close(write_fd)
        proc = box[0]
        _read_events(read_fd, proc, tally)
        return _shell_code(proc.wait())
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)
        os.close(read_fd)
        tally.finish()


def _write_record(out: str, label: str, header: dict, records: list[dict]) -> bool:
    lines = [json.dumps(row, sort_keys=True, separators=(",", ":")) for row in [header] + records]
    try:
        with open(out, "w") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"quality.py: cannot write {label}: {e}", file=sys.stderr)
        return False
    print(f"recorded {header['tests']} tests in {header['wall_ms']} ms -> {label}")
    return True


def cmd_record(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.tests_dir):
        print(f"quality.py: not a directory: {args.tests_dir}", file=sys.stderr)
        return 2
    out = os.path.abspath(args.out)
    problem = _output_problem(out)
    if problem:
        print(f"quality.py: {problem}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sha = args.sha or env.get("GITHUB_SHA") or _git_head(os.getcwd())
    tally = Tally()
    t0 = time.perf_counter()
    child_code = _run_child(args.tests_dir, tally)
    wall_ms = max(0, round((time.perf_counter() - t0) * 1000))
    header = run_header(args.repo, tally.rows, started, wall_ms, child_code, tally.complete, sha, env)
    code = exit_code(child_code, tally.rows, tally.complete)
    wrote = _write_record(out, args.out, header, tally.rows)
    return code if wrote or code else 1


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass
class Row:
    line: int
    cells: dict[str, str]


@dataclass
class Table:
    rel: str
    header: list[str] | None = None
    rows: list[Row] = field(default_factory=list)
    data: bytes = b""
    bad_format: bool = False  # bytes that cannot be compared line by line (already reported)


@dataclass
class Books:
    dir: str
    base: str | None
    tables: dict[str, Table]
    load_problems: list[Problem] = field(default_factory=list)


def _git(books_dir: str, *args: str):
    return subprocess.run(["git", "-C", books_dir] + list(args), capture_output=True)


def _parse_table(rel: str, data: bytes | OSError | None, problems: list[Problem]) -> Table:
    table = Table(rel)
    schema = SCHEMAS[rel]
    if data is None:
        problems.append(Problem(rel, 1, "missing file"))
        return table
    if isinstance(data, OSError):
        problems.append(Problem(rel, 1, f"cannot read file ({data.strerror or type(data).__name__})"))
        return table
    table.data = data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(Problem(rel, 1, "not UTF-8 text"))
        table.bad_format = True
        return table
    if text.startswith("\ufeff"):
        problems.append(Problem(rel, 1, "starts with a UTF-8 BOM; the books are plain UTF-8"))
        table.bad_format = True
        return table
    if text.split("\n", 1)[0].endswith("\r"):
        # a CRLF file ends its header line that way; a "\r\n" inside a quoted test id is data
        problems.append(Problem(rel, 1, "CRLF line endings; the books use LF"))
        table.bad_format = True
        return table
    reader = csv.reader(io.StringIO(text, newline=""))
    while True:
        before = reader.line_num
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as e:
            problems.append(Problem(rel, before + 1, f"unreadable CSV: {e}"))
            break
        start = before + 1  # a quoted field may span lines; the row is reported at its first
        if table.header is None:
            table.header = record
        elif len(record) != len(schema):
            problems.append(Problem(rel, start, f"row has {len(record)} columns, expected {len(schema)}"))
        else:
            table.rows.append(Row(start, dict(zip(schema, record))))
    if table.header is None:
        problems.append(Problem(rel, 1, "empty file; expected the header " + ",".join(schema)))
    return table


def books_from_bytes(books_dir: str, files: dict[str, bytes | OSError | None], base: str | None = None) -> Books:
    """Books from file contents (None: no such file; an OSError: it could not be read), off the disk."""
    problems: list[Problem] = []
    return Books(books_dir, base, {rel: _parse_table(rel, files[rel], problems) for rel in SCHEMAS}, problems)


def _read(path: str) -> bytes | OSError | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        return e


def load(books_dir: str, base: str | None = None) -> Books:
    return books_from_bytes(books_dir, {rel: _read(os.path.join(books_dir, rel)) for rel in SCHEMAS}, base)


Check = Callable[[Books], Iterable[Problem]]

_REPO = re.compile(r"[a-z0-9][a-z0-9-]*")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_SHA = re.compile(r"[0-9a-f]{40}")
_PYTHON = re.compile(r"3\.[0-9]+")
_WEEK = re.compile(r"([0-9]{4})-W([0-9]{2})")
_RUN_LINK = re.compile(r"https://[^/\s]+/[^/\s]+/[^/\s]+/actions/runs/[0-9]+/attempts/[0-9]+")
_COUNT = re.compile(r"0|[1-9][0-9]*")


def _is_stamp(s: str) -> bool:
    if not _STAMP.fullmatch(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _is_iso_week(s: str) -> bool:
    """2026-W53 is a week; 2025-W53 and 2026-W00 are not."""
    m = _WEEK.fullmatch(s)
    if not m:
        return False
    try:
        date.fromisocalendar(int(m[1]), int(m[2]), 1)
    except ValueError:
        return False
    return True


def _counts(row: Row, rel: str, names: Iterable[str]) -> Iterator[Problem | int]:
    """Yield a Problem for each column that is not a non-negative integer, else its value."""
    for name in names:
        value = row.cells[name]
        if _COUNT.fullmatch(value):
            yield int(value)
        else:
            yield Problem(rel, row.line, f"{name} must be a non-negative integer, got {value!r}")


def check_load(books: Books) -> Iterator[Problem]:
    yield from books.load_problems


def check_header(books: Books) -> Iterator[Problem]:
    for rel, schema in SCHEMAS.items():
        header = books.tables[rel].header
        if header is not None and tuple(header) != schema:
            yield Problem(rel, 1, "header does not match the schema: expected " + ",".join(schema))


def check_runs(books: Books) -> Iterator[Problem]:
    seen: dict[tuple[str, str], int] = {}
    for row in books.tables[RUNS].rows:
        c, n = row.cells, row.line
        if not _is_stamp(c["started"]):
            yield Problem(RUNS, n, f"started must look like 2026-11-15T09:30:00Z (UTC), got {c['started']!r}")
        if not _REPO.fullmatch(c["repo"]):
            yield Problem(RUNS, n, f"repo must match [a-z0-9][a-z0-9-]*, got {c['repo']!r}")
        if not _SHA.fullmatch(c["sha"]):
            yield Problem(RUNS, n, f"sha must be 40 lowercase hex characters, got {c['sha']!r}")
        if not c["event"]:
            yield Problem(RUNS, n, "event is empty")
        if not _PYTHON.fullmatch(c["python"]):
            yield Problem(RUNS, n, f"python must look like 3.12, got {c['python']!r}")
        values = list(_counts(row, RUNS, ("tests", "failed", "skipped", "wall_ms", "exit_code")))
        bad = [v for v in values if isinstance(v, Problem)]
        yield from bad
        if not bad:
            tests, failed, skipped, _, code = values
            if failed + skipped > tests:
                yield Problem(RUNS, n, f"failed + skipped ({failed + skipped}) is more than tests ({tests})")
            if code > 255:
                yield Problem(RUNS, n, f"exit_code must be 0 to 255, got {code}")
        if not _RUN_LINK.fullmatch(c["evidence"]):
            yield Problem(RUNS, n, "evidence must look like https://HOST/OWNER/REPO/actions/runs/N/attempts/N, "
                                   f"got {c['evidence']!r}")
        key = (c["evidence"], c["python"])
        if key in seen:
            yield Problem(RUNS, n, f"duplicate of line {seen[key]} (same evidence and python)")
        else:
            seen[key] = n


def check_failures(books: Books) -> Iterator[Problem]:
    seen: dict[tuple[str, str, str], int] = {}
    for row in books.tables[FAILURES].rows:
        c, n = row.cells, row.line
        if not _is_stamp(c["started"]):
            yield Problem(FAILURES, n, f"started must look like 2026-11-15T09:30:00Z (UTC), got {c['started']!r}")
        if not _REPO.fullmatch(c["repo"]):
            yield Problem(FAILURES, n, f"repo must match [a-z0-9][a-z0-9-]*, got {c['repo']!r}")
        if not _SHA.fullmatch(c["sha"]):
            yield Problem(FAILURES, n, f"sha must be 40 lowercase hex characters, got {c['sha']!r}")
        if not _PYTHON.fullmatch(c["python"]):
            yield Problem(FAILURES, n, f"python must look like 3.12, got {c['python']!r}")
        if not c["test_id"]:
            yield Problem(FAILURES, n, "test_id is empty")
        if c["outcome"] not in FAILING:
            yield Problem(FAILURES, n, f"outcome must be fail or error, got {c['outcome']!r}")
        if not _RUN_LINK.fullmatch(c["evidence"]):
            yield Problem(FAILURES, n, "evidence must look like https://HOST/OWNER/REPO/actions/runs/N/attempts/N, "
                                       f"got {c['evidence']!r}")
        key = (c["evidence"], c["python"], c["test_id"])
        if key in seen:
            yield Problem(FAILURES, n, f"duplicate of line {seen[key]} (same evidence, python and test_id)")
        else:
            seen[key] = n


def check_failures_match_runs(books: Books) -> Iterator[Problem]:
    """Every failure belongs to a run, and a run has exactly as many failure rows as it says failed."""
    if any(p.path in (RUNS, FAILURES) for p in books.load_problems):
        return  # a file that did not load says so once; comparing what is left would only add noise
    runs = {(r.cells["evidence"], r.cells["python"]): r for r in books.tables[RUNS].rows}
    counted: dict[tuple[str, str], int] = {}
    for row in books.tables[FAILURES].rows:
        c = row.cells
        key = (c["evidence"], c["python"])
        run = runs.get(key)
        if run is None:
            yield Problem(FAILURES, row.line, f"no run in {RUNS} with evidence {c['evidence']!r} and python {c['python']}")
            continue
        counted[key] = counted.get(key, 0) + 1
        for name in ("started", "repo", "sha"):
            if c[name] != run.cells[name]:
                yield Problem(FAILURES, row.line, f"{name} {c[name]!r} differs from {RUNS} line {run.line} ({run.cells[name]!r})")
    for key, run in runs.items():
        failed = run.cells["failed"]
        if _COUNT.fullmatch(failed) and int(failed) != counted.get(key, 0):
            yield Problem(RUNS, run.line, f"failed is {failed} but {FAILURES} has {counted.get(key, 0)} rows for this run")


def check_weekly(books: Books) -> Iterator[Problem]:
    seen: dict[tuple[str, str, str], int] = {}
    previous: tuple[str, str, str] | None = None
    for row in books.tables[WEEKLY].rows:
        c, n = row.cells, row.line
        if not _is_iso_week(c["week"]):
            yield Problem(WEEKLY, n, f"week must be a real ISO week like 2026-W46 (01 to 53), got {c['week']!r}")
        if not _REPO.fullmatch(c["repo"]):
            yield Problem(WEEKLY, n, f"repo must match [a-z0-9][a-z0-9-]*, got {c['repo']!r}")
        if not c["test_id"]:
            yield Problem(WEEKLY, n, "test_id is empty")
        values = list(_counts(row, WEEKLY, ("runs", "failed", "total_ms", "max_ms")))
        bad = [v for v in values if isinstance(v, Problem)]
        yield from bad
        if not bad:
            runs, failed, total, mx = values
            if runs < 1:
                yield Problem(WEEKLY, n, "runs must be at least 1")
            if failed > runs:
                yield Problem(WEEKLY, n, f"failed ({failed}) is more than runs ({runs})")
            if mx > total:
                yield Problem(WEEKLY, n, f"max_ms ({mx}) is more than total_ms ({total})")
        key = (c["week"], c["repo"], c["test_id"])
        if key in seen:
            yield Problem(WEEKLY, n, f"duplicate of line {seen[key]} (same week, repo and test_id)")
        else:
            seen[key] = n
        if previous is not None and key < previous:
            yield Problem(WEEKLY, n, "not sorted by week, repo, test_id")
        previous = key


def _base_problem(books: Books) -> Problem | None:
    ref = books.base
    try:
        if _git(books.dir, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode != 0:
            return Problem(RUNS, 1, f"cannot check against {ref}: not a commit here (is this a git repo, and is the ref fetched?)")
    except OSError as e:
        return Problem(RUNS, 1, f"cannot check against {ref}: git could not run ({e})")
    return None


def _lines(data: bytes) -> list[bytes]:
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts.pop()
    return parts


APPEND_ONLY = (RUNS, FAILURES)


def check_append_only(books: Books) -> Iterator[Problem]:
    ref = books.base
    if ref is None:
        return
    problem = _base_problem(books)
    if problem:
        yield problem
        return
    top = _git(books.dir, "rev-parse", "--show-toplevel")
    top_dir = os.fsdecode(top.stdout).rstrip("\n")
    if top.returncode != 0 or os.path.realpath(top_dir) != os.path.realpath(books.dir):
        # ls-tree is relative to the folder, so inside a bigger repo it would find nothing
        # and call every edited row clean.
        where = f"it is inside the work tree at {top_dir}" if top.returncode == 0 else "it is not in a git work tree"
        yield Problem(RUNS, 1, f"cannot check against {ref}: the books folder must be the top level of its git "
                               f"work tree, but {where}")
        return
    for rel in APPEND_ONLY:
        yield from _append_only(books, rel)


def _append_only(books: Books, rel: str) -> Iterator[Problem]:
    ref = books.base
    listed = _git(books.dir, "ls-tree", "--name-only", ref, "--", rel)
    if listed.returncode != 0:
        yield Problem(rel, 1, f"cannot check against {ref}: git ls-tree failed")
        return
    if not listed.stdout.strip():
        return  # the file did not exist at the base
    shown = _git(books.dir, "show", f"{ref}:./{rel}")
    if shown.returncode != 0:
        yield Problem(rel, 1, f"cannot check against {ref}: git show failed")
        return
    if books.tables[rel].bad_format:
        return  # load already said why; comparing bytes would only repeat it on every line
    old, new = _lines(shown.stdout), _lines(books.tables[rel].data)
    for i, line in enumerate(old):
        if i >= len(new):
            yield Problem(rel, i + 1, f"removed since {ref}")
        elif new[i] != line:
            yield Problem(rel, i + 1, f"changed since {ref}")


CHECKS: tuple[tuple[str, Check], ...] = (
    ("load", check_load),
    ("header", check_header),
    ("runs", check_runs),
    ("failures", check_failures),
    ("failures-match-runs", check_failures_match_runs),
    ("weekly", check_weekly),
    ("append-only", check_append_only),
)


def run_checks(books: Books) -> list[Problem]:
    problems = [p for _, check in CHECKS for p in check(books)]
    return sorted(set(problems), key=lambda p: (p.path, p.line, p.message))


def cmd_check(args: argparse.Namespace) -> int:
    books_dir = args.books_dir
    if not os.path.isdir(books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    books = load(books_dir, args.base)
    problems = run_checks(books)
    for p in problems:
        print(p)
    if problems:
        print(f"{len(problems)} problems")
        return 1
    print(f"ok, {sum(len(t.rows) for t in books.tables.values())} rows, 0 problems")
    return 0


# ---------------------------------------------------------------------------
# the books as typed rows
# ---------------------------------------------------------------------------


class RunRow(NamedTuple):
    started: str
    repo: str
    sha: str
    event: str
    workflow: str
    python: str
    tests: int
    failed: int
    skipped: int
    wall_ms: int
    exit_code: int
    evidence: str


class FailureRow(NamedTuple):
    started: str
    repo: str
    sha: str
    python: str
    test_id: str
    outcome: str
    evidence: str


class WeeklyRow(NamedTuple):
    week: str
    repo: str
    test_id: str
    runs: int
    failed: int
    total_ms: int
    max_ms: int


def _typed_rows(books: Books, rel: str, cls) -> list:
    """The rows of a table that passed `check`, as typed tuples."""
    ints = {name for name, kind in cls.__annotations__.items() if kind is int}
    return [cls(*(int(r.cells[name]) if name in ints else r.cells[name] for name in cls._fields))
            for r in books.tables[rel].rows]


def week_of(stamp: str) -> str:
    """The ISO week (UTC) of a `2026-11-15T09:30:00Z` stamp."""
    year, week, _ = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").isocalendar()
    return f"{year}-W{week:02d}"


def week_back(week: str, count: int) -> str:
    year, number = int(week[:4]), int(week[6:])
    monday = date.fromisocalendar(year, number, 1) - timedelta(weeks=count)
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _cell(text: str) -> str:
    if any(ch in text for ch in ',"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def _csv_line(cells: Iterable[object]) -> str:
    return ",".join(_cell(str(c)) for c in cells) + "\n"


# ---------------------------------------------------------------------------
# ingest: untrusted artifacts in, books out
# ---------------------------------------------------------------------------

MAX_ARTIFACT_BYTES = 64 << 20
MAX_NUMBER = 1 << 53  # what any JSON consumer still holds exactly
HEADER_KINDS = {"v": int, "repo": str, "sha": str, "event": str, "workflow": str, "python": str, "os": str,
                "started": str, "wall_ms": int, "exit_code": int, "complete": bool, "tests": int,
                "failed": int, "skipped": int, "evidence": str}
ROW_KINDS = {"id": str, "outcome": str, "ms": int}


class Rejected(Exception):
    """An artifact that cannot be booked, and why."""


def _show(value: object, limit: int = 60) -> str:
    """Untrusted text, made safe to print: ASCII only, no control characters, cut short."""
    text = ascii(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


@dataclass(frozen=True)
class RecordedRun:
    """One artifact, parsed and checked: the header, and one (id, outcome, ms) per test line."""
    header: dict
    tests: tuple[tuple[str, str, int], ...]
    digest: str  # of the file's bytes: the tie-breaker between two files that claim the same run

    @property
    def key(self) -> tuple[str, str]:
        return self.header["evidence"], self.header["python"]

    @property
    def is_ci(self) -> bool:
        return self.header["event"] != "local" and self.header["evidence"] != ""

    def verdict(self) -> int:
        """The recorder's own verdict for the run, recomputed: a run cut short never books as green."""
        rows = [{"outcome": outcome} for _, outcome, _ in self.tests]
        return exit_code(self.header["exit_code"], rows, self.header["complete"])

    def failing(self) -> dict[str, str]:
        """test id -> fail or error (error when any of its lines is an error)."""
        found: dict[str, str] = {}
        for test_id, outcome, _ in self.tests:
            if outcome in FAILING:
                found[test_id] = "error" if "error" in (outcome, found.get(test_id)) else "fail"
        return found

    def per_test(self) -> dict[str, tuple[bool, int]]:
        """test id -> (it failed, ms over its lines), for each test with a pass, fail or error line.
        A suite that reuses an id (a nested run) gives one entry, with the lines' time added."""
        seen: dict[str, tuple[bool, int]] = {}
        for test_id, outcome, ms in self.tests:
            if outcome != "skip":
                failed, total = seen.get(test_id, (False, 0))
                seen[test_id] = (failed or outcome in FAILING, total + ms)
        return seen


def _clean_text(value: str, what: str) -> None:
    if "\x00" in value:
        raise Rejected(f"{what} contains a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Rejected(f"{what} is not valid Unicode text") from None


def _check_fields(obj: object, kinds: dict[str, type], what: str) -> dict:
    if not isinstance(obj, dict):
        raise Rejected(f"{what} is not a JSON object")
    missing = [k for k in kinds if k not in obj]
    if missing:
        raise Rejected(f"{what} is missing {', '.join(missing)}")
    extra = sorted(set(obj) - set(kinds))
    if extra:
        raise Rejected(f"{what} has an unknown key {_show(extra[0])}")
    for key, kind in kinds.items():
        value = obj[key]
        if type(value) is not kind:  # `is`: True is not a count, 1.0 is not an int
            raise Rejected(f"{what} {key} must be {kind.__name__}, got {_show(value)}")
        if kind is int and not 0 <= value <= MAX_NUMBER:
            raise Rejected(f"{what} {key} must be an integer from 0 to 2**53, got {_show(value)}")
        if kind is str:
            _clean_text(value, f"{what} {key}")
    return obj


def _load_json(line: bytes, number: int) -> object:
    def twice(pairs):
        found: dict = {}
        for key, value in pairs:
            if key in found:
                raise Rejected(f"line {number}: duplicate key {_show(key)}")
            found[key] = value
        return found

    def constant(name):
        raise Rejected(f"line {number}: {name} is not valid JSON")

    try:
        return json.loads(line.decode("utf-8"), object_pairs_hook=twice, parse_constant=constant)
    except Rejected:
        raise
    except UnicodeDecodeError:
        raise Rejected(f"line {number}: not UTF-8 text") from None
    except (ValueError, RecursionError):
        raise Rejected(f"line {number}: not valid JSON") from None


def parse_artifact(data: bytes) -> RecordedRun:
    """A recorder file, strictly. Every claim in it is checked here and nowhere else; nothing in it
    is executed, imported or evaluated, and a test id is only ever a string."""
    if len(data) > MAX_ARTIFACT_BYTES:
        raise Rejected(f"file is larger than {MAX_ARTIFACT_BYTES >> 20} MB")
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if not lines:
        raise Rejected("file is empty")
    header = _check_fields(_load_json(lines[0], 1), HEADER_KINDS, "header")
    if header["v"] != RECORD_VERSION:
        raise Rejected(f"header v must be {RECORD_VERSION}, got {_show(header['v'])}")
    tests = []
    for number, line in enumerate(lines[1:], start=2):
        row = _check_fields(_load_json(line, number), ROW_KINDS, f"line {number}")
        if row["outcome"] not in OUTCOMES:
            raise Rejected(f"line {number} outcome must be one of {', '.join(OUTCOMES)}, got {_show(row['outcome'])}")
        if not row["id"]:
            raise Rejected(f"line {number} id is empty")
        tests.append((row["id"], row["outcome"], row["ms"]))
    counted = {"tests": len(tests), "failed": sum(o in FAILING for _, o, _ in tests),
               "skipped": sum(o == "skip" for _, o, _ in tests)}
    for key, actual in counted.items():
        if header[key] != actual:
            raise Rejected(f"header {key} is {header[key]} but the file has {actual}")
    run = RecordedRun(header, tuple(tests), hashlib.sha256(data).hexdigest())
    if run.is_ci:
        _check_ci_header(header)
    return run


def _check_ci_header(header: dict) -> None:
    for key, pattern, hint in (("repo", _REPO, "match [a-z0-9][a-z0-9-]*"), ("sha", _SHA, "be 40 lowercase hex characters"),
                               ("python", _PYTHON, "look like 3.12"), ("evidence", _RUN_LINK, "be a run link like "
                               "https://HOST/OWNER/REPO/actions/runs/N/attempts/N")):
        if not pattern.fullmatch(header[key]):
            raise Rejected(f"header {key} must {hint}, got {_show(header[key])}")
    if not _is_stamp(header["started"]):
        raise Rejected(f"header started must look like 2026-11-15T09:30:00Z, got {_show(header['started'])}")
    if header["exit_code"] > 255:
        raise Rejected(f"header exit_code must be 0 to 255, got {header['exit_code']}")


@dataclass
class Scan:
    path: str  # relative to the artifact directory
    status: str  # booked, already, local, rejected
    run: RecordedRun | None = None
    reason: str = ""


def find_artifacts(root: str) -> list[str]:
    """Every *.jsonl under root, any depth, as sorted relative paths. Symlinked directories are not entered."""
    found = []
    for folder, _, names in os.walk(root):
        found += [os.path.relpath(os.path.join(folder, n), root) for n in names if n.endswith(".jsonl")]
    return sorted(found)


def _read_artifact(path: str) -> bytes:
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise Rejected("is a symbolic link")
        if not stat.S_ISREG(info.st_mode):
            raise Rejected("is not a regular file")
        if info.st_size > MAX_ARTIFACT_BYTES:
            raise Rejected(f"file is larger than {MAX_ARTIFACT_BYTES >> 20} MB")
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise Rejected(f"cannot read file ({e.strerror or type(e).__name__})") from None


def scan_artifacts(root: str) -> list[Scan]:
    scans = []
    for rel in find_artifacts(root):
        try:
            run = parse_artifact(_read_artifact(os.path.join(root, rel)))
        except Rejected as e:
            scans.append(Scan(rel, "rejected", reason=str(e)))
        else:
            scans.append(Scan(rel, "booked" if run.is_ci else "local", run))
    return scans


def choose_new_runs(scans: list[Scan], booked: set[tuple[str, str]]) -> list[Scan]:
    """Mark the scans that book a run nobody has booked yet (status stays `booked`), the rest `already`.

    Two files for one run (a download taken twice) book one: the one that sorts first by content
    hash, so the choice never depends on the order the files were found in.
    """
    taken = set(booked)
    candidates = sorted((s for s in scans if s.status == "booked"),
                        key=lambda s: (s.run.header["started"], s.run.key, s.run.digest, s.path))
    for scan in candidates:
        if scan.run.key in taken:
            scan.status, scan.reason = "already", "already booked"
        else:
            taken.add(scan.run.key)
    return [s for s in candidates if s.status == "booked"]


@dataclass
class Plan:
    """What an ingest adds to the books, as the three files' new bytes (None: unchanged)."""
    files: dict[str, bytes | None]
    runs: int
    failures: int
    weekly_rows: int


def plan_ingest(books: Books, new: list[Scan]) -> Plan:
    """The books after booking `new`. runs.csv and failures.csv only grow by whole lines at the end."""
    old = {rel: books.tables[rel].data for rel in SCHEMAS}
    if not new:
        return Plan({rel: None for rel in SCHEMAS}, 0, 0, 0)
    weekly = {(w.week, w.repo, w.test_id): [w.runs, w.failed, w.total_ms, w.max_ms]
              for w in _typed_rows(books, WEEKLY, WeeklyRow)}
    touched: set[tuple[str, str, str]] = set()
    runs_text, failures_text, failures = "", "", 0
    for scan in new:
        h = scan.run.header
        failing = scan.run.failing()
        runs_text += _csv_line((h["started"], h["repo"], h["sha"], h["event"], h["workflow"], h["python"], h["tests"],
                                len(failing), h["skipped"], h["wall_ms"], scan.run.verdict(), h["evidence"]))
        for test_id in sorted(failing):
            failures_text += _csv_line((h["started"], h["repo"], h["sha"], h["python"], test_id, failing[test_id],
                                        h["evidence"]))
            failures += 1
        week = week_of(h["started"])
        for test_id, (failed, ms) in scan.run.per_test().items():
            key = (week, h["repo"], test_id)
            cell = weekly.setdefault(key, [0, 0, 0, 0])
            cell[0] += 1
            cell[1] += failed
            cell[2] += ms
            cell[3] = max(cell[3], ms)
            touched.add(key)
    weekly_text = _csv_line(WEEKLY_SCHEMA) + "".join(_csv_line(k + tuple(v)) for k, v in sorted(weekly.items()))

    def appended(rel: str, text: str) -> bytes:
        data = old[rel]
        return data + (b"" if data.endswith(b"\n") or not data else b"\n") + text.encode("utf-8")

    return Plan({RUNS: appended(RUNS, runs_text), FAILURES: appended(FAILURES, failures_text),
                 WEEKLY: weekly_text.encode("utf-8")}, len(new), failures, len(touched))


def commit_files(books_dir: str, files: dict[str, bytes | None]) -> None:
    """Write the changed files so that either all of them change or none does.

    Every new file is written beside its target first; a failure then leaves the books as they were.
    The renames come last, and one that fails puts the earlier ones back.
    """
    changed = {rel: data for rel, data in files.items() if data is not None}
    paths = {rel: os.path.join(books_dir, rel) for rel in changed}
    temps = {rel: os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{os.getpid()}.tmp")
             for rel, path in paths.items()}
    before = {rel: _read(path) for rel, path in paths.items()}
    swapped: list[str] = []
    try:
        for rel, data in changed.items():
            with open(temps[rel], "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        for rel in changed:
            os.replace(temps[rel], paths[rel])
            swapped.append(rel)
    except BaseException:
        for rel in swapped:
            if isinstance(before[rel], bytes):
                with open(paths[rel], "wb") as f:
                    f.write(before[rel])
        raise
    finally:
        for temp in temps.values():
            with contextlib.suppress(OSError):
                os.remove(temp)


def _print_problems(problems: list[Problem]) -> None:
    for p in problems:
        print(p)


def cmd_ingest(args: argparse.Namespace) -> int:
    for folder in (args.books_dir, args.artifact_dir):
        if not os.path.isdir(folder):
            print(f"quality.py: not a directory: {folder}", file=sys.stderr)
            return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; refusing to ingest into books that fail check")
        return 1
    scans = scan_artifacts(args.artifact_dir)
    booked = {(r.evidence, r.python) for r in _typed_rows(books, RUNS, RunRow)}
    new = choose_new_runs(scans, booked)
    plan = plan_ingest(books, new)
    if new:
        after = run_checks(books_from_bytes(args.books_dir, {rel: data if data is not None else books.tables[rel].data
                                                             for rel, data in plan.files.items()}))
        if after:
            _print_problems(after)
            print(f"{len(after)} problems; nothing written")
            return 1
    wrote = bool(new) and not args.dry_run
    if wrote:
        try:
            commit_files(args.books_dir, plan.files)
        except OSError as e:
            print(f"quality.py: cannot write the books, they are unchanged: {e}", file=sys.stderr)
            return 1
    rejected = [s for s in scans if s.status == "rejected"]
    totals = {"files": len(scans), "booked": len(new), "already_booked": sum(s.status == "already" for s in scans),
              "local": sum(s.status == "local" for s in scans), "rejected": len(rejected),
              "failures": plan.failures, "weekly_rows": plan.weekly_rows}
    if args.json:
        files = [_scan_json(s) for s in scans]
        print(json.dumps({"dry_run": args.dry_run, "files": files, "totals": totals, "wrote": wrote},
                         sort_keys=True, indent=2))
    else:
        _print_ingest(scans, totals, args.dry_run)
    return 1 if rejected else 0


def _scan_json(scan: Scan) -> dict:
    out = {"path": scan.path, "status": scan.status}
    if scan.reason:
        out["reason"] = scan.reason
    if scan.status == "booked":
        h = scan.run.header
        out.update(evidence=h["evidence"], python=h["python"], tests=h["tests"], exit_code=scan.run.verdict())
    return out


def _print_ingest(scans: list[Scan], totals: dict, dry_run: bool) -> None:
    for s in scans:
        name = _show(s.path, 200) if not s.path.isprintable() else s.path
        if s.status == "booked":
            h = s.run.header
            print(f"{'would book' if dry_run else 'booked'}: {name}: {h['repo']} {h['python']} {h['tests']} tests, "
                  f"exit_code {s.run.verdict()}, {h['evidence']}")
        elif s.status == "already":
            print(f"skipped, already booked: {name}")
        elif s.status == "local":
            print(f"skipped, not a CI run (event local or no evidence): {name}")
        else:
            print(f"rejected: {name}: {s.reason}")
    line = (f"{'would book' if dry_run else 'booked'} {totals['booked']} runs, {totals['failures']} failures, "
            f"{totals['weekly_rows']} weekly rows touched; skipped {totals['already_booked']} already booked, "
            f"{totals['local']} local; rejected {totals['rejected']} of {totals['files']} files")
    print(line)
    if totals["rejected"]:
        print("some files were rejected: the others were booked and ingest exits 1 so the rejection is not missed"
              if not dry_run else "some files were rejected; ingest exits 1")


# ---------------------------------------------------------------------------
# summary: every number the weekly brief quotes
# ---------------------------------------------------------------------------

SLOWEST = 10  # tests listed per repo and overall
PRIOR_WEEKS = 4  # calendar ISO weeks before the week, whichever of them have runs


def median(values: list[int]) -> int:
    """The lower of the two middle values for an even count, so the result is always an integer
    that one of the runs actually had."""
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def _slowest(rows: list[WeeklyRow]) -> list[dict]:
    ranked = sorted(rows, key=lambda w: (-(w.total_ms // w.runs), w.test_id, w.repo))
    return [{"max_ms": w.max_ms, "mean_ms": w.total_ms // w.runs, "repo": w.repo, "runs": w.runs, "test_id": w.test_id}
            for w in ranked[:SLOWEST]]


def _flaky(repo_runs: list[RunRow], repo_failures: list[FailureRow], week: str) -> list[dict]:
    """Tests that failed in one run and not in another of the same commit and Python.

    A test is listed when it has a failure row this week. Its failing side is every failure row
    of that repo, sha, Python and test (any week); its passing side is every run in the books (any
    week) of the same repo, sha and Python that has no failure row for the test. The books keep
    failures only, so a run in which the test was skipped or did not exist looks the same as a
    pass, and a run that is red for some other test counts as passing this one. A commit whose
    every run failed the test is not flaky. Python is part of the key because a test that fails
    only on 3.10 is a compatibility bug, not a flake.
    """
    failed_in: dict[tuple[str, str, str], set[str]] = {}
    for f in repo_failures:
        failed_in.setdefault((f.test_id, f.sha, f.python), set()).add(f.evidence)
    listed = {(f.test_id, f.sha, f.python) for f in repo_failures if week_of(f.started) == week}
    out = []
    for key in sorted(listed):
        test_id, sha, python = key
        passed = {r.evidence for r in repo_runs if r.sha == sha and r.python == python} - failed_in[key]
        if passed:
            out.append({"failed_evidence": sorted(failed_in[key]), "passed_evidence": sorted(passed),
                        "python": python, "sha": sha, "test_id": test_id})
    return out


def _repo_summary(repo: str, week: str, runs: list[RunRow], failures: list[FailureRow], weekly: list[WeeklyRow]) -> dict:
    mine = [r for r in runs if r.repo == repo]
    this = [r for r in mine if week_of(r.started) == week]
    walls = [r.wall_ms for r in this]
    by_python = {py: [r.wall_ms for r in this if r.python == py] for py in sorted({r.python for r in this})}
    prior_weeks = {week_back(week, k) for k in range(1, PRIOR_WEEKS + 1)}
    prior = [r for r in mine if week_of(r.started) in prior_weeks]
    prior_median = median([r.wall_ms for r in prior]) if prior else None
    this_median = median(walls)
    event_of = {(r.evidence, r.python): r.event for r in mine}
    repo_failures = [f for f in failures if f.repo == repo]
    fails = [f for f in repo_failures if week_of(f.started) == week]
    rows = [w for w in weekly if w.repo == repo]
    here = [w for w in rows if w.week == week]
    earlier = [w.week for w in rows if w.week < week]
    before = {w.test_id for w in rows if w.week == max(earlier)} if earlier else None
    ids = {w.test_id for w in here}
    return {
        "ci_wall_ms": sum(walls),
        "failed_on_main": [{"evidence": f.evidence, "outcome": f.outcome, "python": f.python, "sha": f.sha,
                            "test_id": f.test_id}
                           for f in sorted(fails, key=lambda f: (f.test_id, f.evidence, f.python))
                           if event_of.get((f.evidence, f.python)) == "push"],
        "flaky": _flaky(mine, repo_failures, week),
        "over_threshold": this_median > SUITE_MEDIAN_THRESHOLD_MS,
        "red_runs": sum(r.exit_code != 0 for r in this),
        "runs": len(this),
        "slowest_tests": [{k: v for k, v in t.items() if k != "repo"} for t in _slowest(here)],
        "suite_ms": {"by_python": {py: {"median": median(v), "runs": len(v)} for py, v in by_python.items()},
                     "max": max(walls), "median": this_median},
        "suite_ms_change": None if prior_median is None else this_median - prior_median,
        "suite_ms_prior4": {"median": prior_median, "weeks": len({week_of(r.started) for r in prior})},
        "tests": max(this, key=lambda r: (r.started, r.evidence, r.python)).tests,
        "tests_added": sorted(ids - before) if before is not None else [],
        "tests_removed": sorted(before - ids) if before is not None else [],
    }


def summarize(runs: list[RunRow], failures: list[FailureRow], weekly: list[WeeklyRow], week: str) -> dict:
    """The week's numbers as plain data: integers, strings, lists and dicts, nothing else."""
    repos = sorted({r.repo for r in runs if week_of(r.started) == week})
    return {
        "generated_from": {"failures": len(failures), "runs": len(runs), "weekly_rows": len(weekly)},
        "repos": {repo: _repo_summary(repo, week, runs, failures, weekly) for repo in repos},
        "slowest_tests": _slowest([w for w in weekly if w.week == week and w.repo in repos]),
        "thresholds": {"suite_median_ms": SUITE_MEDIAN_THRESHOLD_MS},
        "week": week,
    }


def render_summary(s: dict) -> str:
    lines = [f"quality summary for {s['week']} (from {s['generated_from']['runs']} runs, "
             f"{s['generated_from']['failures']} failures, {s['generated_from']['weekly_rows']} weekly rows)"]
    for repo, r in s["repos"].items():
        change = r["suite_ms_change"]
        lines.append(f"{repo}: {r['runs']} runs ({r['red_runs']} red), {r['tests']} tests, suite median "
                     f"{r['suite_ms']['median']} ms (max {r['suite_ms']['max']}), "
                     + ("no prior weeks" if change is None else f"{change:+d} ms vs the prior weeks")
                     + (", OVER THRESHOLD" if r["over_threshold"] else ""))
        lines.append(f"  failed on a push: {len(r['failed_on_main'])}; flaky: {len(r['flaky'])}; "
                     f"tests added {len(r['tests_added'])}, removed {len(r['tests_removed'])}; CI time {r['ci_wall_ms']} ms")
        for t in r["slowest_tests"][:3]:
            lines.append(f"  slow: {t['test_id']} mean {t['mean_ms']} ms over {t['runs']} runs")
    lines.append(f"threshold: suite median above {s['thresholds']['suite_median_ms']} ms")
    return "\n".join(lines)


def cmd_summary(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    if args.week is not None and not _is_iso_week(args.week):
        print(f"quality.py: --week must be a real ISO week like 2026-W46, got {args.week!r}", file=sys.stderr)
        return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; no summary from unchecked books")
        return 1
    runs = _typed_rows(books, RUNS, RunRow)
    week = args.week or max((week_of(r.started) for r in runs), default=None)
    if week is None:
        print("no runs in the books; pass --week to summarize an empty week", file=sys.stderr)
        return 1
    result = summarize(runs, _typed_rows(books, FAILURES, FailureRow), _typed_rows(books, WEEKLY, WeeklyRow), week)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else render_summary(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality.py", description="The Quality Director's recorder and books checker.")
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="run a unittest suite and write per-test time and outcome")
    record.add_argument("tests_dir", metavar="TESTS_DIR")
    record.add_argument("--out", required=True, metavar="FILE")
    record.add_argument("--repo", required=True, metavar="NAME")
    record.add_argument("--sha", type=_sha_arg, metavar="SHA",
                        help="the commit the run tests, 40 lowercase hex (wins over GITHUB_SHA and git)")
    record.set_defaults(func=cmd_record)
    check = sub.add_parser("check", help="validate the quality books")
    check.add_argument("books_dir", metavar="BOOKS_DIR")
    check.add_argument("--base", metavar="REF", help="fail if a runs.csv line at REF changed or was removed")
    check.set_defaults(func=cmd_check)
    ingest = sub.add_parser("ingest", help="book recorder files (JSON Lines) into the quality books")
    ingest.add_argument("books_dir", metavar="BOOKS_DIR")
    ingest.add_argument("artifact_dir", metavar="ARTIFACT_DIR")
    ingest.add_argument("--dry-run", action="store_true", help="say what would be booked; write nothing")
    ingest.add_argument("--json", action="store_true")
    ingest.set_defaults(func=cmd_ingest)
    summary = sub.add_parser("summary", help="the numbers for one week, from books that pass check")
    summary.add_argument("books_dir", metavar="BOOKS_DIR")
    summary.add_argument("--week", metavar="YYYY-Www", help="an ISO week; the latest week in runs.csv by default")
    summary.add_argument("--json", action="store_true")
    summary.set_defaults(func=cmd_summary)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
