"""Tests for bstack's root-cause case CLI (plugins/bstack/skills/root-cause/scripts/rootcause.py)."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/root-cause/scripts/rootcause.py"

spec = importlib.util.spec_from_file_location("rootcause", SCRIPT)
rootcause = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rootcause  # dataclasses look their module up here
spec.loader.exec_module(rootcause)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.run_ok("new", "c", "--symptom", "p99 3x with the flag on", "--control", "flag off, same hosts")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rootcause.main(["--dir", self.dir, *args])
        return code, out.getvalue(), err.getvalue()

    def run_ok(self, *args):
        code, out, err = self.cli(*args)
        self.assertEqual(code, 0, f"{args} exited {code}: {err}")
        return out

    def refused(self, *args, fragment=""):
        code, _, err = self.cli(*args)
        self.assertEqual(code, 1, f"{args} was not refused")
        self.assertIn(fragment, err)
        return err

    def state(self):
        return json.loads(self.run_ok("next", "c", "--json"))

    def fact(self, text, seen="variable", **kw):
        args = ["fact", "c", text, "--source", kw.get("source", "metric"), "--cite", "q", "--seen", seen]
        if "layer" in kw:
            args += ["--layer", str(kw["layer"])]
        if "check" in kw:
            args += ["--check", kw["check"]]
        return self.run_ok(*args).split()[0]

    def mark(self, h, f, verdict="explains"):
        self.run_ok("mark", "c", h, f, verdict, "--why", "evidence")

    def falls_short(self):
        """Two signals, one hypothesis that explains only the first."""
        self.fact("p99 up")
        self.fact("handshakes up")
        self.run_ok("hypo", "c", "a lock serializes requests")
        self.mark("H1", "F1")
        self.mark("H1", "F2", "neutral")


class StepTest(Case):
    def test_no_signal_means_gather(self):
        self.fact("GC unchanged", seen="both")
        self.assertEqual(self.state()["step"], "gather")

    def test_first_hypothesis_then_matrix(self):
        self.fact("p99 up")
        self.assertEqual(self.state()["step"], "hypothesize")
        self.run_ok("hypo", "c", "lock contention")
        st = self.state()
        self.assertEqual(st["step"], "matrix")
        self.assertEqual(st["unmarked"], ["H1xF1"])

    def test_noise_is_validated_after_signals(self):
        self.fact("p99 up")
        self.fact("GC unchanged", seen="both")
        self.run_ok("hypo", "c", "lock contention")
        self.mark("H1", "F1")
        self.assertEqual(self.state()["step"], "validate")

    def test_root_cause_needs_a_fresh_passing_review(self):
        self.fact("p99 up")
        self.run_ok("hypo", "c", "new connection per request")
        self.mark("H1", "F1")
        self.assertEqual(self.state()["step"], "review")
        self.refused("report", "c", fragment="no root cause yet")
        self.run_ok("review", "c", "validation", "--verdict", "fail", "--by", "m2", "--note", "check F1's window")
        self.assertEqual(self.state()["step"], "review")
        self.run_ok("review", "c", "validation", "--verdict", "pass", "--by", "m2")
        st = self.state()
        self.assertEqual((st["step"], st["root_cause"]), ("root-cause", "H1"))
        self.fact("GC unchanged", seen="both")
        self.mark("H1", "F2", "neutral")
        self.assertEqual(self.state()["step"], "review", "a review older than the last change must not count")

    def test_contradiction_discards(self):
        self.fact("p99 up")
        self.run_ok("hypo", "c", "lock contention")
        self.mark("H1", "F1", "contradicts")
        st = self.state()
        self.assertEqual(st["discarded"], {"H1": "F1"})
        self.assertEqual(st["step"], "tactics")

    def test_several_survive_wants_facts_not_hypotheses(self):
        self.fact("p99 up")
        self.run_ok("hypo", "c", "lock contention")
        self.run_ok("hypo", "c", "connection per request")
        self.mark("H1", "F1")
        self.mark("H2", "F1")
        st = self.state()
        self.assertEqual((st["step"], st["satisfied"]), ("gather", ["H1", "H2"]))
        self.refused("hypo", "c", "DNS", fragment="needs facts, not hypotheses")
        self.fact("handshakes up")
        self.mark("H1", "F2", "neutral")
        self.mark("H2", "F2")
        self.assertEqual(self.state()["satisfied"], ["H2"])


class TacticsTest(Case):
    def test_new_hypothesis_waits_for_tactics_one_to_four(self):
        self.falls_short()
        self.assertEqual(self.state()["next_tactic"], "reverify")
        self.refused("hypo", "c", "DNS is slow", fragment="tactic 'reverify' hasn't run")
        for t in ("reverify", "split", "merge", "combine"):
            self.run_ok("tactic", "c", t, "--note", "nothing to do")
        self.assertEqual(self.state()["next_tactic"], "new")
        self.run_ok("hypo", "c", "DNS is slow")
        self.mark("H2", "F1")
        self.mark("H2", "F2", "neutral")
        st = self.state()
        self.assertEqual(st["step"], "discover")
        self.assertIn("layer 1", st["do"])

    def test_a_new_fact_restarts_the_tactics(self):
        self.falls_short()
        self.run_ok("tactic", "c", "reverify", "--note", "ok")
        self.assertEqual(self.state()["next_tactic"], "split")
        self.fact("timeouts in the client log", layer=1)
        self.mark("H1", "F3", "neutral")
        self.assertEqual(self.state()["next_tactic"], "reverify")

    def test_initial_hypotheses_do_not_spend_tactic_five(self):
        self.fact("p99 up")
        self.run_ok("hypo", "c", "lock")
        self.run_ok("hypo", "c", "pool size")
        self.mark("H1", "F1", "neutral")
        self.mark("H2", "F1", "neutral")
        for t in ("reverify", "split", "merge", "combine"):
            self.run_ok("tactic", "c", t, "--note", "n/a")
        self.assertEqual(self.state()["next_tactic"], "new")

    def test_split_into_several_children_retires_the_parent(self):
        self.falls_short()
        self.run_ok("hypo", "c", "DNS per connection", "--tactic", "split", "--from", "H1")
        self.run_ok("hypo", "c", "TLS per connection", "--tactic", "split", "--from", "H1")
        st = self.state()
        self.assertEqual(st["retired"], {"H1": "split into H2, H3"})
        self.refused("mark", "c", "H1", "F1", "explains", "--why", "x", fragment="mark its successor")

    def test_merge_needs_two_and_retires_both(self):
        self.fact("p99 up")
        self.run_ok("hypo", "c", "a")
        self.run_ok("hypo", "c", "b")
        self.refused("hypo", "c", "ab", "--tactic", "merge", "--from", "H1", fragment="two or more")
        self.run_ok("hypo", "c", "ab", "--tactic", "merge", "--from", "H1,H2")
        self.assertEqual(set(self.state()["retired"]), {"H1", "H2"})

    def test_retracted_fact_leaves_the_matrix(self):
        self.falls_short()
        self.run_ok("retract", "c", "F2", "--why", "query used the wrong window")
        st = self.state()
        self.assertEqual(st["step"], "review")
        self.refused("mark", "c", "H1", "F2", "explains", "--why", "x", fragment="retracted")


class StrengthTest(Case):
    def test_few_fits_is_strong_most_is_weak(self):
        self.fact("rare")
        self.fact("common")
        for name in ("a", "b", "c"):
            self.run_ok("hypo", "c", name)
        self.mark("H1", "F1")
        self.mark("H2", "F1", "neutral")
        self.mark("H3", "F1", "neutral")
        for h in ("H1", "H2", "H3"):
            self.mark(h, "F2")
        strength = {s["fact"]: s["strength"] for s in self.state()["signals"]}
        self.assertEqual(strength, {"F1": "strong", "F2": "weak"})
        self.assertEqual(self.state()["strongest"], {"fact": "F1", "points_to": ["H1"]})


class ReportAndRecheckTest(Case):
    def solved(self):
        self.fact("p99 up", check="true")
        self.fact("GC unchanged", seen="both", check="true")
        self.run_ok("hypo", "c", "lock")
        self.run_ok("hypo", "c", "connection per request")
        self.fact("no mutex time", seen="both")
        self.mark("H1", "F1")
        self.mark("H1", "F3", "contradicts")
        for f, v in (("F1", "explains"), ("F2", "neutral"), ("F3", "neutral")):
            self.mark("H2", f, v)
        self.run_ok("gap", "c", "no access to resolver metrics", "--layer", "2")
        self.run_ok("review", "c", "validation", "--verdict", "pass", "--by", "m2")

    def test_report_has_evidence_ruled_out_and_gaps(self):
        self.solved()
        text = self.run_ok("report", "c")
        self.assertIn("**Root cause (H2).** connection per request", text)
        self.assertIn("| H1: lock | F3 | evidence |", text)
        self.assertIn("layer 2: no access to resolver metrics", text)
        self.assertIn("`true`", text)

    def test_recheck_fails_while_a_bug_signal_holds(self):
        self.solved()
        self.refused("recheck", "c", fragment="F1 (a bug-only signal) still holds")
        self.run_ok("recheck", "c", "--expect", "present")

    def test_recheck_passes_when_the_signal_is_gone(self):
        self.fact("p99 up", check="false")
        self.run_ok("recheck", "c")
        self.refused("recheck", "c", "--expect", "present", fragment="F1 no longer reproduces")


class InputTest(Case):
    def test_rejects_bad_names_and_text(self):
        self.refused("new", "Bad Name", "--symptom", "s", "--control", "c", fragment="lowercase")
        self.refused("new", "c", "--symptom", "s", "--control", "c", fragment="already exists")
        self.refused("fact", "c", "x\x1b[2J", "--source", "log", "--cite", "q", "--seen", "both",
                     fragment="control characters")
        self.refused("mark", "c", "H9", "F1", "explains", "--why", "x", fragment="no hypothesis")

    def test_history_is_append_only(self):
        self.fact("p99 up")
        lines = (Path(self.dir) / "c.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(line)["type"] for line in lines], ["new", "fact"])


if __name__ == "__main__":
    unittest.main()
