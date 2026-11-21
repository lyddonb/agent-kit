"""Tests for the debrief skill's debrief.py, run as a command in a throwaway git repo."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/debrief/scripts/debrief.py"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


class DebriefBase(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        sh(self.repo, "git", "init", "-q")
        (self.repo / "proof.txt").write_text("60000 rows\n")
        (self.repo / ".gitignore").write_text("scratch/\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init")
        self.head = sh(self.repo, "git", "rev-parse", "HEAD").stdout.strip()
        self.good = {
            "version": 1,
            "goal": "Imports stop duplicating rows.",
            "changed": ["The importer keys rows on id."],
            "claims": [{"claim": "Importing the 60k-row file writes 60,000 rows", "verdict": "VERIFIED",
                        "check": "make import-check on the sample file", "commit": self.head,
                        "record": "proof.txt", "remaining": "Files over 1 GB"}],
            "next": [{"item": "Stream large files", "source": "ROADMAP.md R4",
                      "why_now": "The 1 GB case is unchecked", "impact": "Imports of any size finish"}],
            "release": {"note": "Importing a file twice no longer duplicates rows."},
        }

    def debrief(self, *args):
        return sh(self.repo, sys.executable, str(SCRIPT), *args)

    def write(self, record, name="2026-11-21-import-dedupe.json"):
        path = self.repo / ".changes" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record))
        return path

    def assertRejected(self, record, text):
        self.write(record)
        done = self.debrief("check")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn(text, done.stderr)

    def edited(self, **claim):
        record = copy.deepcopy(self.good)
        record["claims"][0].update(claim)
        return record


class CheckTest(DebriefBase):
    def test_a_complete_record_passes(self):
        self.write(self.good)
        done = self.debrief("check")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("1 record(s) checked, 0 with problems", done.stdout)

    def test_no_records_is_not_a_failure(self):
        self.assertEqual(self.debrief("check").returncode, 0)

    def test_the_empty_record_new_writes_does_not_pass(self):
        made = self.debrief("new", "import-dedupe", "--date", "2026-11-21")
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertTrue(Path(made.stdout.strip()).exists())
        self.assertEqual(self.debrief("check").returncode, 1)

    def test_new_refuses_to_overwrite(self):
        self.write(self.good)
        self.assertEqual(self.debrief("new", "import-dedupe", "--date", "2026-11-21").returncode, 1)

    def test_verified_without_a_record_is_rejected(self):
        self.assertRejected(self.edited(record=""), "VERIFIED without 'record'")

    def test_verified_without_a_commit_is_rejected(self):
        self.assertRejected(self.edited(commit=""), "VERIFIED without 'commit'")

    def test_a_commit_that_is_not_in_the_repo_is_rejected(self):
        self.assertRejected(self.edited(commit="deadbeef"), "is not in this repository")

    def test_an_untracked_record_file_is_rejected(self):
        (self.repo / "loose.txt").write_text("x")
        self.assertRejected(self.edited(record="loose.txt"), "neither an https URL nor a path git tracks")

    def test_an_ignored_record_file_is_rejected(self):
        (self.repo / "scratch").mkdir()
        (self.repo / "scratch" / "out.txt").write_text("x")
        self.assertRejected(self.edited(record="scratch/out.txt"), "neither an https URL nor a path git tracks")

    def test_a_staged_record_file_and_a_url_pass(self):
        (self.repo / "staged.txt").write_text("x")
        sh(self.repo, "git", "add", "staged.txt")
        for pointer in ("staged.txt", "https://github.com/o/r/actions/runs/1"):
            self.write(self.edited(record=pointer))
            self.assertEqual(self.debrief("check").returncode, 0, pointer)

    def test_an_unproven_claim_must_say_what_remains(self):
        self.assertRejected(self.edited(verdict="INCONCLUSIVE", remaining=""), "INCONCLUSIVE without 'remaining'")

    def test_an_unchecked_claim_needs_no_record(self):
        self.write(self.edited(verdict="UNCHECKED", check="", commit="", record=""))
        self.assertEqual(self.debrief("check").returncode, 0)

    def test_an_unknown_verdict_is_rejected(self):
        self.assertRejected(self.edited(verdict="DONE"), "verdict must be one of")

    def test_a_next_item_without_impact_or_source_is_rejected(self):
        record = copy.deepcopy(self.good)
        record["next"][0].update(impact="", source="")
        self.write(record)
        done = self.debrief("check")
        self.assertIn("next[0] has no 'impact'", done.stderr)
        self.assertIn("next[0] has no 'source' (where it comes from, or 'inferred')", done.stderr)

    def test_an_empty_next_list_passes(self):
        record = copy.deepcopy(self.good)
        record["next"] = []
        self.write(record)
        self.assertEqual(self.debrief("check").returncode, 0)

    def test_release_must_be_exactly_one_kind(self):
        for release in ({}, {"note": "a", "none": "b"}, {"text": "a"}, "a"):
            record = copy.deepcopy(self.good)
            record["release"] = release
            self.assertRejected(record, "'release' must be exactly one of")
        record["release"] = {"none": " "}
        self.assertRejected(record, "release.none is empty")

    def test_a_badly_named_file_is_rejected(self):
        self.write(self.good, "import-dedupe.json")
        self.assertIn("file name must be", self.debrief("check").stderr)


class RenderTest(DebriefBase):
    def test_show_prints_the_newest_record_with_every_part(self):
        older = copy.deepcopy(self.good)
        older["goal"] = "An older goal."
        self.write(older, "2026-11-01-older.json")
        self.write(self.good)
        out = self.debrief("show").stdout
        self.assertIn("**Goal.** Imports stop duplicating rows.", out)
        self.assertNotIn("An older goal.", out)
        self.assertIn("**VERIFIED**: Importing the 60k-row file writes 60,000 rows", out)
        self.assertIn(f"(on {self.head[:12]})", out)
        self.assertIn("Still unchecked: Files over 1 GB", out)
        self.assertIn("From: ROADMAP.md R4", out)
        self.assertIn("Impact: Imports of any size finish", out)

    def test_show_refuses_a_record_with_problems(self):
        self.write(self.edited(record=""))
        done = self.debrief("show")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")

    def test_notes_lists_release_notes_newest_first_and_leaves_out_the_rest(self):
        self.write(self.good)
        for name, release in (("2026-11-22-docs.json", {"none": "docs only"}),
                              ("2026-11-23-kit.json", {"see": "changes.yaml bstack@0.26.0"}),
                              ("2026-11-24-export.json", {"note": "You can now export a month as CSV."})):
            record = copy.deepcopy(self.good)
            record["release"] = release
            self.write(record, name)
        out = self.debrief("notes").stdout
        self.assertLess(out.index("export a month"), out.index("no longer duplicates"))
        self.assertNotIn("docs only", out)
        self.assertNotIn("changes.yaml", out)
        since = self.debrief("notes", "--since", "2026-11-22").stdout
        self.assertIn("export a month", since)
        self.assertNotIn("no longer duplicates", since)


if __name__ == "__main__":
    unittest.main()
