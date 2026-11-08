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

    def test_phase_needs_outcome_and_checkable_acceptance(self):
        self.edit("docs/phases/P1-first-slice.md", "**Outcome.**", "Outcome:")
        self.edit("docs/phases/P1-first-slice.md", "- [ ] filled", "- filled")
        self.edit("docs/phases/P1-first-slice.md", "- [ ] `ROADMAP.md`", "- `ROADMAP.md`")
        found = self.problems()
        self.assertTrue(any("no `**Outcome.**`" in p for p in found), found)
        self.assertTrue(any("Acceptance has no '- [ ]' boxes" in p for p in found), found)

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

    def test_agents_must_name_an_existing_verify_skill(self):
        shutil.rmtree(self.repo / ".agents")
        self.assertFlags("names verify-demo, but no verify-demo/SKILL.md")


if __name__ == "__main__":
    unittest.main()
