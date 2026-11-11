"""Tests for beau-help's whats_new.py and kitgen's changes.yaml checks."""
import contextlib
import datetime
import importlib.util
import io
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


whats_new = load("whats_new", "plugins/bstack/skills/beau-help/scripts/whats_new.py")
kitgen = load("kitgen", "tools/kitgen.py")

TODAY = datetime.date(2026, 11, 10)
ENTRIES = [
    {"id": "a@0.2.0", "date": "2026-11-10", "plugin": "a", "version": "0.2.0", "changes": ["new a"], "try": "do a"},
    {"id": "b@0.1.0", "date": "2026-11-01", "plugin": "b", "version": "0.1.0", "changes": ["new b"]},
    {"id": "a@0.1.0", "date": "2026-09-01", "plugin": "a", "version": "0.1.0", "changes": ["old a"]},
]


class WhatsNewTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.changes = tmp / "changes.json"
        self.changes.write_text(json.dumps({"entries": ENTRIES}))
        self.state = tmp / "state" / "seen.json"
        self.env = unittest.mock.patch.dict(os.environ, {"AGENT_KIT_STATE": str(self.state)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.path = unittest.mock.patch.object(whats_new, "CHANGES", self.changes)
        self.path.start()
        self.addCleanup(self.path.stop)

    def run_script(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(whats_new.main(list(args), today=TODAY), 0)
        return out.getvalue()

    def test_first_run_shows_recent_only_then_nothing(self):
        first = self.run_script()
        self.assertIn("new a", first)
        self.assertIn("new b", first)
        self.assertNotIn("old a", first, "first run should skip entries older than 14 days")
        self.assertIn("Nothing new", self.run_script())

    def test_after_hook_marks_seen_asking_still_shows_recent(self):
        self.run_script("--hook")
        out = self.run_script()
        self.assertIn("Nothing new", out)
        self.assertIn("new a", out, "the release the hook announced must still be readable on request")
        self.assertNotIn("old a", out)

    def test_new_release_shows_only_unseen(self):
        self.run_script()
        newer = {"id": "a@0.3.0", "date": "2026-11-11", "plugin": "a", "version": "0.3.0", "changes": ["newer a"]}
        self.changes.write_text(json.dumps({"entries": [newer] + ENTRIES}))
        out = self.run_script()
        self.assertIn("newer a", out)
        self.assertNotIn("new b", out)

    def test_peek_does_not_mark_seen(self):
        self.run_script("--peek")
        self.assertFalse(self.state.exists())
        self.assertIn("new a", self.run_script())

    def test_hook_reports_once_per_plugin_and_then_stays_silent(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text(json.dumps({"seen": []}))
        payload = json.loads(self.run_script("--hook"))
        self.assertEqual(payload["systemMessage"], "agent-kit updated: a 0.2.0, b 0.1.0. Ask \"what's new\" for details.")
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("Try: `do a`", payload["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.run_script("--hook"), "")

    def test_corrupt_state_counts_as_first_run(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("not json")
        self.assertIn("new a", self.run_script())

    def test_hook_never_fails_session_start(self):
        self.changes.write_text("broken")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_script("--hook"), "")


class CheckChangesTest(unittest.TestCase):
    def entry(self, **kw):
        return {"date": "2026-11-10", "plugin": "a", "version": "0.2.0", "changes": ["x"], **kw}

    def assertRejects(self, changes, current, needle):
        with self.assertRaises(kitgen.KitError) as cm:
            kitgen.check_changes(changes, current)
        self.assertIn(needle, str(cm.exception))

    def test_bumped_version_without_entry_fails(self):
        self.assertRejects([self.entry()], {"a": "0.3.0"}, "no entry for a 0.3.0")

    def test_entry_newer_than_kit_fails(self):
        self.assertRejects([self.entry(version="0.4.0")], {"a": "0.3.0"}, "newer than kit.yaml")

    def test_yaml_mapping_in_changes_fails(self):
        self.assertRejects([self.entry(changes=[{"New skills": "x"}])], {"a": "0.2.0"}, "list of strings")

    def test_entries_must_be_newest_first(self):
        old, new = self.entry(version="0.1.0", date="2026-01-01"), self.entry()
        self.assertRejects([old, new], {"a": "0.2.0"}, "newest first")

    def test_unknown_key_fails(self):
        self.assertRejects([self.entry(note="x")], {"a": "0.2.0"}, "unknown keys")

    def test_valid_history_passes(self):
        kitgen.check_changes([self.entry(), self.entry(version="0.1.0", date="2026-10-01")], {"a": "0.2.0"})

    def test_repo_changes_cover_every_plugin(self):
        files = kitgen.generate(kitgen.load_kit(), kitgen.load_principles(), kitgen.load_changes())
        self.assertIn("docs/CHANGELOG.md", files)


if __name__ == "__main__":
    unittest.main()
