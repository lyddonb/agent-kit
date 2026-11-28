import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = sorted(p for p in (ROOT / "cases").iterdir() if (p / "case.json").is_file())
REBUILD_SECTION = "When the patch no longer applies"


class RuleRemovedPatchTest(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertTrue(CASES, "no case folders under cases/")

    def test_each_case_has_a_patch_that_applies_to_this_tree(self):
        for case in CASES:
            with self.subTest(case=case.name):
                patch = case / "rule-removed.patch"
                self.assertTrue(patch.is_file(), f"{case.name} has no rule-removed.patch")
                result = subprocess.run(
                    ["git", "apply", "--check", "-p1", str(patch)],
                    cwd=ROOT, capture_output=True, text=True,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"{case.name}/rule-removed.patch no longer applies, so the case can't show it "
                    f"fails without its rule. Rebuild it from today's text with the steps under "
                    f"\"{REBUILD_SECTION}\" in cases/README.md.\n{result.stderr}",
                )

    def test_readme_has_the_section_the_stale_patch_message_names(self):
        headings = [
            line.lstrip("#").strip()
            for line in (ROOT / "cases" / "README.md").read_text().splitlines()
            if line.startswith("#")
        ]
        self.assertIn(
            REBUILD_SECTION, headings,
            "the stale-patch failure points authors at a cases/README.md section that is gone",
        )

    def test_each_patch_edits_the_plugin_under_test(self):
        for case in CASES:
            with self.subTest(case=case.name):
                plugin = json.loads((case / "case.json").read_text())["plugin"]
                targets = [
                    line.split()[1].split("/", 1)[1]
                    for line in (case / "rule-removed.patch").read_text().splitlines()
                    if line.startswith("+++ ")
                ]
                self.assertTrue(targets, f"{case.name}/rule-removed.patch changes no file")
                for target in targets:
                    self.assertTrue(
                        target.startswith(plugin + "/"),
                        f"{case.name}/rule-removed.patch edits {target}, outside {plugin}",
                    )


if __name__ == "__main__":
    unittest.main()
