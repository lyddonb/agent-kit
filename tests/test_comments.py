"""Tests for no-comments' comments.py: which comments a diff adds to Python files.

Each test builds a throwaway git repo with one commit on `main`, changes it, and runs the script
as a user would.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/no-comments/scripts/comments.py"

START = '''"""A module."""
import os


def load(path):
    # read the whole file
    return open(path).read()
'''


class Repo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.write("app.py", START)
        self.commit("start")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def run_script(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--base", "main", *args],
            cwd=cwd or self.root, capture_output=True, text=True,
        )

    def listed(self, *args):
        done = self.run_script(*args)
        self.assertIn(done.returncode, (0, 1), done.stderr)
        self.assertEqual(done.returncode, 1 if done.stdout else 0, "the exit code follows the list")
        return done.stdout.splitlines()


class AddedComments(Repo):
    def test_a_diff_with_no_python_change_passes_with_empty_output(self):
        self.write("README.md", "# heading\n")
        done = self.run_script()
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertIn("adds 0", done.stderr)

    def test_a_new_comment_fails_and_names_its_file_and_line(self):
        self.write("app.py", START + "\n\n# helpers below\n")
        self.assertEqual(self.listed(), ["app.py:10: # helpers below"])

    def test_a_comment_after_code_on_the_same_line_is_found(self):
        self.write("app.py", START + "LIMIT = 5  # five is enough\n")
        self.assertEqual(self.listed(), ["app.py:8: # five is enough"])

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        self.write("app.py", START + 'TEXT = """\n# not a comment\n"""\nCOLOR = "#fff"\n')
        self.assertEqual(self.listed(), [])

    def test_an_untracked_file_counts(self):
        self.write("pkg/new.py", "# brand new\nX = 1\n")
        self.assertEqual(self.listed(), ["pkg/new.py:1: # brand new"])

    def test_a_comment_that_was_already_there_is_not_listed(self):
        self.write("app.py", START + "X = 1\n")
        self.assertEqual(self.listed(), [])

    def test_removing_a_comment_passes(self):
        self.write("app.py", START.replace("    # read the whole file\n", ""))
        self.assertEqual(self.listed(), [])


class MovedAndEdited(Repo):
    def test_a_comment_moved_to_another_file_adds_nothing(self):
        self.write("app.py", START.replace("    # read the whole file\n", ""))
        self.write("io.py", "def load(path):\n    # read the whole file\n    return 1\n")
        self.assertEqual(self.listed(), [])

    def test_a_second_copy_of_an_existing_comment_is_new(self):
        self.write("app.py", START + "\n\ndef again(path):\n    # read the whole file\n    return 2\n")
        self.assertEqual(self.listed(), ["app.py:11: # read the whole file"])

    def test_an_edited_comment_is_new(self):
        self.write("app.py", START.replace("# read the whole file", "# read all of the file"))
        self.assertEqual(self.listed(), ["app.py:6: # read all of the file"])


class KeepList(Repo):
    def test_a_shebang_and_an_encoding_line_are_kept(self):
        self.write("tool.py", "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nX = 1\n")
        self.assertEqual(self.listed(), [])

    def test_a_shebang_look_alike_below_line_one_is_listed(self):
        self.write("tool.py", "X = 1\n#!/usr/bin/env python3\n")
        self.assertEqual(self.listed(), ["tool.py:2: #!/usr/bin/env python3"])

    def test_tool_directives_are_kept(self):
        self.write("tool.py", "import os  # noqa: F401\nX = f()  # type: ignore[misc]\n# fmt: off\nY = 1\n")
        self.assertEqual(self.listed(), [])

    def test_a_license_header_is_kept_whole(self):
        self.write("lib.py", "# Copyright 2026 Someone\n#\n# Licensed under the MIT license.\n\nX = 1\n")
        self.assertEqual(self.listed(), [])

    def test_a_license_header_does_not_keep_comments_below_the_first_code(self):
        self.write("lib.py", "# Copyright 2026 Someone\n\nX = 1\n# set above\n")
        self.assertEqual(self.listed(), ["lib.py:4: # set above"])

    def test_the_word_license_below_the_header_keeps_nothing(self):
        self.write("lib.py", "X = 1\n# check the license first\n")
        self.assertEqual(self.listed(), ["lib.py:2: # check the license first"])

    def test_an_opening_block_with_no_license_words_is_listed(self):
        self.write("lib.py", "# this module loads files\nX = 1\n")
        self.assertEqual(self.listed(), ["lib.py:1: # this module loads files"])

    def test_a_comment_with_a_link_is_kept(self):
        self.write("app.py", START + "LIMIT = 100  # https://example.com/issues/12\n")
        self.assertEqual(self.listed(), [])

    def test_a_link_keeps_the_whole_block_of_comment_lines_it_sits_in(self):
        self.write("app.py", START + "# the API rejects larger batches,\n# see https://example.com/issues/12\nLIMIT = 100\n")
        self.assertEqual(self.listed(), [])

    def test_a_link_does_not_reach_past_a_blank_line_or_onto_a_code_line(self):
        self.write("app.py", START + "# unrelated note\n\n# https://example.com/issues/12\nLIMIT = 100  # a cap\n")
        self.assertEqual(self.listed(), ["app.py:8: # unrelated note", "app.py:11: # a cap"])


class HeadAndOutput(Repo):
    def test_head_reads_that_commit_and_not_the_working_tree(self):
        self.git("checkout", "-q", "-b", "work")
        self.write("app.py", START + "# committed\n")
        self.commit("add a comment")
        self.write("app.py", START + "# committed\n# not committed\n")
        self.assertEqual(self.listed("--head", "work"), ["app.py:8: # committed"])
        self.assertEqual(self.listed(), ["app.py:8: # committed", "app.py:9: # not committed"])

    def test_json_prints_a_list_of_path_line_and_text(self):
        self.write("app.py", START + "# one more\n")
        done = self.run_script("--json")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(json.loads(done.stdout), [{"path": "app.py", "line": 8, "text": "# one more"}])

    def test_root_runs_it_from_another_folder(self):
        self.write("app.py", START + "# one more\n")
        done = self.run_script("--root", str(self.root), cwd=ROOT)
        self.assertEqual(done.stdout.splitlines(), ["app.py:8: # one more"])


class CannotRun(Repo):
    def assert_unusable(self, done, said):
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn(said, done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_an_unknown_ref_exits_2(self):
        done = subprocess.run([sys.executable, str(SCRIPT), "--base", "no-such-ref"], cwd=self.root, capture_output=True, text=True)
        self.assert_unusable(done, "comments: git merge-base")

    def test_a_folder_below_the_repo_root_exits_2(self):
        self.write("pkg/x.py", "X = 1\n")
        self.assert_unusable(self.run_script(cwd=self.root / "pkg"), "not the top of a git work tree")

    def test_a_python_file_it_cannot_tokenize_exits_2(self):
        self.write("broken.py", 'X = """never closed\n')
        self.assert_unusable(self.run_script(), "broken.py: cannot tokenize")

    def test_bytes_that_are_not_utf8_exit_2(self):
        (self.root / "latin.py").write_bytes(b"X = 1\nY = 2\nZ = '\xff'\n")
        self.assert_unusable(self.run_script(), "latin.py: cannot tokenize")

    def test_a_python_file_it_cannot_read_exits_2(self):
        (self.root / "gone.py").symlink_to(self.root / "nowhere.py")
        self.assert_unusable(self.run_script(), "gone.py: cannot read")


if __name__ == "__main__":
    unittest.main()
