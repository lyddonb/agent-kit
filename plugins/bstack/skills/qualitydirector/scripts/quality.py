#!/usr/bin/env python3
"""The Quality Director's two primitives: record a test run, and check the quality books.

Usage:
    uv run --python 3.12 quality.py record TESTS_DIR --out FILE --repo NAME [--sha SHA]
    uv run --python 3.12 quality.py check BOOKS_DIR [--base REF]

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

`check` validates books/runs.csv and books/tests-weekly.csv under BOOKS_DIR and prints one
`path:line: message` line per problem (path relative to BOOKS_DIR), then
`ok, N rows, 0 problems` or `N problems`. Exit 0 when clean, 1 when there are problems,
2 on bad usage. With --base REF, runs.csv must be append-only against REF.

Standard library only; needs Python 3.10 or later (run it through uv).

Shape: `Books` is loaded once (both CSV tables with line numbers). Each entry in `CHECKS`
takes a `Books` and yields `Problem`s. A new check is a new entry in that registry.
"""
import sys

if sys.version_info < (3, 10):
    sys.stderr.write(
        f"quality.py needs Python 3.10 or later (this is {sys.version_info[0]}.{sys.version_info[1]}). "
        "Run it with: uv run --python 3.12 <path to quality.py> ...\n")
    raise SystemExit(2)

import argparse
import csv
import io
import json
import os
import re
import select
import signal
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

RECORD_VERSION = 1
OUTCOMES = ("pass", "skip", "fail", "error")  # ordered by severity; a test keeps its worst
RUN_KEYS = ("v", "repo", "sha", "event", "workflow", "python", "os", "started",
            "wall_ms", "exit_code", "complete", "tests", "failed", "skipped", "evidence")
TEST_KEYS = ("id", "outcome", "ms")

RUNS = "books/runs.csv"
WEEKLY = "books/tests-weekly.csv"
RUNS_SCHEMA = ("started", "repo", "sha", "event", "workflow", "python",
               "tests", "failed", "skipped", "wall_ms", "exit_code", "evidence")
WEEKLY_SCHEMA = ("week", "repo", "test_id", "runs", "failed", "p50_ms", "max_ms")
SCHEMAS = {RUNS: RUNS_SCHEMA, WEEKLY: WEEKLY_SCHEMA}

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


def _load_table(books_dir: str, rel: str, problems: list[Problem]) -> Table:
    table = Table(rel)
    schema = SCHEMAS[rel]
    path = os.path.join(books_dir, rel)
    try:
        with open(path, "rb") as f:
            table.data = f.read()
    except FileNotFoundError:
        problems.append(Problem(rel, 1, "missing file"))
        return table
    except OSError as e:
        problems.append(Problem(rel, 1, f"cannot read file ({e.strerror or type(e).__name__})"))
        return table
    try:
        text = table.data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(Problem(rel, 1, "not UTF-8 text"))
        table.bad_format = True
        return table
    if text.startswith("\ufeff"):
        problems.append(Problem(rel, 1, "starts with a UTF-8 BOM; the books are plain UTF-8"))
        table.bad_format = True
        return table
    if "\r\n" in text:
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
        start, end = before + 1, reader.line_num
        if table.header is None:
            table.header = record
        elif end != start:
            problems.append(Problem(rel, start, "row spans more than one line (embedded newline or unclosed quote)"))
        elif len(record) != len(schema):
            problems.append(Problem(rel, start, f"row has {len(record)} columns, expected {len(schema)}"))
        else:
            table.rows.append(Row(start, dict(zip(schema, record))))
    if table.header is None:
        problems.append(Problem(rel, 1, "empty file; expected the header " + ",".join(schema)))
    return table


def load(books_dir: str, base: str | None = None) -> Books:
    problems: list[Problem] = []
    tables = {rel: _load_table(books_dir, rel, problems) for rel in SCHEMAS}
    return Books(books_dir, base, tables, problems)


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


def check_weekly(books: Books) -> Iterator[Problem]:
    seen: dict[tuple[str, str, str], int] = {}
    for row in books.tables[WEEKLY].rows:
        c, n = row.cells, row.line
        if not _is_iso_week(c["week"]):
            yield Problem(WEEKLY, n, f"week must be a real ISO week like 2026-W46 (01 to 53), got {c['week']!r}")
        if not _REPO.fullmatch(c["repo"]):
            yield Problem(WEEKLY, n, f"repo must match [a-z0-9][a-z0-9-]*, got {c['repo']!r}")
        if not c["test_id"]:
            yield Problem(WEEKLY, n, "test_id is empty")
        values = list(_counts(row, WEEKLY, ("runs", "failed", "p50_ms", "max_ms")))
        bad = [v for v in values if isinstance(v, Problem)]
        yield from bad
        if not bad:
            runs, failed, p50, mx = values
            if runs < 1:
                yield Problem(WEEKLY, n, "runs must be at least 1")
            if failed > runs:
                yield Problem(WEEKLY, n, f"failed ({failed}) is more than runs ({runs})")
            if p50 > mx:
                yield Problem(WEEKLY, n, f"p50_ms ({p50}) is more than max_ms ({mx})")
        key = (c["week"], c["repo"], c["test_id"])
        if key in seen:
            yield Problem(WEEKLY, n, f"duplicate of line {seen[key]} (same week, repo and test_id)")
        else:
            seen[key] = n


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
    listed = _git(books.dir, "ls-tree", "--name-only", ref, "--", RUNS)
    if listed.returncode != 0:
        yield Problem(RUNS, 1, f"cannot check against {ref}: git ls-tree failed")
        return
    if not listed.stdout.strip():
        return  # runs.csv did not exist at the base
    shown = _git(books.dir, "show", f"{ref}:./{RUNS}")
    if shown.returncode != 0:
        yield Problem(RUNS, 1, f"cannot check against {ref}: git show failed")
        return
    if books.tables[RUNS].bad_format:
        return  # load already said why; comparing bytes would only repeat it on every line
    old, new = _lines(shown.stdout), _lines(books.tables[RUNS].data)
    for i, line in enumerate(old):
        if i >= len(new):
            yield Problem(RUNS, i + 1, f"removed since {ref}")
        elif new[i] != line:
            yield Problem(RUNS, i + 1, f"changed since {ref}")


CHECKS: tuple[tuple[str, Check], ...] = (
    ("load", check_load),
    ("header", check_header),
    ("runs", check_runs),
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
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
