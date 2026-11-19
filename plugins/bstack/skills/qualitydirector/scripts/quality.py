#!/usr/bin/env python3
"""The Quality Director's primitives: record a test run, fetch the runs of watched repos from GitHub,
book them into the quality books, check the books, and summarize a week.

Usage:
    uv run --python 3.12 quality.py record TESTS_DIR --out FILE --repo NAME [--sha SHA]
    uv run --python 3.12 quality.py fetch BOOKS_DIR OUT_DIR [--since YYYY-MM-DD] [--repo SLUG]
    uv run --python 3.12 quality.py ingest BOOKS_DIR FETCH_DIR [--dry-run] [--json]
    uv run --python 3.12 quality.py check BOOKS_DIR [--base REF]
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

The books are four CSV files under BOOKS_DIR: books/runs.csv (one row per recorded CI run, append
only), books/failures.csv (one row per failing test in a run, append only), books/tests-weekly.csv
(per ISO week, repo and test: runs, failed, total and max milliseconds; rows are updated in place and
kept sorted) and books/watched.csv (the repos to book: `repo,github,workflow`, for example
`agentfiles,lyddonb/agentfiles,ci`; edited by hand).

Trust: CI runs pull-request code, so anyone who can get a workflow to run can write any recorder
file, and runs.csv and failures.csv cannot be edited afterwards. Who a run is therefore comes from
GitHub's API, never from the file. `fetch` writes the API's account of each run as manifest.json;
`ingest` believes the manifest for repo, sha, event, workflow, start time and the run link, and a
recorder file only for what it measured (python, wall_ms, exit_code, complete, its test rows, and the
attempt number inside its evidence when that names this run).

`fetch` asks GitHub through the `gh` CLI (found on PATH, or at $QUALITY_GH) for the completed runs
of each watched repo's workflow created on or after --since (default: the day of the latest
`started` in runs.csv for that repo, else 7 days before today UTC; `--today` sets "today" for tests),
and writes OUT_DIR/<repo>/<run_id>/manifest.json plus OUT_DIR/<repo>/<run_id>/artifacts/<name>/ for each
artifact whose name starts with `test-results-`. It never writes under BOOKS_DIR. A run from a fork
(its head repository is not the watched one) is listed and not downloaded. A push to a branch other than
the default branch is skipped, so every booked `push` run is a push to the default branch and
summary's `failed_on_main` is true to its name. A run whose artifacts are all booked is skipped. An
expired artifact, a failed call or an unsafe archive is reported and the rest carries on. Exit 0 when
everything listed was fetched, 1 when any run could not be, 2 on bad usage, a missing gh, or an OUT_DIR
inside BOOKS_DIR. The calls it makes, in order, for each repo: `gh api --paginate
"repos/O/N/actions/runs?status=completed&per_page=100&created=>=SINCE"`, `gh api repos/O/N`,
and for each run `gh api --paginate "repos/O/N/actions/runs/ID/artifacts?per_page=100"` and, for
each artifact, `gh api repos/O/N/actions/artifacts/ID/zip`. `--since` filters on a run's creation
date, so a re-run of an old run needs an earlier --since.

`check` validates the four files and prints one `path:line: message` line per problem (path
relative to BOOKS_DIR), then `ok, N rows, 0 problems` or `N problems`. Exit 0 when clean, 1 when
there are problems, 2 on bad usage. With --base REF, runs.csv and failures.csv must be
append-only against REF. It also checks across the files: every failures row belongs to a run,
and a run has exactly as many failures rows as its `failed` says. Every row is held to the row
rules (RUN_RULES, FAILURE_RULES, WEEKLY_RULES, WATCHED_RULES): stamps and weeks in 2020 to 2099,
`python` as 3.0 to 3.99 without leading zeros, cells of at most 1000 characters, and no cell that
starts with = + - @ tab or CR (a spreadsheet would run it) or holds a control character other than
newline and tab (a terminal would obey it).

`ingest` reads the layout `fetch` writes. For each <repo>/<run_id>/manifest.json: it must agree with
its folder, the repo must be on the watch list with the same github and workflow, `fork` must be false,
`started` must not be after `updated` plus 5 minutes and must be in 2020 to 2099, and a push must be to
the default branch; a manifest that fails is rejected by name with its artifact files unread. Each
*.jsonl under <run>/artifacts is parsed strictly (see `parse_artifact`); a file that is not valid is
named with the reason and skipped, and ingest exits 1 after booking the good ones. The rows a file would
add are built and held to the same row rules `check` uses before anything is planned, so no file can pass
here and fail `check`. Two files in one run folder for the same attempt and python with different
content are both rejected (identical copies count once); a forged file never wins by sorting first. A run
already in runs.csv (same evidence and python) is skipped, so a second ingest changes nothing. The runs.csv
`exit_code` is the recorder's verdict recomputed from the rows (a run cut short at child exit 0 books as
1), and a test with both an `error` and a `fail` line is an `error`: the worst outcome wins. Caps: 8 MB
per file, 20000 test lines per file, 1000 characters per cell, 2000 files and 32 MB of artifacts per
ingest (the rest are counted and named, not read, and ingest exits 1). The three files are built in
memory, checked, and written only if the result passes, all or none. Anything artifact-derived that is
printed has its non-printable characters escaped.

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
import shutil
import signal
import stat
import subprocess
import time
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
WATCHED = "books/watched.csv"
RUNS_SCHEMA = ("started", "repo", "sha", "event", "workflow", "python",
               "tests", "failed", "skipped", "wall_ms", "exit_code", "evidence")
FAILURES_SCHEMA = ("started", "repo", "sha", "python", "test_id", "outcome", "evidence")
WEEKLY_SCHEMA = ("week", "repo", "test_id", "runs", "failed", "total_ms", "max_ms")
WATCHED_SCHEMA = ("repo", "github", "workflow")
SCHEMAS = {RUNS: RUNS_SCHEMA, FAILURES: FAILURES_SCHEMA, WEEKLY: WEEKLY_SCHEMA, WATCHED: WATCHED_SCHEMA}
YEAR_MIN, YEAR_MAX = 2020, 2099  # the years a stamp or a week in the books may have
MAX_CELL = 1000  # characters in one cell, a test id included; the csv module's own field limit (131072) is never reached
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
_PYTHON = re.compile(r"3\.(0|[1-9][0-9]?)")
_WEEK = re.compile(r"([0-9]{4})-W([0-9]{2})")
_RUN_LINK = re.compile(r"https://[^/\s]+/[^/\s]+/[^/\s]+/actions/runs/[0-9]+/attempts/[0-9]+")
_COUNT = re.compile(r"0|[1-9][0-9]*")
_GITHUB = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
# C0 controls (ESC among them), DEL and the C1 controls (NEL, 8-bit CSI), but not newline or tab; the line and
# paragraph separators; the bidirectional controls; and the zero-width characters
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\u200b-\u200d\ufeff]")
_FORMULA_FIRST = "=+-@\uff1d\uff0b\uff0d\uff20"  # a spreadsheet runs a cell whose first real character is one of these (ASCII or fullwidth)
_FORMULA_SKIP = " \u00a0\t\n"  # characters a spreadsheet may skip before it sees that first character


def _is_stamp(s: str) -> bool:
    """A real UTC stamp like 2026-11-15T09:30:00Z, in the years the books accept (2020 to 2099)."""
    if not _STAMP.fullmatch(s):
        return False
    try:
        when = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return YEAR_MIN <= when.year <= YEAR_MAX


def _is_iso_week(s: str) -> bool:
    """2026-W53 is a week; 2025-W53 and 2026-W00 are not; the years are the books' 2020 to 2099."""
    m = _WEEK.fullmatch(s)
    if not m or not YEAR_MIN <= int(m[1]) <= YEAR_MAX:
        return False
    try:
        date.fromisocalendar(int(m[1]), int(m[2]), 1)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# row rules: the one definition of a good row, used by `check` on every row in the books and by
# `ingest` on every row a file would add, before the file is planned
# ---------------------------------------------------------------------------
#
# A rule takes a row's cells (a dict of column name to text) and yields a message for each
# problem. `check` reports a message with the row's line; ingest rejects the file that would
# produce the row, so a file that `check` would refuse can never reach the planner.

Rule = Callable[[dict], Iterator[str]]


def text_problem(value: str) -> str | None:
    """Why a text cell cannot go into a CSV the books share with a spreadsheet and a terminal.

    Rejected: a value that starts with a tab or a carriage return, or whose first character after any
    run of space, no-break space, tab and newline is `=`, `+`, `-` or `@` or their fullwidth forms
    (a spreadsheet would run it); any C0 control except newline and tab, DEL, any C1 control
    (U+0080 to U+009F, NEL and 8-bit CSI among them), U+2028, U+2029, the bidirectional controls
    (U+202A to U+202E, U+2066 to U+2069) and the zero-width characters (U+200B to U+200D, U+FEFF)
    (a terminal would obey them or they would hide what the value says); and a value over 1000
    characters. Newline and tab inside a value are allowed."""
    first = value[:1] if value[:1] in ("\t", "\r") else value.lstrip(_FORMULA_SKIP)[:1]
    if first and first in ("\t", "\r") + tuple(_FORMULA_FIRST):
        return f"starts with {_show(first, 8)}; a spreadsheet would run it as a formula"
    if _CONTROL.search(value):
        return "contains a control character (a C0 or C1 control, a line or paragraph separator, a bidirectional control or a zero-width character)"
    if len(value) > MAX_CELL:
        return f"is longer than {MAX_CELL} characters"
    return None


def _text_rule(*columns: str) -> Rule:
    """Hygiene for the cells that hold free text. The other columns are held to a pattern that already
    excludes what text_problem looks for."""
    def rule(cells: dict) -> Iterator[str]:
        for name in columns:
            why = text_problem(cells[name])
            if why:
                yield f"{name} {why}"
    return rule


def _stamp_rule(cells: dict) -> Iterator[str]:
    if not _is_stamp(cells["started"]):
        yield (f"started must look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
               f"got {_show(cells['started'])}")


def _repo_rule(cells: dict) -> Iterator[str]:
    if not _REPO.fullmatch(cells["repo"]):
        yield f"repo must match [a-z0-9][a-z0-9-]*, got {_show(cells['repo'])}"


def _sha_rule(cells: dict) -> Iterator[str]:
    if not _SHA.fullmatch(cells["sha"]):
        yield f"sha must be 40 lowercase hex characters, got {_show(cells['sha'])}"


def _python_rule(cells: dict) -> Iterator[str]:
    if not _PYTHON.fullmatch(cells["python"]):
        yield f"python must look like 3.12, got {_show(cells['python'])}"


def _evidence_rule(cells: dict) -> Iterator[str]:
    if not _RUN_LINK.fullmatch(cells["evidence"]):
        yield ("evidence must look like https://HOST/OWNER/REPO/actions/runs/N/attempts/N, "
               f"got {_show(cells['evidence'])}")


def _count_rule(names: tuple[str, ...]) -> Rule:
    def rule(cells: dict) -> Iterator[str]:
        for name in names:
            if not _COUNT.fullmatch(cells[name]):
                yield f"{name} must be a non-negative integer, got {_show(cells[name])}"
    return rule


def _counts_ok(cells: dict, names: tuple[str, ...]) -> list[int] | None:
    return [int(cells[n]) for n in names] if all(_COUNT.fullmatch(cells[n]) for n in names) else None


def _run_totals_rule(cells: dict) -> Iterator[str]:
    values = _counts_ok(cells, ("tests", "failed", "skipped", "wall_ms", "exit_code"))
    if values:
        tests, failed, skipped, _, code = values
        if failed + skipped > tests:
            yield f"failed + skipped ({failed + skipped}) is more than tests ({tests})"
        if code > 255:
            yield f"exit_code must be 0 to 255, got {code}"


def _event_rule(cells: dict) -> Iterator[str]:
    if not cells["event"]:
        yield "event is empty"


def _test_id_rule(cells: dict) -> Iterator[str]:
    if not cells["test_id"]:
        yield "test_id is empty"


def _outcome_rule(cells: dict) -> Iterator[str]:
    if cells["outcome"] not in FAILING:
        yield f"outcome must be fail or error, got {_show(cells['outcome'])}"


def _week_rule(cells: dict) -> Iterator[str]:
    if not _is_iso_week(cells["week"]):
        yield (f"week must be a real ISO week like 2026-W46 (01 to 53) in {YEAR_MIN} to {YEAR_MAX}, "
               f"got {_show(cells['week'])}")


def _weekly_limits_rule(cells: dict) -> Iterator[str]:
    values = _counts_ok(cells, ("runs", "failed", "total_ms", "max_ms"))
    if values:
        runs, failed, total, mx = values
        if runs < 1:
            yield "runs must be at least 1"
        if failed > runs:
            yield f"failed ({failed}) is more than runs ({runs})"
        if mx > total:
            yield f"max_ms ({mx}) is more than total_ms ({total})"


def _github_rule(cells: dict) -> Iterator[str]:
    if not _GITHUB.fullmatch(cells["github"]):
        yield f"github must look like OWNER/NAME, got {_show(cells['github'])}"


def _workflow_rule(cells: dict) -> Iterator[str]:
    if not cells["workflow"]:
        yield "workflow is empty"


RUN_RULES: dict[str, Rule] = {
    "started": _stamp_rule, "repo": _repo_rule, "sha": _sha_rule, "event": _event_rule, "python": _python_rule,
    "counts": _count_rule(("tests", "failed", "skipped", "wall_ms", "exit_code")), "totals": _run_totals_rule,
    "evidence": _evidence_rule, "text": _text_rule("event", "workflow", "evidence"),
}
FAILURE_RULES: dict[str, Rule] = {
    "started": _stamp_rule, "repo": _repo_rule, "sha": _sha_rule, "python": _python_rule, "test_id": _test_id_rule,
    "outcome": _outcome_rule, "evidence": _evidence_rule, "text": _text_rule("test_id", "evidence"),
}
WEEKLY_RULES: dict[str, Rule] = {
    "week": _week_rule, "repo": _repo_rule, "test_id": _test_id_rule,
    "counts": _count_rule(("runs", "failed", "total_ms", "max_ms")), "limits": _weekly_limits_rule,
    "text": _text_rule("test_id"),
}
WATCHED_RULES: dict[str, Rule] = {
    "repo": _repo_rule, "github": _github_rule, "workflow": _workflow_rule, "text": _text_rule("workflow"),
}


def rule_messages(rules: dict[str, Rule], cells: dict) -> Iterator[str]:
    for rule in rules.values():
        yield from rule(cells)


def check_load(books: Books) -> Iterator[Problem]:
    yield from books.load_problems


def check_header(books: Books) -> Iterator[Problem]:
    for rel, schema in SCHEMAS.items():
        header = books.tables[rel].header
        if header is not None and tuple(header) != schema:
            yield Problem(rel, 1, "header does not match the schema: expected " + ",".join(schema))


def _check_rows(books: Books, rel: str, rules: dict[str, Rule]) -> Iterator[Problem]:
    for row in books.tables[rel].rows:
        for message in rule_messages(rules, row.cells):
            yield Problem(rel, row.line, message)


def check_runs(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, RUNS, RUN_RULES)
    seen: dict[tuple[str, str], int] = {}
    for row in books.tables[RUNS].rows:
        key = (row.cells["evidence"], row.cells["python"])
        if key in seen:
            yield Problem(RUNS, row.line, f"duplicate of line {seen[key]} (same evidence and python)")
        else:
            seen[key] = row.line


def check_failures(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, FAILURES, FAILURE_RULES)
    seen: dict[tuple[str, str, str], int] = {}
    for row in books.tables[FAILURES].rows:
        c = row.cells
        key = (c["evidence"], c["python"], c["test_id"])
        if key in seen:
            yield Problem(FAILURES, row.line, f"duplicate of line {seen[key]} (same evidence, python and test_id)")
        else:
            seen[key] = row.line


def check_failures_match_runs(books: Books) -> Iterator[Problem]:
    """Every failure belongs to a run, and a run has min(failed, MAX_FAILURE_ROWS) failure rows."""
    if any(p.path in (RUNS, FAILURES) for p in books.load_problems):
        return  # a file that did not load says so once; comparing what is left would only add noise
    runs = {(r.cells["evidence"], r.cells["python"]): r for r in books.tables[RUNS].rows}
    counted: dict[tuple[str, str], int] = {}
    for row in books.tables[FAILURES].rows:
        c = row.cells
        key = (c["evidence"], c["python"])
        run = runs.get(key)
        if run is None:
            yield Problem(FAILURES, row.line, f"no run in {RUNS} with evidence {_show(c['evidence'])} and python {_show(c['python'])}")
            continue
        counted[key] = counted.get(key, 0) + 1
        for name in ("started", "repo", "sha"):
            if c[name] != run.cells[name]:
                yield Problem(FAILURES, row.line, f"{name} {_show(c[name])} differs from {RUNS} line {run.line} ({_show(run.cells[name])})")
    for key, run in runs.items():
        failed = run.cells["failed"]
        if _COUNT.fullmatch(failed) and min(int(failed), MAX_FAILURE_ROWS) != counted.get(key, 0):
            yield Problem(RUNS, run.line, f"failed is {failed} but {FAILURES} has {counted.get(key, 0)} rows for this run "
                          f"(it should have {min(int(failed), MAX_FAILURE_ROWS)})")


def check_weekly(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, WEEKLY, WEEKLY_RULES)
    seen: dict[tuple[str, str, str], int] = {}
    previous: tuple[str, str, str] | None = None
    for row in books.tables[WEEKLY].rows:
        c, n = row.cells, row.line
        key = (c["week"], c["repo"], c["test_id"])
        if key in seen:
            yield Problem(WEEKLY, n, f"duplicate of line {seen[key]} (same week, repo and test_id)")
        else:
            seen[key] = n
        if previous is not None and key < previous:
            yield Problem(WEEKLY, n, "not sorted by week, repo, test_id")
        previous = key


def check_watched(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, WATCHED, WATCHED_RULES)
    repos: dict[str, int] = {}
    pairs: dict[tuple[str, str], int] = {}
    for row in books.tables[WATCHED].rows:
        c, n = row.cells, row.line
        if c["repo"] in repos:
            yield Problem(WATCHED, n, f"duplicate of line {repos[c['repo']]} (same repo)")
        else:
            repos[c["repo"]] = n
        pair = (c["github"].lower(), c["workflow"])  # GitHub names are not case sensitive
        if pair in pairs:
            yield Problem(WATCHED, n, f"duplicate of line {pairs[pair]} (same github and workflow)")
        else:
            pairs[pair] = n


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
    ("watched", check_watched),
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
    return f"{year:04d}-W{week:02d}"


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
# ingest: fetched runs in, books out
# ---------------------------------------------------------------------------
#
# Who a run is comes from GitHub's API, written by `fetch` into manifest.json. What a recorder
# file says about itself (repo, sha, event, workflow, started) is ignored: CI runs pull-request
# code, so anyone who can get a workflow to run can write any file. A file is believed only for
# what it measured: python, wall_ms, exit_code, complete, the test rows and, inside `evidence`,
# the attempt number (and only when it names this run).

MAX_ARTIFACT_BYTES = 8 << 20  # one artifact file
MAX_MANIFEST_BYTES = 64 << 10
MAX_TEST_ROWS = 20_000  # test lines in one file
MAX_FILES = 2000  # artifact files read by one ingest
MAX_INGEST_BYTES = 32 << 20  # artifact bytes read by one ingest
MAX_RUN_FILES = 100  # artifact files in one run folder
MAX_RUN_BYTES = 32 << 20  # artifact bytes in one run folder (what fetch lets a run unpack to)
MAX_RECORDS_PER_RUN = 8  # distinct (attempt, python) records in one run folder
MAX_FAILURE_ROWS = 200  # failures.csv rows for one run record, the first by test id
START_SLACK = timedelta(minutes=5)  # a run's `started` may be this much after its `updated`
MAX_NUMBER = 1 << 53  # what any JSON consumer still holds exactly
HEADER_KINDS = {"v": int, "repo": str, "sha": str, "event": str, "workflow": str, "python": str, "os": str,
                "started": str, "wall_ms": int, "exit_code": int, "complete": bool, "tests": int,
                "failed": int, "skipped": int, "evidence": str}
ROW_KINDS = {"id": str, "outcome": str, "ms": int}
MANIFEST_KINDS = {"v": int, "repo": str, "github": str, "run_id": int, "run_attempt": int, "workflow": str,
                  "event": str, "head_sha": str, "head_branch": str, "default_branch": str, "started": str,
                  "updated": str, "conclusion": str, "fork": bool}
MANIFEST = "manifest.json"
ARTIFACTS = "artifacts"


class Rejected(Exception):
    """A file that cannot be booked, and why."""


def _show(value: object, limit: int = 60) -> str:
    """Untrusted text, made safe to print: ASCII only, no control characters, cut short."""
    text = ascii(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def printable(text: str) -> str:
    """Text for the terminal with each character that is not printable written as an escape (\\n, \\x1b)."""
    return "".join(ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii") for ch in text)


class Manifest(NamedTuple):
    """What the API reported about one run, as `fetch` wrote it."""
    v: int
    repo: str
    github: str
    run_id: int
    run_attempt: int
    workflow: str
    event: str
    head_sha: str
    head_branch: str
    default_branch: str
    started: str
    updated: str
    conclusion: str
    fork: bool

    def evidence(self, attempt: int) -> str:
        return f"https://github.com/{self.github}/actions/runs/{self.run_id}/attempts/{attempt}"


@dataclass(frozen=True)
class RecordedRun:
    """One artifact file, believed for what it measured, under the identity of its manifest."""
    manifest: Manifest
    attempt: int
    python: str
    wall_ms: int
    exit_code: int
    complete: bool
    tests: tuple[tuple[str, str, int], ...]  # (id, outcome, ms) per line
    digest: str  # of what is believed, so two files are the same run's same data or they are not

    @property
    def evidence(self) -> str:
        return self.manifest.evidence(self.attempt)

    @property
    def key(self) -> tuple[str, str]:
        return self.evidence, self.python

    def verdict(self) -> int:
        """The recorder's own verdict for the run, recomputed: a run cut short never books as green."""
        rows = [{"outcome": outcome} for _, outcome, _ in self.tests]
        return exit_code(self.exit_code, rows, self.complete)

    def failing(self) -> dict[str, str]:
        """test id -> fail or error. A test with both an error line and a fail line is an error:
        the worst outcome wins, whatever order the lines come in."""
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

    def run_cells(self) -> dict[str, str]:
        """The runs.csv row this file would add."""
        m = self.manifest
        skipped = sum(outcome == "skip" for _, outcome, _ in self.tests)
        return _cells(RUNS_SCHEMA, started=m.started, repo=m.repo, sha=m.head_sha, event=m.event, workflow=m.workflow,
                      python=self.python, tests=len(self.tests), failed=len(self.failing()), skipped=skipped,
                      wall_ms=self.wall_ms, exit_code=self.verdict(), evidence=self.evidence)

    def failure_cells(self) -> Iterator[dict[str, str]]:
        """The failures.csv rows, one per failing test, sorted by test id: the first MAX_FAILURE_ROWS of them."""
        m, failing = self.manifest, self.failing()
        for test_id in sorted(failing)[:MAX_FAILURE_ROWS]:
            yield _cells(FAILURES_SCHEMA, started=m.started, repo=m.repo, sha=m.head_sha, python=self.python,
                         test_id=test_id, outcome=failing[test_id], evidence=self.evidence)

    def weekly_cells(self) -> Iterator[dict[str, str]]:
        """What this file adds to tests-weekly.csv, as one row per test (runs 1, its failure, its time)."""
        week = week_of(self.manifest.started)
        for test_id, (failed, ms) in self.per_test().items():
            yield _cells(WEEKLY_SCHEMA, week=week, repo=self.manifest.repo, test_id=test_id, runs=1, failed=int(failed),
                         total_ms=ms, max_ms=ms)


def _cells(schema: tuple[str, ...], **values: object) -> dict[str, str]:
    return {name: str(values[name]) for name in schema}


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


def _load_json(line: bytes, where: str) -> object:
    def twice(pairs):
        found: dict = {}
        for key, value in pairs:
            if key in found:
                raise Rejected(f"{where}: duplicate key {_show(key)}")
            found[key] = value
        return found

    def constant(name):
        raise Rejected(f"{where}: {name} is not valid JSON")

    try:
        return json.loads(line.decode("utf-8"), object_pairs_hook=twice, parse_constant=constant)
    except Rejected:
        raise
    except UnicodeDecodeError:
        raise Rejected(f"{where}: not UTF-8 text") from None
    except (ValueError, RecursionError):
        raise Rejected(f"{where}: not valid JSON") from None


def _read_file(path: str, cap: int) -> bytes:
    """A regular file's bytes, refusing a link, a pipe or anything over `cap` before reading it."""
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise Rejected("is a symbolic link")
        if not stat.S_ISREG(info.st_mode):
            raise Rejected("is not a regular file")
        if info.st_size > cap:
            raise Rejected(f"file is larger than {_size(cap)}")
        with open(path, "rb") as f:
            return f.read(cap + 1)
    except OSError as e:
        raise Rejected(f"cannot read file ({e.strerror or type(e).__name__})") from None


def _size(cap: int) -> str:
    return f"{cap >> 20} MB" if cap >= 1 << 20 else f"{cap >> 10} KB"


def _problems(messages: Iterable[str], limit: int = 3) -> list[str]:
    found: list[str] = []
    for message in messages:
        if message not in found:
            found.append(message)
            if len(found) > limit:
                break
    return found


def _fail_if(messages: Iterable[str], prefix: str = "") -> None:
    found = _problems(messages)
    if found:
        raise Rejected(prefix + "; ".join(found[:3]) + (" ..." if len(found) > 3 else ""))


def read_manifest(path: str, folder_repo: str, folder_run: str, watched: dict[str, tuple[str, str]]) -> Manifest:
    """A run's manifest, checked. It is trusted for who the run is, so it must agree with where it
    was found, with the watch list, and with the rules every booked row is held to."""
    obj = _check_fields(_load_json(_read_file(path, MAX_MANIFEST_BYTES), "manifest"), MANIFEST_KINDS, "manifest")
    if obj["v"] != RECORD_VERSION:
        raise Rejected(f"manifest v must be {RECORD_VERSION}, got {_show(obj['v'])}")
    m = Manifest(**obj)
    for name in ("run_id", "run_attempt"):
        if getattr(m, name) < 1:
            raise Rejected(f"{name} must be at least 1, got {getattr(m, name)}")
    for name in ("head_branch", "default_branch"):
        value = getattr(m, name)
        if not value or len(value) > 255 or _CONTROL.search(value):
            raise Rejected(f"{name} must be 1 to 255 characters without control characters, got {_show(value)}")
    if not _GITHUB.fullmatch(m.github):
        raise Rejected(f"github must look like OWNER/NAME, got {_show(m.github)}")
    placeholder = _cells(RUNS_SCHEMA, started=m.started, repo=m.repo, sha=m.head_sha, event=m.event, workflow=m.workflow,
                         python="3.12", tests=0, failed=0, skipped=0, wall_ms=0, exit_code=0, evidence=m.evidence(m.run_attempt))
    _fail_if(rule_messages(RUN_RULES, placeholder))
    if not _is_stamp(m.updated):
        raise Rejected(f"updated must look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
                       f"got {_show(m.updated)}")
    if m.repo != folder_repo:
        raise Rejected(f"repo {printable(m.repo)} is not in folder {printable(folder_repo)}")
    if str(m.run_id) != folder_run:
        raise Rejected(f"run_id {m.run_id} is not in folder {printable(folder_run)}")
    if m.repo not in watched:
        raise Rejected(f"repo {m.repo} is not on the watch list")
    github, workflow = watched[m.repo]
    if m.github.lower() != github.lower():
        raise Rejected(f"github {printable(m.github)} is not {printable(github)}, the watch list's")
    if m.workflow != workflow:
        raise Rejected(f"workflow {printable(m.workflow)} is not {printable(workflow)}, the watch list's")
    if m.fork:
        raise Rejected("run is from a fork: its code is not the repo's")
    if m.event == "push" and m.head_branch != m.default_branch:
        raise Rejected(f"push to {printable(m.head_branch)}, not the default branch {printable(m.default_branch)}")
    started = datetime.strptime(m.started, "%Y-%m-%dT%H:%M:%SZ")
    if started > datetime.strptime(m.updated, "%Y-%m-%dT%H:%M:%SZ") + START_SLACK:
        raise Rejected(f"started {m.started} is after updated {m.updated}")
    return m


def _attempt_of(evidence: str, m: Manifest) -> int:
    """The attempt a file's evidence names, when it names this run in canonical form and the attempt exists."""
    found = _EVIDENCE.fullmatch(evidence)
    if found and found[1].lower() == m.github.lower() and found[2] == str(m.run_id) and 1 <= int(found[3]) <= m.run_attempt:
        return int(found[3])
    raise Rejected(f"header evidence must be {m.evidence('N')} with N from 1 to {m.run_attempt}, got {_show(evidence)}")


_EVIDENCE = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/actions/runs/([1-9][0-9]*)/attempts/([1-9][0-9]*)")


def parse_artifact(data: bytes, m: Manifest) -> RecordedRun:
    """A recorder file, strictly, under the identity of its manifest. Nothing in it is executed,
    imported or evaluated, and a test id is only ever a string.

    The header's repo, sha, event, workflow and started are not read for booking. The rows the
    books would get from this file are then built and held to every row rule `check` has, so a
    file that would make `check` fail is rejected here, by name, and never reaches the plan."""
    if len(data) > MAX_ARTIFACT_BYTES:
        raise Rejected(f"file is larger than {_size(MAX_ARTIFACT_BYTES)}")
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if not lines:
        raise Rejected("file is empty")
    if len(lines) - 1 > MAX_TEST_ROWS:
        raise Rejected(f"file has more than {MAX_TEST_ROWS} test rows")
    header = _check_fields(_load_json(lines[0], "line 1"), HEADER_KINDS, "header")
    if header["v"] != RECORD_VERSION:
        raise Rejected(f"header v must be {RECORD_VERSION}, got {_show(header['v'])}")
    tests = []
    for number, line in enumerate(lines[1:], start=2):
        row = _check_fields(_load_json(line, f"line {number}"), ROW_KINDS, f"line {number}")
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
    attempt = _attempt_of(header["evidence"], m)
    believed = [attempt, header["python"], header["wall_ms"], header["exit_code"], header["complete"], tests]
    run = RecordedRun(m, attempt, header["python"], header["wall_ms"], header["exit_code"], header["complete"],
                      tuple(tests), hashlib.sha256(json.dumps(believed).encode("utf-8")).hexdigest())
    gate(run)
    return run


def gate(run: RecordedRun) -> None:
    """Hold every row this file would add to every row rule `check` has: the same functions, so there is
    one definition of a good row."""
    messages: list[str] = []

    def add(rules: dict[str, Rule], cells: dict[str, str]) -> None:
        if len(messages) <= 3:
            messages.extend(m for m in rule_messages(rules, cells) if m not in messages)

    add(RUN_RULES, run.run_cells())
    for cells in run.failure_cells():
        add(FAILURE_RULES, cells)
    for cells in run.weekly_cells():
        add(WEEKLY_RULES, cells)
    for test_id in {t for t, outcome, _ in run.tests if outcome == "skip"}:
        add({"test_id": _test_id_rule, "text": _text_rule("test_id")}, {"test_id": test_id})  # skipped: no row, same id rules
    _fail_if(messages, "would fail check: ")


@dataclass
class Scan:
    path: str  # relative to the fetch directory
    status: str  # booked, already, duplicate, no artifacts, rejected
    run: RecordedRun | None = None
    reason: str = ""


def _layout(root: str) -> tuple[dict[tuple[str, str], tuple[str | None, list[str]]], list[str]]:
    """The run folders under root: (repo, run) -> (manifest path or None, artifact files), and the
    *.jsonl files that are not under <repo>/<run_id>/artifacts/. All paths relative, sorted. Symlinked
    directories are not entered."""
    runs: dict[tuple[str, str], list] = {}  # (repo, run) -> [manifest path or None, artifact files]
    stray = []
    for folder, _, names in os.walk(root):
        for name in names:
            rel = os.path.relpath(os.path.join(folder, name), root)
            parts = rel.split(os.sep)
            if len(parts) == 3 and name == MANIFEST:
                runs.setdefault((parts[0], parts[1]), [None, []])[0] = rel
            elif name.endswith(".jsonl"):
                if len(parts) >= 4 and parts[2] == ARTIFACTS:
                    runs.setdefault((parts[0], parts[1]), [None, []])[1].append(rel)
                else:
                    stray.append(rel)
    for _, files in runs.values():
        files.sort()
    return {key: (value[0], value[1]) for key, value in sorted(runs.items())}, sorted(stray)


@dataclass
class Scanned:
    scans: list[Scan]
    unread: list[tuple[str, str]]  # (run folder, cap) left unread because a per-ingest budget was spent


def _folder_bytes(root: str, artifacts: list[str]) -> int:
    total = 0
    for rel in artifacts:
        try:
            total += os.lstat(os.path.join(root, rel)).st_size
        except OSError:
            pass
    return total


def _peek_key(path: str, m: Manifest) -> tuple[str, str] | None:
    """The (evidence, python) a file's first line claims for this run, or None when it does not plainly
    claim one. Only the first line is read, and only to tell a file that is booked already from one
    that is not, before the budgets are spent on it."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        with open(path, "rb") as f:
            header = json.loads(f.readline(1 << 16))
        evidence, python = header["evidence"], header["python"]
        if type(evidence) is str and type(python) is str:
            return m.evidence(_attempt_of(evidence, m)), python
    except (OSError, ValueError, KeyError, TypeError, Rejected, RecursionError):
        pass
    return None


def scan_fetched(root: str, watched: dict[str, tuple[str, str]], booked: set[tuple[str, str]] | None = None) -> Scanned:
    """Read the run folders in order of the manifest's `started`, then run id, each under its own caps
    (MAX_RUN_FILES, MAX_RUN_BYTES, MAX_RECORDS_PER_RUN). A folder is read whole or not at all: one that
    the per-ingest budgets (MAX_FILES, MAX_INGEST_BYTES) cannot hold is named in `unread` and a later
    ingest reads it. A folder whose files all claim a record that is booked already is not read and costs no budget."""
    runs, stray = _layout(root)
    found = Scanned([Scan(rel, "rejected", reason="not inside <repo>/<run_id>/artifacts/ of a run folder") for rel in stray], [])
    booked = booked or set()
    manifests: list[tuple[tuple, str, str, str | None, list[str], Manifest | None, str]] = []
    for (repo, run_id), (manifest_path, artifacts) in runs.items():
        m, why = None, ""
        if manifest_path is not None:
            try:
                m = read_manifest(os.path.join(root, manifest_path), repo, run_id, watched)
            except Rejected as e:
                why = str(e)
        order = (m.started if m else "", m.run_id if m else (int(run_id) if run_id.isdigit() else 0), repo, run_id)
        manifests.append((order, repo, run_id, manifest_path, artifacts, m, why))
    manifests.sort(key=lambda x: x[0])
    files_read = bytes_read = 0
    for _, repo, run_id, manifest_path, artifacts, m, why in manifests:
        folder = f"{repo}/{run_id}"
        if manifest_path is not None and m is None:
            note = f" ({len(artifacts)} artifact file{'s' * (len(artifacts) != 1)} not read)" if artifacts else ""
            found.scans.append(Scan(manifest_path, "rejected", reason=why + note))
            continue
        if m is not None and not artifacts:
            found.scans.append(Scan(manifest_path, "no artifacts"))
            continue
        size = _folder_bytes(root, artifacts)
        if m is None:  # no manifest: each file is rejected unread, and the files are counted against the budget
            if files_read + len(artifacts) > MAX_FILES:
                found.unread.append((folder, f"{MAX_FILES}-file cap"))
                continue
            files_read += len(artifacts)
            found.scans.extend(Scan(rel, "rejected", reason=f"no {MANIFEST} in its run folder") for rel in artifacts)
            continue
        if len(artifacts) > MAX_RUN_FILES or size > MAX_RUN_BYTES:
            found.scans.append(Scan(manifest_path, "rejected", reason=(
                f"run {folder} has {len(artifacts)} artifact files and {size} bytes, over the per-run caps of {MAX_RUN_FILES} files "
                f"and {_size(MAX_RUN_BYTES)}; none of it is read or booked")))
            continue
        if all(_peek_key(os.path.join(root, rel), m) in booked for rel in artifacts):
            found.scans.extend(Scan(rel, "already", reason="already booked") for rel in artifacts)
            continue
        if files_read + len(artifacts) > MAX_FILES:
            found.unread.append((folder, f"{MAX_FILES}-file cap"))
            continue
        if bytes_read + size > MAX_INGEST_BYTES:
            found.unread.append((folder, f"{_size(MAX_INGEST_BYTES)} cap"))
            continue
        files_read += len(artifacts)
        bytes_read += size
        mine = []
        for rel in artifacts:
            try:
                mine.append(Scan(rel, "booked", parse_artifact(_read_file(os.path.join(root, rel), MAX_ARTIFACT_BYTES), m)))
            except Rejected as e:
                mine.append(Scan(rel, "rejected", reason=str(e)))
        records = {s.run.key for s in mine if s.status == "booked"}
        if len(records) > MAX_RECORDS_PER_RUN:
            for scan in mine:
                if scan.status == "booked":
                    scan.status, scan.run = "rejected", None
                    scan.reason = (f"run {folder} has {len(records)} records (distinct attempt and python), more than "
                                   f"{MAX_RECORDS_PER_RUN}; none of it is booked")
        found.scans.extend(mine)
    found.scans.sort(key=lambda s: s.path)
    return found


def settle_duplicates(scans: list[Scan]) -> None:
    """Files that claim one (evidence, python) in one batch. Identical content counts once. Content that
    differs is rejected on every file: a forged file next to a genuine one must never decide which is
    believed, so neither is."""
    groups: dict[tuple[str, str], list[Scan]] = {}
    for scan in scans:
        if scan.status == "booked":
            groups.setdefault(scan.run.key, []).append(scan)
    for group in groups.values():
        if len(group) < 2:
            continue
        digests = {s.path: s.run.digest for s in group}
        if len(set(digests.values())) > 1:
            for scan in group:
                other = next(path for path, digest in digests.items() if digest != digests[scan.path])
                scan.status, scan.run = "rejected", None
                scan.reason = (f"conflicts with {printable(other)}: the same attempt and python with different content, "
                               "so neither is booked")
        else:
            for scan in group[1:]:
                scan.status, scan.reason = "duplicate", f"duplicate of {printable(group[0].path)}"


def choose_new_runs(scans: list[Scan], booked: set[tuple[str, str]]) -> list[Scan]:
    """Mark the scans that book a run nobody has booked yet (status stays `booked`), the rest `already`."""
    taken = set(booked)
    candidates = sorted((s for s in scans if s.status == "booked"),
                        key=lambda s: (s.run.manifest.started, s.run.key, s.path))
    for scan in candidates:
        if scan.run.key in taken:
            scan.status, scan.reason = "already", "already booked"
        else:
            taken.add(scan.run.key)
    return [s for s in candidates if s.status == "booked"]


@dataclass
class Plan:
    """What an ingest adds to the books, as the files' new bytes (None: unchanged)."""
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
        runs_text += _csv_line(scan.run.run_cells()[k] for k in RUNS_SCHEMA)
        for cells in scan.run.failure_cells():
            failures_text += _csv_line(cells[k] for k in FAILURES_SCHEMA)
            failures += 1
        for cells in scan.run.weekly_cells():
            key = (cells["week"], cells["repo"], cells["test_id"])
            cell = weekly.setdefault(key, [0, 0, 0, 0])
            cell[0] += 1
            cell[1] += int(cells["failed"])
            cell[2] += int(cells["total_ms"])
            cell[3] = max(cell[3], int(cells["max_ms"]))
            touched.add(key)
    weekly_text = _csv_line(WEEKLY_SCHEMA) + "".join(_csv_line(k + tuple(v)) for k, v in sorted(weekly.items()))

    def appended(rel: str, text: str) -> bytes:
        data = old[rel]
        return data + (b"" if data.endswith(b"\n") or not data else b"\n") + text.encode("utf-8")

    files: dict[str, bytes | None] = {rel: None for rel in SCHEMAS}
    files.update({RUNS: appended(RUNS, runs_text), FAILURES: appended(FAILURES, failures_text),
                  WEEKLY: weekly_text.encode("utf-8")})
    return Plan(files, len(new), failures, len(touched))


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


def watch_list(books: Books) -> dict[str, tuple[str, str]]:
    """repo -> (github, workflow) from books that passed check."""
    return {r.cells["repo"]: (r.cells["github"], r.cells["workflow"]) for r in books.tables[WATCHED].rows}


def cmd_ingest(args: argparse.Namespace) -> int:
    for folder in (args.books_dir, args.fetch_dir):
        if not os.path.isdir(folder):
            print(f"quality.py: not a directory: {folder}", file=sys.stderr)
            return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; refusing to ingest into books that fail check")
        return 1
    booked = {(r.evidence, r.python) for r in _typed_rows(books, RUNS, RunRow)}
    found = scan_fetched(args.fetch_dir, watch_list(books), booked)
    scans = found.scans
    settle_duplicates(scans)
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
    count = lambda status: sum(s.status == status for s in scans)
    unread = len(found.unread)
    totals = {"files": len(scans), "booked": len(new), "already_booked": count("already"), "duplicates": count("duplicate"),
              "no_artifacts": count("no artifacts"), "rejected": count("rejected"), "unread": unread,
              "failures": plan.failures, "weekly_rows": plan.weekly_rows}
    if args.json:
        print(json.dumps({"dry_run": args.dry_run, "files": [_scan_json(s) for s in scans], "totals": totals,
                          "wrote": wrote}, sort_keys=True, indent=2))
    else:
        _print_ingest(scans, totals, found, args.dry_run)
    return 1 if totals["rejected"] or unread else 0


def _scan_json(scan: Scan) -> dict:
    out = {"path": scan.path, "status": scan.status}
    if scan.reason:
        out["reason"] = scan.reason
    if scan.status == "booked":
        out.update(evidence=scan.run.evidence, python=scan.run.python, tests=len(scan.run.tests),
                   exit_code=scan.run.verdict())
    return out


def _print_ingest(scans: list[Scan], totals: dict, found: Scanned, dry_run: bool) -> None:
    for s in scans:
        name = _show(s.path, 200) if not s.path.isprintable() else s.path
        if s.status == "booked":
            m = s.run.manifest
            print(f"{'would book' if dry_run else 'booked'}: {name}: {m.repo} {s.run.python} {len(s.run.tests)} tests, "
                  f"exit_code {s.run.verdict()}, {s.run.evidence}")
        elif s.status == "already":
            print(f"skipped, already booked: {name}")
        elif s.status == "duplicate":
            print(f"skipped, {s.reason}: {name}")
        elif s.status == "no artifacts":
            print(f"no artifacts: {name}")
        else:
            print(f"rejected: {name}: {s.reason}")
    for folder, cap in found.unread:
        print(f"left unread, the {cap}: {printable(folder)}")
    if found.unread:
        print(f"{len(found.unread)} run folder{'s' * (len(found.unread) != 1)} left unread: ingest again to book "
              f"{'it' if len(found.unread) == 1 else 'them'}")
    print(f"{'would book' if dry_run else 'booked'} {totals['booked']} runs, {totals['failures']} failures, "
          f"{totals['weekly_rows']} weekly rows touched; skipped {totals['already_booked']} already booked, "
          f"{totals['duplicates']} duplicates; rejected {totals['rejected']} of {totals['files']} files")
    if totals["rejected"] or totals["unread"]:
        print("some files were rejected or not read: the others were booked and ingest exits 1 so it is not missed"
              if not dry_run else "some files were rejected or not read; ingest exits 1")


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
    """Tests that failed in one run and not in another of the same commit, Python and event.

    A test is listed when it has a failure row this week. Its failing side is every failure row
    of that repo, sha, Python, event and test (any week); its passing side is every run in the books (any
    week) of the same repo, sha, Python and event that has no failure row for the test. The books keep
    failures only, so a run in which the test was skipped or did not exist looks the same as a
    pass, and a run that is red for some other test counts as passing this one. A commit whose
    every run failed the test is not flaky. Python is part of the key because a test that fails
    only on 3.10 is a compatibility bug, not a flake. The event is part of it because a pull request
    branch can point at a commit that is already on main and report a failure that main never had.
    """
    event_of = {(r.evidence, r.python): r.event for r in repo_runs}
    failed_in: dict[tuple[str, str, str, str], set[str]] = {}
    for f in repo_failures:
        failed_in.setdefault((f.test_id, f.sha, f.python, event_of.get((f.evidence, f.python), "")), set()).add(f.evidence)
    listed = {(f.test_id, f.sha, f.python, event_of.get((f.evidence, f.python), ""))
              for f in repo_failures if week_of(f.started) == week}
    out = []
    for key in sorted(listed):
        test_id, sha, python, event = key
        passed = {r.evidence for r in repo_runs if r.sha == sha and r.python == python and r.event == event} - failed_in[key]
        if passed:
            out.append({"event": event, "failed_evidence": sorted(failed_in[key]), "passed_evidence": sorted(passed),
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
    on_pr = [f for f in sorted(fails, key=lambda f: (f.test_id, f.evidence, f.python))
             if event_of.get((f.evidence, f.python)) == "pull_request"]
    return {
        "caught_on_pr": {"count": len({f.test_id for f in on_pr}),
                         "failures": [{"evidence": f.evidence, "outcome": f.outcome, "python": f.python, "sha": f.sha,
                                       "test_id": f.test_id} for f in on_pr]},
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
        lines.append(f"  failed on a push: {len(r['failed_on_main'])}; caught on a pull request: "
                     f"{r['caught_on_pr']['count']} tests; flaky: {len(r['flaky'])}; "
                     f"tests added {len(r['tests_added'])}, removed {len(r['tests_removed'])}; CI time {r['ci_wall_ms']} ms")
        for t in r["slowest_tests"][:3]:
            lines.append(f"  slow: {printable(t['test_id'])} mean {t['mean_ms']} ms over {t['runs']} runs")
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


# ---------------------------------------------------------------------------
# fetch: GitHub's own account of each run, and its test-results artifacts, onto disk
# ---------------------------------------------------------------------------
#
# `fetch` is the only command that talks to GitHub, through the `gh` CLI (`gh api`). It writes
# under OUT_DIR only, never under BOOKS_DIR. What it writes is what `ingest` reads:
#   OUT_DIR/<repo>/<run_id>/manifest.json             the API's account of the run (see Manifest)
#   OUT_DIR/<repo>/<run_id>/artifacts/<name>/*.jsonl  the run's test-results-* artifacts, unzipped
# The artifacts are downloaded as they are and believed only by `ingest`, and only for what they measured.

ARTIFACT_PREFIX = "test-results-"
_ARTIFACT_NAME = re.compile(r"test-results-[A-Za-z0-9._-]{1,100}")
MAX_ARTIFACTS_PER_RUN = 12
MAX_ZIP_BYTES = 32 << 20  # one downloaded archive
MAX_ZIP_MEMBERS = 100
MAX_UNPACKED_BYTES = 16 << 20  # what one archive unpacks to
MAX_RUN_UNPACKED_BYTES = 32 << 20  # what all the archives of one run unpack to
SINCE_OVERLAP_DAYS = 3  # the default --since lists this many days before the latest booked start again
GH_TIMEOUT_SECONDS = 300
LOOKBACK_DAYS = 7  # how far back a repo with nothing booked yet is listed


class GhError(Exception):
    """A `gh api` call that failed, and why."""


class Gh:
    def __init__(self, exe: str):
        self.exe = exe

    def api(self, endpoint: str, paginate: bool = False) -> bytes:
        argv = [self.exe, "api", *(["--paginate"] if paginate else []), endpoint]
        try:
            done = subprocess.run(argv, capture_output=True, timeout=GH_TIMEOUT_SECONDS,
                                  env={**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"})
        except (OSError, subprocess.SubprocessError) as e:
            raise GhError(f"gh could not run: {type(e).__name__}") from None
        if done.returncode != 0:
            raise GhError(f"gh api {endpoint.split('?')[0]} failed: "
                          + (printable(done.stderr.decode('utf-8', 'replace').strip()) or f"exit {done.returncode}"))
        return done.stdout

    def pages(self, endpoint: str) -> list[dict]:
        """A paginated listing: `gh api --paginate` prints one JSON object per page, one after another."""
        raw = self.api(endpoint, paginate=True).decode("utf-8", "replace")
        decoder, at, found = json.JSONDecoder(), 0, []
        try:
            while True:
                while at < len(raw) and raw[at].isspace():
                    at += 1
                if at >= len(raw):
                    break
                page, at = decoder.raw_decode(raw, at)
                if not isinstance(page, dict):
                    raise ValueError("a page is not an object")
                found.append(page)
        except (ValueError, RecursionError):
            raise GhError(f"gh api {endpoint.split('?')[0]} did not answer with JSON") from None
        return found


def find_gh() -> str | None:
    """QUALITY_GH when set (tests point it at a fake), else `gh` on PATH."""
    return shutil.which(os.environ.get("QUALITY_GH") or "gh")


def _day(text: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _inside(folder: str, parent: str) -> bool:
    folder, parent = os.path.realpath(folder), os.path.realpath(parent)
    return folder == parent or folder.startswith(parent.rstrip(os.sep) + os.sep)


def _safe_member(name: str) -> bool:
    parts = name.split("/")
    return (0 < len(name) <= 200 and "\\" not in name and not _CONTROL.search(name)
            and all(p not in ("", ".", "..") for p in parts))


class OverCap(Rejected):
    """An archive or a run that unpacks to more than its cap: the whole run is failed."""


def extract_archive(raw: bytes, dest: str, run_left: list[int] | None = None) -> int:
    """Unzip the *.jsonl members of an artifact into `dest`, replacing it. An archive with a member whose
    name climbs out, is absolute, or is a link, or one that is too big, is refused whole. Bytes are counted
    as they are written, never taken from the header, and writing stops the moment a cap is passed: one
    member (8 MB), the archive (16 MB), and `run_left[0]`, the bytes the run may still unpack (spent here).
    Returns the files written."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise Rejected("is not a zip archive") from None
    if run_left is None:
        run_left = [MAX_RUN_UNPACKED_BYTES]
    with archive:
        members = [i for i in archive.infolist() if not i.filename.endswith("/")]
        if len(members) > MAX_ZIP_MEMBERS:
            raise Rejected(f"has more than {MAX_ZIP_MEMBERS} files")
        for info in members:
            if not _safe_member(info.filename) or stat.S_ISLNK(info.external_attr >> 16):
                raise Rejected(f"has an unsafe member name {_show(info.filename, 80)}")
            if info.file_size > MAX_ARTIFACT_BYTES:
                raise Rejected(f"has a file larger than {_size(MAX_ARTIFACT_BYTES)}")
        partial = dest + ".partial"
        shutil.rmtree(partial, ignore_errors=True)
        written = total = 0
        try:
            for info in members:
                if not info.filename.endswith(".jsonl"):
                    continue
                path = os.path.join(partial, *info.filename.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                size = 0
                with archive.open(info) as member, open(path, "xb") as f:
                    while chunk := member.read(1 << 16):
                        size += len(chunk)
                        total += len(chunk)
                        run_left[0] -= len(chunk)
                        if size > MAX_ARTIFACT_BYTES:
                            raise Rejected(f"has a file larger than {_size(MAX_ARTIFACT_BYTES)}")
                        if total > MAX_UNPACKED_BYTES:
                            raise OverCap(f"unpacks to more than {_size(MAX_UNPACKED_BYTES)}")
                        if run_left[0] < 0:
                            raise OverCap(f"unpacks, with the run's other artifacts, to more than {_size(MAX_RUN_UNPACKED_BYTES)}")
                        f.write(chunk)
                written += 1
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if written:
                os.replace(partial, dest)
            else:
                os.makedirs(dest)
        finally:
            shutil.rmtree(partial, ignore_errors=True)
    return written


@dataclass
class FetchTally:
    runs: int = 0  # fetched
    artifacts: int = 0
    listed: int = 0
    forks: int = 0
    pushes: int = 0
    booked: int = 0
    empty: int = 0
    failed: int = 0

    def fail(self, where: str, why: str) -> None:
        self.failed += 1
        print(f"  FAILED {where}: {why}")


def _latest_started(books: Books, repo: str) -> str | None:
    """The day SINCE_OVERLAP_DAYS before the repo's latest booked start: a run still going or whose download
    failed when a newer run was booked is listed again, and a run already booked is skipped."""
    stamps = [r.cells["started"] for r in books.tables[RUNS].rows if r.cells["repo"] == repo]
    return (date.fromisoformat(max(stamps)[:10]) - timedelta(days=SINCE_OVERLAP_DAYS)).isoformat() if stamps else None


def _booked_per_run(books: Books) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in books.tables[RUNS].rows:
        counts[r.cells["evidence"]] = counts.get(r.cells["evidence"], 0) + 1
    return counts


def _write_json(path: str, value: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{os.getpid()}.tmp"
    with open(temp, "w") as f:
        f.write(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temp, path)


def _manifest_of(run: dict, repo: str, github: str, workflow: str, default_branch: str) -> Manifest:
    """The manifest for one API run object. Raises Rejected when the API left out what the manifest holds."""
    def field(key: str, kind: type) -> object:
        value = run.get(key)
        if type(value) is not kind:
            raise Rejected(f"run has no usable {key}")
        return value

    head = run.get("head_repository")
    fork = not isinstance(head, dict) or str(head.get("full_name") or "").lower() != github.lower()
    return Manifest(RECORD_VERSION, repo, github, field("id", int), field("run_attempt", int), workflow, field("event", str),
                    field("head_sha", str), str(run.get("head_branch") or ""), default_branch,
                    field("run_started_at", str), field("updated_at", str), str(run.get("conclusion") or ""), fork)


def fetch_repo(gh: Gh, out_dir: str, repo: str, github: str, workflow: str, since: str,
               tally: FetchTally, booked: dict[str, int]) -> None:
    print(f"{repo} ({github}, {workflow}): runs created since {since}")
    try:
        listing = gh.pages(f"repos/{github}/actions/runs?status=completed&per_page=100&created=%3E%3D{since}")
    except GhError as e:
        tally.fail("listing", str(e))
        return
    runs = sorted((r for page in listing for r in page.get("workflow_runs", []) if isinstance(r, dict)
                   and r.get("name") == workflow and type(r.get("id")) is int), key=lambda r: r["id"])
    tally.listed += len(runs)
    if not runs:
        return
    try:
        info = json.loads(gh.api(f"repos/{github}"))
        default_branch = info.get("default_branch") if isinstance(info, dict) else None
    except (GhError, ValueError) as e:
        tally.fail("default branch", str(e) if isinstance(e, GhError) else f"gh api repos/{github} did not answer with JSON")
        return
    if not isinstance(default_branch, str) or not default_branch:
        tally.fail("default branch", f"gh api repos/{github} did not name one")
        return
    for run in runs:
        fetch_run(gh, out_dir, repo, github, workflow, default_branch, run, tally, booked)


def fetch_run(gh: Gh, out_dir: str, repo: str, github: str, workflow: str, default_branch: str, run: dict,
              tally: FetchTally, booked: dict[str, int]) -> None:
    run_id = run["id"]
    if run.get("status") != "completed":
        print(f"  skipped {run_id}: not completed ({printable(str(run.get('status')))}); it is listed again next time")
        return
    head = run.get("head_repository")
    if not isinstance(head, dict) or str(head.get("full_name") or "").lower() != github.lower():
        tally.forks += 1
        print(f"  skipped {run_id}: fork ({printable(str((head or {}).get('full_name')))}), its code is not the repo's; not downloaded")
        return
    branch = str(run.get("head_branch") or "")
    if run.get("event") == "push" and branch != default_branch:
        tally.pushes += 1
        print(f"  skipped {run_id}: push to {printable(branch)}, not the default branch {printable(default_branch)}")
        return
    try:
        manifest = _manifest_of(run, repo, github, workflow, default_branch)
        artifacts = [a for page in gh.pages(f"repos/{github}/actions/runs/{run_id}/artifacts?per_page=100")
                     for a in page.get("artifacts", []) if isinstance(a, dict)]
    except (Rejected, GhError) as e:
        tally.fail(str(run_id), str(e))
        return
    wanted = [a for a in artifacts if str(a.get("name", "")).startswith(ARTIFACT_PREFIX)]
    if not wanted:
        tally.empty += 1  # counted in the totals line; most runs (a docs-only change) have none
        return
    if len(wanted) > MAX_ARTIFACTS_PER_RUN:
        tally.fail(str(run_id), f"has {len(wanted)} test-results artifacts, more than the {MAX_ARTIFACTS_PER_RUN} a run may have; nothing fetched")
        return
    fresh = []
    for a in wanted:
        name = str(a.get("name"))
        if a.get("expired") is True:
            tally.fail(str(run_id), f"artifact {printable(name)} expired")
        elif not _ARTIFACT_NAME.fullmatch(name) or type(a.get("id")) is not int:
            tally.fail(str(run_id), f"artifact {_show(name, 80)} is not a plain name or has no id")
        else:
            fresh.append(a)
    if not fresh:
        return
    if booked.get(manifest.evidence(manifest.run_attempt), 0) >= len(fresh):
        tally.booked += 1
        print(f"  skipped {run_id}: already booked")
        return
    folder = os.path.join(out_dir, repo, str(run_id))
    _write_json(os.path.join(folder, MANIFEST), manifest._asdict())
    got, run_left = 0, [MAX_RUN_UNPACKED_BYTES]
    for a in fresh:
        name = a["name"]
        try:
            if type(a.get("size_in_bytes")) is int and a["size_in_bytes"] > MAX_ZIP_BYTES:
                raise Rejected(f"is larger than {_size(MAX_ZIP_BYTES)}")
            raw = gh.api(f"repos/{github}/actions/artifacts/{a['id']}/zip")
            if len(raw) > MAX_ZIP_BYTES:
                raise Rejected(f"is larger than {_size(MAX_ZIP_BYTES)}")
            extract_archive(raw, os.path.join(folder, ARTIFACTS, name), run_left)
            got += 1
        except OverCap as e:
            shutil.rmtree(folder, ignore_errors=True)
            tally.fail(str(run_id), f"artifact {name} ({a['id']}) {e}; the run is not fetched")
            return
        except (Rejected, GhError, OSError) as e:
            tally.fail(str(run_id), f"artifact {name} ({a['id']}) not fetched: {e if not isinstance(e, OSError) else e.strerror}")
    if got:
        tally.runs += 1
        tally.artifacts += got
        print(f"  fetched {run_id}: {printable(str(run.get('event')))} {printable(branch)} attempt {manifest.run_attempt}, "
              f"{got} artifact{'s' * (got != 1)}")


def cmd_fetch(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    today = _day(args.today) if args.today else datetime.now(timezone.utc).date()
    if today is None or (args.since is not None and _day(args.since) is None):
        print("quality.py: --since and --today must be a date like 2026-11-15", file=sys.stderr)
        return 2
    if _inside(args.out_dir, args.books_dir):
        print(f"quality.py: {args.out_dir} is inside the books folder; fetch never writes there", file=sys.stderr)
        return 2
    exe = find_gh()
    if exe is None:
        print("quality.py: cannot find the gh CLI (put it on PATH, or set QUALITY_GH to its path)", file=sys.stderr)
        return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; refusing to fetch with books that fail check")
        return 1
    watched = [(r.cells["repo"], r.cells["github"], r.cells["workflow"]) for r in books.tables[WATCHED].rows]
    if args.repo is not None:
        watched = [w for w in watched if w[0] == args.repo]
        if not watched:
            print(f"quality.py: {args.repo!r} is not in books/watched.csv", file=sys.stderr)
            return 2
    if not watched:
        print("nothing to fetch: books/watched.csv lists no repos")
        return 0
    os.makedirs(args.out_dir, exist_ok=True)
    gh, tally, booked = Gh(exe), FetchTally(), _booked_per_run(books)
    for repo, github, workflow in watched:
        since = args.since or _latest_started(books, repo) or (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
        fetch_repo(gh, args.out_dir, repo, github, workflow, since, tally, booked)
    t = tally
    print(f"fetched {t.runs} runs ({t.artifacts} artifacts); listed {t.listed}; skipped {t.forks} forks, "
          f"{t.pushes} pushes to a non-default branch, {t.booked} already booked, {t.empty} without test-results artifacts; "
          f"{t.failed} failed")
    return 1 if t.failed else 0


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
    fetch = sub.add_parser("fetch", help="download the test-results artifacts and GitHub's account of each watched run")
    fetch.add_argument("books_dir", metavar="BOOKS_DIR")
    fetch.add_argument("out_dir", metavar="OUT_DIR")
    fetch.add_argument("--since", metavar="YYYY-MM-DD", help="runs created on or after this day (default: 3 days before "
                       "the repo's latest started in runs.csv, else 7 days before today UTC)")
    fetch.add_argument("--repo", metavar="SLUG", help="only this watched repo")
    fetch.add_argument("--today", metavar="YYYY-MM-DD", help="the date to count the 7 days back from (for tests)")
    fetch.set_defaults(func=cmd_fetch)
    ingest = sub.add_parser("ingest", help="book the runs `fetch` downloaded into the quality books")
    ingest.add_argument("books_dir", metavar="BOOKS_DIR")
    ingest.add_argument("fetch_dir", metavar="FETCH_DIR")
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
