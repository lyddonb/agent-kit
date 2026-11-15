"""Tests for the Quality Director's recorder and books checker
(plugins/bstack/skills/qualitydirector/scripts/quality.py).

`record` is tested the way it is used: a throwaway suite in a temp dir, a subprocess, and
assertions on the output file, stdout, stderr and the exit code. `check` is called in process
and judged by what it prints and returns.
"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# QUALITY_SCRIPT points the suite at another copy of the script, to show a test failing on old code.
SCRIPT = Path(os.environ.get("QUALITY_SCRIPT")
              or ROOT / "plugins/bstack/skills/qualitydirector/scripts/quality.py")
FIXTURE = ROOT / "tests/fixtures/quality"

spec = importlib.util.spec_from_file_location("quality", SCRIPT)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)

GITHUB_ENV = {
    "GITHUB_SHA": "0123456789abcdef0123456789abcdef01234567",
    "GITHUB_EVENT_NAME": "pull_request",
    "GITHUB_WORKFLOW": "ci",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "example/demo",
    "GITHUB_RUN_ID": "4242",
    "GITHUB_RUN_ATTEMPT": "2",
}
EVIDENCE = "https://github.com/example/demo/actions/runs/4242/attempts/2"


def kill_group(proc: subprocess.Popen) -> None:
    """Kill everything the process started (its process group): a looping child that outlives the
    recorder would otherwise hold the pipes open and hang communicate() forever."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


def reap(proc: subprocess.Popen, timeout: float, input=None) -> tuple[str, str]:
    """communicate() that fails the test, and kills the whole group, instead of hanging."""
    try:
        return proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        proc.communicate(timeout=10)
        raise AssertionError(f"still running after {timeout}s: {proc.args}") from None
    finally:
        kill_group(proc)


def run_in_group(cmd, *, timeout: float = 60, input=None, **kw) -> subprocess.CompletedProcess:
    """subprocess.run in its own process group, with a timeout that fails the test."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if input is not None else None, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True, **kw)
    out, err = reap(proc, timeout, input)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def src(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def shell_code(returncode: int) -> int:
    """subprocess reports death by signal N as -N; a shell (and the recorder) says 128+N."""
    return returncode if returncode >= 0 else 128 - returncode


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------

class Recorded:
    def __init__(self, proc, out: Path):
        self.proc = proc
        self.exit = proc.returncode
        self.out = out
        self.raw = out.read_text() if out.is_file() else None
        lines = self.raw.splitlines() if self.raw else []
        self.lines = lines
        self.header = json.loads(lines[0]) if lines else None
        self.rows = [json.loads(line) for line in lines[1:]]

    def outcomes(self) -> dict[str, str]:
        return {r["id"]: r["outcome"] for r in self.rows}


class RecordCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name) / "work"
        (self.work / "tests").mkdir(parents=True)

    def write(self, rel: str, text: str):
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src(text))

    def clean_env(self, extra=None) -> dict:
        skip = ("RUNNER_OS", "PYTHONWARNINGS", "PYTHONDEVMODE", "PYTHONSAFEPATH", "PYTHONPATH")
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_") and k not in skip}
        # stop git from finding a repo above the temp dir, so "no repo" really means none
        clean["GIT_CEILING_DIRECTORIES"] = str(self.work.parent)
        clean["PYTHONDONTWRITEBYTECODE"] = "1"
        clean.update(extra or {})
        return clean

    def run_plain(self, *, env=None, py=()) -> subprocess.CompletedProcess:
        """`python PY... -m unittest discover -s tests`; its exit code, as a shell says it, is `plain_code`."""
        return run_in_group([sys.executable, *py, "-m", "unittest", "discover", "-s", "tests"], cwd=self.work,
                            env=self.clean_env(env))

    def run_record(self, *, env=None, args=None, tests="tests", out="out.jsonl", py=()) -> Recorded:
        clean = self.clean_env(env)
        argv = args if args is not None else ["record", tests, "--out", out, "--repo", "demo"]
        proc = run_in_group([sys.executable, *py, str(SCRIPT)] + argv, cwd=self.work, env=clean)
        return Recorded(proc, self.work / out)

    def spawn_recorder(self, **kw) -> subprocess.Popen:
        """A recorder to signal by hand, in its own process group; whatever it leaves is killed at cleanup."""
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "record", "tests", "--out", "out.jsonl", "--repo", "demo"],
                                cwd=self.work, env=self.clean_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True, **kw)
        self.addCleanup(kill_group, proc)
        return proc

    def git_head(self) -> str:
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(self.work)]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
        head = subprocess.run(git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        self.assertRegex(head, r"^[0-9a-f]{40}$")
        return head

    def record_one(self, body: str, module_extra: str = "", **kw) -> Recorded:
        self.write("tests/test_case.py", "import unittest\n" + module_extra + "\nclass T(unittest.TestCase):\n"
                   + textwrap.indent(src(body), "    "))
        return self.run_record(**kw)


class OutcomeTest(RecordCase):
    CASES = {
        "pass": ("def test_x(self):\n    pass\n", "pass", 0),
        "fail": ("def test_x(self):\n    self.fail('no')\n", "fail", 1),
        "error": ("def test_x(self):\n    raise RuntimeError('boom')\n", "error", 1),
        "skip": ("@unittest.skip('later')\ndef test_x(self):\n    pass\n", "skip", 0),
        "expected failure": ("@unittest.expectedFailure\ndef test_x(self):\n    self.fail('known')\n", "pass", 0),
        "unexpected success": ("@unittest.expectedFailure\ndef test_x(self):\n    pass\n", "fail", 1),
        "failing subTest": (
            "def test_x(self):\n"
            "    for i in range(3):\n"
            "        with self.subTest(i=i):\n"
            "            self.assertNotEqual(i, 1)\n", "fail", 1),
        "erroring subTest": (
            "def test_x(self):\n"
            "    with self.subTest(i=1):\n"
            "        raise RuntimeError('boom')\n", "error", 1),
        "passing subTests": (
            "def test_x(self):\n"
            "    for i in range(3):\n"
            "        with self.subTest(i=i):\n"
            "            pass\n", "pass", 0),
        "SystemExit inside a test": ("def test_x(self):\n    raise SystemExit(0)\n", "error", 1),
        "failing subTest then a skip": (
            "def test_x(self):\n"
            "    with self.subTest(i=1):\n"
            "        self.fail('a')\n"
            "    self.skipTest('late')\n", "fail", 1),
        "erroring subTest then failing subTest": (
            "def test_x(self):\n"
            "    with self.subTest(i=1):\n"
            "        raise RuntimeError('a')\n"
            "    with self.subTest(i=2):\n"
            "        self.fail('b')\n", "error", 1),
        "skipped subTest is still one test": (
            "def test_x(self):\n"
            "    with self.subTest(i=1):\n"
            "        self.skipTest('s')\n", "skip", 0),
    }

    def test_each_outcome_and_exit_code(self):
        for name, (body, outcome, code) in self.CASES.items():
            with self.subTest(name):
                shutil.rmtree(self.work / "tests")
                (self.work / "tests").mkdir()
                rec = self.record_one(body)
                self.assertEqual(rec.outcomes(), {"test_case.T.test_x": outcome}, rec.proc.stderr)
                self.assertEqual(rec.exit, code, rec.proc.stderr)

    def test_a_test_with_many_failing_subtests_is_one_line(self):
        rec = self.record_one(
            "def test_x(self):\n"
            "    for i in range(4):\n"
            "        with self.subTest(i=i):\n"
            "            self.fail(i)\n")
        self.assertEqual(len(rec.rows), 1)
        self.assertEqual(rec.header["failed"], 1)

    def test_a_mixed_suite_counts_every_outcome(self):
        rec = self.record_one(
            "def test_a(self):\n    pass\n"
            "def test_b(self):\n    self.fail('x')\n"
            "def test_c(self):\n    raise RuntimeError('x')\n"
            "@unittest.skip('s')\ndef test_d(self):\n    pass\n")
        self.assertEqual(rec.outcomes(), {
            "test_case.T.test_a": "pass", "test_case.T.test_b": "fail",
            "test_case.T.test_c": "error", "test_case.T.test_d": "skip"})
        self.assertEqual((rec.header["tests"], rec.header["failed"], rec.header["skipped"]), (4, 2, 1))
        self.assertEqual(rec.exit, 1)


class NeverDropAFailureTest(RecordCase):
    def assertRows(self, rec: Recorded, expected: dict, exit_code: int = 1):
        self.assertEqual(rec.outcomes(), expected, rec.proc.stderr)
        self.assertEqual(len(rec.rows), len(expected), rec.rows)
        if exit_code:  # a failing run exits as plain unittest does: 1, or 5 on 3.12+ when no test started
            exit_code = shell_code(self.run_plain().returncode)
            self.assertNotEqual(exit_code, 0)
        self.assertEqual(rec.exit, exit_code, rec.proc.stderr)
        self.assertEqual(rec.header["tests"], len(expected))

    def test_module_that_fails_to_import(self):
        self.write("tests/test_good.py", "import unittest\nclass G(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
        self.write("tests/test_broken.py", "import module_that_does_not_exist\n")
        self.assertRows(self.run_record(), {"test_good.G.test_ok": "pass",
                                            "unittest.loader._FailedTest.test_broken": "error"})

    def test_module_with_a_syntax_error(self):
        self.write("tests/test_syntax.py", "def (:\n")
        self.assertRows(self.run_record(), {"unittest.loader._FailedTest.test_syntax": "error"})

    def test_module_that_exits_at_import(self):
        self.write("tests/test_exits.py", "import sys\nsys.exit(0)\n")
        self.assertRows(self.run_record(), {"unittest.loader._FailedTest.test_exits": "error"})

    def test_setUpClass_raises(self):
        rec = self.record_one(
            "@classmethod\ndef setUpClass(cls):\n    raise RuntimeError('boom')\n"
            "def test_x(self):\n    pass\n")
        self.assertRows(rec, {"setUpClass (test_case.T)": "error"})

    def test_setUpModule_raises(self):
        rec = self.record_one(
            "def test_x(self):\n    pass\n",
            module_extra="def setUpModule():\n    raise RuntimeError('boom')\n")
        self.assertRows(rec, {"setUpModule (test_case)": "error"})

    def test_tearDownClass_raises_after_a_passing_test(self):
        rec = self.record_one(
            "@classmethod\ndef tearDownClass(cls):\n    raise RuntimeError('boom')\n"
            "def test_x(self):\n    pass\n")
        self.assertRows(rec, {"test_case.T.test_x": "pass", "tearDownClass (test_case.T)": "error"})

    def test_class_skipped_in_setUpClass_is_recorded_as_skip(self):
        rec = self.record_one(
            "@classmethod\ndef setUpClass(cls):\n    raise unittest.SkipTest('no')\n"
            "def test_x(self):\n    pass\n")
        self.assertRows(rec, {"setUpClass (test_case.T)": "skip"}, exit_code=0)


class ExitCodeTest(RecordCase):
    def test_zero_tests_discovered_is_a_failure_and_still_writes_the_file(self):
        self.write("tests/test_nothing.py", "x = 1\n")
        rec = self.run_record()
        self.assertEqual(rec.exit, shell_code(self.run_plain().returncode) or 1)  # plain says 0 before 3.12, 5 after
        self.assertEqual(rec.rows, [])
        self.assertEqual(rec.header["tests"], 0)
        self.assertRegex(rec.proc.stdout, r"^recorded 0 tests in \d+ ms -> out\.jsonl\n$")

    def test_an_empty_directory_is_a_failure(self):
        self.assertEqual(self.run_record().exit, shell_code(self.run_plain().returncode) or 1)

    def test_failing_run_writes_the_file_and_prints_the_summary(self):
        rec = self.record_one("def test_x(self):\n    self.fail('no')\n")
        self.assertEqual(rec.exit, 1)
        self.assertRegex(rec.proc.stdout, r"^recorded 1 tests in \d+ ms -> out\.jsonl\n$")
        self.assertIn("FAILED", rec.proc.stderr)

    def marker_suite(self):
        """A suite that leaves a file behind if (and only if) it runs."""
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n    open('ran.txt', 'w').close()\n"))
        return self.work / "ran.txt"

    def test_a_missing_output_directory_is_bad_usage_before_any_test_runs(self):
        marker = self.marker_suite()
        rec = self.run_record(out="no/such/dir/out.jsonl")
        self.assertEqual(rec.exit, 2, rec.proc.stderr)
        self.assertIn("output directory does not exist", rec.proc.stderr)
        self.assertFalse(marker.exists(), "the suite ran")
        self.assertEqual(rec.proc.stdout, "")

    def test_an_output_directory_that_is_not_writable_is_bad_usage_before_any_test_runs(self):
        if os.geteuid() == 0:
            self.skipTest("root can write anywhere")
        marker = self.marker_suite()
        (self.work / "ro").mkdir()
        (self.work / "ro").chmod(0o555)
        self.addCleanup((self.work / "ro").chmod, 0o755)
        rec = self.run_record(out="ro/out.jsonl")
        self.assertEqual(rec.exit, 2, rec.proc.stderr)
        self.assertIn("not writable", rec.proc.stderr)
        self.assertFalse(marker.exists(), "the suite ran")

    def test_an_output_path_that_is_a_directory_is_bad_usage_before_any_test_runs(self):
        marker = self.marker_suite()
        (self.work / "out.jsonl").mkdir()
        rec = self.run_record()
        self.assertEqual(rec.exit, 2, rec.proc.stderr)
        self.assertIn("is a directory", rec.proc.stderr)
        self.assertFalse(marker.exists(), "the suite ran")

    def test_a_test_that_removes_the_output_directory_still_cannot_turn_the_run_green(self):
        # the pre-run check passes, then the directory goes away: the write fails, the verdict does not change
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n    shutil.rmtree('gone')\n", "import shutil\n"))
        (self.work / "gone").mkdir()
        rec = self.run_record(out="gone/out.jsonl")
        self.assertEqual(rec.exit, 1, rec.proc.stderr)
        self.assertIn("cannot write", rec.proc.stderr)

    def test_bad_usage_exits_2(self):
        self.write("tests/test_case.py", "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n")
        for name, args in {
            "missing directory": ["record", "nope", "--out", "o.jsonl", "--repo", "demo"],
            "directory is a file": ["record", "tests/test_case.py", "--out", "o.jsonl", "--repo", "demo"],
            "no --out": ["record", "tests", "--repo", "demo"],
            "no --repo": ["record", "tests", "--out", "o.jsonl"],
            "no command": [],
            "unknown command": ["frobnicate"],
        }.items():
            with self.subTest(name):
                rec = self.run_record(args=args, out="o.jsonl")
                self.assertEqual(rec.exit, 2, rec.proc.stderr)
                self.assertIsNone(rec.raw)

    def test_an_uncaught_exception_during_the_run_is_not_exit_0(self):
        # a loader hook that explodes is the nearest thing to the recorder itself breaking
        self.write("tests/test_case.py", "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n")
        self.write("sitecustomize.py", "import unittest.loader as l\n"
                   "def boom(*a, **k):\n    raise RuntimeError('loader exploded')\n"
                   "l.TestLoader.discover = boom\n")
        rec = self.run_record(env={"PYTHONPATH": str(self.work)})
        self.assertNotEqual(rec.exit, 0)
        self.assertIn("loader exploded", rec.proc.stderr)


class OutputShapeTest(RecordCase):
    def setUp(self):
        super().setUp()
        self.rec = self.record_one(
            "def test_a(self):\n    pass\n"
            "def test_b(self):\n    self.fail('x')\n"
            "@unittest.skip('s')\ndef test_c(self):\n    pass\n", env=GITHUB_ENV)

    def test_keys_are_sorted_and_compact_and_the_header_has_every_field(self):
        for line in self.rec.lines:
            self.assertEqual(line, json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")))
        self.assertEqual(set(self.rec.header), set(quality.RUN_KEYS))
        for row in self.rec.rows:
            self.assertEqual(set(row), set(quality.TEST_KEYS))

    def test_every_number_is_an_integer(self):
        def no_float(text):
            raise AssertionError(f"non-integer number {text} in {self.rec.raw}")
        for line in self.rec.lines:
            for value in json.loads(line, parse_float=no_float).values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.assertIs(type(value), int)
        self.assertGreaterEqual(self.rec.header["wall_ms"], 0)
        self.assertTrue(all(r["ms"] >= 0 for r in self.rec.rows))

    def test_header_describes_the_run(self):
        h = self.rec.header
        self.assertEqual((h["v"], h["repo"], h["tests"], h["failed"], h["skipped"]), (1, "demo", 3, 1, 1))
        self.assertIs(h["complete"], True)
        self.assertRegex(h["started"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(h["python"], f"{sys.version_info[0]}.{sys.version_info[1]}")
        self.assertTrue(h["os"])

    def test_header_reads_the_github_environment(self):
        h = self.rec.header
        self.assertEqual(h["sha"], GITHUB_ENV["GITHUB_SHA"])
        self.assertEqual(h["event"], "pull_request")
        self.assertEqual(h["workflow"], "ci")
        self.assertEqual(h["evidence"], EVIDENCE)

    def test_header_without_the_github_environment(self):
        rec = self.run_record()
        h = rec.header
        self.assertEqual((h["sha"], h["event"], h["workflow"], h["evidence"]), ("", "local", "", ""))

    def test_evidence_needs_all_four_variables(self):
        for missing in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            with self.subTest(missing):
                env = {k: v for k, v in GITHUB_ENV.items() if k != missing}
                self.assertEqual(self.run_record(env=env).header["evidence"], "")

    def test_sha_falls_back_to_git_head(self):
        head = self.git_head()
        self.assertEqual(self.run_record().header["sha"], head)

    def test_stdout_is_one_line_and_unittests_report_stays_on_stderr(self):
        self.assertRegex(self.rec.proc.stdout, r"^recorded 3 tests in \d+ ms -> out\.jsonl\n$")
        self.assertIn("Ran 3 tests", self.rec.proc.stderr)
        self.assertNotIn("Ran 3 tests", self.rec.proc.stdout)

    def test_the_current_directory_is_importable_first(self):
        self.write("helper_in_cwd.py", "VALUE = 7\n")
        rec = self.record_one("def test_x(self):\n    import helper_in_cwd\n    self.assertEqual(helper_in_cwd.VALUE, 7)\n")
        self.assertEqual(rec.exit, 0, rec.proc.stderr)


class ExitDecisionTest(unittest.TestCase):
    """exit_code is the whole verdict: each guard has a row that only it can fail."""
    P, S = {"outcome": "pass"}, {"outcome": "skip"}
    F, E = {"outcome": "fail"}, {"outcome": "error"}

    def test_table(self):
        for name, code, rows, complete, want in (
            ("all pass", 0, [self.P, self.P], True, 0),
            ("skips are fine", 0, [self.S], True, 0),
            ("no test ran, the child says 0 (plain unittest before 3.12)", 0, [], True, 1),
            ("no test ran, the child says 5 (3.12 and later): its code stands", 5, [], True, 5),
            ("the child says 1, rows look fine", 1, [self.P], True, 1),
            ("the child says 5 with an error row (setUpModule on 3.12): its code stands", 5, [self.E], True, 5),
            ("the child was cut short with 3 before any test finished", 3, [], False, 3),
            ("the child died of SIGINT (130) with a pass row", 130, [self.P], False, 130),
            ("the child says 0, a row failed (a test that called os._exit(0))", 0, [self.P, self.F], True, 1),
            ("the child says 0, a row errored", 0, [self.E], True, 1),
            ("both say failed", 1, [self.F], True, 1),
            ("the child says 0, rows look fine, the run never completed (os._exit(0) in a setUpClass)",
             0, [self.P], False, 1),
            ("the child says 0, a skip row, the run never completed", 0, [self.S], False, 1),
            ("the child says 4 and the run never completed: its code stands", 4, [self.P], False, 4),
        ):
            with self.subTest(name):
                self.assertEqual(quality.exit_code(code, rows, complete), want)


class TallyTest(unittest.TestCase):
    """The parent's row builder, fed the child's lines directly."""

    def tally(self, *lines: str) -> "quality.Tally":
        tally = quality.Tally()
        for line in lines:
            tally.feed(line)
        return tally

    def test_a_pass_that_was_reported_but_never_ended_is_an_error(self):
        # the child died between the outcome and the end event
        tally = self.tally("S\tt.A.test_x", "O\tpass\tt.A.test_x")
        tally.finish()
        self.assertEqual([(r["id"], r["outcome"]) for r in tally.rows], [("t.A.test_x", "error")])

    def test_a_skip_that_was_reported_but_never_ended_is_an_error(self):
        tally = self.tally("S\tt.A.test_x", "O\tskip\tt.A.test_x")
        tally.finish()
        self.assertEqual(tally.rows[0]["outcome"], "error")

    def test_a_test_that_ended_keeps_its_reported_outcome(self):
        tally = self.tally("S\tt.A.test_x", "O\tpass\tt.A.test_x", "E\t5\tt.A.test_x")
        tally.finish()
        self.assertEqual(tally.rows, [{"id": "t.A.test_x", "outcome": "pass", "ms": 5}])

    def test_complete_only_after_the_run_complete_event(self):
        self.assertFalse(self.tally().complete)
        self.assertFalse(self.tally("S\tt.A.test_x", "O\tpass\tt.A.test_x", "E\t5\tt.A.test_x").complete)
        self.assertTrue(self.tally("S\tt.A.test_x", "O\tpass\tt.A.test_x", "E\t5\tt.A.test_x", "C").complete)


def case_source(body: str, before: str = "") -> str:
    return "import unittest\n" + before + "\nclass T(unittest.TestCase):\n" + textwrap.indent(src(body), "    ")


def one_test(body: str, before: str = "") -> dict:
    return {"tests/test_case.py": case_source("def test_x(self):\n" + textwrap.indent(body, "    "), before)}


DEP = "import warnings\ndef f():\n    warnings.warn('old', DeprecationWarning)\n"
CATCH = "with warnings.catch_warnings(record=True) as w:\n    dep.f()\nself.assertEqual(len(w), {n})\n"

DUMP = "open(os.environ['PARITY_DUMP'], 'w').write(repr({}))\n"

# name: (files, options). options: empty_is_1 = plain says 0 (before 3.12), the recorder says 1;
# incomplete = the run is cut short: the header says complete false, and the recorder says 1 when plain says 0;
# dump = what the test writes to PARITY_DUMP in each run must be equal.
PARITY = {
    "all pass": (one_test("pass\n"), {}),
    "one failure": (one_test("self.fail('no')\n"), {}),
    "DeprecationWarning from another module is seen": (
        {"tests/dep.py": DEP, **one_test(CATCH.format(n=1), "import warnings, dep\n")}, {}),
    "DeprecationWarning from another module is not expected": (
        {"tests/dep.py": DEP, **one_test(CATCH.format(n=0), "import warnings, dep\n")}, {}),
    "urllib.parse without importing it": (
        one_test("import urllib\nself.assertEqual(urllib.parse.quote('a b'), 'a%20b')\n"), {}),
    "import quality inside a test": (one_test("import quality\n"), {}),
    "chdir, then import a helper that sits in the new directory": (one_test(
        "d = tempfile.mkdtemp()\nself.addCleanup(shutil.rmtree, d)\n"
        "open(os.path.join(d, 'helper_there.py'), 'w').write('X = 1')\nos.chdir(d)\nimport helper_there\n",
        "import os, shutil, tempfile\n"), {}),
    "chdir, then re-import a helper from the original directory": ({"helper_here.py": "X = 1\n", **one_test(
        "import helper_here\nd = tempfile.mkdtemp()\nself.addCleanup(shutil.rmtree, d)\nos.chdir(d)\n"
        "sys.modules.pop('helper_here')\nimport helper_here\n", "import os, shutil, sys, tempfile\n")}, {}),
    "chdir that is never undone": (one_test("os.chdir(tempfile.gettempdir())\n", "import os, tempfile\n"), {}),
    "SystemExit(0) in setUpClass, no row (documented: 1 when plain says 0)": ({"tests/test_case.py": case_source(
        "@classmethod\ndef setUpClass(cls):\n    raise SystemExit(0)\ndef test_x(self):\n    pass\n")}, {"empty_is_1": True, "incomplete": True}),
    "SystemExit(1) in setUpClass": ({"tests/test_case.py": case_source(
        "@classmethod\ndef setUpClass(cls):\n    raise SystemExit(1)\ndef test_x(self):\n    pass\n")}, {"incomplete": True}),
    "KeyboardInterrupt in setUpClass": ({"tests/test_case.py": case_source(
        "@classmethod\ndef setUpClass(cls):\n    raise KeyboardInterrupt\ndef test_x(self):\n    pass\n")}, {"incomplete": True}),
    "error in setUpModule": (one_test("pass\n", "def setUpModule():\n    raise RuntimeError('boom')\n"), {}),
    "error in tearDownModule": (one_test("pass\n", "def tearDownModule():\n    raise RuntimeError('boom')\n"), {}),
    "error in tearDownClass": ({"tests/test_case.py": case_source(
        "@classmethod\ndef tearDownClass(cls):\n    raise RuntimeError('boom')\ndef test_x(self):\n    pass\n")}, {}),
    "error in an addCleanup": ({"tests/test_case.py": case_source(
        "def test_x(self):\n    self.addCleanup(self.boom)\ndef boom(self):\n    raise RuntimeError('boom')\n")}, {}),
    "error in an addClassCleanup": ({"tests/test_case.py": case_source(
        "@classmethod\ndef setUpClass(cls):\n    cls.addClassCleanup(cls.boom)\n"
        "@classmethod\ndef boom(cls):\n    raise RuntimeError('boom')\ndef test_x(self):\n    pass\n")}, {}),
    "load_tests raising": (one_test(
        "pass\n", "def load_tests(loader, tests, pattern):\n    raise RuntimeError('boom')\n"), {}),
    "load_tests exiting": (one_test(
        "pass\n", "def load_tests(loader, tests, pattern):\n    raise SystemExit(4)\n"), {"incomplete": True}),
    "failing subTest then a skip": (one_test(
        "with self.subTest(i=1):\n    self.fail('a')\nself.skipTest('late')\n"), {}),
    "setUpModule error next to a passing module": ({
        "tests/test_a.py": case_source("def test_x(self):\n    pass\n", "def setUpModule():\n    raise RuntimeError('b')\n"),
        "tests/test_b.py": case_source("def test_y(self):\n    pass\n")}, {}),
    "no tests at all (documented: 1 when plain says 0)": ({"tests/test_nothing.py": "x = 1\n"}, {"empty_is_1": True}),
    "sys.path is the same": (one_test(DUMP.format("sys.path"), "import os, sys\n"), {"dump": "equal"}),
    "sys.argv is the same": (one_test(DUMP.format("sys.argv"), "import os, sys\n"), {"dump": "equal"}),
    "sys.orig_argv is the same": (one_test(DUMP.format("sys.orig_argv"), "import os, sys\n"), {"dump": "equal"}),
    "sys.argv is what unittest sets": (one_test(
        "self.assertEqual(sys.argv[1:], ['discover', '-s', 'tests'])\n"
        "self.assertTrue(sys.argv[0].endswith(' -m unittest'), sys.argv)\n", "import sys\n"), {}),
    "the same modules are loaded, no more and no fewer": (one_test(
        DUMP.format("sorted(sys.modules)"), "import os, sys\n"), {"dump": "equal"}),
    "KeyboardInterrupt in a test": (one_test("raise KeyboardInterrupt\n"), {"incomplete": True}),
    "KeyboardInterrupt in a test after a failure": ({
        "tests/test_a.py": case_source("def test_a(self):\n    self.fail('no')\n"),
        "tests/test_b.py": case_source("def test_b(self):\n    raise KeyboardInterrupt\n")}, {"incomplete": True}),
    "SystemExit(3) in setUpClass after a passing module": ({
        "tests/test_a.py": case_source("def test_a(self):\n    pass\n"),
        "tests/test_b.py": case_source(
            "@classmethod\ndef setUpClass(cls):\n    raise SystemExit(3)\ndef test_b(self):\n    pass\n")}, {"incomplete": True}),
    "SystemExit(0) in setUpClass after a passing module (documented: 1 when plain says 0)": ({
        "tests/test_a.py": case_source("def test_a(self):\n    pass\n"),
        "tests/test_b.py": case_source(
            "@classmethod\ndef setUpClass(cls):\n    raise SystemExit(0)\ndef test_b(self):\n    pass\n")}, {"incomplete": True}),
    "os._exit(0) in setUpClass after a passing module (documented: 1 when plain says 0)": ({
        "tests/test_a.py": case_source("def test_a(self):\n    pass\n"),
        "tests/test_b.py": case_source(
            "@classmethod\ndef setUpClass(cls):\n    os._exit(0)\ndef test_b(self):\n    pass\n", "import os\n")},
        {"incomplete": True}),
    "os.closerange(3, 256) in a test, then a passing test (documented: 1 when plain says 0)": ({
        "tests/test_case.py": case_source(
            "def test_a(self):\n    os.closerange(3, 256)\ndef test_b(self):\n    pass\n", "import os\n")},
        {"incomplete": True}),
    "sys.modules['json'] is stubbed and left, then a test fails": ({"tests/test_case.py": case_source(
        "def test_a(self):\n    sys.modules['json'] = object()\ndef test_b(self):\n    self.fail('no')\n",
        "import sys\n")}, {}),
    "sys.modules['json'] is deleted, then a test fails": ({"tests/test_case.py": case_source(
        "def test_a(self):\n    sys.modules.pop('json', None)\ndef test_b(self):\n    self.fail('no')\n",
        "import sys\n")}, {}),
    "a helper module named json sits next to a failing test": ({
        "tests/json.py": "VALUE = 1\n", **one_test("self.fail('no')\n")}, {}),
    "a helper module named subprocess sits next to a failing test": ({
        "tests/subprocess.py": "VALUE = 1\n", **one_test("self.fail('no')\n")}, {}),
    "importlib.util is reached through importlib": (one_test(
        "import importlib\nself.assertIsNotNone(importlib.util.find_spec('os'))\n"), {}),
    "sys.stdout is closed and left closed": (one_test("sys.stdout.close()\n", "import sys\n"), {}),
    "sys.stderr is replaced and left that way, then a test fails": ({"tests/test_case.py": case_source(
        "def test_a(self):\n    sys.stderr = open(os.devnull, 'w')\ndef test_b(self):\n    self.fail('no')\n",
        "import os, sys\n")}, {}),
    "PATH is emptied and left empty": (one_test("os.environ['PATH'] = ''\n", "import os\n"), {}),
    "os.write, time.perf_counter and TestResult.addFailure are patched and left, then a test fails": ({
        "tests/test_case.py": case_source(
            "def test_a(self):\n"
            "    orig = unittest.TestResult.addFailure\n"
            "    unittest.TestResult.addFailure = lambda self, test, err: orig(self, test, err)\n"
            "    os.write = lambda fd, data: len(data)\n"
            "    time.perf_counter = lambda: 1.0\n"
            "def test_b(self):\n    self.fail('no')\n", "import os, time\n")}, {}),
}

FAILED_HEADER = re.compile(r"^(?:FAIL|ERROR): (.+)$", re.M)
DESCRIPTION = re.compile(r"^(\S+) \((.+?)\)(?: \(.*\))?$")  # "test_x (mod.Class.test_x)" or, before 3.11, "test_x (mod.Class)"


def row_ids_for(description: str) -> set[str]:
    """The ids a recorder row may carry for a test that unittest names in a FAIL or ERROR header."""
    m = DESCRIPTION.match(description)
    return {description} | ({m[2], f"{m[2]}.{m[1]}"} if m else set())


class ParityTest(RecordCase):
    """For tiny suites, `quality.py record` must give the exit code and the failures of
    `python -m unittest discover -s tests`, with the same interpreter."""

    def test_the_recorder_agrees_with_plain_unittest(self):
        for name, (files, opts) in PARITY.items():
            with self.subTest(name):
                shutil.rmtree(self.work)
                (self.work / "tests").mkdir(parents=True)
                for rel, text in files.items():
                    self.write(rel, text)
                dumps = {"plain": self.work / "dump-plain.txt", "record": self.work / "dump-record.txt"}
                plain = self.run_plain(env={"PARITY_DUMP": str(dumps["plain"])})
                rec = self.run_record(env={"PARITY_DUMP": str(dumps["record"])})
                code = shell_code(plain.returncode)
                stricter = opts.get("empty_is_1") or opts.get("incomplete")
                self.assertEqual(rec.exit, 1 if stricter and code == 0 else code,
                                 f"plain exit {plain.returncode}\n--- plain\n{plain.stderr}\n--- recorder\n{rec.proc.stderr}")
                self.assertIsNotNone(rec.raw, f"no file at the requested path\n{rec.proc.stderr}")
                failing = {r["id"] for r in rec.rows if r["outcome"] in ("fail", "error")}
                for description in FAILED_HEADER.findall(plain.stderr):
                    self.assertTrue(row_ids_for(description) & failing,
                                    f"unittest reported {description!r}; rows: {rec.rows}")
                if opts.get("dump") == "equal":
                    self.assertEqual(dumps["record"].read_text(), dumps["plain"].read_text())
                self.assertEqual(rec.header["exit_code"], code, "the header says how the run ended")
                self.assertIs(rec.header["complete"], not opts.get("incomplete"), "the header says whether the run finished")

    def test_the_file_is_where_it_was_asked_after_a_chdir_that_is_never_undone(self):
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n    os.chdir(tempfile.gettempdir())\n", "import os, tempfile\n"))
        (self.work / "here").mkdir()
        rec = self.run_record(out="here/out.jsonl")
        self.assertEqual((rec.exit, rec.header["tests"]), (0, 1), rec.proc.stderr)
        self.assertRegex(rec.proc.stdout, r"-> here/out\.jsonl\n$")

    def test_the_sha_comes_from_the_directory_the_run_started_in(self):
        head = self.git_head()
        self.write("tests/test_case.py", case_source("def test_x(self):\n    os.chdir('/')\n", "import os\n"))
        self.assertEqual(self.run_record().header["sha"], head)

    def test_a_test_that_changes_the_environment_does_not_change_the_header(self):
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n    os.environ['GITHUB_SHA'] = 'x'\n    os.environ['GITHUB_EVENT_NAME'] = 'x'\n",
            "import os\n"))
        h = self.run_record(env=GITHUB_ENV).header
        self.assertEqual((h["sha"], h["event"]), (GITHUB_ENV["GITHUB_SHA"], "pull_request"))

    def test_the_script_directory_is_not_importable_from_a_test(self):
        self.write("tests/test_case.py", case_source("def test_x(self):\n    import quality\n"))
        rec = self.run_record()
        self.assertEqual((rec.exit, rec.outcomes()), (1, {"test_case.T.test_x": "error"}), rec.proc.stderr)
        self.assertIn("ModuleNotFoundError", rec.proc.stderr)

    def test_a_run_cut_short_still_writes_the_rows_recorded_so_far(self):
        self.write("tests/test_a.py", case_source("def test_a(self):\n    pass\n"))
        self.write("tests/test_b.py", case_source(
            "@classmethod\ndef setUpClass(cls):\n    raise SystemExit(3)\ndef test_b(self):\n    pass\n"))
        rec = self.run_record()
        self.assertEqual((rec.exit, rec.header["exit_code"]), (3, 3), rec.proc.stderr)
        self.assertEqual(rec.outcomes(), {"test_a.T.test_a": "pass"})

    def test_the_sha_survives_a_test_that_empties_PATH(self):
        head = self.git_head()
        self.write("tests/test_case.py", case_source("def test_x(self):\n    os.environ['PATH'] = ''\n", "import os\n"))
        rec = self.run_record()
        self.assertEqual((rec.exit, rec.header["sha"]), (0, head), rec.proc.stderr)

    def test_a_test_that_closes_stdout_leaves_the_summary_line_and_exit_0(self):
        self.write("tests/test_case.py", case_source("def test_x(self):\n    sys.stdout.close()\n", "import sys\n"))
        rec = self.run_record()
        self.assertEqual(shell_code(self.run_plain().returncode), 0)
        self.assertEqual(rec.exit, 0, rec.proc.stderr)
        self.assertRegex(rec.proc.stdout, r"^recorded 1 tests in \d+ ms -> out\.jsonl\n$")

    def test_a_test_sees_the_recorders_own_stdin(self):
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n    self.assertEqual(sys.stdin.read(), 'piped in')\n", "import sys\n"))
        proc = run_in_group([sys.executable, str(SCRIPT), "record", "tests", "--out", "out.jsonl", "--repo", "demo"],
                            cwd=self.work, env=self.clean_env(), input="piped in")
        self.assertEqual(proc.returncode, 0, proc.stderr)


class RunCutShortTest(RecordCase):
    """A run that does not reach the end still writes a file that says so."""

    def suite(self, later: str, first: str = "def test_a(self):\n    pass\n"):
        self.write("tests/test_a.py", case_source(first))
        self.write("tests/test_b.py", case_source(later))

    def assertEndedLike(self, rec: Recorded, plain, want_exit: int | None = None):
        code = shell_code(plain.returncode)
        self.assertEqual(rec.exit, code if want_exit is None else want_exit, rec.proc.stderr)
        self.assertEqual(rec.header["exit_code"], code)
        self.assertIsNotNone(rec.raw)
        self.assertIs(rec.header["complete"], False, "a cut-short run says so")

    def test_a_keyboard_interrupt_is_an_error_row_not_a_pass(self):
        self.suite("def test_b(self):\n    raise KeyboardInterrupt\n")
        plain, rec = self.run_plain(), self.run_record()
        self.assertEqual(shell_code(plain.returncode), 130)
        self.assertEndedLike(rec, plain)
        self.assertEqual(rec.outcomes(), {"test_a.T.test_a": "pass", "test_b.T.test_b": "error"})
        self.assertEqual((rec.header["tests"], rec.header["failed"]), (2, 1))

    def test_a_keyboard_interrupt_in_the_first_test_is_still_a_row(self):
        self.write("tests/test_case.py", case_source("def test_x(self):\n    raise KeyboardInterrupt\n"))
        rec = self.run_record()
        self.assertEqual(rec.outcomes(), {"test_case.T.test_x": "error"})
        self.assertEqual((rec.exit, rec.header["exit_code"], rec.header["failed"]), (130, 130, 1))

    def test_SystemExit_in_setUpClass_keeps_the_rows_so_far_and_says_how_it_ended(self):
        for code in (3, 0):
            with self.subTest(code=code):
                self.suite(f"@classmethod\ndef setUpClass(cls):\n    raise SystemExit({code})\n"
                           "def test_b(self):\n    pass\n")
                plain, rec = self.run_plain(), self.run_record()
                self.assertEqual(shell_code(plain.returncode), code)
                self.assertEndedLike(rec, plain, want_exit=code or 1)  # plain says 0; a cut-short run is never green
                self.assertEqual(rec.outcomes(), {"test_a.T.test_a": "pass"})

    def test_a_fatal_signal_is_an_error_row_and_exit_128_plus_the_signal(self):
        self.write("tests/test_a.py", case_source("def test_a(self):\n    pass\n"))
        self.write("tests/test_b.py", case_source("def test_b(self):\n    os.kill(os.getpid(), signal.SIGKILL)\n",
                                                 "import os, signal\n"))
        plain, rec = self.run_plain(), self.run_record()
        self.assertEqual(shell_code(plain.returncode), 137)
        self.assertEndedLike(rec, plain)
        self.assertEqual(rec.outcomes(), {"test_a.T.test_a": "pass", "test_b.T.test_b": "error"})

    def test_os_exit_0_after_a_failure_keeps_the_rows_and_is_never_green(self):
        self.write("tests/test_a.py", case_source("def test_a(self):\n    self.fail('no')\n"))
        self.write("tests/test_b.py", case_source("def test_b(self):\n    os._exit(0)\n", "import os\n"))
        plain, rec = self.run_plain(), self.run_record()
        self.assertEqual(plain.returncode, 0, "plain unittest calls this green; the recorder documents the difference")
        self.assertEndedLike(rec, plain, want_exit=1)
        self.assertEqual(rec.outcomes(), {"test_a.T.test_a": "fail", "test_b.T.test_b": "error"})
        self.assertEqual(rec.header["failed"], 2)

    def test_os_exit_0_in_a_passing_suite_is_still_not_green(self):
        self.write("tests/test_case.py", case_source("def test_x(self):\n    os._exit(0)\n", "import os\n"))
        rec = self.run_record()
        self.assertEqual((rec.exit, rec.header["exit_code"], rec.outcomes()), (1, 0, {"test_case.T.test_x": "error"}))

    def test_os_exit_0_in_a_later_setUpClass_is_not_green(self):
        self.suite("@classmethod\ndef setUpClass(cls):\n    os._exit(0)\ndef test_b(self):\n    pass\n")
        self.write("tests/test_b.py", "import os\n" + (self.work / "tests/test_b.py").read_text())
        plain, rec = self.run_plain(), self.run_record()
        self.assertEqual(plain.returncode, 0, "plain unittest calls this green; the recorder documents the difference")
        self.assertEndedLike(rec, plain, want_exit=1)
        self.assertEqual(rec.outcomes(), {"test_a.T.test_a": "pass"})

    def test_a_test_that_closes_every_descriptor_leaves_a_header_that_says_incomplete(self):
        for name, later, plain_code in (("then a failing test", "self.fail('no')", 1), ("then a passing test", "pass", 0)):
            with self.subTest(name):
                self.write("tests/test_case.py", case_source(
                    "def test_a(self):\n    os.closerange(3, 256)\n"
                    f"def test_b(self):\n    {later}\n", "import os\n"))
                plain, rec = self.run_plain(), self.run_record()
                self.assertEqual(plain.returncode, plain_code)
                self.assertEqual(rec.header["complete"], False, rec.proc.stderr)
                self.assertEqual(rec.exit, 1, "the failing row cannot be recovered; the run must not be green")
                self.assertEqual(rec.header["exit_code"], plain_code)

    def test_a_forked_copy_that_keeps_running_the_suite_adds_no_rows(self):
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n"
            "    pid = os.fork()\n"
            "    if pid == 0:\n"
            "        raise RuntimeError('the forked copy carries on as a test')\n"
            "    os.waitpid(pid, 0)\n", "import os\n"))
        rec = self.run_record()
        self.assertEqual(rec.rows, [{"id": "test_case.T.test_x", "ms": rec.rows[0]["ms"], "outcome": "pass"}], rec.proc.stderr)
        self.assertEqual((rec.exit, rec.header["complete"], rec.header["failed"]), (0, True, 0), rec.proc.stderr)

    def test_a_recorder_started_with_SIGHUP_ignored_ignores_it_as_plain_unittest_does(self):
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n    open('started.txt', 'w').close()\n"
            "    for _ in range(400):\n        if os.path.exists('go.txt'):\n            break\n        time.sleep(0.05)\n",
            "import os, time\n"))
        proc = self.spawn_recorder(preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
        for _ in range(600):
            if (self.work / "started.txt").exists() or proc.poll() is not None:
                break
            time.sleep(0.05)
        proc.send_signal(signal.SIGHUP)
        (self.work / "go.txt").touch()
        reap(proc, 25)
        rec = Recorded(proc, self.work / "out.jsonl")
        self.assertEqual((rec.exit, rec.header["exit_code"], rec.outcomes()), (0, 0, {"test_case.T.test_x": "pass"}),
                         proc.stderr)

    def test_a_forked_process_that_outlives_the_run_and_holds_the_pipe_does_not_hang_the_recorder(self):
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n"
            "    pid = os.fork()\n"
            "    if pid == 0:\n"
            "        null = os.open(os.devnull, os.O_RDWR)\n"
            "        for fd in (0, 1, 2):\n"
            "            os.dup2(null, fd)\n"
            "        time.sleep(60)\n"
            "        os._exit(0)\n"
            "    open('sleeper.txt', 'w').write(str(pid))\n", "import os, time\n"))
        proc = self.spawn_recorder()  # its group, sleeper included, is killed at cleanup
        reap(proc, 30)
        rec = Recorded(proc, self.work / "out.jsonl")
        self.assertEqual((rec.exit, rec.outcomes()), (0, {"test_case.T.test_x": "pass"}))

    def test_SIGTERM_to_the_recorder_reaches_the_suite_and_the_file_still_says_what_happened(self):
        self.write("tests/test_case.py", case_source(
            "def test_x(self):\n    open('started.txt', 'w').close()\n    while True:\n        time.sleep(0.05)\n",
            "import time\n"))
        proc = self.spawn_recorder()
        for _ in range(600):
            if (self.work / "started.txt").exists() or proc.poll() is not None:
                break
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        reap(proc, 20)
        rec = Recorded(proc, self.work / "out.jsonl")
        self.assertEqual((rec.exit, rec.header["exit_code"]), (143, 143))
        self.assertEqual(rec.outcomes(), {"test_case.T.test_x": "error"})

    def test_a_test_id_with_odd_characters_round_trips(self):
        odd = "odd\n\tid \\ \\n caf\u00e9 \U0001f600 \x00"
        self.write("tests/test_case.py", case_source(
            f"def id(self):\n    return {odd!r}\ndef test_x(self):\n    self.fail('no')\n"))
        self.assertEqual(self.run_record().outcomes(), {odd: "fail"})


class InterpreterFlagsTest(RecordCase):
    """The child is started with the parent's interpreter options, and a test sees the same ones."""

    CASES = {
        "none": ([], {}),
        "-O": (["-O"], {}), "-OO": (["-OO"], {}),
        "-B": (["-B"], {}), "-s": (["-s"], {}), "-S": (["-S"], {}), "-E": (["-E"], {}), "-I": (["-I"], {}),
        "-b": (["-b"], {}), "-bb": (["-bb"], {}), "-q": (["-q"], {}),
        "-W": (["-W", "error::UserWarning"], {}),
        "two -W": (["-W", "ignore::UserWarning", "-W", "error::DeprecationWarning"], {}),
        "-X dev": (["-X", "dev"], {}),
        "-X utf8=0": (["-X", "utf8=0"], {}),
        "-X an option of our own": (["-X", "quality_probe=1"], {}),
        "-W and -X dev and -bb": (["-W", "error::UserWarning", "-X", "dev", "-bb"], {}),
        "PYTHONWARNINGS": ([], {"PYTHONWARNINGS": "error::UserWarning"}),
        "PYTHONWARNINGS and -W": (["-W", "ignore::DeprecationWarning"], {"PYTHONWARNINGS": "error::UserWarning,ignore::ResourceWarning"}),
        "PYTHONOPTIMIZE": ([], {"PYTHONOPTIMIZE": "1"}),
        "PYTHONOPTIMIZE and -OO": (["-OO"], {"PYTHONOPTIMIZE": "1"}),
        "PYTHONDEVMODE": ([], {"PYTHONDEVMODE": "1"}),
        "PYTHONSAFEPATH": ([], {"PYTHONSAFEPATH": "1"}),
        "PYTHONPATH": ([], {"PYTHONPATH": "/nonexistent-a:/nonexistent-b"}),
        "PYTHONNOUSERSITE": ([], {"PYTHONNOUSERSITE": "1"}),
    }
    if sys.version_info >= (3, 11):
        CASES["-P"] = (["-P"], {})

    PROBE = DUMP.format("(tuple(sys.flags), sys.warnoptions, sorted(sys._xoptions.items(), key=str), sys.path, "
                        "sys.orig_argv, sys.argv, sorted(sys.modules))")

    def test_a_test_sees_the_same_interpreter_as_under_plain_unittest(self):
        self.write("tests/test_case.py", case_source("def test_x(self):\n" + textwrap.indent(self.PROBE, "    "),
                                                    "import os, sys\n"))
        for name, (py, env) in self.CASES.items():
            with self.subTest(name):
                dumps = {"plain": self.work / "plain.txt", "record": self.work / "record.txt"}
                plain = self.run_plain(py=py, env={**env, "PARITY_DUMP": str(dumps["plain"])})
                rec = self.run_record(py=py, env={**env, "PARITY_DUMP": str(dumps["record"])})
                self.assertEqual((rec.exit, plain.returncode), (0, 0), f"{plain.stderr}\n---\n{rec.proc.stderr}")
                want, got = (ast.literal_eval(d.read_text()) for d in (dumps["plain"], dumps["record"]))
                for label, a, b in zip(("flags", "warnoptions", "xoptions", "path", "orig_argv", "argv", "modules"), want, got):
                    if label == "orig_argv" and (len(py) > 2 or py == ["-B"]):
                        continue  # options are rebuilt in a fixed order; -B also comes from the harness's environment
                    self.assertEqual(b, a, label)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

RUNS_ROW = dict(zip(quality.RUNS_SCHEMA, (
    "2026-11-16T09:30:00Z", "agentfiles", "fedcba9876543210fedcba9876543210fedcba98", "push", "ci",
    "3.12", "79", "0", "1", "4210", "0", "https://github.com/example/agentfiles/actions/runs/103/attempts/1")))
WEEKLY_ROW = dict(zip(quality.WEEKLY_SCHEMA, (
    "2026-W47", "agentfiles", "tests.test_a.A.test_three", "5", "0", "12", "40")))


class CheckCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "books-repo"
        shutil.copytree(FIXTURE, self.dir)

    def check(self, *extra, books_dir=None) -> tuple[int, list[str]]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = quality.main(["check", str(books_dir or self.dir), *extra])
        return code, out.getvalue().splitlines()

    def append(self, rel: str, **cells) -> int:
        schema = quality.SCHEMAS[rel]
        base = RUNS_ROW if rel == quality.RUNS else WEEKLY_ROW
        row = {**base, **cells}
        path = self.dir / rel
        with open(path, "a") as f:
            f.write(",".join(row[k] for k in schema) + "\n")
        return len(path.read_text().splitlines())

    def assertFlags(self, rel: str, line: int, kind: str, **kw):
        code, lines = self.check(**kw)
        want = f"{rel}:{line}: "
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith(want) and kind in l for l in lines), f"want {want}...{kind!r} in {lines}")
        self.assertEqual(lines[-1], f"{len(lines) - 1} problems")


class GoodBooksTest(CheckCase):
    def test_the_fixture_is_clean(self):
        self.assertEqual(self.check(), (0, ["ok, 4 rows, 0 problems"]))

    def test_a_valid_new_row_in_each_file_is_clean(self):
        self.append(quality.RUNS)
        self.append(quality.WEEKLY)
        self.assertEqual(self.check(), (0, ["ok, 6 rows, 0 problems"]))

    def test_same_evidence_on_another_python_is_not_a_duplicate(self):
        self.append(quality.RUNS, evidence="https://github.com/example/agentfiles/actions/runs/101/attempts/1", python="3.13")
        self.assertEqual(self.check()[0], 0)

    def test_not_a_directory_is_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, lines = self.check(books_dir=self.dir / "nope")
        self.assertEqual((code, lines), (2, []))
        self.assertIn("not a directory", err.getvalue())

    def test_missing_argument_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            quality.main(["check"])
        self.assertEqual(cm.exception.code, 2)


class FileProblemsTest(CheckCase):
    def test_missing_files(self):
        for rel in quality.SCHEMAS:
            with self.subTest(rel):
                (self.dir / rel).rename(self.dir / (rel + ".gone"))
                code, lines = self.check()
                self.assertEqual(code, 1)
                self.assertIn(f"{rel}:1: missing file", lines)
                (self.dir / (rel + ".gone")).rename(self.dir / rel)

    def test_wrong_header(self):
        for rel, schema in quality.SCHEMAS.items():
            with self.subTest(rel):
                path = self.dir / rel
                good = path.read_text()
                path.write_text(good.replace(schema[0], "renamed", 1))
                self.assertFlags(rel, 1, "header does not match the schema")
                path.write_text(good)

    def test_empty_file(self):
        (self.dir / quality.RUNS).write_text("")
        self.assertFlags(quality.RUNS, 1, "empty file")

    def test_wrong_column_count(self):
        with open(self.dir / quality.WEEKLY, "a") as f:
            f.write("2026-W47,agentfiles,t,1,0,1\n")
        self.assertFlags(quality.WEEKLY, 4, "6 columns, expected 7")

    def test_row_with_an_embedded_newline(self):
        with open(self.dir / quality.RUNS, "a") as f:
            f.write('2026-11-16T09:30:00Z,"agent\nfiles",x\n')
        self.assertFlags(quality.RUNS, 4, "spans more than one line")

    def test_crlf_line_endings_name_the_cause_once(self):
        for rel in quality.SCHEMAS:
            with self.subTest(rel):
                path = self.dir / rel
                good = path.read_bytes()
                path.write_bytes(good.replace(b"\n", b"\r\n"))
                code, lines = self.check()
                self.assertEqual((code, lines), (1, [f"{rel}:1: CRLF line endings; the books use LF", "1 problems"]))
                path.write_bytes(good)

    def test_a_utf8_bom_names_the_cause_once(self):
        for rel in quality.SCHEMAS:
            with self.subTest(rel):
                path = self.dir / rel
                good = path.read_bytes()
                path.write_bytes(b"\xef\xbb\xbf" + good)
                code, lines = self.check()
                self.assertEqual(code, 1)
                self.assertEqual(len(lines), 2, lines)
                self.assertRegex(lines[0], rf"^{re.escape(rel)}:1: starts with a UTF-8 BOM")
                path.write_bytes(good)

    def test_binary_file(self):
        (self.dir / quality.RUNS).write_bytes(b"\xff\xfe\x00")
        self.assertFlags(quality.RUNS, 1, "not UTF-8")


class RunsRulesTest(CheckCase):
    BAD = {
        "started": ["2026-11-16 09:30:00", "2026-11-16T09:30:00+00:00", "2026-13-45T09:30:00Z", ""],
        "repo": ["Agent_Files", "-lead", ""],
        "sha": ["abc123", "0123456789ABCDEF0123456789ABCDEF01234567", "0123456789abcdef0123456789abcdef0123456g", ""],
        "event": [""],
        "python": ["2.7", "3", "3.x", "3.12.1", ""],
        "tests": ["-1", "x", "1.5", "", "٣"],
        "failed": ["-1", "x", "1.5", ""],
        "skipped": ["-1", "x", ""],
        "wall_ms": ["-5", "x", "1e3", ""],
        "exit_code": ["-1", "x", "1.5", "", "٣", "256", "1000"],
        "evidence": ["http://example.com/run", "", "ftp://x", "https://", "https://github.com/example/demo",
                     "https://github.com/example/demo/actions/runs/1",
                     "https://github.com/example/demo/actions/runs/x/attempts/1",
                     "https://github.com/example/demo/actions/runs/1/attempts/",
                     "https://github.com/example/demo/actions/runs/1/attempts/1 and more"],
    }

    def test_each_bad_value_is_flagged_with_file_line_and_field(self):
        for field, values in self.BAD.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    path = self.dir / quality.RUNS
                    good = path.read_text()
                    line = self.append(quality.RUNS, **{field: value, "evidence": value if field == "evidence" else RUNS_ROW["evidence"]})
                    self.assertFlags(quality.RUNS, line, field)
                    path.write_text(good)

    def test_failed_plus_skipped_more_than_tests(self):
        line = self.append(quality.RUNS, tests="5", failed="3", skipped="3")
        self.assertFlags(quality.RUNS, line, "failed + skipped")

    def test_exit_code_0_with_failures_is_a_real_case(self):
        self.append(quality.RUNS, tests="5", failed="2", exit_code="0")
        self.assertEqual(self.check()[0], 0)

    def test_exit_code_255_is_fine(self):
        self.append(quality.RUNS, exit_code="255")
        self.assertEqual(self.check()[0], 0)

    def test_evidence_on_another_host_is_fine(self):
        self.append(quality.RUNS, evidence="https://ghe.example.com/team/repo/actions/runs/7/attempts/3")
        self.assertEqual(self.check()[0], 0)

    def test_failed_plus_skipped_equal_to_tests_is_fine(self):
        self.append(quality.RUNS, tests="5", failed="3", skipped="2")
        self.assertEqual(self.check()[0], 0)

    def test_duplicate_evidence_and_python(self):
        line = self.append(quality.RUNS, started="2026-11-16T10:00:00Z",
                           evidence="https://github.com/example/agentfiles/actions/runs/101/attempts/1", python="3.12")
        self.assertFlags(quality.RUNS, line, "duplicate of line 2")


class WeeklyRulesTest(CheckCase):
    BAD = {
        "week": ["2026-46", "2026-W4", "26-W46", "2026-w46", "", "2026-W00", "2026-W54", "2025-W53", "2021-W53",
                 "0000-W01"],
        "repo": ["Agent_Files", ""],
        "test_id": [""],
        "runs": ["0", "-1", "x", ""],
        "failed": ["-1", "x", ""],
        "p50_ms": ["-1", "x", ""],
        "max_ms": ["-1", "1.5", ""],
    }

    def test_each_bad_value_is_flagged_with_file_line_and_field(self):
        for field, values in self.BAD.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    path = self.dir / quality.WEEKLY
                    good = path.read_text()
                    line = self.append(quality.WEEKLY, **{field: value})
                    self.assertFlags(quality.WEEKLY, line, field if field != "runs" else "runs")
                    path.write_text(good)

    def test_failed_more_than_runs(self):
        line = self.append(quality.WEEKLY, runs="2", failed="3")
        self.assertFlags(quality.WEEKLY, line, "failed (3) is more than runs (2)")

    def test_week_53_is_fine_only_in_years_that_have_it(self):
        self.append(quality.WEEKLY, week="2026-W53")
        self.append(quality.WEEKLY, week="2020-W53")
        self.append(quality.WEEKLY, week="2026-W01")
        self.assertEqual(self.check()[0], 0)

    def test_p50_more_than_max(self):
        line = self.append(quality.WEEKLY, p50_ms="50", max_ms="49")
        self.assertFlags(quality.WEEKLY, line, "p50_ms (50) is more than max_ms (49)")

    def test_p50_equal_to_max_is_fine(self):
        self.append(quality.WEEKLY, p50_ms="40", max_ms="40")
        self.assertEqual(self.check()[0], 0)

    def test_duplicate_week_repo_test(self):
        line = self.append(quality.WEEKLY, test_id="tests.test_a.A.test_one", week="2026-W46")
        self.assertFlags(quality.WEEKLY, line, "duplicate of line 2")

    def test_same_test_in_another_week_or_repo_is_not_a_duplicate(self):
        self.append(quality.WEEKLY, test_id="tests.test_a.A.test_one", week="2026-W47")
        self.append(quality.WEEKLY, test_id="tests.test_a.A.test_one", week="2026-W46", repo="other")
        self.assertEqual(self.check()[0], 0)


class AppendOnlyTest(CheckCase):
    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(self.dir), *args],
                              check=True, capture_output=True, text=True).stdout

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "books")

    def test_a_pure_append_passes(self):
        self.append(quality.RUNS)
        self.assertEqual(self.check("--base", "HEAD"), (0, ["ok, 5 rows, 0 problems"]))

    def test_no_change_passes(self):
        self.assertEqual(self.check("--base", "HEAD")[0], 0)

    def test_an_edited_row_is_caught_on_its_line(self):
        path = self.dir / quality.RUNS
        path.write_text(path.read_text().replace(",4210,", ",4211,"))
        code, lines = self.check("--base", "HEAD")
        self.assertEqual(code, 1)
        self.assertIn("books/runs.csv:2: changed since HEAD", lines)

    def test_a_removed_row_is_caught(self):
        path = self.dir / quality.RUNS
        first_two = path.read_text().splitlines(keepends=True)[:2]
        path.write_text("".join(first_two))
        code, lines = self.check("--base", "HEAD")
        self.assertEqual(code, 1)
        self.assertIn("books/runs.csv:3: removed since HEAD", lines)

    def test_a_reordered_row_is_caught(self):
        path = self.dir / quality.RUNS
        header, a, b = path.read_text().splitlines(keepends=True)
        path.write_text(header + b + a)
        code, lines = self.check("--base", "HEAD")
        self.assertEqual(code, 1)
        self.assertIn("books/runs.csv:2: changed since HEAD", lines)

    def test_the_weekly_file_has_no_append_only_rule_yet(self):
        path = self.dir / quality.WEEKLY
        path.write_text(path.read_text().replace(",12,40", ",13,40"))
        self.assertEqual(self.check("--base", "HEAD")[0], 0)

    def test_a_bad_ref_is_reported(self):
        code, lines = self.check("--base", "no-such-ref")
        self.assertEqual(code, 1)
        self.assertTrue(any("cannot check against no-such-ref" in l for l in lines), lines)

    def test_a_directory_that_is_not_a_git_repo_is_reported(self):
        plain = Path(self._tmp.name) / "plain"
        shutil.copytree(FIXTURE, plain)
        env = {"GIT_CEILING_DIRECTORIES": self._tmp.name}
        with unittest.mock.patch.dict(os.environ, env):
            code, lines = self.check("--base", "HEAD", books_dir=plain)
        self.assertEqual(code, 1)
        self.assertTrue(any("cannot check against HEAD" in l for l in lines), lines)

    def test_crlf_or_a_bom_against_a_base_is_one_message_not_one_per_line(self):
        path = self.dir / quality.RUNS
        good = path.read_bytes()
        for name, bad, want in (("CRLF", good.replace(b"\n", b"\r\n"), "CRLF line endings"),
                                ("BOM", b"\xef\xbb\xbf" + good, "starts with a UTF-8 BOM")):
            with self.subTest(name):
                path.write_bytes(bad)
                code, lines = self.check("--base", "HEAD")
                self.assertEqual(code, 1)
                self.assertEqual(len(lines), 2, lines)
                self.assertIn(want, lines[0])
                self.assertNotIn("changed since", "\n".join(lines))

    def test_a_books_folder_inside_a_bigger_repo_is_reported_not_called_clean(self):
        outer = Path(self._tmp.name) / "outer"
        nested = outer / "quality"
        shutil.copytree(FIXTURE, nested)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(outer), *a],
                                        check=True, capture_output=True, text=True)
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "books live in a subfolder")
        runs = nested / quality.RUNS
        runs.write_text(runs.read_text().replace(",4210,", ",4211,"))  # edit a row that is already committed
        code, lines = self.check("--base", "HEAD", books_dir=nested)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any("top level of its git work tree" in l for l in lines), lines)

    def test_the_top_level_is_found_through_a_symlinked_path(self):
        link = Path(self._tmp.name) / "link"
        link.symlink_to(self.dir, target_is_directory=True)
        self.assertEqual(self.check("--base", "HEAD", books_dir=link)[0], 0)

    def test_runs_csv_absent_at_the_base_passes(self):
        self.git("rm", "-q", "--cached", quality.RUNS)
        self.git("commit", "-q", "-m", "drop runs")
        self.assertEqual(self.check("--base", "HEAD")[0], 0)


if __name__ == "__main__":
    unittest.main()
