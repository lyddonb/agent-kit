import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = sorted(p for p in (ROOT / "cases").iterdir() if (p / "case.json").is_file())


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
                    f"fails without its rule; rebuild it against this tree:\n{result.stderr}",
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
