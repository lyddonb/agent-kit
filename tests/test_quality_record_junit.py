"""Tests for `quality.py record-junit` (plugins/bstack/skills/qualitydirector/scripts/quality.py).

The command is run as a subprocess, as CI runs it, with a fake child in place of pytest: a small
script that copies a given JUnit XML file to the path the command watches and exits with a given
status. No test here needs pytest.
"""
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# QUALITY_SCRIPT points the suite at another copy of the script, as in test_quality.py.
SCRIPT = Path(os.environ.get("QUALITY_SCRIPT")
              or ROOT / "plugins/bstack/skills/qualitydirector/scripts/quality.py")

spec = importlib.util.spec_from_file_location("quality", SCRIPT)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)

FAKE_CHILD = textwrap.dedent("""
    import os, shutil, sys
    src, dest, code, sig = sys.argv[1:5]
    open("ran.txt", "w").close()
    if src != "-":
        shutil.copyfile(src, dest)
    if sig != "0":
        os.kill(os.getpid(), int(sig))
    sys.exit(int(code))
""")
SHA = "0123456789abcdef0123456789abcdef01234567"
CI_ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "acme/demo",
          "GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "push", "GITHUB_WORKFLOW": "ci"}


def case(classname: str | None, name: str, time: str | None = "0.01", child: str = "") -> str:
    attrs = ""
    if classname is not None:
        attrs += f' classname="{classname}"'
    attrs += f' name="{name}"'
    if time is not None:
        attrs += f' time="{time}"'
    return f"<testcase{attrs}>{child}</testcase>" if child else f"<testcase{attrs} />"


def suite(*cases: str, name: str = "pytest") -> str:
    return f'<testsuite name="{name}" errors="0" failures="0" skipped="0" tests="{len(cases)}" time="1.0">{"".join(cases)}</testsuite>'


def junit_xml(*cases: str) -> str:
    return f'<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">{suite(*cases)}</testsuites>'


FAIL = '<failure message="assert 1 == 2">assert 1 == 2</failure>'
ERROR = '<error message="setup failed">setup failed</error>'
SKIP = '<skipped type="pytest.skip" message="not here">not here</skipped>'

BOMB = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><testsuites><testsuite><testcase classname="t" name="&c;"/>'
        '</testsuite></testsuites>')
EXTERNAL = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hostname">]><testsuites><testsuite>'
            '<testcase classname="t" name="&e;"/></testsuite></testsuites>')


class Recorded:
    def __init__(self, proc: subprocess.CompletedProcess, out: Path, work: Path):
        self.proc = proc
        self.exit = proc.returncode
        self.out = out
        self.ran = (work / "ran.txt").exists()
        lines = out.read_text().splitlines() if out.is_file() else []
        self.header = json.loads(lines[0]) if lines else None
        self.rows = [json.loads(line) for line in lines[1:]]

    def outcomes(self) -> dict[str, str]:
        return {r["id"]: r["outcome"] for r in self.rows}


class RecordJunitCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name) / "work"
        self.work.mkdir()
        (self.work / "fake_child.py").write_text(FAKE_CHILD)

    def env(self, extra=None) -> dict:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
        clean["GIT_CEILING_DIRECTORIES"] = str(self.work.parent)  # no repo above the temp dir
        clean["PYTHONDONTWRITEBYTECODE"] = "1"
        clean.update(extra or {})
        return clean

    def run_cmd(self, *, xml: str | bytes | None = None, code=0, sig=0, junit="junit.xml", out="out.jsonl",
                env=None, extra=(), child=None, repo="demo") -> Recorded:
        if xml is not None:
            (self.work / "given.xml").write_bytes(xml.encode("utf-8") if isinstance(xml, str) else xml)
        command = child if child is not None else [sys.executable, "fake_child.py", "given.xml" if xml is not None else "-",
                                                    junit, str(code), str(int(sig))]
        argv = [sys.executable, str(SCRIPT), "record-junit", "--junit", junit, "--out", out, "--repo", repo, *extra, "--", *command]
        proc = subprocess.run(argv, cwd=self.work, env=self.env(env), capture_output=True, text=True, timeout=60)
        return Recorded(proc, self.work / out, self.work)

    def assertRefused(self, rec: Recorded, why: str):
        self.assertNotEqual(rec.exit, 0)
        self.assertEqual(rec.rows, [])
        self.assertFalse(rec.header["complete"])
        self.assertEqual(rec.header["tests"], 0)
        self.assertIn("junit file", rec.proc.stderr)
        self.assertIn(why, rec.proc.stderr)
        self.assertEqual(len(rec.proc.stderr.strip().splitlines()), 1, rec.proc.stderr)


class Outcomes(RecordJunitCase):
    def test_each_outcome_maps(self):
        rec = self.run_cmd(xml=junit_xml(
            case("tests.test_a.TestK", "test_pass"),
            case("tests.test_a.TestK", "test_fail", child=FAIL),
            case("tests.test_a.TestK", "test_skip", child=SKIP),
            case("tests.test_a.TestK", "test_setup_error", child=ERROR),
            case("tests.test_a.TestK", "test_both", child=FAIL + ERROR),
            case("tests.test_a.TestK", "test_xfail", child='<skipped type="pytest.xfail" message="expected">x</skipped>'),
            case("tests.test_a.TestK", "test_xpass"),
            case("tests.test_a.TestK", "test_strict_xpass", child='<failure message="[XPASS(strict)]">x</failure>'),
            case("", "tests.test_broken", child='<error message="collection failure">ImportError</error>'),
        ), code=1)
        p = "tests.test_a.TestK."
        self.assertEqual(rec.outcomes(), {
            p + "test_pass": "pass", p + "test_fail": "fail", p + "test_skip": "skip", p + "test_setup_error": "error",
            p + "test_both": "error", p + "test_xfail": "skip", p + "test_xpass": "pass", p + "test_strict_xpass": "fail",
            "tests.test_broken": "error"})

    def test_rows_keep_the_files_order_and_duplicates(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "b"), case("t", "a"), case("t", "b", child=FAIL)), code=1)
        self.assertEqual([(r["id"], r["outcome"]) for r in rec.rows], [("t.b", "pass"), ("t.a", "pass"), ("t.b", "fail")])

    def test_several_suites_and_a_lone_testsuite_root(self):
        two = f'<testsuites>{suite(case("a", "x"), name="one")}{suite(case("b", "y", child=FAIL), name="two")}</testsuites>'
        self.assertEqual(self.run_cmd(xml=two, code=1).outcomes(), {"a.x": "pass", "b.y": "fail"})
        rec = self.run_cmd(xml=suite(case("c", "z")), junit="j2.xml", out="o2.jsonl")
        self.assertEqual(rec.outcomes(), {"c.z": "pass"})

    def test_ms_edge_values(self):
        times = {"plain": "1.234", "rounds": "0.0016", "tiny": "0.0004", "missing": None, "text": "abc", "empty": "",
                 "negative": "-1", "nan": "nan", "inf": "inf", "overflow": "1e400", "huge": "1e300", "times_1000_overflows": "1e306", "zero": "0"}
        rec = self.run_cmd(xml=junit_xml(*(case("t", n, time=v) for n, v in times.items())))
        got = {r["id"]: r["ms"] for r in rec.rows}
        day = quality.MAX_JUNIT_TEST_MS
        self.assertEqual(got, {"t.plain": 1234, "t.rounds": 2, "t.tiny": 0, "t.missing": 0, "t.text": 0, "t.empty": 0,
                               "t.negative": 0, "t.nan": 0, "t.inf": 0, "t.overflow": day, "t.huge": day, "t.times_1000_overflows": day, "t.zero": 0})

    def test_only_plain_ascii_decimal_seconds_are_read(self):
        times = {"underscore": "1_000", "arabic_indic": "\u0661", "plus": "+1", "spaces": " 1 ", "exp": "1.5e1", "just_under_a_day": "86399.999"}
        rec = self.run_cmd(xml=junit_xml(*(case("t", n, time=v) for n, v in times.items())))
        self.assertEqual({r["id"]: r["ms"] for r in rec.rows},
                         {"t.underscore": 0, "t.arabic_indic": 0, "t.plus": 0, "t.spaces": 0, "t.exp": 15000, "t.just_under_a_day": 86399999})

    def test_outcome_children_in_any_case_or_namespace_and_rerun_or_flaky_ones_count(self):
        rec = self.run_cmd(xml=junit_xml(
            case("t", "upper", child="<Failure/>"), case("t", "ns", child='<f:failure xmlns:f="urn:x"/>'),
            case("t", "rerun", child="<rerunFailure/>"), case("t", "flaky", child="<flakyFailure/>"),
            case("t", "flaky_error", child="<flakyError/>"), case("t", "inside_output", child="<system-out>&lt;failure/&gt;</system-out>"),
            '<n:testcase xmlns:n="urn:y" classname="t" name="namespaced" time="0.1"><n:error/></n:testcase>'), code=1)
        self.assertEqual(rec.outcomes(), {"t.upper": "fail", "t.ns": "fail", "t.rerun": "fail", "t.flaky": "fail",
                                          "t.flaky_error": "error", "t.inside_output": "pass", "t.namespaced": "error"})
        self.assertTrue(rec.header["complete"])

    def test_a_rerun_plugins_empty_failed_attempt_makes_the_run_incomplete(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "flaky", time="0.000"), case("t", "flaky"), case("t", "steady")), code=0)
        self.assertFalse(rec.header["complete"])
        self.assertEqual(rec.exit, 1)
        self.assertIn("appear more than once with a passing entry", rec.proc.stderr)

    def test_a_test_with_a_failure_and_a_teardown_error_listed_twice_is_believed(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "both", child=FAIL), case("t", "both", child=ERROR)), code=1)
        self.assertTrue(rec.header["complete"], rec.proc.stderr)
        self.assertEqual(rec.proc.stderr, "")

    def test_exit_1_with_no_failing_test_in_the_file_is_incomplete(self):
        rec = self.run_cmd(xml='<testsuites failures="3"><testsuite>' + case("t", "a") + "</testsuite></testsuites>", code=1)
        self.assertFalse(rec.header["complete"])
        self.assertEqual(rec.exit, 1)
        self.assertIn("exited 1", rec.proc.stderr)


class Ids(RecordJunitCase):
    def test_id_building(self):
        rec = self.run_cmd(xml=junit_xml(case("tests.test_a.TestK", "test_m[a-b]"), case("", "tests.test_broken"),
                                         case(None, "bare"), case("", ""), case("only.class", "")))
        self.assertEqual([r["id"] for r in rec.rows],
                         ["tests.test_a.TestK.test_m[a-b]", "tests.test_broken", "bare", "(unnamed test)", "only.class."])

    def test_ids_are_not_otherwise_altered(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "=SUM(A1)"), case("t", "with, comma")))
        self.assertEqual([r["id"] for r in rec.rows], ["t.=SUM(A1)", "t.with, comma"])

    def test_a_long_id_is_shortened_to_exactly_1000_with_a_hash_tag(self):
        full = "tests.test_p." + "x" * 1500
        tag = "...#" + hashlib.sha256(full.encode()).hexdigest()[:12]
        rec = self.run_cmd(xml=junit_xml(case("tests", full[len("tests."):]), case("t", "y" * 998), case("t", "y" * 999)))
        long_id, at_limit, over_limit = (r["id"] for r in rec.rows)
        self.assertEqual(long_id, full[:1000 - len(tag)] + tag)
        self.assertEqual(len(long_id), 1000)
        self.assertEqual(at_limit, "t." + "y" * 998)
        self.assertEqual(len(over_limit), 1000)
        self.assertTrue(over_limit.endswith("...#" + hashlib.sha256(("t." + "y" * 999).encode()).hexdigest()[:12]))

    def test_ids_sharing_a_long_prefix_stay_distinct_and_are_deterministic(self):
        prefix = "tests.test_p.test_m[" + "z" * 990
        xml = junit_xml(case("", prefix + "one" + "q" * 100 + "]"), case("", prefix + "two" + "q" * 100 + "]"))
        first = self.run_cmd(xml=xml)
        second = self.run_cmd(xml=xml, junit="again.xml", out="again.jsonl")
        ids = [r["id"] for r in first.rows]
        self.assertEqual({len(i) for i in ids}, {1000})
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(ids, [r["id"] for r in second.rows])
        self.assertEqual(ids[0][:984], ids[1][:984])
        self.assertNotEqual(ids[0][984:], ids[1][984:])


class Verdict(RecordJunitCase):
    def test_header_and_counts(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "a"), case("t", "b", child=FAIL), case("t", "c", child=ERROR),
                                         case("t", "d", child=SKIP)), code=1, extra=["--sha", SHA], env=CI_ENV)
        h = rec.header
        self.assertEqual(set(h), set(quality.RUN_KEYS))
        self.assertEqual((h["v"], h["repo"], h["sha"], h["event"], h["workflow"], h["os"]), (1, "demo", SHA, "push", "ci", sys.platform))
        self.assertEqual((h["tests"], h["failed"], h["skipped"], h["exit_code"], h["complete"]), (4, 2, 1, 1, True))
        self.assertEqual(h["python"], f"{sys.version_info[0]}.{sys.version_info[1]}")
        self.assertEqual(h["evidence"], "https://github.com/acme/demo/actions/runs/7/attempts/1")
        self.assertRegex(h["started"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsInstance(h["wall_ms"], int)
        self.assertEqual(rec.exit, 1)
        self.assertRegex(rec.proc.stdout, r"^recorded 4 tests in \d+ ms -> out\.jsonl\n$")

    def test_wall_time_is_measured_around_the_child(self):
        slow = [sys.executable, "-c", "import time; time.sleep(0.05)"]
        rec = self.run_cmd(child=slow)
        self.assertGreaterEqual(rec.header["wall_ms"], 50)

    def test_sha_comes_from_the_flag_then_github_sha_then_empty(self):
        xml = junit_xml(case("t", "a"))
        other = "f" * 40
        self.assertEqual(self.run_cmd(xml=xml, extra=["--sha", other], env={"GITHUB_SHA": SHA}).header["sha"], other)
        self.assertEqual(self.run_cmd(xml=xml, env={"GITHUB_SHA": SHA}, junit="b.xml", out="b.jsonl").header["sha"], SHA)
        self.assertEqual(self.run_cmd(xml=xml, junit="c.xml", out="c.jsonl").header["sha"], "")

    def test_exit_codes_and_complete_for_each_child_status(self):
        passing, failing = junit_xml(case("t", "a")), junit_xml(case("t", "a", child=FAIL))
        table = {  # name: (xml, child code, expected exit, complete)
            "0 all passed": (passing, 0, 0, True),
            "1 some failed": (failing, 1, 1, True),
            "2 interrupted": (passing, 2, 2, False),
            "3 internal error": (passing, 3, 3, False),
            "4 usage error": (passing, 4, 4, False),
            "5 nothing collected": (junit_xml(), 5, 5, True),
            "0 with no tests": (junit_xml(), 0, 1, True),
            "0 with a failure row": (failing, 0, 1, True),
        }
        for n, (name, (xml, code, want, complete)) in enumerate(table.items()):
            with self.subTest(name):
                rec = self.run_cmd(xml=xml, code=code, junit=f"{n}.xml", out=f"{n}.jsonl")
                self.assertEqual((rec.exit, rec.header["complete"], rec.header["exit_code"]), (want, complete, code))

    def test_a_child_killed_by_a_signal_is_incomplete_and_exits_128_plus_n(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "a")), sig=signal.SIGTERM)
        self.assertEqual((rec.exit, rec.header["exit_code"], rec.header["complete"]), (143, 143, False))

    def test_a_signal_with_no_file_still_writes_an_incomplete_record(self):
        rec = self.run_cmd(sig=signal.SIGTERM)
        self.assertRefused(rec, "did not write it")
        self.assertEqual(rec.exit, 143)

    def test_the_child_sees_the_test_output_directly(self):
        rec = self.run_cmd(child=[sys.executable, "-c", "print('hello from the child')"])
        self.assertIn("hello from the child", rec.proc.stdout)

    def test_the_command_gets_no_extra_arguments_and_no_shell(self):
        probe = "import sys, json; print(json.dumps(sys.argv[1:]))"
        rec = self.run_cmd(child=[sys.executable, "-c", probe, "a b", ";", "$HOME", "--junitxml=x"])
        self.assertEqual(json.loads(rec.proc.stdout.splitlines()[0]), ["a b", ";", "$HOME", "--junitxml=x"])


class WriteFailure(RecordJunitCase):
    def test_a_record_that_cannot_be_written_after_a_good_run_exits_1(self):
        drop = "import shutil; shutil.rmtree('outdir')"
        (self.work / "outdir").mkdir()
        (self.work / "given.xml").write_text(junit_xml(case("t", "a")))
        script = f"import shutil; shutil.copyfile('given.xml', 'junit.xml'); {drop}"
        rec = self.run_cmd(child=[sys.executable, "-c", script], out="outdir/out.jsonl")
        self.assertEqual(rec.exit, 1)
        self.assertIn("cannot write", rec.proc.stderr)


class Refused(RecordJunitCase):
    def test_missing_file(self):
        self.assertRefused(self.run_cmd(child=[sys.executable, "-c", "pass"]), "did not write it")

    def test_missing_file_after_a_failing_child_keeps_its_status(self):
        rec = self.run_cmd(child=[sys.executable, "-c", "raise SystemExit(4)"])
        self.assertRefused(rec, "did not write it")
        self.assertEqual((rec.exit, rec.header["exit_code"]), (4, 4))

    def test_a_fifo_left_at_the_path_is_refused_and_does_not_hang(self):
        rec = self.run_cmd(child=["sh", "-c", 'mkfifo "$1"', "x", "junit.xml"])
        self.assertRefused(rec, "not a regular file")

    def test_file_too_big(self):
        pad = "<!-- " + "x" * quality.MAX_ARTIFACT_BYTES + " -->"
        self.assertRefused(self.run_cmd(xml=junit_xml(case("t", "a")) + pad), "larger than")

    def test_doctype_with_entity_expansion(self):
        rec = self.run_cmd(xml=BOMB)
        self.assertRefused(rec, "DOCTYPE")

    def test_doctype_with_an_external_entity(self):
        self.assertRefused(self.run_cmd(xml=EXTERNAL), "DOCTYPE")

    def test_doctype_in_any_case_and_after_the_root(self):
        self.assertRefused(self.run_cmd(xml='<?xml version="1.0"?><!doctype a><testsuites/>'), "DOCTYPE")

    def test_doctype_hidden_by_utf16_is_refused_too(self):
        xml = '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE a [<!ENTITY e "x">]><testsuites/>'
        rec = self.run_cmd(xml=xml.encode("utf-16"))
        self.assertNotEqual(rec.exit, 0)
        self.assertEqual((rec.rows, rec.header["complete"]), ([], False))

    def test_an_unknown_encoding_is_refused_not_a_crash(self):
        rec = self.run_cmd(xml='<?xml version="1.0" encoding="no-such-codec"?><testsuites/>')
        self.assertRefused(rec, "not valid XML")

    def test_not_xml(self):
        self.assertRefused(self.run_cmd(xml="this is not xml"), "not valid XML")

    def test_truncated_xml(self):
        self.assertRefused(self.run_cmd(xml=junit_xml(case("t", "a"))[:-30]), "not valid XML")

    def test_wrong_root(self):
        self.assertRefused(self.run_cmd(xml="<html><testcase classname='a' name='b'/></html>"), "not testsuites or testsuite")

    def test_too_many_testcases(self):
        xml = junit_xml(*(case("t", f"n{i}", time="0") for i in range(quality.MAX_TEST_ROWS + 1)))
        self.assertRefused(self.run_cmd(xml=xml), "testcases")

    def test_the_limit_itself_is_accepted(self):
        xml = junit_xml(*(case("t", f"n{i}", time="0") for i in range(quality.MAX_TEST_ROWS)))
        rec = self.run_cmd(xml=xml)
        self.assertEqual((rec.exit, rec.header["tests"], rec.header["complete"]), (0, quality.MAX_TEST_ROWS, True))

    def test_the_refusal_line_prints_only_printable_text(self):
        rec = self.run_cmd(xml="<?xml version='1.0'?><\x1b[31mroot/>".encode())
        self.assertNotIn("\x1b", rec.proc.stderr)

    def test_the_file_is_never_deleted(self):
        for n, xml in enumerate([junit_xml(case("t", "a")), "not xml", BOMB]):
            with self.subTest(n):
                junit = f"keep{n}.xml"
                self.run_cmd(xml=xml, junit=junit, out=f"keep{n}.jsonl")
                self.assertEqual((self.work / junit).read_text(), xml)


class UsageErrors(RecordJunitCase):
    def assertUsage(self, rec: Recorded, why: str, ran: bool = False):
        self.assertEqual(rec.exit, 2, rec.proc.stderr)
        self.assertIn(why, rec.proc.stderr)
        self.assertIsNone(rec.header)
        self.assertEqual(rec.ran, ran)

    def test_no_command(self):
        self.assertUsage(self.run_cmd(child=[]), "no command after --")

    def test_no_double_dash_at_all(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "record-junit", "--junit", "j.xml", "--out", "o", "--repo", "demo"],
                              cwd=self.work, env=self.env(), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no command", proc.stderr)

    def test_command_not_found(self):
        self.assertUsage(self.run_cmd(child=["no-such-command-here"]), "command not found")

    def test_out_directory_missing(self):
        self.assertUsage(self.run_cmd(xml=junit_xml(), out="no/such/out.jsonl"), "output directory does not exist")

    def test_out_is_a_directory(self):
        (self.work / "adir").mkdir()
        self.assertUsage(self.run_cmd(xml=junit_xml(), out="adir"), "is a directory")

    def test_junit_file_already_exists(self):
        (self.work / "junit.xml").write_text(junit_xml(case("t", "stale")))
        rec = self.run_cmd(xml=junit_xml(case("t", "fresh")))
        self.assertUsage(rec, "already exists")
        self.assertIn("earlier run", rec.proc.stderr)
        self.assertEqual((self.work / "junit.xml").read_text(), junit_xml(case("t", "stale")))

    def test_junit_directory_missing(self):
        self.assertUsage(self.run_cmd(xml=junit_xml(), junit="no/such/dir/junit.xml"), "junit directory does not exist")

    def test_junit_and_out_are_the_same_path(self):
        self.assertUsage(self.run_cmd(xml=junit_xml(), junit="same", out="same"), "same path")

    def test_bad_sha_and_missing_options_exit_2(self):
        bad = self.run_cmd(xml=junit_xml(), extra=["--sha", "XYZ"])
        self.assertUsage(bad, "40 lowercase hex")
        proc = subprocess.run([sys.executable, str(SCRIPT), "record-junit", "--out", "o", "--repo", "demo", "--", "true"],
                              cwd=self.work, env=self.env(), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


class RoundTrip(RecordJunitCase):
    """The record goes through the reader and the row gate that `ingest` uses."""

    MANIFEST = dict(v=1, repo="demo", github="acme/demo", run_id=7, run_attempt=1, workflow="ci", event="push",
                    head_sha="a" * 40, head_branch="main", default_branch="main", started="2026-11-20T10:00:00Z",
                    updated="2026-11-20T10:05:00Z", conclusion="success", fork=False)

    def booked(self, rec: Recorded):
        run = quality.parse_artifact(rec.out.read_bytes(), quality.Manifest(**self.MANIFEST))
        quality.gate(run)
        return run

    def test_a_passing_run(self):
        rec = self.run_cmd(xml=junit_xml(case("tests.test_a.TestK", "test_a"), case("tests.test_a.TestK", "test_b", child=SKIP)),
                           env=CI_ENV, extra=["--sha", SHA])
        run = self.booked(rec)
        self.assertEqual((len(run.tests), len(run.failing()), run.complete), (2, 0, True))
        self.assertEqual(run.verdict(), 0)

    def test_a_failing_run(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "a", child=FAIL), case("", "tests.test_broken", child=ERROR)), code=1, env=CI_ENV)
        run = self.booked(rec)
        self.assertEqual(len(run.failing()), 2)
        self.assertEqual(run.verdict(), 1)

    def test_a_run_with_a_shortened_id(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "m[" + "k" * 1400 + "]"), case("t", "ok")), env=CI_ENV)
        run = self.booked(rec)
        self.assertEqual([len(t[0]) for t in run.tests], [1000, 4])

    def test_an_incomplete_record_books_as_red(self):
        rec = self.run_cmd(child=[sys.executable, "-c", "pass"], env=CI_ENV)
        run = self.booked(rec)
        self.assertEqual((len(run.tests), run.complete), (0, False))
        self.assertEqual(run.verdict(), 1)

    def test_an_id_the_books_refuse_is_left_alone_and_ingest_rejects_the_file(self):
        rec = self.run_cmd(xml=junit_xml(case("t", "bad\x7fname")), env=CI_ENV)
        self.assertEqual(rec.rows[0]["id"], "t.bad\x7fname")
        with self.assertRaises(quality.Rejected):
            self.booked(rec)


if __name__ == "__main__":
    unittest.main()
