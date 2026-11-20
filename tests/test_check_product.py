"""Tests for bstack's scaffold-product checker (plugins/bstack/skills/scaffold-product/scripts/check-product.py)."""
import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "plugins/bstack/skills/scaffold-product"
spec = importlib.util.spec_from_file_location("check_product", SKILL / "scripts/check-product.py")
check_product = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_product)


def filled_scaffold() -> Path:
    """The templates copied and filled the way the skill tells an agent to."""
    repo = Path(tempfile.mkdtemp()) / "demo"
    shutil.copytree(SKILL / "references/templates", repo)
    (repo / "docs/phases/P1-SLUG.md").rename(repo / "docs/phases/P1-first-slice.md")
    for f in repo.rglob("*.md"):
        text = re.sub(r"\{\{app\}\}", "demo", f.read_text())
        text = re.sub(r"\{\{(G\d+)\}\}", r"\1", text)
        f.write_text(re.sub(r"\{\{[^}]*\}\}", "filled", text))
    (repo / ".agents/skills/verify-demo").mkdir(parents=True)
    (repo / ".agents/skills/verify-demo/SKILL.md").write_text("---\nname: verify-demo\n---\n")
    return repo


class CheckProductTest(unittest.TestCase):
    def setUp(self):
        self.repo = filled_scaffold()

    def problems(self):
        return check_product.check(self.repo)

    def edit(self, rel, old, new):
        path = self.repo / rel
        text = path.read_text()
        self.assertIn(old, text, f"fixture drifted: {old!r} not in {rel}")
        path.write_text(text.replace(old, new))

    def assertFlags(self, fragment):
        found = self.problems()
        self.assertTrue(any(fragment in p for p in found), f"expected a problem containing {fragment!r}, got {found}")

    def test_filled_templates_pass(self):
        self.assertEqual(self.problems(), [])

    def test_unfilled_placeholder_is_flagged(self):
        self.edit("docs/VISION.md", "## The problem\n\nfilled", "## The problem\n\n{{who has it}}")
        self.assertFlags("docs/VISION.md:5: unfilled template placeholder")

    def test_review_guide_placeholder_is_flagged_and_the_file_is_optional(self):
        self.edit("REVIEW.md", "- filled", "- {{where a bug costs the most}}")
        self.assertFlags("REVIEW.md:7: unfilled template placeholder")
        (self.repo / "REVIEW.md").unlink()
        self.assertEqual(self.problems(), [])

    def test_missing_file_is_flagged(self):
        (self.repo / "IDEAS.md").unlink()
        self.assertFlags("IDEAS.md: missing")

    def test_vision_needs_goal_ids(self):
        self.edit("docs/VISION.md", "| G1 |", "| Goal one |")
        self.assertFlags("no goals table")

    def test_decisions_are_numbered_in_order_with_a_status(self):
        path = self.repo / "docs/DECISIONS.md"
        path.write_text(path.read_text() + "\n### D3. Skipped a number\nno status here\n")
        found = self.problems()
        self.assertTrue(any("D3 follows D1" in p for p in found), found)
        self.assertTrue(any("D3 has no status line" in p for p in found), found)

    SPEC = "docs/phases/P1-first-slice.md"

    def test_phase_needs_outcome_and_checkable_criteria(self):
        self.edit(self.SPEC, "**Outcome.**", "Outcome:")
        self.edit(self.SPEC, "- [ ] **C1.** filled Probe: filled.", "- filled")
        self.edit(self.SPEC, "- [ ] **C2.**", "- **C2.**")
        found = self.problems()
        self.assertTrue(any("no `**Outcome.**`" in p for p in found), found)
        self.assertTrue(any("Criteria has no '- [ ] **C1.**' boxes" in p for p in found), found)

    def test_older_acceptance_format_points_at_the_upgrade(self):
        self.edit(self.SPEC, "## Criteria", "## Acceptance")
        found = self.problems()
        self.assertEqual(len(found), 1, found)
        self.assertIn("older spec format ('## Acceptance')", found[0])

    def test_ideal_state_needs_three_levels_and_a_confirmed_line(self):
        self.edit(self.SPEC, "3. **Surprising.** filled\n", "")
        self.edit(self.SPEC, "**Confirmed.** filled\n", "")
        found = self.problems()
        self.assertTrue(any("ideal state has no level **Surprising.**" in p for p in found), found)
        self.assertTrue(any("no `**Confirmed.**` line" in p for p in found), found)

    def test_missing_ideal_state_is_flagged(self):
        self.edit(self.SPEC, "## Ideal state", "## Hopes")
        self.assertFlags("no '## Ideal state' section")

    def test_unconfirmed_ideal_state_is_fine_while_specced(self):
        self.edit(self.SPEC, "**Confirmed.** filled", "**Confirmed.** Not yet.")
        self.assertEqual(self.problems(), [])

    def test_building_needs_a_person_to_confirm_the_ideal_state(self):
        for said in ("Not yet.", "Beau, 2026-11-16 (draft, from README)", ""):
            for status in ("Planned", "Building", "In progress", "Gated"):
                with self.subTest(said=said, status=status):
                    self.repo = filled_scaffold()
                    self.edit(self.SPEC, "**Confirmed.** filled", f"**Confirmed.** {said}".rstrip())
                    self.edit("ROADMAP.md", "| Specced |", f"| {status} |")
                    self.assertFlags(f"the phase is {status} but no person has confirmed levels 1 and 2")

    def test_confirmed_ideal_state_lets_building_pass(self):
        self.edit(self.SPEC, "**Confirmed.** filled", "**Confirmed.** Beau, 2026-11-16, PR #12.")
        self.edit("ROADMAP.md", "| Specced |", "| Building |")
        self.assertEqual(self.problems(), [])

    def test_criteria_need_ids_and_probes(self):
        self.edit(self.SPEC, "- [ ] **C1.** filled Probe: filled.", "- [ ] filled Probe: filled.")
        self.edit(self.SPEC, "- [ ] **A1.** filled Probe: filled.", "- [ ] **A1.** never filled.")
        found = self.problems()
        self.assertTrue(any(":35: criterion has no id; start it with **C<n>.**" in p for p in found), found)
        self.assertTrue(any(":42: A1 names no 'Probe:'" in p for p in found), found)

    def test_probe_on_a_continuation_line_counts(self):
        self.edit(self.SPEC, "- [ ] **A1.** filled Probe: filled.", "- [ ] **A1.** filled.\n  Probe: filled.")
        self.assertEqual(self.problems(), [])

    def test_checked_box_needs_evidence(self):
        self.edit(self.SPEC, "- [ ] **C1.** filled Probe: filled.", "- [x] **C1.** filled Probe: filled.")
        self.assertFlags("C1 is checked without 'Evidence:'")
        self.edit(self.SPEC, "- [x] **C1.** filled Probe: filled.", "- [x] **C1.** filled Probe: filled. Evidence: verify-demo run 3.")
        self.assertEqual(self.problems(), [])

    def test_ids_are_unique_and_never_reused(self):
        self.edit(self.SPEC, "- [ ] **C2.**", "- ~~**C3.** dropped~~ Dropped: out of scope.\n- [ ] **C3.** Probe: x.\n- [ ] **C1.**")
        found = self.problems()
        self.assertTrue(any("C3 is used twice" in p for p in found), found)
        self.assertTrue(any("C1 is used twice" in p for p in found), found)

    def test_struck_criterion_needs_no_box_or_probe(self):
        self.edit(self.SPEC, "- [ ] **C2.**", "- ~~**C3.** dropped~~ Dropped: out of scope.\n- [ ] **C2.**")
        self.assertEqual(self.problems(), [])

    def test_ids_match_their_section(self):
        self.edit(self.SPEC, "- [ ] **A1.**", "- [ ] **C9.**")
        self.assertFlags("C9 is under Anti-criteria; ids there start with A")

    def test_anti_criteria_are_required(self):
        self.edit(self.SPEC, "## Anti-criteria", "## Worries")
        self.assertFlags("no '## Anti-criteria' section")

    def test_done_phase_with_unchecked_boxes_is_flagged(self):
        self.edit("ROADMAP.md", "| Specced |", "| Done |")
        self.assertFlags("the phase is Done but 3 box(es) are unchecked")

    def test_done_phase_with_every_box_proven_passes(self):
        self.edit("ROADMAP.md", "| Specced |", "| Done |")
        path = self.repo / self.SPEC
        path.write_text(path.read_text().replace("- [ ] ", "- [x] ").replace("Probe: filled.", "Probe: filled. Evidence: ran it.")
                        .replace("0 problems.", "0 problems. Evidence: ran it."))
        self.assertEqual(self.problems(), [])

    def test_roadmap_and_specs_match(self):
        self.edit("ROADMAP.md", "| P1 filled | Specced |", "| P1 filled | Specced |\n| P2 Next | Not started | x |")
        self.assertFlags("P2 has no spec")

    def test_roadmap_status_uses_lifecycle_words(self):
        self.edit("ROADMAP.md", "| Specced |", "| Halfway |")
        self.assertFlags("status 'Halfway' should start with")

    def test_work_units_are_not_phases(self):
        self.edit("ROADMAP.md", "| P1 filled | Specced |", "| P1 filled | Specced |\n| P1.1 | Some unit | x |")
        self.assertEqual(self.problems(), [])

    def test_plan_for_a_done_phase_is_flagged(self):
        self.edit("ROADMAP.md", "| Specced |", "| Done |")
        (self.repo / "docs/plans").mkdir()
        (self.repo / "docs/plans/P1-first-slice.md").write_text("# plan\n")
        self.assertFlags("P1 is done; delete its plan")

    def test_spec_cannot_serve_a_missing_goal(self):
        self.edit("docs/phases/P1-first-slice.md", "**Serves.** G1.", "**Serves.** G1, G7.")
        found = self.problems()
        self.assertEqual(len(found), 1, found)
        self.assertIn("serves G7, which is not a goal", found[0])

    def test_drafts_are_counted_not_failed(self):
        self.edit("docs/VISION.md", "| G1 | filled |", "| G1 | filled (draft, from README) |")
        self.assertEqual(self.problems(), [])
        self.assertEqual(check_product.drafts(self.repo), 1)

    GOALS_OLD = "| # | Goal | Good looks like |\n|---|---|---|\n| G1 | filled | filled |\n"

    def goals_table(self, table):
        path = self.repo / "docs/VISION.md"
        text = path.read_text()
        start, end = text.index("| # | Goal"), text.index("## Non-goals")
        path.write_text(text[:start] + table + "\n" + text[end:])

    def test_goal_row_needs_a_measure_a_lever_and_a_first_move(self):
        for column, row in (("Measure", "| G1 | g | good |  | lever | move |"),
                            ("Lever", "| G1 | g | good | measure | | move |"),
                            ("First move", "| G1 | g | good | measure | lever | \t |")):
            self.goals_table("| # | Goal | Good looks like | Measure | Lever | First move |\n|---|---|---|---|---|---|\n" + row + "\n")
            found = self.problems()
            self.assertEqual(len(found), 1, found)
            self.assertIn(f"docs/VISION.md:11: G1 has no {column}", found[0])

    def test_goal_columns_are_found_by_name_whatever_the_case_or_order(self):
        self.goals_table("| # | Goal | FIRST MOVE | **lever** | Owner | measure | Good looks like |\n|---|---|---|---|---|---|---|\n"
                         "| G1 | g | move | lever | me | measure | good |\n| G2 | g | move |  | me | measure | good |\n")
        found = self.problems()
        self.assertEqual(len(found), 1, found)
        self.assertIn("docs/VISION.md:12: G2 has no Lever", found[0])

    def test_goal_row_shorter_than_its_header_is_flagged_not_crashed(self):
        self.goals_table("| # | Goal | Good looks like | Measure | Lever | First move |\n|---|---|---|---|---|---|\n| G1 | g | good | measure |\n")
        found = self.problems()
        self.assertEqual(len(found), 2, found)
        self.assertIn("G1 has no Lever", found[0])
        self.assertIn("G1 has no First move", found[1])

    def test_goal_cell_that_is_only_a_dash_or_tbd_is_empty(self):
        self.goals_table("| # | Goal | Good looks like | Measure | Lever | First move |\n|---|---|---|---|---|---|\n| G1 | g | good | - | TBD | ? |\n")
        self.assertEqual(len(self.problems()), 3)

    def test_pipes_inside_a_goal_cell_do_not_shift_the_columns(self):
        self.goals_table("| # | Goal | Good looks like | Measure | Lever | First move |\n|---|---|---|---|---|---|\n"
                         "| G1 | a \\| b | good | `wc -l log | sort` | lever | move |\n")
        self.assertEqual(self.problems(), [])

    def test_goals_table_with_only_some_of_the_columns_names_the_missing_ones(self):
        self.goals_table("| # | Goal | Good looks like | Measure |\n|---|---|---|---|\n| G1 | g | good | measure |\n")
        found = self.problems()
        self.assertEqual(len(found), 1, found)
        self.assertIn("docs/VISION.md:9: goals table has a Measure column but no Lever or First move column", found[0])

    def test_older_goals_table_is_a_note_not_a_problem(self):
        self.goals_table(self.GOALS_OLD)
        self.assertEqual(self.problems(), [])
        notes = check_product.notes(self.repo)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("docs/VISION.md:9: goals table has no Measure, Lever and First move columns", notes[0])

    def test_filled_templates_have_no_notes(self):
        self.assertEqual(check_product.notes(self.repo), [])

    def test_a_later_table_that_cites_goal_ids_is_not_the_goals_table(self):
        self.edit("docs/VISION.md", "## Principles", "## Who owns what\n\n| Goal | Owner |\n|---|---|\n| G1 | Sam |\n\n## Principles")
        self.assertEqual(self.problems(), [])
        self.assertEqual(check_product.notes(self.repo), [])

    def test_a_note_does_not_change_the_exit_code_and_is_printed_apart(self):
        import contextlib, io
        self.goals_table(self.GOALS_OLD)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_product.main(["check-product.py", str(self.repo)])
        self.assertEqual(code, 0)
        self.assertIn("note: docs/VISION.md:9: goals table has no Measure", err.getvalue())
        self.assertIn("0 problem(s), 0 draft marker(s) awaiting confirmation, 1 note(s)", out.getvalue())

    def test_agents_must_name_an_existing_verify_skill(self):
        shutil.rmtree(self.repo / ".agents")
        self.assertFlags("names verify-demo, but no verify-demo/SKILL.md")


if __name__ == "__main__":
    unittest.main()
