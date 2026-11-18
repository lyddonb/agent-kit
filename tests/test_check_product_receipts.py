"""Tests for `check-product.py --receipts RUN_ID [--base REF]` (bstack's scaffold-product checker)."""
import hashlib
import json
import shutil
import sys
import unittest

import receipt_helpers as h
from test_check_product import filled_scaffold

REAL = h.real_ledger_available()
SPEC = "docs/phases/P1-first-slice.md"
RUN = "r1"


def receipt_entry(criterion, commit, spec_text, verdict="VERIFIED", spec=SPEC, sha=None, seq=2):
    return {"seq": seq, "type": "verification", "data": {"verdict": verdict, "receipt": {
        "criterion": criterion, "spec": spec, "spec_sha256": sha or hashlib.sha256(spec_text.encode()).hexdigest(),
        "probe": "./probe.sh", "commit": commit, "exit": 0, "dirty": False}}}


class ReceiptsBase(unittest.TestCase):
    """A product repo on `main`, one commit, whose C1 and A1 are unchecked, and a branch about to tick them."""

    def setUp(self):
        self.tmp = h.tmpdir(self)
        scaffold = filled_scaffold()
        self.addCleanup(shutil.rmtree, scaffold.parent, True)
        self.repo = self.tmp / "demo"
        shutil.copytree(scaffold, self.repo)
        (self.repo / "src.txt").write_text("one\n")
        for cmd in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
            h.git(self.repo, *cmd)
        self.base_spec = (self.repo / SPEC).read_text()
        self.base = h.commit(self.repo, "base")
        self.bin = h.stub_ledger_bin(self.tmp)

    def tick(self, text, ids=("C1",)):
        for i in ids:
            text = text.replace(f"- [ ] **{i}.**", f"- [x] **{i}.**")
            line = next(l for l in text.splitlines() if l.startswith(f"- [x] **{i}.**"))
            text = text.replace(line, line + " Evidence: ran it.")
        return text

    def write_spec(self, text):
        (self.repo / SPEC).write_text(text)

    def write_ledger(self, *entries, run=RUN):
        path = self.repo / ".audit/runs" / run / "ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def check(self, *extra, bin_dir=None, receipts=RUN):
        args = [sys.executable, h.CHECK_PRODUCT_PY, str(self.repo)]
        if receipts:
            args += ["--receipts", receipts]
            args += ["--base", self.base]
        return h.run(args + list(extra), self.repo, bin_dir or self.bin)

    def assertPasses(self, done, summary):
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(summary, done.stdout)

    def assertProblemFree(self, done, crit):
        """No problem line names crit; returns crit so a caller can chain on it."""
        self.assertFalse([l for l in done.stderr.splitlines() if crit in l], done.stderr)
        return crit

    def assertProblem(self, done, *fragments):
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        lines = [l for l in done.stderr.splitlines() if all(f in l for f in fragments)]
        self.assertTrue(lines, f"no problem line with {fragments} in:\n{done.stderr}")
        return lines[0]


class ReceiptChecksTest(ReceiptsBase):
    def ticked_with_receipt(self, **kw):
        ticked = self.tick(self.base_spec)
        self.write_ledger(receipt_entry("P1-C1", self.base, self.base_spec, **kw))
        self.write_spec(ticked)
        return ticked

    def test_newly_checked_box_with_a_current_receipt_passes(self):
        self.ticked_with_receipt()
        h.commit(self.repo, "tick C1")
        self.assertPasses(self.check(), "receipts: 1 newly checked, 1 backed")

    def test_later_commits_that_touch_only_audit_evidence_and_the_spec_keep_it_current(self):
        ticked = self.ticked_with_receipt()
        h.commit(self.repo, "tick C1")
        self.write_spec(ticked + "\nA note added later.\n")
        (self.repo / ".evidence").mkdir()
        (self.repo / ".evidence/c1.txt").write_text("output\n")
        self.write_ledger(receipt_entry("P1-C1", self.base, self.base_spec),
                          receipt_entry("P1-C1", self.base, self.base_spec, seq=3))
        h.commit(self.repo, "more ledger, evidence, spec text")
        self.assertPasses(self.check(), "receipts: 1 newly checked, 1 backed")

    def test_an_edit_to_another_phase_spec_does_not_make_it_stale(self):
        self.ticked_with_receipt()
        h.commit(self.repo, "tick C1")
        (self.repo / "docs/phases/P2-other.md").write_text((self.repo / SPEC).read_text().replace("P1", "P2"))
        h.commit(self.repo, "a second phase spec changes in the same branch")
        done = self.check()
        self.assertNotIn("stale", done.stderr)
        self.assertIn("P1-C1", self.assertProblemFree(done, "P1-C1"))

    def test_uncommitted_spec_and_ledger_edits_are_not_stale(self):
        self.ticked_with_receipt()
        self.assertPasses(self.check(), "receipts: 1 newly checked, 1 backed")

    def test_without_the_flag_nothing_changes(self):
        self.write_spec(self.tick(self.base_spec))
        h.commit(self.repo, "tick C1 with no receipt")
        done = self.check(receipts=None)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("receipts", done.stdout)

    def test_a_box_already_checked_at_base_needs_no_receipt(self):
        self.write_spec(self.tick(self.base_spec))
        self.base = h.commit(self.repo, "C1 checked on main")
        self.write_ledger()
        h.commit(self.repo, "branch work")
        self.assertPasses(self.check(), "receipts: 0 newly checked, 0 backed")

    def test_a_spec_that_is_new_on_the_branch_has_every_checked_box_new(self):
        new = self.base_spec.replace("# P1.", "# P1b.")
        (self.repo / "docs/phases/P1b-second.md").write_text(self.tick(new))
        h.commit(self.repo, "new spec")
        self.write_ledger()
        done = self.check()
        self.assertProblem(done, "docs/phases/P1b-second.md", "P1b-C1", "no receipt")

    def test_anti_criteria_need_receipts_too(self):
        self.write_spec(self.tick(self.base_spec, ids=("A1",)))
        h.commit(self.repo, "tick A1")
        self.write_ledger()
        self.assertProblem(self.check(), "P1-A1", "no receipt")

    def test_no_receipt(self):
        self.write_spec(self.tick(self.base_spec))
        h.commit(self.repo, "tick C1")
        self.write_ledger(receipt_entry("P1-C2", self.base, self.base_spec))
        line = self.assertProblem(self.check(), "P1-C1", "no receipt")
        self.assertTrue(line.startswith(f"{SPEC}:"), line)

    def test_last_receipt_not_verified_fails_and_says_what_it_is(self):
        ticked = self.tick(self.base_spec)
        self.write_ledger(receipt_entry("P1-C1", self.base, self.base_spec),
                          receipt_entry("P1-C1", self.base, self.base_spec, verdict="INCONCLUSIVE", seq=3))
        self.write_spec(ticked)
        h.commit(self.repo, "tick C1")
        self.assertProblem(self.check(), "P1-C1", "INCONCLUSIVE")

    def test_an_earlier_failure_is_superseded_by_a_later_verified_receipt(self):
        ticked = self.tick(self.base_spec)
        self.write_ledger(receipt_entry("P1-C1", self.base, self.base_spec, verdict="NOT VERIFIED"),
                          receipt_entry("P1-C1", self.base, self.base_spec, seq=3))
        self.write_spec(ticked)
        h.commit(self.repo, "tick C1")
        self.assertPasses(self.check(), "1 backed")

    def test_receipt_for_another_spec(self):
        self.ticked_with_receipt(spec="docs/phases/P9-other.md")
        h.commit(self.repo, "tick C1")
        self.assertProblem(self.check(), "P1-C1", "docs/phases/P9-other.md", "not docs/phases/P1-first-slice.md")

    def test_spec_hash_that_does_not_match_the_spec_at_the_receipt_commit(self):
        self.ticked_with_receipt(sha="0" * 64)
        h.commit(self.repo, "tick C1")
        self.assertProblem(self.check(), "P1-C1", "spec_sha256")

    def test_a_receipt_commit_this_clone_does_not_have_says_so(self):
        self.ticked_with_receipt()
        self.write_ledger(receipt_entry("P1-C1", "0" * 40, self.base_spec))
        h.commit(self.repo, "tick C1")
        self.assertProblem(self.check(), "P1-C1", "is not in this clone", "re-run its probe")

    def test_a_criterion_rewritten_after_its_receipt_is_not_backed(self):
        ticked = self.ticked_with_receipt()
        line = next(l for l in ticked.splitlines() if l.startswith("- [x] **C1.**"))
        self.write_spec(ticked.replace(line, "- [x] **C1.** Payments never double-charge. Probe: `./load-test.sh`. Evidence: ran it."))
        h.commit(self.repo, "tick C1 and change what it claims")
        self.assertProblem(self.check(), "P1-C1", "text or probe changed after its receipt")

    def test_updating_the_roadmap_and_other_records_does_not_make_it_stale(self):
        self.ticked_with_receipt()
        for rel in ("ROADMAP.md", "HUMAN_TASKS.md", "IDEAS.md", "docs/DECISIONS.md"):
            with (self.repo / rel).open("a") as f:
                f.write("\nA line the playbook adds with the tick.\n")
        h.commit(self.repo, "tick C1 and update the records")
        self.assertNotIn("stale", self.check().stderr)

    def test_renaming_a_spec_makes_no_box_newly_checked(self):
        self.write_spec(self.tick(self.base_spec))
        self.base = h.commit(self.repo, "C1 checked on main")
        self.write_ledger()
        h.git(self.repo, "mv", SPEC, "docs/phases/P1-renamed.md")
        h.commit(self.repo, "rename the spec")
        self.assertIn("receipts: 0 newly checked, 0 backed", self.check().stdout)

    def test_a_base_spec_that_is_not_utf8_is_read_without_a_traceback(self):
        (self.repo / SPEC).write_bytes(self.base_spec.encode() + b"\xff\xfe\n")
        self.base = h.commit(self.repo, "odd bytes on main")
        self.ticked_with_receipt()
        h.commit(self.repo, "tick C1")
        done = self.check()
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("receipts: 1 newly checked", done.stdout)

    def test_source_committed_after_the_probe_makes_it_stale(self):
        self.ticked_with_receipt()
        (self.repo / "src.txt").write_text("two\n")
        h.commit(self.repo, "tick C1 and change source")
        self.assertProblem(self.check(), "P1-C1", "stale", "source changed")

    def test_uncommitted_source_change_makes_it_stale(self):
        self.ticked_with_receipt()
        h.commit(self.repo, "tick C1")
        (self.repo / "src.txt").write_text("two\n")
        self.assertProblem(self.check(), "P1-C1", "stale", "uncommitted")

    def test_ledger_that_fails_verify_is_one_problem_and_stops_the_receipt_checks(self):
        self.write_spec(self.tick(self.base_spec))
        h.commit(self.repo, "tick C1 with no receipt")
        self.write_ledger()
        done = self.check(bin_dir=h.stub_ledger_bin(self.tmp, verify_rc=1))
        self.assertEqual(done.returncode, 1)
        self.assertIn("the run's ledger fails verify", done.stderr)
        self.assertNotIn("no receipt", done.stderr)

    def test_normal_problems_still_report_alongside(self):
        ticked = self.ticked_with_receipt()
        self.write_spec(ticked.replace("**Outcome.**", "Outcome:"))
        h.commit(self.repo, "tick C1, drop the outcome line")
        done = self.check()
        self.assertProblem(done, "no `**Outcome.**`")
        self.assertIn("receipts: 1 newly checked, 1 backed", done.stdout)


class ReceiptsUsageTest(ReceiptsBase):
    def test_ledger_not_on_path_exits_2(self):
        self.write_ledger()
        done = self.check(bin_dir=h.bare_bin(self.tmp))
        self.assertEqual(done.returncode, 2)
        self.assertIn("`ledger` is not on PATH", done.stderr)

    def test_missing_run_folder_exits_2(self):
        done = self.check(receipts="nope")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no ledger for run nope", done.stderr)

    def test_missing_base_ref_exits_2(self):
        self.write_ledger()
        done = h.run([sys.executable, h.CHECK_PRODUCT_PY, str(self.repo), "--receipts", RUN], self.repo, self.bin)
        self.assertEqual(done.returncode, 2)
        self.assertIn("base ref origin/main does not exist", done.stderr)

    def test_default_base_is_origin_main(self):
        self.write_ledger()
        h.git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        self.write_spec(self.tick(self.base_spec))
        h.commit(self.repo, "tick C1 with no receipt")
        done = h.run([sys.executable, h.CHECK_PRODUCT_PY, str(self.repo), "--receipts", RUN], self.repo, self.bin)
        self.assertProblem(done, "P1-C1", "no receipt")

    def test_base_without_receipts_is_a_usage_error(self):
        done = h.run([sys.executable, h.CHECK_PRODUCT_PY, str(self.repo), "--base", "main"], self.repo, self.bin)
        self.assertEqual(done.returncode, 2)
        self.assertIn("--base only goes with --receipts", done.stderr)


@unittest.skipUnless(REAL, "needs agent-ledger 1.1.0 (set AGENT_LEDGER_SRC to its src folder)")
class EndToEndTest(ReceiptsBase):
    def test_receipt_py_then_tick_then_check_then_source_change_goes_stale(self):
        bin_dir = h.real_ledger_bin(self.tmp)
        init = h.run(["ledger", "init", "demo", "--actor", h.ACTOR, "--date", "2026-11-16"], self.repo, bin_dir)
        self.assertEqual(init.returncode, 0, init.stderr)
        run_id = "2026-11-16-demo"
        h.commit(self.repo, "ledger")
        wrote = h.run([sys.executable, h.RECEIPT_PY, "--run", run_id, "--actor", h.ACTOR, "--spec", SPEC,
                       "--criterion", "C1", "--", "grep", "-q", "one", "src.txt"], self.repo, bin_dir)
        self.assertEqual(wrote.returncode, 0, wrote.stderr)
        self.assertIn("P1-C1 VERIFIED", wrote.stdout)
        self.write_spec(self.tick(self.base_spec))
        h.commit(self.repo, "tick C1, receipt and evidence")
        args = [sys.executable, h.CHECK_PRODUCT_PY, str(self.repo), "--receipts", run_id, "--base", self.base]
        ok = h.run(args, self.repo, bin_dir)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("receipts: 1 newly checked, 1 backed", ok.stdout)
        (self.repo / "src.txt").write_text("two\n")
        h.commit(self.repo, "change source")
        stale = h.run(args, self.repo, bin_dir)
        self.assertProblem(stale, "P1-C1", "stale")


if __name__ == "__main__":
    unittest.main()
