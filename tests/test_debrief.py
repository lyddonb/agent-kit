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

    def test_a_pattern_folder_link_or_submodule_is_not_a_record(self):
        (self.repo / "dir").mkdir()
        (self.repo / "dir" / "a.txt").write_text("x")
        (self.repo / "link.txt").symlink_to("proof.txt")
        sh(self.repo, "git", "add", "dir", "link.txt")
        sh(self.repo, "git", "update-index", "--add", "--cacheinfo", f"160000,{self.head},sub")
        for pointer in ("link.txt", "sub", "*", "*.txt", ":(glob)**", ":/", ":/proof.txt", "dir", "dir/", "./proof.txt"):
            self.write(self.edited(record=pointer))
            done = self.debrief("check")
            self.assertEqual(done.returncode, 1, f"{pointer!r} names no single tracked file but passed")
            self.assertIn("neither an https URL nor a path git tracks", done.stderr, pointer)

    def test_a_file_whose_name_is_a_glob_character_is_a_record(self):
        (self.repo / "*").write_text("x")
        sh(self.repo, "git", "add", "--", ":(literal)*")
        self.write(self.edited(record="*"))
        done = self.debrief("check")
        self.assertEqual(done.returncode, 0, done.stderr)

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


class BaseCheckTest(DebriefBase):
    """`check --base`: a branch off `main` in the throwaway repo stands in for a pull request."""

    def setUp(self):
        super().setUp()
        sh(self.repo, "git", "branch", "-M", "main")
        sh(self.repo, "git", "switch", "-qc", "work")

    def commit(self, message="work"):
        sh(self.repo, "git", "add", "-A")
        done = sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)
        self.assertEqual(done.returncode, 0, done.stderr)

    def change_source(self, name="app.py"):
        (self.repo / name).write_text("print(1)\n")
        self.commit()

    def check(self):
        return self.debrief("check", "--base", "main")

    def test_a_source_change_with_no_record_fails_and_names_the_file(self):
        self.change_source()
        done = self.check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("changes app.py and adds no change record", done.stderr)

    def test_a_source_change_with_a_good_record_passes(self):
        self.change_source()
        self.write(self.good)
        self.commit()
        done = self.check()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("1 record(s) checked, 0 with problems", done.stdout)

    def test_a_source_change_with_a_bad_record_fails(self):
        self.change_source()
        self.write(self.edited(record=""))
        self.commit()
        done = self.check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("VERIFIED without 'record'", done.stderr)

    def test_a_change_to_bookkeeping_files_only_needs_no_record(self):
        (self.repo / "ROADMAP.md").write_text("# Roadmap\n")
        (self.repo / "docs" / "phases").mkdir(parents=True)
        (self.repo / "docs" / "phases" / "P1-x.md").write_text("spec\n")
        self.commit()
        done = self.check()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("0 record(s) checked", done.stdout)

    def test_deleting_a_source_file_owes_a_record(self):
        sh(self.repo, "git", "rm", "-q", "proof.txt")
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_a_record_already_on_the_base_does_not_count(self):
        sh(self.repo, "git", "switch", "-q", "main")
        self.write(self.good, "2026-11-01-older.json")
        self.commit()
        sh(self.repo, "git", "switch", "-qc", "later")
        self.change_source()
        done = self.check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("adds no change record", done.stderr)

    def test_editing_an_old_record_does_not_count_but_is_checked(self):
        sh(self.repo, "git", "switch", "-q", "main")
        self.write(self.good, "2026-11-01-older.json")
        self.commit()
        sh(self.repo, "git", "switch", "-qc", "later")
        self.change_source()
        self.write(self.edited(record=""), "2026-11-01-older.json")
        self.commit()
        done = self.check()
        self.assertIn("adds no change record", done.stderr)
        self.assertIn("VERIFIED without 'record'", done.stderr)

    def test_evidence_files_beside_a_record_are_not_records(self):
        self.change_source()
        folder = self.repo / ".changes" / "2026-11-21-import-dedupe"
        folder.mkdir(parents=True)
        (folder / "out.json").write_text("{}")
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_commits_that_landed_on_the_base_since_the_branch_are_not_this_pull_request(self):
        self.write(self.good)
        self.change_source()
        sh(self.repo, "git", "switch", "-q", "main")
        (self.repo / "other.py").write_text("x = 1\n")
        self.commit("someone else's change, with no record")
        sh(self.repo, "git", "switch", "-q", "work")
        self.assertEqual(self.check().returncode, 0)

    def test_observe_reports_the_failure_and_exits_zero(self):
        self.change_source()
        done = self.debrief("check", "--base", "main", "--observe")
        self.assertEqual(done.returncode, 0)
        self.assertIn("adds no change record", done.stderr)
        self.assertIn("observe: this pull request would have failed", done.stdout)

    def test_observe_says_nothing_extra_when_the_check_passes(self):
        self.change_source()
        self.write(self.good)
        self.commit()
        self.assertNotIn("observe:", self.debrief("check", "--base", "main", "--observe").stdout)

    def test_observe_without_base_and_an_unknown_base_under_observe_are_usage_errors(self):
        self.assertEqual(self.debrief("check", "--observe").returncode, 2)
        self.assertEqual(self.debrief("check", "--base", "origin/nope", "--observe").returncode, 2)

    def test_an_unknown_base_is_a_usage_error(self):
        done = self.debrief("check", "--base", "origin/nope")
        self.assertEqual(done.returncode, 2)
        self.assertIn("cannot compare HEAD with 'origin/nope'", done.stderr)

    def exempt_on_main(self, text):
        sh(self.repo, "git", "switch", "-q", "main")
        (self.repo / ".changes").mkdir(exist_ok=True)
        (self.repo / ".changes" / "exempt").write_text(text)
        self.commit("exempt list")
        sh(self.repo, "git", "switch", "-qc", "later")

    def test_paths_the_base_exempts_need_no_record(self):
        self.exempt_on_main("# weekly brief data\nbooks/\nquestions.md  # answered by hand\n")
        (self.repo / "books").mkdir()
        (self.repo / "books" / "runs.csv").write_text("a\n")
        (self.repo / "questions.md").write_text("Q1\n")
        self.commit()
        done = self.check()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("exempt on main (.changes/exempt): books, questions.md", done.stdout)

    def test_an_exempt_path_with_a_source_change_still_owes_a_record(self):
        self.exempt_on_main("books\n")
        (self.repo / "books").mkdir()
        (self.repo / "books" / "runs.csv").write_text("a\n")
        self.change_source()
        done = self.check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("changes app.py and adds no change record", done.stderr)
        self.assertNotIn("books/runs.csv", done.stderr)

    def test_an_exempt_path_matches_from_the_root_and_literally(self):
        self.exempt_on_main("books\nq*.md\n")
        (self.repo / "src" / "books").mkdir(parents=True)
        (self.repo / "src" / "books" / "ledger.py").write_text("x = 1\n")
        (self.repo / "qx.md").write_text("x\n")
        self.commit()
        done = self.check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("changes qx.md, src/books/ledger.py and adds no change record", done.stderr)

    def test_a_list_the_pull_request_adds_does_not_exempt_the_pull_request(self):
        (self.repo / ".changes").mkdir()
        (self.repo / ".changes" / "exempt").write_text("app.py\n")
        self.change_source()
        done = self.check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("changes app.py and adds no change record", done.stderr)

    def test_a_pull_request_that_only_edits_the_list_needs_no_record(self):
        (self.repo / ".changes").mkdir()
        (self.repo / ".changes" / "exempt").write_text("briefs/\n")
        self.commit()
        self.assertEqual(self.check().returncode, 0)

    def test_a_pull_request_that_leaves_a_bad_list_fails(self):
        for bad in (".", "/books", "../elsewhere", "books/.."):
            with self.subTest(bad=bad):
                (self.repo / ".changes").mkdir(exist_ok=True)
                (self.repo / ".changes" / "exempt").write_text(f"briefs\n{bad}\n")
                self.commit(f"list with {bad}")
                done = self.check()
                self.assertEqual(done.returncode, 1)
                self.assertIn(f"leaves a bad .changes/exempt: .changes/exempt line 2: {bad!r}", done.stderr)

    def test_a_bad_list_on_the_base_exempts_nothing(self):
        self.exempt_on_main("books\n.\n")
        (self.repo / "books").mkdir()
        (self.repo / "books" / "runs.csv").write_text("a\n")
        self.commit()
        done = self.check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("main: ignoring .changes/exempt", done.stderr)
        self.assertIn("changes books/runs.csv and adds no change record", done.stderr)

    def test_base_and_files_together_are_refused(self):
        self.assertEqual(self.debrief("check", "--base", "main", "x.json").returncode, 2)

    def test_a_record_that_links_outside_the_repo_is_not_read(self):
        outside = Path(tempfile.mkdtemp()) / "runner-secrets.json"
        outside.write_text(json.dumps({"version": "s3cr3t-value", "api_token_name": 1}))
        self.change_source()
        (self.repo / ".changes").mkdir()
        (self.repo / ".changes" / "2026-11-21-leak.json").symlink_to(outside)
        self.commit()
        done = self.check()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("is a symlink", done.stderr)
        self.assertNotIn("s3cr3t-value", done.stderr, "the linked file's contents reached the log")
        self.assertNotIn("api_token_name", done.stderr, "the linked file's keys reached the log")

    def test_a_record_that_links_to_an_endless_device_does_not_hang(self):
        self.change_source()
        (self.repo / ".changes").mkdir()
        (self.repo / ".changes" / "2026-11-21-zero.json").symlink_to("/dev/zero")
        self.commit()
        done = subprocess.run([sys.executable, str(SCRIPT), "check", "--base", "main"], cwd=self.repo,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("is a symlink", done.stderr)

    def test_a_record_git_holds_as_a_link_or_executable_is_rejected(self):
        self.change_source()
        for mode, name in (("120000", "2026-11-21-link.json"), ("100755", "2026-11-21-exec.json")):
            path = self.write(self.good, name)
            blob = sh(self.repo, "git", "hash-object", "-w", str(path)).stdout.strip()
            sh(self.repo, "git", "update-index", "--add", "--cacheinfo", f"{mode},{blob},.changes/{name}")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "modes")
        done = self.check()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("2026-11-21-link.json: git holds it as mode 120000", done.stderr)
        self.assertIn("2026-11-21-exec.json: git holds it as mode 100755", done.stderr)

    def test_a_changes_folder_that_links_outside_the_repo_is_not_read(self):
        outside = Path(tempfile.mkdtemp())
        (outside / "2026-11-21-import-dedupe.json").write_text(json.dumps({"version": "s3cr3t-value"}))
        (self.repo / ".changes").symlink_to(outside, target_is_directory=True)
        done = self.debrief("check")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("is outside the repository", done.stderr)
        self.assertNotIn("s3cr3t-value", done.stderr, "the linked file's contents reached the log")


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
