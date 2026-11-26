"""Tests for the skill-use book: `quality.py book-skills`, its rows in `check`, and `skills` in `summary`
(plugins/bstack/skills/qualitydirector/scripts/quality.py).

Every transcript here is invented. `book-skills` runs in process with HOME pointed at a temp folder, and is judged
by what it writes to books/skill-uses.csv, what it prints and what it returns.
"""
import contextlib
import csv
import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("QUALITY_SCRIPT")
              or ROOT / "plugins/bstack/skills/qualitydirector/scripts/quality.py")
FIXTURE = ROOT / "tests/fixtures/quality"

spec = importlib.util.spec_from_file_location("quality", SCRIPT)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)

HEADER = ",".join(quality.SKILLS_SCHEMA) + "\n"
SECRET = "PRIVATE-CONVERSATION-TEXT"  # stands for anything a person typed or a tool printed
DAY = "2026-11-10"  # a Tuesday in 2026-W46
TODAY = "2026-11-18"  # 2026-W47 is the open week
OLD_SHA, NEW_SHA = "a" * 40, "b" * 40
ROW = dict(zip(quality.SKILLS_SCHEMA, ("2026-W46", "alpha", "mine:@demo", NEW_SHA, "claude-code", "auto", "3", "1", "0",
                                       "unjudged", "0123456789abcdef", "1000", "200", "300")))
LEGACY_HEADER = ",".join(quality.SKILLS_LEGACY_SCHEMA) + "\n"  # the header R38 shipped, before the token columns


def stamp(n: int, day: str = DAY) -> str:
    return f"{day}T10:{n // 60:02d}:{n % 60:02d}.000Z"


class Session:
    """A Claude Code transcript under construction: each call adds one record, a second apart. Record and tool-call
    ids come from one counter, so no two sessions in a test share one unless the test copies the records."""
    serial = itertools.count(1)

    def __init__(self, day: str = DAY, **common):
        self.day, self.common, self.records = day, common, []

    def _add(self, kind: str, content, **extra) -> dict:
        record = {"type": kind, "timestamp": stamp(len(self.records), self.day), "uuid": f"uuid-{next(self.serial)}",
                  "isSidechain": False, "message": {"role": kind, "content": content}, **self.common, **extra}
        self.records.append(record)
        return record

    def prompt(self, text: str = SECRET, origin: str | None = "human") -> dict:
        return self._add("user", text, **({"origin": {"kind": origin}} if origin else {}))

    def respond(self, content: list, usage: tuple[int, int, int] | None = None, records: int = 1) -> None:
        """One model response, split over `records` assistant records that repeat its id and usage, as Claude Code
        writes a response with several parts."""
        message_id = f"msg_{next(self.serial)}"
        for _ in range(records):
            record = self._add("assistant", content)
            record["message"]["id"] = message_id
            if usage is not None:
                record["message"]["usage"] = dict(zip(("input_tokens", "output_tokens", "cache_creation_input_tokens"), usage),
                                                  cache_read_input_tokens=99999)

    def call(self, name: str, usage: tuple[int, int, int] | None = None, **given) -> str:
        tool_id = f"toolu_{next(self.serial)}"
        self.respond([{"type": "text", "text": SECRET}, {"type": "tool_use", "id": tool_id, "name": name, "input": given}], usage)
        return tool_id

    def result(self, tool_id: str, error: bool | None = False) -> None:
        part = {"type": "tool_result", "tool_use_id": tool_id, "content": SECRET}
        if error is not None:
            part["is_error"] = error
        self._add("user", [part])

    def skill(self, name: str, base: str = "/somewhere/plugins/demo/skills/alpha", usage: tuple[int, int, int] | None = None) -> str:
        """A Skill tool call, its result, and the record that loads the skill's text."""
        tool_id = self.call("Skill", usage, skill=name)
        self.result(tool_id)
        self._add("user", [{"type": "text", "text": f"Base directory for this skill: {base}\n\n{SECRET}"}],
                  isMeta=True, sourceToolUseID=tool_id)
        return tool_id

    def slash(self, name: str, origin: str | None = "human", base: str | None = "/somewhere/plugins/demo/skills/alpha") -> None:
        self.prompt(f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>\n"
                    f"<command-args>{SECRET}</command-args>", origin)
        if base is not None:
            self._add("user", [{"type": "text", "text": f"Base directory for this skill: {base}\n\n{SECRET}"}], isMeta=True)

    def work(self, count: int, tool: str = "Bash", error: bool | None = False, usage: tuple[int, int, int] | None = None) -> None:
        for _ in range(count):
            self.result(self.call(tool, usage, command=SECRET), error)

    def text(self) -> str:
        return "".join(json.dumps(r) + "\n" for r in self.records)


class SkillsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.books = self.tmp / "books-repo"
        shutil.copytree(FIXTURE, self.books)
        (self.books / quality.SKILLS).write_text(HEADER)
        self.home = self.tmp / "home"
        self.claude, self.cursor = self.home / ".claude/projects", self.home / ".cursor/projects"
        self.claude.mkdir(parents=True)
        self.cursor.mkdir(parents=True)
        patch = unittest.mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, session: Session, name: str = "s1.jsonl") -> Path:
        path = self.claude / "-some-project" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(session.text())
        return path

    def run_cli(self, *args) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = quality.main([str(a) for a in args])
        return code, out.getvalue()

    def book(self, *extra) -> tuple[int, str]:
        return self.run_cli("book-skills", self.books, "--today", TODAY, *extra)

    def rows(self) -> list[dict]:
        with open(self.books / quality.SKILLS, newline="") as f:
            return list(csv.DictReader(f))

    def booked(self, *extra) -> list[dict]:
        code, out = self.book(*extra)
        self.assertEqual(code, 0, out)
        return self.rows()

    def one(self, session: Session, *extra) -> dict:
        self.write(session)
        rows = self.booked(*extra)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]


class WhatCountsAsAUseTest(SkillsCase):
    def test_a_skill_tool_call_is_one_row_with_every_column(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        row = self.one(s)
        self.assertEqual({k: v for k, v in row.items() if k != "use"},
                         {"week": "2026-W46", "skill": "alpha", "source": "demo", "version": "", "tool": "claude-code",
                          "how": "auto", "calls": "0", "searches": "0", "errors": "0", "verdict": "unjudged",
                          "input_tokens": "0", "output_tokens": "0", "cache_write_tokens": "0"})
        self.assertRegex(row["use"], r"^[0-9a-f]{16}$")

    def test_a_typed_slash_command_that_loads_a_skill_is_a_use(self):
        s = Session()
        s.slash("demo:alpha")
        self.assertEqual(self.one(s)["how"], "typed")

    def test_a_slash_command_that_loads_no_skill_is_not_a_use(self):
        s = Session()
        s.slash("model", base=None)
        s.prompt()
        self.write(s)
        self.assertEqual(self.booked(), [])

    def test_a_read_of_an_installed_skill_file_is_a_use_and_a_read_in_a_checkout_is_not(self):
        s = Session()
        s.prompt()
        s.result(s.call("Read", file_path=f"{self.home}/.claude/skills/gamma/SKILL.md"))
        s.result(s.call("Read", file_path=f"{self.home}/code/kit/plugins/demo/skills/beta/SKILL.md"))
        s.result(s.call("Read", file_path=f"{self.home}/.claude/skills/gamma/README.md"))
        self.assertEqual(self.one(s)["skill"], "gamma")

    def test_reading_a_skill_file_the_chain_already_loaded_is_not_a_second_use(self):
        s = Session()
        s.prompt()
        s.skill("gamma", base=f"{self.home}/.claude/skills/gamma")
        for _ in range(2):
            s.result(s.call("Read", file_path=f"{self.home}/.claude/skills/gamma/SKILL.md"))
        self.assertEqual(self.one(s)["calls"], "2")

    def test_only_user_and_assistant_records_are_read(self):
        s = Session()
        s.prompt()
        tool_id = s.skill("demo:alpha")
        copy = {**s.records[1], "type": "api-request", "message": {"content": [
            {"type": "tool_use", "id": tool_id + "x", "name": "Skill", "input": {"skill": "demo:alpha"}}]}}
        s.records.append(copy)
        self.one(s)

    def test_a_name_the_books_would_refuse_is_counted_and_not_booked(self):
        s = Session()
        s.prompt()
        for name in ("=HYPERLINK(1)", "two words", "demo:" + "x" * 101, "a,b"):
            s.skill(name)
        self.write(s)
        code, out = self.book()
        self.assertEqual((code, self.rows()), (0, []), out)
        self.assertIn("4 with a name the books refuse", out)


class HowInvokedTest(SkillsCase):
    def how(self, session: Session) -> str:
        return self.one(session)["how"]

    def test_named_when_the_turn_before_names_the_skill(self):
        s = Session()
        s.prompt("please use dry-run-skill on this")
        s.skill("demo:dry-run-skill")
        self.assertEqual(self.how(s), "named")

    def test_auto_when_the_turn_before_does_not(self):
        s = Session()
        s.prompt("please fix the build")
        s.skill("demo:dry-run-skill")
        self.assertEqual(self.how(s), "auto")

    def test_subagent_when_the_call_is_in_a_sidechain(self):
        s = Session(isSidechain=True, agentId="agent-1")
        s.prompt("use dry-run-skill", origin=None)
        s.skill("demo:dry-run-skill")
        self.assertEqual(self.how(s), "subagent")

    def test_a_slash_command_from_another_session_is_named_not_typed(self):
        s = Session()
        s.slash("demo:alpha", origin="peer")
        self.assertEqual(self.how(s), "named")

    def test_a_slash_command_with_no_origin_is_typed_and_counted(self):
        s = Session()
        s.slash("demo:alpha", origin=None)
        self.write(s)
        code, out = self.book()
        self.assertEqual([r["how"] for r in self.rows()], ["typed"], out)
        self.assertIn("1 slash commands with no origin", out)

    def test_what_names_a_skill(self):
        cases = [("run beau-mode on it", "beau-mode", True), ("Beau Mode please", "beau-mode", True),
                 ("not-beau-mode-like", "beau-mode", False), ("how does this work", "how", False),
                 ("use /how here", "how", True), ("use demo:how here", "how", True), ("the how skill", "how", True),
                 ("skill how, then stop", "how", True), ("somehow", "how", False), ("", "how", False)]
        for text, skill, want in cases:
            with self.subTest(text=text, skill=skill):
                self.assertIs(quality.names_skill(text, skill), want)


class WindowTest(SkillsCase):
    def counts(self, session: Session) -> tuple[str, str, str]:
        row = self.one(session)
        return row["calls"], row["searches"], row["errors"]

    def test_counts_stop_at_twenty_tool_results(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.work(19)
        s.work(6, error=True)
        self.assertEqual(self.counts(s), ("20", "0", "1"))

    def test_a_tool_search_and_an_error_are_counted_and_a_missing_is_error_is_not_an_error(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.work(2, tool="ToolSearch")
        s.work(3, error=True)
        s.work(4, error=None)
        self.assertEqual(self.counts(s), ("9", "2", "3"))

    def test_the_window_ends_at_the_next_turn_a_human_typed(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.work(2)
        s.prompt(origin="task-notification")
        s.work(1)
        s.prompt(origin="human")
        s.work(5, error=True)
        self.assertEqual(self.counts(s), ("3", "0", "0"))

    def test_a_typed_command_counts_what_follows_it(self):
        s = Session()
        s.slash("demo:alpha")
        s.work(4, error=True)
        self.assertEqual(self.counts(s), ("4", "0", "4"))

    def test_another_chain_in_the_same_file_is_not_counted(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.work(2)
        s.common = {"isSidechain": True, "agentId": "agent-1"}
        s.work(7, error=True)
        self.assertEqual(self.counts(s), ("2", "0", "0"))


class TokensTest(SkillsCase):
    def tokens(self, session: Session) -> tuple[str, str, str]:
        row = self.one(session)
        return row["input_tokens"], row["output_tokens"], row["cache_write_tokens"]

    def test_each_response_after_the_load_counts_once_and_the_loading_response_does_not(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha", usage=(5, 5, 5))
        s.respond([{"type": "text", "text": SECRET}], (100, 10, 1000), records=3)
        s.work(2, usage=(1, 2, 3))
        self.assertEqual(self.tokens(s), ("102", "14", "1006"), "a response split over three records counts once; "
                         "cache reads are not booked; the response that called Skill is the cost before the use")

    def test_tokens_stop_where_the_counts_stop_at_twenty_tool_results(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.work(20, usage=(1, 1, 1))
        s.work(3, usage=(50, 50, 50))
        self.assertEqual(self.tokens(s), ("20", "20", "20"))

    def test_tokens_stop_at_the_next_typed_turn_and_leave_out_another_chain(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.work(1, usage=(1, 1, 1))
        common, s.common = s.common, {"isSidechain": True, "agentId": "agent-1"}
        s.work(2, usage=(7, 7, 7))
        s.common = common
        s.prompt(origin="human")
        s.work(2, usage=(9, 9, 9))
        self.assertEqual(self.tokens(s), ("1", "1", "1"))

    def test_a_later_part_of_the_response_that_made_the_load_is_not_counted(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha", usage=(5, 5, 5))
        loading = next(r for r in s.records if r["type"] == "assistant")
        s.records.append({**loading, "uuid": "uuid-later-part", "message": {**loading["message"], "content": [{"type": "text", "text": SECRET}]}})
        s.work(1, usage=(1, 1, 1))
        self.assertEqual(self.tokens(s), ("1", "1", "1"))

    def test_a_response_with_no_usage_counts_as_zero(self):
        s = Session()
        s.slash("demo:alpha")
        s.work(1)
        s.work(1, usage=(4, 0, 2))
        self.assertEqual(self.tokens(s), ("4", "0", "2"))


class LegacyHeaderTest(SkillsCase):
    """Books still on the header R38 shipped: every command keeps working on them, and migrate-skills moves them on."""
    def setUp(self):
        super().setUp()
        (self.books / quality.SKILLS).write_text(LEGACY_HEADER)
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.work(2, usage=(1, 2, 3))
        self.write(s)

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(self.books), *args],
                       check=True, capture_output=True)

    def test_book_skills_appends_rows_in_the_legacy_shape_and_says_how_to_add_tokens(self):
        code, out = self.book()
        self.assertEqual(code, 0, out)
        lines = (self.books / quality.SKILLS).read_text().splitlines()
        self.assertEqual((lines[0] + "\n", len(lines), lines[1].count(",")), (LEGACY_HEADER, 2, 10), lines)
        self.assertIn("run migrate-skills", out)
        self.assertEqual(self.run_cli("check", self.books)[0], 0)

    def test_summary_of_a_legacy_book_has_no_token_keys(self):
        self.book()
        result = json.loads(self.run_cli("summary", self.books, "--json", "--week", "2026-W46")[1])
        self.assertEqual(result["skills"]["by_skill"][0], {
            "skill": "alpha", "source": "demo", "uses": 1, "by_how": {"typed": 0, "named": 0, "auto": 1, "subagent": 0},
            "by_tool": {"claude-code": 1, "cursor": 0}, "calls": 2, "searches": 0, "errors": 0, "unjudged": 1})

    def test_migrate_adds_empty_token_cells_passes_append_only_and_runs_once(self):
        self.book()
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "books")
        before = (self.books / quality.SKILLS).read_text().splitlines()
        code, out = self.run_cli("migrate-skills", self.books)
        self.assertEqual((code, out), (0, f"added input_tokens, output_tokens, cache_write_tokens to {quality.SKILLS}: 1 rows keep them empty\n"))
        after = (self.books / quality.SKILLS).read_text()
        self.assertEqual(after, HEADER + before[1] + ",,,\n")
        self.assertEqual(self.run_cli("check", self.books, "--base", "HEAD")[0], 0)
        self.assertEqual(self.run_cli("migrate-skills", self.books)[0], 0)
        self.assertEqual((self.books / quality.SKILLS).read_text(), after, "a second migrate changes nothing")
        s = Session(day="2026-11-11")
        s.prompt()
        s.skill("demo:beta")
        s.work(1, usage=(7, 8, 9))
        self.write(s, "s2.jsonl")
        row = self.booked()[-1]
        self.assertEqual((row["skill"], row["input_tokens"], row["output_tokens"], row["cache_write_tokens"]), ("beta", "7", "8", "9"))
        self.assertEqual(self.run_cli("check", self.books, "--base", "HEAD")[0], 0)

    def test_a_migration_that_changes_an_old_cell_or_drops_the_padding_fails_append_only(self):
        """Planted faults: the exception for the migration covers adding empty cells and nothing else."""
        self.book()
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "books")
        path = self.books / quality.SKILLS
        old = path.read_text().splitlines()
        path.write_text(HEADER + old[1].replace(",auto,", ",named,") + ",,,\n")
        code, lines = self.run_cli("check", self.books, "--base", "HEAD")
        self.assertEqual(code, 1)
        self.assertIn("books/skill-uses.csv:2: changed since HEAD (beyond adding empty cells for the new columns)", lines)
        path.write_text(HEADER + old[1] + ",0,0,0\n")
        self.assertEqual(self.run_cli("check", self.books, "--base", "HEAD")[0], 1, "an old row may not gain measured tokens")
        path.write_text(HEADER + old[1] + "\n")
        self.assertEqual(self.run_cli("check", self.books, "--base", "HEAD")[0], 1, "a new header needs the cells too")


class RunTwiceTest(SkillsCase):
    def test_a_second_run_changes_nothing(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.slash("demo:alpha")
        self.write(s)
        self.assertEqual(len(self.booked()), 2)
        before = (self.books / quality.SKILLS).read_bytes()
        code, out = self.book()
        self.assertEqual((code, (self.books / quality.SKILLS).read_bytes()), (0, before))
        self.assertIn("booked 0 skill uses; 2 already booked", out)

    def test_a_use_copied_into_a_resumed_session_file_is_booked_once_with_its_longest_window(self):
        short = Session()
        short.prompt()
        short.skill("demo:alpha")
        short.work(2)
        long = Session()
        long.records = [dict(r) for r in short.records]
        long.work(3, error=True)
        for first, second in (("a.jsonl", "b.jsonl"), ("b.jsonl", "a.jsonl")):
            with self.subTest(long_copy=second):
                (self.books / quality.SKILLS).write_text(HEADER)
                self.write(short, first)
                self.write(long, second)
                rows = self.booked()
                self.assertEqual([(r["calls"], r["errors"]) for r in rows], [("5", "3")])

    def test_the_open_week_waits_and_is_booked_once_it_closes(self):
        s = Session(day="2026-11-17")
        s.prompt()
        s.skill("demo:alpha")
        self.write(s)
        code, out = self.book()
        self.assertEqual((code, self.rows()), (0, []), out)
        self.assertIn("1 in the open week", out)
        self.assertEqual([r["week"] for r in self.booked("--today", "2026-11-23")], ["2026-W47"])

    def test_since_leaves_out_earlier_uses(self):
        for day, name in (("2026-11-03", "old.jsonl"), (DAY, "new.jsonl")):
            s = Session(day=day)
            s.prompt()
            s.skill("demo:alpha")
            self.write(s, name)
        self.assertEqual([r["week"] for r in self.booked("--since", "2026-11-09")], ["2026-W46"])

    def test_dry_run_writes_nothing_and_json_reports_counts_only(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        self.write(s)
        code, out = self.book("--dry-run", "--json")
        report = json.loads(out)
        self.assertEqual((code, report["wrote"], report["dry_run"], report["weeks"]), (0, False, True, {"2026-W46": 1}))
        self.assertEqual(report["totals"]["booked"], 1)
        self.assertEqual(self.rows(), [])
        self.assertNotIn("alpha", out)

    def test_new_rows_go_after_the_old_ones(self):
        (self.books / quality.SKILLS).write_text(HEADER + ",".join(ROW[k] for k in quality.SKILLS_SCHEMA) + "\n")
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        self.write(s)
        rows = self.booked()
        self.assertEqual([r["use"] == ROW["use"] for r in rows], [True, False])


class PrivacyTest(SkillsCase):
    def test_no_transcript_text_reaches_the_book_or_the_output(self):
        s = Session()
        s.prompt()
        s.skill("demo:alpha")
        s.slash("demo:alpha")
        s.work(3, error=True)
        self.write(s)
        outputs = [self.book("--dry-run")[1], self.book("--dry-run", "--json")[1], self.book()[1]]
        self.assertEqual(len(self.rows()), 2)
        for text in outputs + [(self.books / quality.SKILLS).read_text()]:
            self.assertNotIn(SECRET, text)
            self.assertNotIn("some-project", text)
            self.assertNotIn("toolu_", text)


class RefusalsTest(SkillsCase):
    def test_books_without_the_file_are_refused_with_exit_2(self):
        (self.books / quality.SKILLS).unlink()
        code, out = self.book()
        self.assertEqual(code, 2)
        self.assertIn("books/skill-uses.csv", out)
        self.assertFalse((self.books / quality.SKILLS).exists())

    def test_books_that_fail_check_are_refused_with_exit_1(self):
        (self.books / quality.SKILLS).write_text(HEADER + "x\n")
        self.assertEqual(self.book()[0], 1)

    def test_bad_dates_and_a_missing_lock_are_usage_errors(self):
        for extra in (("--since", "yesterday"), ("--today", "2026-13-01"), ("--lock", self.tmp / "nope.lock")):
            with self.subTest(extra=extra):
                self.assertEqual(self.book(*extra)[0], 2)


class LockTest(SkillsCase):
    def lock(self, commit: str) -> str:
        return json.dumps({"version": 1, "sources": {}, "items": {
            "plugin:mine:@demo": {"commit": commit, "hash": "sha256:0"},
            "skill:shared:skills/gamma": {"commit": commit, "hash": "sha256:0"},
            "skill:vendor:skills/patterns": {"commit": commit, "hash": "sha256:0"}}})

    def setUp(self):
        super().setUp()
        self.lock_path = self.tmp / "profiles" / "agentfiles.lock"
        self.lock_path.parent.mkdir()
        self.lock_path.write_text(self.lock(NEW_SHA))

    def sources(self, *names: str) -> list[tuple[str, str, str]]:
        s = Session()
        s.prompt()
        for name in names:
            s.skill(name, base="/gone")
        self.write(s)
        return sorted((r["skill"], r["source"], r["version"]) for r in self.booked("--lock", self.lock_path))

    def test_a_plugin_skill_takes_the_plugins_lock_item(self):
        self.assertEqual(self.sources("demo:alpha"), [("alpha", "mine:@demo", NEW_SHA)])

    def test_a_standalone_skill_takes_its_own_item_with_or_without_the_source_prefix(self):
        self.assertEqual(self.sources("gamma", "bundle:vendor-patterns"),
                         [("gamma", "shared:skills/gamma", NEW_SHA), ("vendor-patterns", "vendor:skills/patterns", NEW_SHA)])

    def test_a_skill_no_item_installs_keeps_its_plugin_and_an_empty_version(self):
        (self.books / quality.SKILLS).write_text(HEADER)
        s = Session()
        s.prompt()
        s.skill("other:alpha", base="/gone")
        s.skill("loose", base="/gone")
        s.skill("demo:alpha", base="/gone")
        self.write(s)
        code, out = self.book("--lock", self.lock_path)
        self.assertEqual(sorted((r["skill"], r["source"], r["version"]) for r in self.rows()),
                         [("alpha", "mine:@demo", NEW_SHA), ("alpha", "other", ""), ("loose", "", "")], out)
        self.assertIn("of the 3: 2 not in the lock", out)

    def test_the_version_is_the_locks_commit_on_the_day_of_the_use(self):
        def git(*args, when=None):
            env = {**os.environ, **({"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {})}
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(self.lock_path.parent), *args],
                           check=True, capture_output=True, env=env)
        git("init", "-q")
        self.lock_path.write_text(self.lock(OLD_SHA))
        git("add", "-A")
        git("commit", "-q", "-m", "old pin", when="2026-11-01T00:00:00Z")
        self.lock_path.write_text(self.lock(NEW_SHA))
        git("commit", "-q", "-am", "new pin", when="2026-11-11T12:00:00Z")
        for day, name in (("2026-11-10", "before.jsonl"), ("2026-11-11", "same-day.jsonl"), ("2026-10-20", "no-commit-yet.jsonl")):
            s = Session(day=day)
            s.prompt()
            s.skill("demo:alpha", base="/gone")
            self.write(s, name)
        rows = self.booked("--lock", self.lock_path)
        self.assertEqual(sorted((r["week"], r["version"]) for r in rows),
                         [("2026-W43", NEW_SHA), ("2026-W46", OLD_SHA), ("2026-W46", NEW_SHA)])

    def test_a_bare_name_takes_its_plugin_from_the_folder_it_loaded_from(self):
        tree = self.tmp / "kit/plugins/demo/skills/alpha"
        tree.mkdir(parents=True)
        linked = self.home / ".agents/skills/alpha"
        linked.parent.mkdir(parents=True)
        linked.symlink_to(tree)
        opaque = self.home / "apps/plugin_01ABC/skills/alpha"
        opaque.mkdir(parents=True)
        (opaque.parent.parent / ".claude-plugin").mkdir()
        (opaque.parent.parent / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "demo"}))
        s = Session()
        s.prompt()
        s.skill("alpha", base=f"{self.home}/somewhere/plugins/demo/skills/alpha")
        s.skill("alpha", base=str(linked))
        s.skill("alpha", base=str(opaque))
        s.skill("alpha", base=f"{self.home}/code/project/.claude/skills/alpha")
        self.write(s)
        rows = self.booked("--lock", self.lock_path)
        self.assertEqual(sorted(r["source"] for r in rows), ["", "mine:@demo", "mine:@demo", "mine:@demo"])


class CursorTest(SkillsCase):
    def transcript(self, name: str, *paths: str, tool: str = "Read") -> Path:
        path = self.cursor / "workspace-x/agent-transcripts" / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True)
        lines = [{"role": "user", "message": {"content": [{"type": "text", "text": SECRET}]}}]
        lines += [{"role": "assistant", "message": {"content": [{"type": "tool_use", "name": tool, "input": {"path": p}}]}} for p in paths]
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        when = quality.datetime(2026, 11, 10, 12, tzinfo=quality.timezone.utc).timestamp()
        os.utime(path, (when, when))
        return path

    def test_one_row_per_transcript_and_skill_with_a_use_and_nothing_else(self):
        installed = f"{self.home}/.cursor/skills-cursor/alpha/SKILL.md"
        self.transcript("one", installed, installed, f"{self.home}/code/kit/skills/beta/SKILL.md")
        self.transcript("two", installed, tool="ReadFile")
        rows = self.booked()
        self.assertEqual([{k: r[k] for k in ("week", "skill", "tool", "how", "calls", "searches", "errors", "verdict") + quality.SKILL_TOKENS}
                          for r in rows],
                         [{"week": "2026-W46", "skill": "alpha", "tool": "cursor", "how": "", "calls": "", "searches": "",
                           "errors": "", "verdict": "unjudged", "input_tokens": "", "output_tokens": "", "cache_write_tokens": ""}] * 2)
        self.assertEqual(self.book()[1].splitlines()[0][:22], "booked 0 skill uses; 2")

    def test_a_resumed_transcript_whose_date_moved_is_not_booked_again(self):
        path = self.transcript("one", f"{self.home}/.cursor/skills-cursor/alpha/SKILL.md")
        self.assertEqual(len(self.booked()), 1)
        later = quality.datetime(2026, 11, 20, 12, tzinfo=quality.timezone.utc).timestamp()
        os.utime(path, (later, later))
        self.assertEqual(len(self.booked("--today", "2026-11-30")), 1)


class CheckSkillUsesTest(SkillsCase):
    def check(self, *extra) -> tuple[int, list[str]]:
        code, out = self.run_cli("check", self.books, *extra)
        return code, out.splitlines()

    def append(self, **cells) -> None:
        row = {**ROW, **cells}
        with open(self.books / quality.SKILLS, "a") as f:
            f.write(",".join(row[k] for k in quality.SKILLS_SCHEMA) + "\n")

    def test_books_without_the_file_and_with_a_header_only_file_both_pass(self):
        self.assertEqual(self.check(), (0, ["ok, 7 rows, 0 problems"]))
        (self.books / quality.SKILLS).unlink()
        self.assertEqual(self.check(), (0, ["ok, 7 rows, 0 problems"]))

    def test_a_good_row_of_each_tool_passes_and_is_counted(self):
        self.append()
        self.append(tool="cursor", how="", calls="", searches="", errors="", use="f" * 16, source="", version="",
                    input_tokens="", output_tokens="", cache_write_tokens="")
        self.assertEqual(self.check(), (0, ["ok, 9 rows, 0 problems"]))

    def test_each_bad_cell_is_named_on_its_line(self):
        bad = {"week": "2026-W60", "skill": "two words", "source": "=cmd", "version": "abc", "tool": "codex",
               "how": "explicit", "calls": "21", "searches": "4", "errors": "-1", "verdict": "effective", "use": "XYZ"}
        for column, value in bad.items():
            with self.subTest(column=column):
                (self.books / quality.SKILLS).write_text(HEADER)
                self.append(**{column: value})
                code, lines = self.check()
                self.assertEqual(code, 1, lines)
                self.assertTrue(lines[0].startswith("books/skill-uses.csv:2: "), lines)

    def test_token_cells_are_all_or_none_and_none_on_a_cursor_row(self):
        self.append(input_tokens="", output_tokens="", cache_write_tokens="")
        self.assertEqual(self.check()[0], 0, "a row booked before the token columns has none")
        for cells in ({"output_tokens": ""}, {"input_tokens": "-1"}, {"tool": "cursor", "how": "", "calls": "", "searches": "",
                                                                       "errors": "", "source": "", "version": ""}):
            with self.subTest(cells=cells):
                (self.books / quality.SKILLS).write_text(HEADER)
                self.append(**cells)
                code, lines = self.check()
                self.assertEqual(code, 1, lines)
                self.assertTrue(lines[0].startswith("books/skill-uses.csv:2: "), lines)

    def test_a_cursor_row_with_counts_and_a_claude_code_row_without_them_are_problems(self):
        self.append(tool="cursor")
        self.append(calls="", searches="", errors="", use="f" * 16)
        code, lines = self.check()
        self.assertEqual((code, [l.split(":")[1] for l in lines[:-1]]), (1, ["2", "3"]), lines)

    def test_the_same_use_twice_is_a_problem(self):
        self.append()
        self.append(skill="beta")
        code, lines = self.check()
        self.assertEqual(code, 1)
        self.assertIn("books/skill-uses.csv:3: duplicate of line 2 (same use)", lines)

    def test_a_wrong_header_is_a_problem(self):
        (self.books / quality.SKILLS).write_text("week,skill\n")
        self.assertEqual(self.check()[0], 1)

    def test_the_book_is_append_only_against_a_base(self):
        def git(*args):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(self.books), *args],
                           check=True, capture_output=True)
        self.append()
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "books")
        self.append(use="f" * 16)
        self.assertEqual(self.check("--base", "HEAD")[0], 0)
        path = self.books / quality.SKILLS
        path.write_text(path.read_text().replace(",auto,", ",named,", 1))
        code, lines = self.check("--base", "HEAD")
        self.assertEqual((code, lines[0]), (1, "books/skill-uses.csv:2: changed since HEAD"))
        path.unlink()
        self.assertIn("books/skill-uses.csv:1: removed since HEAD", self.check("--base", "HEAD")[1])


class SummaryTest(SkillsCase):
    def summary(self, *extra) -> str:
        code, out = self.run_cli("summary", self.books, *extra)
        self.assertEqual(code, 0, out)
        return out

    def test_books_without_the_file_print_what_they_printed_before_the_book_existed(self):
        (self.books / quality.SKILLS).unlink()
        self.assertEqual(self.summary("--json"), (ROOT / "tests/fixtures/quality-summary.json").read_text())

    def test_uses_per_skill_for_the_week_most_used_first(self):
        week = json.loads(self.summary("--json"))["week"]
        rows = [dict(ROW, week=week, use=f"{i:016x}") for i in range(5)]
        rows[0].update(input_tokens="1001")
        rows[1].update(how="typed", calls="20", searches="0", errors="4", input_tokens="", output_tokens="", cache_write_tokens="")
        rows[2].update(tool="cursor", how="", calls="", searches="", errors="", input_tokens="", output_tokens="", cache_write_tokens="")
        rows[3].update(skill="beta", source="", version="", how="subagent", input_tokens="10", output_tokens="0", cache_write_tokens="1")
        rows[4].update(week="2026-W40")
        (self.books / quality.SKILLS).write_text(HEADER + "".join(",".join(r[k] for k in quality.SKILLS_SCHEMA) + "\n" for r in rows))
        result = json.loads(self.summary("--json"))
        self.assertEqual(result["skills"], {"uses": 4, "window": 20, "by_skill": [
            {"skill": "alpha", "source": "mine:@demo", "uses": 3, "by_how": {"typed": 1, "named": 0, "auto": 1, "subagent": 0},
             "by_tool": {"claude-code": 2, "cursor": 1}, "calls": 23, "searches": 1, "errors": 4, "unjudged": 3,
             "input_tokens": 1001, "output_tokens": 200, "cache_write_tokens": 300, "token_uses": 1, "tokens_per_use": 1501},
            {"skill": "beta", "source": "", "uses": 1, "by_how": {"typed": 0, "named": 0, "auto": 0, "subagent": 1},
             "by_tool": {"claude-code": 1, "cursor": 0}, "calls": 3, "searches": 1, "errors": 0, "unjudged": 1,
             "input_tokens": 10, "output_tokens": 0, "cache_write_tokens": 1, "token_uses": 1, "tokens_per_use": 11}]},
            "tokens per use count only the rows that measured them: not the cursor row, not one booked before the columns")
        without = {k: v for k, v in result.items() if k != "skills"}
        self.assertEqual(without, json.loads((ROOT / "tests/fixtures/quality-summary.json").read_text()))
        self.assertIn("skills: 4 uses of 2 skills", self.summary())

    def test_tokens_per_use_is_rounded_to_a_whole_token_and_none_when_nothing_measured_them(self):
        week = json.loads(self.summary("--json"))["week"]
        rows = [dict(ROW, week=week, use=f"{i:016x}", input_tokens=str(n), output_tokens="0", cache_write_tokens="0")
                for i, n in enumerate((1, 2))]
        rows.append(dict(ROW, week=week, skill="beta", use="f" * 16, input_tokens="", output_tokens="", cache_write_tokens=""))
        (self.books / quality.SKILLS).write_text(HEADER + "".join(",".join(r[k] for k in quality.SKILLS_SCHEMA) + "\n" for r in rows))
        by_skill = json.loads(self.summary("--json"))["skills"]["by_skill"]
        self.assertEqual([(s["skill"], s["token_uses"], s["tokens_per_use"]) for s in by_skill], [("alpha", 2, 2), ("beta", 0, None)])

    def test_a_header_only_book_reports_zero_uses(self):
        self.assertEqual(json.loads(self.summary("--json"))["skills"], {"by_skill": [], "uses": 0, "window": 20})


if __name__ == "__main__":
    unittest.main()
