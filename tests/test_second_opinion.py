"""Tests for beau-mode's second_opinion.py: one prompt to another agent CLI, one result back.

The tests put fake `claude` and `cursor-agent` executables first on PATH. A fake prints canned output chosen by
environment variables, so nothing here starts a real CLI or touches the network.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/beau-mode/scripts/second_opinion.py"

FAKE = f'''#!{sys.executable}
import json, os, subprocess, sys, time
name = os.path.basename(sys.argv[0])
prompt = sys.stdin.read()
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "sleep":
    time.sleep(float(os.environ.get("FAKE_START_DELAY", "0")))
    child = subprocess.Popen(["sleep", "30"])
    with open(os.environ["FAKE_PIDFILE"], "w") as f:
        f.write(str(child.pid))
    time.sleep(30)
if mode == "fail":
    sys.stderr.write("\\n".join("line %d" % i for i in range(40)) + "\\n")
    sys.exit(3)
if mode == "garbage":
    print("not json at all")
    sys.exit(0)
text = {{"ok": "the answer", "blank": "  \\n", "iserror": "boom"}}.get(mode)
if mode == "echo":
    text = json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "ls": sorted(os.listdir(".")), "stdin": prompt}})
body = {{"result": text, "is_error": mode == "iserror"}}
if name == "claude":
    body["total_cost_usd"] = 0.25
else:
    body.update({{"type": "result", "subtype": "success"}})
print(json.dumps(body))
'''


class SecondOpinionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name in ("claude", "cursor-agent"):
            path = self.bin / name
            path.write_text(FAKE)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.prompt = self.dir / "prompt.md"
        self.prompt.write_text("review this please")

    def run_so(self, *args, mode="ok", path=None, stdin=None, timeout=60, start_delay=0):
        env = {**os.environ, "PATH": path if path is not None else f"{self.bin}{os.pathsep}{os.environ['PATH']}",
               "FAKE_MODE": mode, "FAKE_PIDFILE": str(self.dir / "pid"), "FAKE_START_DELAY": str(start_delay)}
        done = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env,
                              input=stdin, timeout=timeout)
        return done.returncode, done.stdout, done.stderr

    def review(self, reviewer="cli:claude:opus", *extra, **kw):
        code, out, err = self.run_so("--reviewer", reviewer, "--prompt-file", str(self.prompt), "--json", *extra, **kw)
        return code, json.loads(out), err

    def echoed(self, reviewer="cli:claude:opus", *extra):
        code, res, _ = self.review(reviewer, *extra, mode="echo")
        self.assertEqual((code, res["status"]), (0, "ok"))
        return json.loads(res["answer"])


class StatusTest(SecondOpinionCase):
    def test_ok_for_each_agent(self):
        code, res, _ = self.review("cli:claude:opus")
        self.assertEqual((code, res["status"], res["answer"], res["cost_usd"]), (0, "ok", "the answer", 0.25))
        self.assertEqual((res["reviewer"], res["agent"], res["model"]), ("cli:claude:opus", "claude", "opus"))
        code, res, _ = self.review("cli:cursor-agent:gpt-5.6-sol-high")
        self.assertEqual((code, res["status"], res["answer"], res["cost_usd"]), (0, "ok", "the answer", None))
        self.assertEqual(res["model"], "gpt-5.6-sol-high")
        self.assertEqual(set(res), {"reviewer", "agent", "model", "status", "answer", "seconds", "cost_usd", "detail"})

    def test_a_model_keeps_every_character_after_the_second_colon(self):
        _, res, _ = self.review("cli:cursor-agent:vendor:model:x")
        self.assertEqual(res["model"], "vendor:model:x")

    def test_is_error_true_is_an_error_even_with_exit_zero(self):
        for reviewer in ("cli:claude:opus", "cli:cursor-agent:m"):
            code, res, _ = self.review(reviewer, mode="iserror")
            self.assertEqual((code, res["status"], res["answer"]), (1, "error", ""))
            self.assertIn("boom", res["detail"])

    def test_a_blank_result_is_empty(self):
        for reviewer in ("cli:claude:opus", "cli:cursor-agent:m"):
            code, res, _ = self.review(reviewer, mode="blank")
            self.assertEqual((code, res["status"]), (1, "empty"))

    def test_exit_zero_with_output_that_is_not_json_is_an_error(self):
        for reviewer in ("cli:claude:opus", "cli:cursor-agent:m"):
            code, res, _ = self.review(reviewer, mode="garbage")
            self.assertEqual((code, res["status"]), (1, "error"))
            self.assertIn("not JSON", res["detail"])

    def test_a_non_zero_exit_is_an_error_with_the_end_of_stderr(self):
        code, res, _ = self.review(mode="fail")
        self.assertEqual((code, res["status"]), (1, "error"))
        self.assertIn("exit 3", res["detail"])
        self.assertIn("line 39", res["detail"])
        self.assertNotIn("line 5\n", res["detail"])
        self.assertEqual(len(res["detail"].splitlines()), 21)

    def test_a_missing_binary(self):
        empty = self.dir / "empty"
        empty.mkdir()
        code, res, _ = self.review(path=str(empty))
        self.assertEqual((code, res["status"]), (1, "missing"))

    def test_without_json_the_answer_goes_to_stdout_and_a_failure_to_stderr(self):
        code, out, err = self.run_so("--reviewer", "cli:claude:opus", "--prompt-file", str(self.prompt))
        self.assertEqual((code, out, err), (0, "the answer\n", ""))
        code, out, err = self.run_so("--reviewer", "cli:claude:opus", "--prompt-file", str(self.prompt), mode="garbage")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("error", err)


class UsageTest(SecondOpinionCase):
    def test_bad_specs_and_unknown_agents_exit_two_with_no_result(self):
        for reviewer in ("claude:opus", "cli:claude", "cli::opus", "cli:claude:", "cli:codex:gpt", "opus", ""):
            code, out, err = self.run_so("--reviewer", reviewer, "--prompt-file", str(self.prompt), "--json")
            self.assertEqual((code, out), (2, ""), reviewer)
            self.assertIn("error:", err)

    def test_a_missing_prompt_file_or_cwd_exits_two(self):
        code, out, _ = self.run_so("--reviewer", "cli:claude:opus", "--prompt-file", str(self.dir / "nope"))
        self.assertEqual((code, out), (2, ""))
        code, out, _ = self.run_so("--reviewer", "cli:claude:opus", "--prompt-file", str(self.prompt), "--cwd", str(self.dir / "nope"))
        self.assertEqual((code, out), (2, ""))

    def test_list_says_which_binaries_are_on_path(self):
        code, out, _ = self.run_so("--list")
        self.assertEqual((code, out.splitlines()), (0, ["claude: found", "cursor-agent: found"]))
        empty = self.dir / "empty"
        empty.mkdir()
        code, out, _ = self.run_so("--list", path=str(empty))
        self.assertEqual((code, out.splitlines()), (0, ["claude: missing", "cursor-agent: missing"]))


class InvocationTest(SecondOpinionCase):
    def test_the_prompt_reaches_stdin(self):
        self.assertEqual(self.echoed()["stdin"], "review this please")

    def test_the_prompt_can_come_from_stdin(self):
        code, out, _ = self.run_so("--reviewer", "cli:claude:opus", "--prompt-file", "-", "--json", mode="echo", stdin="from stdin")
        self.assertEqual(json.loads(json.loads(out)["answer"])["stdin"], "from stdin")

    def test_claude_runs_read_only_and_isolated(self):
        argv = self.echoed("cli:claude:opus")["argv"]
        self.assertEqual(argv[:5], ["-p", "--model", "opus", "--output-format", "json"])
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        for flag in ("--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, argv)

    def test_cursor_agent_runs_read_only(self):
        argv = self.echoed("cli:cursor-agent:gpt-x")["argv"]
        self.assertEqual(argv, ["-p", "--model", "gpt-x", "--output-format", "json", "--mode", "ask", "--trust"])

    def test_the_default_cwd_is_a_new_empty_folder_removed_afterwards(self):
        seen = self.echoed()
        self.assertEqual(seen["ls"], [])
        self.assertFalse(os.path.exists(seen["cwd"]))
        self.assertNotEqual(os.path.realpath(seen["cwd"]), os.path.realpath(os.getcwd()))

    def test_cwd_is_honoured(self):
        work = self.dir / "work"
        work.mkdir()
        (work / "code.py").write_text("x")
        seen = self.echoed("cli:claude:opus", "--cwd", str(work))
        self.assertEqual((os.path.realpath(seen["cwd"]), seen["ls"]), (os.path.realpath(work), ["code.py"]))
        self.assertTrue(work.exists())


class TimeoutTest(SecondOpinionCase):
    def assert_timeout_kills_the_grandchild(self, start_delay):
        began = time.monotonic()
        code, res, _ = self.review("cli:claude:opus", "--timeout", "1", mode="sleep", timeout=20, start_delay=start_delay)
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual((code, res["status"]), (1, "timeout"))
        pid = int((self.dir / "pid").read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        os.kill(pid, 9)
        self.fail("the grandchild survived the timeout")

    def test_a_timeout_kills_the_cli_and_what_it_started(self):
        self.assert_timeout_kills_the_grandchild(start_delay=0)

    def test_a_cli_slower_to_start_than_the_timeout_still_has_its_grandchild_killed(self):
        self.assert_timeout_kills_the_grandchild(start_delay=2)


if __name__ == "__main__":
    unittest.main()
