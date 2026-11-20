"""Tests for the command check in tools/validate.py: a skill doc never names a kit script,
subcommand or flag that does not exist."""
import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("validate", ROOT / "tools/validate.py")
validate = importlib.util.module_from_spec(spec)
sys.modules["validate"] = validate  # dataclasses look the module up by name
spec.loader.exec_module(validate)

BOOKS_PY = """
    import argparse

    def main(argv=None):
        parser = argparse.ArgumentParser(prog="books.py")
        parser.add_argument("--dir")
        sub = parser.add_subparsers(dest="command", required=True)
        s = sub.add_parser("check")
        s.add_argument("books_dir")
        s.add_argument("--base")
        s = sub.add_parser("summary")
        s.add_argument("books_dir")
        s.add_argument("--month", required=True)
        mode = s.add_mutually_exclusive_group()
        mode.add_argument("--json", action="store_true")
        return parser.parse_args(argv)
"""
CHECK_PY = """
    import subprocess, sys

    def git(*args):
        return subprocess.run(["git", "status", "--porcelain", *args])

    def main(argv):
        flags = {a for a in argv[1:] if a.startswith("--")}
        if flags - {"--matrix", "--json"}:
            return 2
        return 0
"""
WEEKLY_SH = """
    while [ $# -gt 0 ]; do
      case "$1" in
        --repo) REPO=$2; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        -i|--install) ACTION=install; shift ;;
        --out=*) OUT=${1#*=}; shift ;;
      esac
    done
"""
FENCE = "```"


class CommandCheckTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.write("plugins/p/skills/books/scripts/books.py", BOOKS_PY)
        self.write("plugins/p/skills/books/scripts/check-machine.py", CHECK_PY)
        self.write("plugins/p/skills/books/scripts/weekly.sh", WEEKLY_SH)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def check(self, doc, rel="plugins/p/skills/books/SKILL.md"):
        """The errors and the number of commands checked for one doc."""
        self.write(rel, doc)
        report = validate.Report()
        checked = validate.check_commands(self.root, report)
        return report.errors, checked

    def assert_clean(self, doc, commands=1):
        errors, checked = self.check(doc)
        self.assertEqual(errors, [])
        self.assertEqual(checked, commands, "the check must see the command to be able to pass it")

    def assert_one_error(self, doc, *needles):
        errors, _ = self.check(doc)
        self.assertEqual(len(errors), 1, errors)
        for needle in needles:
            self.assertIn(needle, errors[0])

    # --- commands that exist pass, in every form the kit's docs use ---

    def test_known_subcommand_and_flags_pass(self):
        self.assert_clean("Run `books.py summary BOOKS_DIR --month 2026-11 --json`.\n")

    def test_optional_flags_in_brackets_pass(self):
        self.assert_clean(f"{FENCE}\n<skill dir>/scripts/books.py check BOOKS_DIR [--base REF]\n{FENCE}\n")

    def test_flags_of_the_program_that_runs_the_script_are_not_the_scripts(self):
        self.assert_clean(f"{FENCE}\nuv run --no-project --python 3.12 <skill dir>/scripts/books.py check B\n{FENCE}\n")

    def test_words_after_a_pipe_redirect_or_bare_dashes_belong_to_another_program(self):
        self.assert_clean("`books.py summary B --month M | jq --arg x`", 1)
        self.assert_clean("`books.py summary B --month M > out.json --not-a-flag`", 1)
        self.assert_clean("`weekly.sh --repo o/r -- git log --oneline`", 1)

    def test_a_quoted_argument_or_placeholder_is_one_argument(self):
        self.assert_clean("`books.py summary B --month \"${{ a || --b }}\" --json`")
        self.assert_clean("`books.py summary B --month <current month> --json`")
        self.assert_clean("`python3 <this skill's folder>/scripts/books.py check <books dir>`")

    def test_a_top_level_flag_and_its_value_may_come_before_the_subcommand(self):
        self.assert_clean("`books.py --dir cases check B`")

    def test_a_script_that_reads_argv_itself_and_a_shell_script(self):
        self.assert_clean("`check-machine.py SPEC.md --matrix`")
        self.assert_clean("`scripts/weekly.sh --repo OWNER/BOOKS [--dry-run]`")
        self.assert_clean("`scripts/weekly.sh --install --out=x`")
        self.assert_one_error("`scripts/weekly.sh --status`", "--status", "--dry-run, --install, --out, --repo")

    def test_a_script_this_repo_does_not_ship_is_left_alone(self):
        errors, checked = self.check("agentfiles installs `ledger: agent-ledger:ci/run_ledger.py --fast`.\n")
        self.assertEqual((errors, checked), ([], 0))

    # --- commands that do not exist fail, and the message says what does ---

    def test_missing_script(self):
        self.assert_one_error("Run `python3 <skill dir>/scripts/log.sh start`.\n",
                              "SKILL.md:1", "scripts/log.sh", "no skill ships")

    def test_unknown_subcommand(self):
        self.assert_one_error("Run `books.py sumary BOOKS_DIR`.\n", "no 'sumary' subcommand", "check, summary")

    def test_flag_of_another_subcommand(self):
        self.assert_one_error("Run `books.py check BOOKS_DIR --json`.\n",
                              "--json", "`books.py check`", "--base")

    def test_flag_on_a_continuation_line_is_reported_at_the_commands_first_line(self):
        doc = f"Intro.\n\n{FENCE}sh\nuv run scripts/books.py summary B \\\n  --month M --weekly\n{FENCE}\n"
        self.assert_one_error(doc, "SKILL.md:4", "--weekly")

    def test_subcommand_in_the_wrong_case_or_spelling(self):
        self.assert_one_error("`books.py Summary B`", "no 'Summary' subcommand")
        self.assert_one_error("`books.py sum_mary B`", "no 'sum_mary' subcommand")

    def test_flag_a_script_that_reads_argv_does_not_take(self):
        # --porcelain is a literal in the script, but in a git call, not in the function that reads argv.
        self.assert_one_error("`check-machine.py SPEC.md --porcelain`", "--porcelain", "--json, --matrix")

    def test_placeholder_subcommand_still_checks_flags_against_every_subcommand(self):
        self.assert_clean("`books.py <command> BOOKS_DIR --base REF`")
        self.assert_one_error("`books.py <command> BOOKS_DIR --weekly`", "--weekly")

    def test_alias_declared_in_the_doc(self):
        doc = ("`Q` below is `uv run --python 3.12 <this skill>/scripts/books.py`.\n\n"
               f"{FENCE}\nQ summary BOOKS --month M\nQ ingest BOOKS\n{FENCE}\n")
        errors, checked = self.check(doc, "plugins/p/skills/books/references/weekly.md")
        self.assertEqual(checked, 3)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("weekly.md:5", errors[0])
        self.assertIn("no 'ingest' subcommand", errors[0])

    def test_snippets_are_checked_and_their_generated_copies_are_not_reported_twice(self):
        self.write("plugins/p/snippets/books.md", "Numbers come from `books.py totals BOOKS_DIR`.\n")
        doc = ("<!-- BEGIN GENERATED: snippet:books -->\nNumbers come from `books.py totals BOOKS_DIR`.\n"
               "<!-- END GENERATED: snippet:books -->\n\nThen `books.py check B --weekly`.\n")
        errors, _ = self.check(doc)
        self.assertEqual(len(errors), 2, errors)
        self.assertIn("plugins/p/snippets/books.md:1", errors[1])
        self.assertIn("SKILL.md:5", errors[0])

    def test_flag_before_the_subcommand_must_be_the_scripts_own(self):
        # argparse rejects `books.py --json summary`: --json belongs to summary and must follow it.
        self.assert_one_error("`books.py --json summary B --month M`", "--json", "before the subcommand", "--dir")
        self.assert_one_error("`books.py summary B --month M --dir X`", "--dir", "`books.py summary`")

    def test_a_script_run_after_another_command_is_still_checked(self):
        self.assert_one_error("`cd BOOKS && python3 scripts/books.py summary B --weekly`", "--weekly")
        self.assert_one_error("`git pull; scripts/weekly.sh --status`", "--status")
        self.assert_one_error("`echo $(books.py sumary B)`", "no 'sumary' subcommand")

    def test_a_flag_is_reported_whole(self):
        self.assert_one_error("`books.py summary B --month M --dryRun`", "passes --dryRun to")

    # --- text that is not a run of the script is left alone ---

    def test_a_script_another_program_reads_keeps_that_programs_flags(self):
        for doc in ("`uv run ruff check plugins/p/skills/books/scripts/books.py --select E`",
                    "`cat scripts/weekly.sh --show-ends`",
                    "`wc -l books.py --total`"):
            errors, _ = self.check(doc)
            self.assertEqual(errors, [], doc)

    def test_a_trailing_comment_is_not_arguments(self):
        self.assert_clean(f"{FENCE}\nscripts/books.py summary B --month M   # compare with git log --oneline\n{FENCE}\n")

    def test_the_projects_own_scripts_folder_is_not_a_skills(self):
        errors, _ = self.check("Run the project's tests with `./scripts/test.sh --fast`.\n")
        self.assertEqual(errors, [])

    def test_a_generated_marker_quoted_in_prose_hides_nothing(self):
        doc = ("Text between `<!-- BEGIN GENERATED -->` markers is written by make.\n\n`books.py summary B --weekly`\n\n"
               "<!-- BEGIN GENERATED x -->\nstuff\n<!-- END GENERATED x -->\n")
        self.assert_one_error(doc, "SKILL.md:3", "--weekly")

    def test_a_backtick_fence_inside_a_tilde_fence_is_text(self):
        doc = f"~~~\n{FENCE}\nscripts/books.py summary B --weekly\n{FENCE}\n~~~\n\n`books.py check B --weekly`\n"
        errors, checked = self.check(doc)
        self.assertEqual((len(errors), checked), (2, 2), errors)

    def test_a_file_of_the_same_name_in_another_folder_is_not_the_kit_script(self):
        errors, _ = self.check("Read `docs/books.py --y` too.\n")
        self.assertEqual(errors, [])

    # --- scripts written in other ordinary ways are read correctly ---

    def test_argparse_imported_by_name_aliases_and_negatable_flags(self):
        self.write("plugins/p/skills/other/scripts/tool.py", """
            from argparse import ArgumentParser, BooleanOptionalAction

            def main():
                p: ArgumentParser = ArgumentParser()
                sub = p.add_subparsers()
                rm = sub.add_parser("remove", aliases=["rm"])
                rm.add_argument("--color", action=BooleanOptionalAction)
        """)
        self.assert_clean("`scripts/tool.py rm --no-color` and `tool.py remove --color`", 2)
        self.assert_one_error("`scripts/tool.py rm --no-colour`", "--no-colour")

    def test_shell_script_that_tests_its_arguments_without_a_case(self):
        self.write("plugins/p/skills/other/scripts/tool.sh", """
            # --verbose is planned
            if [ "$1" = "--json" ]; then JSON=1; fi
        """)
        self.assert_clean("`scripts/tool.sh --json`")
        self.assert_one_error("`scripts/tool.sh --verbose`", "--verbose", "--json")

    # --- the check refuses to guess ---

    def test_argparse_call_it_cannot_trace_is_an_error_not_a_pass(self):
        self.write("plugins/p/skills/other/scripts/tool.py", """
            import argparse

            def common(p):
                p.add_argument("--verbose")

            def main():
                parser = argparse.ArgumentParser()
                common(parser)
        """)
        self.assert_one_error("No commands here.\n", "tool.py", "can't trace to a parser")

    def test_argparse_flag_that_is_not_a_literal_is_an_error_not_an_empty_script(self):
        self.write("plugins/p/skills/other/scripts/tool.py", """
            import argparse

            def main():
                p = argparse.ArgumentParser()
                for flag in ("--alpha", "--beta"):
                    p.add_argument(flag)
        """)
        # One error, on the script. The doc that uses it is not blamed for a flag the check can't see.
        self.assert_one_error("`scripts/tool.py --alpha 1`", "tool.py", "not a string literal")

    def test_two_skills_cannot_ship_the_same_script_name(self):
        self.write("plugins/p/skills/other/scripts/books.py", "import sys\n")
        self.assert_one_error("No commands here.\n", "'books.py'", "also used by")


if __name__ == "__main__":
    unittest.main()
