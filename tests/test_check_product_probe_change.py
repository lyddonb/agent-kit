"""Tests for `check-product.py --base REF`: a box checked in the diff that wrote its probe (R29 unit 2)."""
import sys
import unittest

import receipt_helpers as h
from test_check_product_receipts import RUN, SPEC, ReceiptsBase, receipt_entry

C1 = "- [ ] **C1.** filled Probe: filled."
EASIER = "- [ ] **C1.** filled Probe: `true`."
CONFIRMED = "\n  **Confirmed.** Beau, 2026-11-26, in review: `true` is the probe he wants."


class ProbeChangeTest(ReceiptsBase):
    def setUp(self):
        super().setUp()
        self.assertIn(C1, self.base_spec, "the fixture's C1 line is the one these tests rewrite")

    def base_check(self, base=None):
        args = [sys.executable, h.CHECK_PRODUCT_PY, str(self.repo), "--base", base or self.base]
        return h.run(args, self.repo, self.bin)

    def branch(self, spec_text, message="the branch"):
        self.write_spec(spec_text)
        return h.commit(self.repo, message)

    def observed(self, done):
        self.assertEqual(done.returncode, 0, f"observe mode never fails the run:\n{done.stdout}{done.stderr}")
        return [l for l in done.stderr.splitlines() if l.startswith("observe: ")]

    def test_a_probe_rewritten_in_the_diff_that_checks_its_box_is_reported(self):
        self.branch(self.tick(self.base_spec.replace(C1, EASIER)))
        done = self.base_check()
        lines = self.observed(done)
        self.assertEqual(len(lines), 1, done.stderr)
        self.assertIn(f"{SPEC}:", lines[0])
        self.assertIn("P1-C1's Probe: changed in the diff that checks it", lines[0])
        self.assertIn("1 self-judged probe(s) observed", done.stdout)

    def test_a_new_confirmed_line_on_the_item_passes_it(self):
        self.branch(self.tick(self.base_spec.replace(C1, EASIER + CONFIRMED)))
        done = self.base_check()
        self.assertEqual(self.observed(done), [], done.stderr)
        self.assertNotIn("self-judged", done.stdout)

    def test_a_confirmed_line_already_there_at_base_does_not_cover_a_new_probe(self):
        self.base = self.branch(self.base_spec.replace(C1, C1 + CONFIRMED), "an earlier probe change, confirmed")
        confirmed = (self.repo / SPEC).read_text()
        self.branch(self.tick(confirmed.replace(C1, EASIER)))
        self.assertEqual(len(self.observed(self.base_check())), 1)

    def test_the_ideal_states_confirmed_line_does_not_count(self):
        spec = self.tick(self.base_spec.replace(C1, EASIER))
        self.assertIn("**Confirmed.**", spec, "the fixture's ideal state has a Confirmed line")
        self.branch(spec.replace("**Confirmed.**", "**Confirmed.** Again,", 1))
        self.assertEqual(len(self.observed(self.base_check())), 1)

    def test_a_reworded_claim_with_the_same_probe_is_not_reported(self):
        self.branch(self.tick(self.base_spec.replace(C1, "- [ ] **C1.** filled, reworded Probe: filled.")))
        self.assertEqual(self.observed(self.base_check()), [])

    def test_a_checked_box_with_its_probe_unchanged_is_not_reported(self):
        self.branch(self.tick(self.base_spec))
        self.assertEqual(self.observed(self.base_check()), [])

    def test_a_rewritten_probe_left_unchecked_is_not_reported(self):
        self.branch(self.base_spec.replace(C1, EASIER))
        self.assertEqual(self.observed(self.base_check()), [])

    def test_a_criterion_new_in_the_diff_and_checked_in_it_is_reported(self):
        self.branch(self.tick(self.base_spec.replace(C1, C1 + "\n- [ ] **C9.** new Probe: `true`."), ids=("C9",)))
        lines = self.observed(self.base_check())
        self.assertEqual(len(lines), 1)
        self.assertIn("P1-C9 is new in this diff and checked in it", lines[0])

    def test_renaming_the_spec_still_compares_against_its_phase(self):
        h.git(self.repo, "mv", SPEC, "docs/phases/P1-renamed.md")
        (self.repo / "docs/phases/P1-renamed.md").write_text(self.tick(self.base_spec.replace(C1, EASIER)))
        h.commit(self.repo, "rename and rewrite")
        lines = self.observed(self.base_check())
        self.assertEqual(len(lines), 1)
        self.assertIn("docs/phases/P1-renamed.md:", lines[0])

    def test_with_receipts_it_reports_too_and_a_later_confirmation_keeps_the_receipt(self):
        easier = self.base_spec.replace(C1, EASIER)
        rewrite = self.branch(easier, "rewrite C1's probe")
        self.write_ledger(receipt_entry("P1-C1", rewrite, easier))
        self.branch(self.tick(easier), "tick C1")
        done = self.check()
        self.assertEqual(len(self.observed(done)), 1, done.stderr)
        self.assertIn("receipts: 1 newly checked, 1 backed", done.stdout)
        self.branch(self.tick(easier.replace(EASIER, EASIER + CONFIRMED)), "Beau confirms the probe")
        done = self.check()
        self.assertEqual(self.observed(done), [], done.stderr)
        self.assertIn("receipts: 1 newly checked, 1 backed", done.stdout)

    def test_a_confirmation_written_before_the_evidence_keeps_the_receipt(self):
        easier = self.base_spec.replace(C1, EASIER)
        rewrite = self.branch(easier, "rewrite C1's probe")
        self.write_ledger(receipt_entry("P1-C1", rewrite, easier))
        inline = EASIER + " **Confirmed.** Beau, 2026-11-26."
        self.branch(self.tick(easier.replace(EASIER, inline)), "confirm on the item's line, then tick")
        line = next(l for l in (self.repo / SPEC).read_text().splitlines() if "**C1.**" in l)
        self.assertLess(line.index("**Confirmed.**"), line.index("Evidence:"), "the fixture puts it before Evidence")
        done = self.check()
        self.assertEqual(self.observed(done), [], done.stderr)
        self.assertIn("receipts: 1 newly checked, 1 backed", done.stdout)

    def test_without_a_base_nothing_is_compared(self):
        self.branch(self.tick(self.base_spec.replace(C1, EASIER)))
        done = self.check(receipts=None)
        self.assertEqual(self.observed(done), [])

    def test_a_missing_base_ref_exits_2(self):
        done = self.base_check("no-such-ref")
        self.assertEqual(done.returncode, 2)
        self.assertIn("base ref no-such-ref does not exist", done.stderr)

    def test_outside_a_git_repo_exits_2(self):
        h.git(self.repo, "init", "-q")
        (self.repo / ".git").rename(self.repo / "not-git")
        done = h.run([sys.executable, h.CHECK_PRODUCT_PY, str(self.repo), "--base", "main"], self.tmp, self.bin)
        self.assertEqual(done.returncode, 2)
        self.assertIn("not inside a git repo", done.stderr)


if __name__ == "__main__":
    unittest.main()
