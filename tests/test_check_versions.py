"""Tests for tools/check_versions.py: plugin changes must bump the plugin's version."""
import importlib.util
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_versions", ROOT / "tools/check_versions.py")
check_versions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_versions)

KIT = """
defaults: {{version: 0.1.0}}
plugins:
  - name: alpha
    version: {alpha}
  - name: beta
"""


class CheckVersionsTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        self.write("kit.yaml", KIT.format(alpha="1.0.0"))
        self.write("plugins/alpha/skills/a/SKILL.md", "a\n")
        self.write("plugins/beta/skills/b/SKILL.md", "b\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "change")

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo,
                       check=True, capture_output=True)

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def problems(self):
        return check_versions.problems("main", self.repo)

    def test_change_without_bump_names_the_plugin_and_the_fix(self):
        self.write("plugins/alpha/skills/a/SKILL.md", "a changed\n")
        self.commit("edit alpha")
        found = self.problems()
        self.assertEqual(len(found), 1, found)
        self.assertIn("'alpha'", found[0])
        self.assertIn("Bump `version` for alpha in kit.yaml", found[0])

    def test_change_with_bump_passes(self):
        self.write("plugins/alpha/skills/a/SKILL.md", "a changed\n")
        self.write("kit.yaml", KIT.format(alpha="1.0.1"))
        self.commit("edit and bump alpha")
        self.assertEqual(self.problems(), [])

    def test_plugin_on_the_defaults_version_is_checked_too(self):
        self.write("plugins/beta/skills/b/SKILL.md", "b changed\n")
        self.commit("edit beta")
        self.assertEqual(len(self.problems()), 1, "beta inherits 0.1.0 from defaults and must still be bumped")

    def test_new_plugin_needs_no_bump(self):
        self.write("kit.yaml", KIT.format(alpha="1.0.0") + "  - name: gamma\n")
        self.write("plugins/gamma/skills/g/SKILL.md", "g\n")
        self.commit("add gamma")
        self.assertEqual(self.problems(), [])

    def test_changes_outside_plugins_need_no_bump(self):
        self.write("docs/x.md", "x\n")
        self.commit("docs")
        self.assertEqual(self.problems(), [])


if __name__ == "__main__":
    unittest.main()
