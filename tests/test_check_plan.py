"""Tests for beau-mode's plan checker (plugins/bstack/skills/beau-mode/scripts/check-plan.py)."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/beau-mode/scripts/check-plan.py"
GOOD = (ROOT / "tests/fixtures/plan-good.md").read_text()
PLAYBOOK = ROOT / "plugins/bstack/skills/beau-mode/playbooks/multi-phase-plan.md"

spec = importlib.util.spec_from_file_location("check_plan", SCRIPT)
check_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_plan)


def problems(text: str) -> list[str]:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "plan.md"
        path.write_text(text)
        return check_plan.check(path)[1]


class CheckPlanTest(unittest.TestCase):
    def test_good_plan_passes(self):
        self.assertEqual(problems(GOOD), [])

    def test_skeleton_fails_only_on_placeholders(self):
        text = PLAYBOOK.read_text().split("````markdown\n", 1)[1].split("\n````", 1)[0]
        left = [p for p in problems(text) if "placeholder" not in p and "lanes at the PR head" not in p]
        self.assertEqual(left, [])

    def assertProblem(self, text: str, fragment: str):
        found = problems(text)
        self.assertTrue(any(fragment in p for p in found), f"{fragment!r} not in {found}")

    def test_missing_rule(self):
        self.assertProblem(GOOD.replace("**Verify, unit.** Tests alone", "**Verify, unit.** Unit tests", 1),
                           "Verify, unit. does not open with the rule")

    def test_lane_without_predicate(self):
        self.assertProblem(GOOD.replace("Pass when the table holds 60000 distinct rows.", "Done."),
                           "lane 2 has no pass predicate")

    def test_lane_count_mismatch(self):
        self.assertProblem(GOOD.replace("2 lanes at the PR head", "3 lanes at the PR head"), "expected 1 to 3")

    def test_first_lane_must_be_regression(self):
        self.assertProblem(GOOD.replace("Lane 1. Regression lane against trunk. Export", "Lane 1. Export"),
                           "lane 1 is not the regression lane")

    def test_perf_exemption_needs_reason(self):
        self.assertProblem(GOOD.replace("Not perf-sensitive. It changes one print call.", "Not perf-sensitive."),
                           "needs a reason")

    def test_style(self):
        self.assertProblem(GOOD.replace("The rule is that", "The rule — that"), "long dash")
        self.assertProblem(GOOD.replace("Retries that land", "Note: retries that land"), "mid-sentence colon")
        self.assertProblem(GOOD.replace("Wall time", "<metric>"), "unfilled placeholder")

    def test_sub_block_order(self):
        self.assertProblem(GOOD.replace("**You see.**", "**Seen.**", 1), "sub-blocks are")

    def test_requires_prototype_appendix(self):
        self.assertProblem(GOOD.replace("## Appendix A. Prototype evidence", "## Appendix A. Notes"),
                           "Prototype evidence")


if __name__ == "__main__":
    unittest.main()
