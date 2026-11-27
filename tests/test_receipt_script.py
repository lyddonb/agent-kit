"""Tests for bstack's receipt writer (plugins/bstack/skills/verify-work/scripts/receipt.py)."""
import importlib.util
import json
import re
import sys
import unittest

import receipt_helpers as h

spec = importlib.util.spec_from_file_location("receipt", h.RECEIPT_PY)
receipt = importlib.util.module_from_spec(spec)
sys.modules["receipt"] = receipt
spec.loader.exec_module(receipt)

REAL = h.real_ledger_available()
PROBE_FILES = {h.SPEC: h.SPEC_TEXT, "src.txt": "one\n"}


class VerdictRuleTest(unittest.TestCase):
    def test_three_way_rule(self):
        d = receipt.decide_verdict
        self.assertEqual(d(0, None, False), "VERIFIED")
        self.assertEqual(d(None, None, False), "VERIFIED")
        self.assertEqual(d(1, None, False), "NOT VERIFIED")
        self.assertEqual(d(2, "the UI half", True), "NOT VERIFIED")
        self.assertEqual(d(0, "the UI half", False), "INCONCLUSIVE")
        self.assertEqual(d(0, None, True), "INCONCLUSIVE")

    def test_an_exit_the_probe_marks_as_saying_nothing_is_inconclusive(self):
        d = receipt.decide_verdict
        self.assertEqual(d(2, None, False, inconclusive_exits={2}), "INCONCLUSIVE")
        self.assertEqual(d(2, "x", True, inconclusive_exits={2, 3}), "INCONCLUSIVE")
        self.assertEqual(d(1, None, False, inconclusive_exits={2}), "NOT VERIFIED", "an unlisted failure still fails")
        self.assertEqual(d(2, None, False), "NOT VERIFIED", "exit 2 is an ordinary failure unless the caller says so")
        self.assertEqual(d(0, None, False, inconclusive_exits={2}), "VERIFIED")


class ReceiptBase(unittest.TestCase):
    def setUp(self):
        self.tmp = h.tmpdir(self)
        self.repo = h.new_repo(self.tmp, PROBE_FILES)
        self.head = h.git(self.repo, "rev-parse", "HEAD")

    def receipt(self, bin_dir, probe, criterion="C8", spec_path=h.SPEC, extra=(), run_id="r1", cwd=None):
        cmd = [h.sys.executable, h.RECEIPT_PY, "--run", run_id, "--actor", h.ACTOR, "--spec", spec_path,
               "--criterion", criterion, *extra, "--", *probe]
        return h.run(cmd, cwd or self.repo, bin_dir)

    def ledger_file(self, run_id="r1"):
        return self.repo / ".audit/runs" / run_id / "ledger.jsonl"


class RefusalTest(ReceiptBase):
    """A refusal exits 2, says why on stderr, runs no probe and writes nothing. These run without agent-ledger 1.1.0."""

    def setUp(self):
        super().setUp()
        self.ok = h.stub_ledger_bin(self.tmp)
        self.ledger_file().parent.mkdir(parents=True)
        self.ledger_file().write_text("")
        h.commit(self.repo, "run folder")
        self.probe = ["sh", "-c", "touch ran.marker"]

    def assertRefused(self, done, fragment):
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(fragment, done.stderr)
        self.assertFalse((self.repo / "ran.marker").exists(), "the probe ran")
        self.assertFalse((self.repo / ".evidence").exists(), "evidence was written")
        self.assertEqual(self.ledger_file().read_text(), "")

    def test_missing_spec(self):
        self.assertRefused(self.receipt(self.ok, self.probe, spec_path="docs/phases/P9-none.md"), "spec file not found")

    def test_criterion_not_in_spec(self):
        self.assertRefused(self.receipt(self.ok, self.probe, criterion="C99"), "C99 is not a live item")

    def test_struck_item_is_not_a_criterion(self):
        self.assertRefused(self.receipt(self.ok, self.probe, criterion="C4"), "C4 is not a live item")

    def test_leading_zero_is_refused_even_when_the_spec_has_the_item(self):
        self.assertRefused(self.receipt(self.ok, self.probe, criterion="C08"), "no leading zero")

    def test_ledger_not_on_path(self):
        done = self.receipt(h.bare_bin(self.tmp), self.probe)
        self.assertRefused(done, "agent-ledger 1.1.0 or newer")
        self.assertIn("not on PATH", done.stderr)

    def test_ledger_without_receipts_command(self):
        done = self.receipt(h.stub_ledger_bin(self.tmp, receipts_rc=2), self.probe)
        self.assertRefused(done, "no `receipts` command")
        self.assertIn("1.1.0", done.stderr)

    def test_not_a_git_repo(self):
        plain = self.tmp / "plain"
        (plain / "docs/phases").mkdir(parents=True)
        (plain / h.SPEC).write_text(h.SPEC_TEXT)
        done = self.receipt(self.ok, self.probe, cwd=plain)
        self.assertEqual(done.returncode, 2)
        self.assertIn("not inside a git repo", done.stderr)
        self.assertFalse((plain / "ran.marker").exists())
        self.assertFalse((plain / ".evidence").exists())

    def test_unknown_run_is_refused_before_the_probe_runs(self):
        done = self.receipt(self.ok, self.probe, run_id="nope")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no ledger for run nope", done.stderr)
        self.assertFalse((self.repo / "ran.marker").exists())

    def test_empty_not_run_is_refused(self):
        self.assertRefused(self.receipt(self.ok, self.probe, extra=["--not-run", " "]), "--not-run needs text")

    def test_exit_0_cannot_be_marked_inconclusive(self):
        self.assertRefused(self.receipt(self.ok, self.probe, extra=["--inconclusive-exit", "0"]),
                           "--inconclusive-exit 0")

    def test_a_failing_ledger_append_is_shown_and_its_code_returned(self):
        done = self.receipt(h.stub_ledger_bin(self.tmp, append_rc=2), ["true"])
        self.assertEqual(done.returncode, 2)
        self.assertIn("stub: append refused", done.stderr)
        self.assertNotIn("VERIFIED", done.stdout)


class BookkeepingListTest(unittest.TestCase):
    def test_the_scripts_agree_on_which_files_are_records_not_source(self):
        found = [re.search(r"^BOOKKEEPING = \((.*?)\)", p.read_text(), re.M | re.S).group(1).split()
                 for p in (h.RECEIPT_PY, h.CHECK_PRODUCT_PY, h.DEBRIEF_PY)]
        self.assertEqual(found[0], found[1])
        self.assertEqual(found[0], found[2])
        self.assertIn('"ROADMAP.md",', found[0])


@unittest.skipUnless(REAL, "needs agent-ledger 1.1.0 (set AGENT_LEDGER_SRC to its src folder)")
class RealLedgerTest(ReceiptBase):
    def setUp(self):
        super().setUp()
        self.bin = h.real_ledger_bin(self.tmp)
        init = h.run(["ledger", "init", "demo", "--actor", h.ACTOR, "--date", "2026-11-16"], self.repo, self.bin)
        self.assertEqual(init.returncode, 0, init.stderr)
        self.run_id = "2026-11-16-demo"
        self.head = h.commit(self.repo, "ledger")

    def go(self, probe, **kw):
        kw.setdefault("run_id", self.run_id)
        return self.receipt(self.bin, probe, **kw)

    def entries(self):
        lines = (self.repo / ".audit/runs" / self.run_id / "ledger.jsonl").read_text().splitlines()
        return [json.loads(l) for l in lines]

    def last(self):
        e = self.entries()[-1]
        self.assertEqual(e["type"], "verification")
        return e

    def test_passing_probe_is_verified_and_lands_in_the_ledger(self):
        done = self.go(["sh", "-c", "echo out; echo err >&2"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines()[-1], "P2e-C8 VERIFIED (seq 2)")
        self.assertIn("out", done.stdout)
        entry = self.last()
        self.assertEqual(entry["summary"], "P2e-C8 VERIFIED")
        data = entry["data"]
        self.assertEqual(data["verdict"], "VERIFIED")
        r = data["receipt"]
        self.assertEqual(r["criterion"], "P2e-C8")
        self.assertEqual(r["spec"], h.SPEC)
        self.assertEqual(r["spec_sha256"], h.sha256_file(self.repo / h.SPEC))
        self.assertEqual(r["probe"], "sh -c 'echo out; echo err >&2'")
        self.assertEqual(r["commit"], self.head)
        self.assertEqual((r["exit"], r["dirty"]), (0, False))
        self.assertNotIn("not_run", r)
        shown = h.run(["ledger", "receipts", self.run_id], self.repo, self.bin)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("| P2e-C8 | VERIFIED |", shown.stdout)
        self.assertEqual(h.run(["ledger", "verify", f".audit/runs/{self.run_id}"], self.repo, self.bin).returncode, 0)

    def test_evidence_file_holds_the_combined_output_and_its_hash_is_in_the_entry(self):
        self.go(["sh", "-c", "echo out; echo err >&2"])
        path = self.repo / ".evidence" / self.run_id / "p2e-c8.txt"
        self.assertEqual(sorted(path.read_text().split()), ["err", "out"])
        pointer = f".evidence/{self.run_id}/p2e-c8.txt sha256:{h.sha256_file(path)}"
        self.assertEqual(self.last()["evidence"], [pointer, self.head])

    def test_failing_probe_is_not_verified_but_the_receipt_is_written(self):
        done = self.go(["sh", "-c", "echo broke; exit 3"])
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.splitlines()[-1], "P2e-C8 NOT VERIFIED (seq 2)")
        data = self.last()["data"]
        self.assertEqual((data["verdict"], data["receipt"]["exit"]), ("NOT VERIFIED", 3))

    def test_a_listed_exit_is_inconclusive_and_keeps_its_exit_code(self):
        done = self.go(["sh", "-c", "echo plugin did not load; exit 2"], extra=["--inconclusive-exit", "2"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines()[-1], "P2e-C8 INCONCLUSIVE (seq 2)")
        entry = self.last()
        self.assertEqual((entry["data"]["verdict"], entry["data"]["receipt"]["exit"]), ("INCONCLUSIVE", 2))
        self.assertIn("exit 2 says nothing", entry["why"])
        shown = h.run(["ledger", "receipts", self.run_id], self.repo, self.bin)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("| P2e-C8 | INCONCLUSIVE |", shown.stdout)
        self.assertEqual(h.run(["ledger", "verify", f".audit/runs/{self.run_id}"], self.repo, self.bin).returncode, 0)

    def test_an_exit_not_listed_stays_not_verified(self):
        self.go(["sh", "-c", "exit 1"], extra=["--inconclusive-exit", "2"])
        self.assertEqual(self.last()["data"]["verdict"], "NOT VERIFIED")
        self.go(["sh", "-c", "exit 2"])
        self.assertEqual(self.last()["data"]["verdict"], "NOT VERIFIED")

    def test_missing_probe_command_is_not_verified(self):
        done = self.go(["definitely-not-a-command-xyz"])
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.last()["data"]["verdict"], "NOT VERIFIED")

    def test_not_run_makes_a_passing_probe_inconclusive(self):
        self.go(["true"], extra=["--not-run", "the browser half"])
        data = self.last()["data"]
        self.assertEqual(data["verdict"], "INCONCLUSIVE")
        self.assertEqual(data["receipt"]["not_run"], "the browser half")

    def test_a_failing_probe_stays_not_verified_even_with_not_run(self):
        self.go(["false"], extra=["--not-run", "x"])
        self.assertEqual(self.last()["data"]["verdict"], "NOT VERIFIED")

    def test_tracked_change_makes_it_inconclusive_and_dirty(self):
        (self.repo / "src.txt").write_text("edited\n")
        self.go(["true"])
        data = self.last()["data"]
        self.assertEqual((data["verdict"], data["receipt"]["dirty"]), ("INCONCLUSIVE", True))

    def test_a_probe_that_edits_a_tracked_file_makes_it_inconclusive(self):
        self.go(["sh", "-c", "echo changed > src.txt"])
        self.assertEqual(self.last()["data"]["verdict"], "INCONCLUSIVE")

    def test_dirt_under_audit_and_a_ticked_box_does_not_count(self):
        (self.repo / h.SPEC).write_text(h.SPEC_TEXT.replace("- [ ] **C8.**", "- [x] **C8.**"))
        self.go(["true"], criterion="C9")
        self.assertEqual(self.last()["data"]["verdict"], "VERIFIED")
        self.go(["true"])  # the first append left tracked .audit changes, which don't count either
        data = self.last()["data"]
        self.assertEqual((data["verdict"], data["receipt"]["dirty"]), ("VERIFIED", False))

    def test_an_untracked_file_present_before_the_probe_makes_it_inconclusive(self):
        (self.repo / "extra.txt").write_text("two\n")  # in no commit, yet the probe below passes because of it
        self.go(["grep", "-q", "two", "extra.txt"])
        data = self.last()["data"]
        self.assertEqual((data["verdict"], data["receipt"]["dirty"]), ("INCONCLUSIVE", True))

    def test_a_file_the_probe_itself_leaves_behind_does_not_count(self):
        self.go(["sh", "-c", "echo cache > probe-output.tmp"])
        self.assertEqual(self.last()["data"]["verdict"], "VERIFIED")

    def test_updating_the_roadmap_before_the_probe_does_not_count(self):
        (self.repo / "ROADMAP.md").write_text("| P2e | Building |\n")
        h.commit(self.repo, "a roadmap")
        (self.repo / "ROADMAP.md").write_text("| P2e | Gated |\n")
        self.go(["true"])
        self.assertEqual(self.last()["data"]["verdict"], "VERIFIED")

    def test_two_criteria_ticked_one_after_the_other_both_hash_the_committed_spec(self):
        committed = h.sha256_file(self.repo / h.SPEC)
        self.go(["true"])
        (self.repo / h.SPEC).write_text(h.SPEC_TEXT.replace("- [ ] **C8.**", "- [x] **C8.**"))
        self.go(["true"], criterion="C9")
        self.assertEqual([e["data"]["receipt"]["spec_sha256"] for e in self.entries()[-2:]], [committed, committed])

    def test_a_criterion_that_is_not_committed_yet_is_refused(self):
        before = len(self.entries())
        (self.repo / h.SPEC).write_text(h.SPEC_TEXT + "\n- [ ] **C12.** New and uncommitted. Probe: `true`.\n")
        done = self.go(["true"], criterion="C12")
        self.assertEqual(done.returncode, 2)
        self.assertIn("must be committed first", done.stderr)
        self.assertEqual(len(self.entries()), before)

    def test_evidence_folder_that_cannot_be_made_is_refused_before_the_probe_runs(self):
        (self.repo / ".evidence").write_text("a file where the folder should be\n")
        before = len(self.entries())
        done = self.go(["sh", "-c", "echo ran > probe-ran.txt"])
        self.assertEqual(done.returncode, 2)
        self.assertNotIn("Traceback", done.stderr)
        self.assertFalse((self.repo / "probe-ran.txt").exists())
        self.assertEqual(len(self.entries()), before)

    def test_an_uncommitted_edit_to_another_phase_spec_does_not_count(self):
        other = self.repo / "docs/phases/P3-other.md"
        other.write_text("# P3\n")
        h.commit(self.repo, "a second phase spec")
        other.write_text("# P3\n\n- [x] **C1.** ticked in the same PR\n")
        self.go(["true"])
        data = self.last()["data"]
        self.assertEqual((data["verdict"], data["receipt"]["dirty"]), ("VERIFIED", False))

    def test_root_flag_runs_the_probe_at_that_root(self):
        done = self.go(["sh", "-c", "pwd"], extra=["--root", str(self.repo)], cwd=self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(str(self.repo), done.stdout)
        self.assertEqual(self.last()["data"]["receipt"]["criterion"], "P2e-C8")


CHECKLIST = ".agents/checklist.json"


def checklist_text(*items):
    return json.dumps({"version": 1, "items": [
        {"id": i, "trigger": {"paths": ["**"]}, "check": check, "source": "made up",
         "added": "2026-11-01", "review_by": "2027-02-01"} for i, check in items]})


ITEMS = checklist_text(("passes", {"command": "echo checked; test -f src.txt"}),
                       ("fails", {"command": "echo broken >&2; exit 3"}),
                       ("asks", {"question": "Does it work signed out?", "probe": "Run it with no login."}))


class ItemBase(ReceiptBase):
    def setUp(self):
        self.tmp = h.tmpdir(self)
        self.repo = h.new_repo(self.tmp, {**PROBE_FILES, CHECKLIST: ITEMS})

    def item(self, bin_dir, item_id, probe=(), extra=(), run_id="r1"):
        cmd = [h.sys.executable, h.RECEIPT_PY, "--run", run_id, "--actor", h.ACTOR, "--item", item_id, *extra]
        return h.run(cmd + (["--", *probe] if probe else []), self.repo, bin_dir)


class ItemRefusalTest(ItemBase):
    """A refused checklist item exits 2, runs nothing and writes nothing. These run without agent-ledger."""

    def setUp(self):
        super().setUp()
        self.ok = h.stub_ledger_bin(self.tmp)
        self.ledger_file().parent.mkdir(parents=True)
        self.ledger_file().write_text("")
        h.commit(self.repo, "run folder")

    def assertRefused(self, done, fragment):
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(fragment, done.stderr)
        self.assertFalse((self.repo / "ran.marker").exists(), "the probe ran")
        self.assertFalse((self.repo / ".evidence").exists(), "evidence was written")
        self.assertEqual(self.ledger_file().read_text(), "")

    def test_an_unknown_item_names_the_ones_the_file_has(self):
        self.assertRefused(self.item(self.ok, "nope"), "'nope' is not an item in .agents/checklist.json at HEAD (it has: passes, fails, asks)")

    def test_a_command_item_takes_no_command_of_the_callers(self):
        self.assertRefused(self.item(self.ok, "passes", ["sh", "-c", "touch ran.marker"]),
                           "it runs as the checklist states it")

    def test_a_question_item_needs_a_command(self):
        self.assertRefused(self.item(self.ok, "asks"), "put the command that answers its probe after `--`")

    def test_an_item_that_is_only_in_the_working_tree_is_refused(self):
        (self.repo / CHECKLIST).write_text(checklist_text(("new", {"command": "touch ran.marker"})))
        self.assertRefused(self.item(self.ok, "new"), "'new' is not an item")

    def test_a_checklist_that_is_not_committed_is_refused(self):
        h.git(self.repo, "rm", "-q", CHECKLIST)
        h.commit(self.repo, "no checklist")
        self.assertRefused(self.item(self.ok, "passes"), "is not committed")

    def test_a_committed_checklist_that_breaks_the_format_is_refused(self):
        (self.repo / CHECKLIST).write_text('{"version": 1, "items": [{"id": "x"}]}')
        h.commit(self.repo, "broken checklist")
        self.assertRefused(self.item(self.ok, "x"), "the checklist at HEAD is not usable")

    def test_item_and_criterion_together_are_refused(self):
        self.assertRefused(self.item(self.ok, "passes", extra=["--spec", h.SPEC, "--criterion", "C8"]),
                           "either --item, or --spec with --criterion")

    def test_neither_item_nor_criterion_is_refused(self):
        done = h.run([h.sys.executable, h.RECEIPT_PY, "--run", "r1", "--actor", h.ACTOR, "--", "true"], self.repo, self.ok)
        self.assertRefused(done, "give --spec with --criterion, or --item")

    def test_checklist_without_item_is_refused(self):
        done = h.run([h.sys.executable, h.RECEIPT_PY, "--run", "r1", "--actor", h.ACTOR, "--spec", h.SPEC,
                      "--criterion", "C8", "--checklist", CHECKLIST, "--", "true"], self.repo, self.ok)
        self.assertRefused(done, "--checklist goes with --item")

    def test_an_unknown_run_is_refused_before_the_command_runs(self):
        (self.repo / CHECKLIST).write_text(checklist_text(("marks", {"command": "touch ran.marker"})))
        h.commit(self.repo, "an item that leaves a mark")
        done = self.item(self.ok, "marks", run_id="other")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no ledger for run other", done.stderr)
        self.assertFalse((self.repo / "ran.marker").exists(), "the command ran")


@unittest.skipUnless(REAL, "needs agent-ledger 1.1.0 (set AGENT_LEDGER_SRC to its src folder)")
class ItemRealLedgerTest(ItemBase):
    def setUp(self):
        super().setUp()
        self.bin = h.real_ledger_bin(self.tmp)
        init = h.run(["ledger", "init", "demo", "--actor", h.ACTOR, "--date", "2026-11-16"], self.repo, self.bin)
        self.assertEqual(init.returncode, 0, init.stderr)
        self.run_id = "2026-11-16-demo"
        self.head = h.commit(self.repo, "ledger")

    def go(self, item_id, probe=(), extra=()):
        return self.item(self.bin, item_id, probe, extra, run_id=self.run_id)

    def last(self):
        lines = (self.repo / ".audit/runs" / self.run_id / "ledger.jsonl").read_text().splitlines()
        entry = json.loads(lines[-1])
        self.assertEqual(entry["type"], "verification")
        return entry

    def test_a_command_item_runs_its_own_command_and_the_exit_code_is_the_verdict(self):
        done = self.go("passes")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines()[-1], "checklist:passes VERIFIED (seq 2)")
        entry = self.last()
        self.assertEqual(entry["summary"], "checklist:passes VERIFIED")
        data = entry["data"]
        self.assertEqual(data["verdict"], "VERIFIED")
        self.assertNotIn("receipt", data)
        self.assertEqual(data["checklist"], {
            "item": "passes", "file": CHECKLIST, "file_sha256": h.sha256_file(self.repo / CHECKLIST),
            "probe": "sh -c 'echo checked; test -f src.txt'", "commit": self.head, "exit": 0, "dirty": False})
        self.assertEqual((self.repo / ".evidence" / self.run_id / "checklist-passes.txt").read_text(), "checked\n")

    def test_the_ledger_still_verifies_and_the_item_is_not_a_spec_receipt(self):
        self.go("passes")
        self.assertEqual(h.run(["ledger", "verify", f".audit/runs/{self.run_id}"], self.repo, self.bin).returncode, 0)
        shown = h.run(["ledger", "receipts", self.run_id], self.repo, self.bin)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertNotIn("passes", shown.stdout + shown.stderr)

    def test_a_failing_command_item_is_not_verified(self):
        done = self.go("fails")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines()[-1], "checklist:fails NOT VERIFIED (seq 2)")
        self.assertEqual(self.last()["data"]["checklist"]["exit"], 3)

    def test_a_question_item_records_the_command_that_answered_it(self):
        done = self.go("asks", ["sh", "-c", "exit 0"])
        self.assertEqual(done.stdout.splitlines()[-1], "checklist:asks VERIFIED (seq 2)")
        self.assertEqual(self.last()["data"]["checklist"]["probe"], "sh -c 'exit 0'")

    def test_not_run_and_a_dirty_tree_make_it_inconclusive(self):
        self.assertEqual(self.go("asks", ["true"], ["--not-run", "the signed-out half"]).stdout.splitlines()[-1],
                         "checklist:asks INCONCLUSIVE (seq 2)")
        self.assertEqual(self.last()["data"]["checklist"]["not_run"], "the signed-out half")
        (self.repo / "src.txt").write_text("two\n")
        self.assertEqual(self.go("passes").stdout.splitlines()[-1], "checklist:passes INCONCLUSIVE (seq 3)")
        self.assertTrue(self.last()["data"]["checklist"]["dirty"])

    def test_a_listed_exit_makes_a_failing_item_inconclusive(self):
        done = self.go("fails", extra=["--inconclusive-exit", "3"])
        self.assertEqual(done.stdout.splitlines()[-1], "checklist:fails INCONCLUSIVE (seq 2)")
        self.assertEqual(self.last()["data"]["checklist"]["exit"], 3)

    def test_the_command_run_is_the_committed_one_not_an_uncommitted_edit(self):
        (self.repo / CHECKLIST).write_text(ITEMS.replace("echo broken >&2; exit 3", "exit 0"))
        done = self.go("fails")
        self.assertEqual(self.last()["data"]["checklist"]["exit"], 3)
        self.assertIn("NOT VERIFIED", done.stdout)


if __name__ == "__main__":
    unittest.main()
