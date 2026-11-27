"""Tests for bstack's Stop hook (plugins/bstack/hooks/stop_checks.py), run as Claude Code runs it:
JSON on stdin, a real git repo with .agents/checks.yaml, and a fake `ledger` on PATH."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins/bstack/hooks"
HOOK = HOOKS / "stop_checks.py"

FAKE_LEDGER = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LEDGER_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
"""

EDIT = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": "a.py"}}]}}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


class StopChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        (self.repo / ".agents").mkdir(parents=True)
        git(self.repo, "init", "-q")
        git(self.repo, "remote", "add", "origin", "https://github.com/tester/repo.git")
        (self.repo / "ok").write_text("yes\n")
        self.configure('stop: ["test \\"$(cat ok)\\" = yes", "true"]')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        self.policy = self.tmp / "policy.yaml"
        flags = self.tmp / "flags"
        (flags / ".audit" / "runs").mkdir(parents=True)
        (self.tmp / "flags.yaml").write_text(f"root: '{flags}'\nmachine: 'test-mac'\n")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "ledger").write_text(FAKE_LEDGER)
        (bin_dir / "ledger").chmod(0o755)
        self.ledger_log = self.tmp / "ledger.log"
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "BSTACK_POLICY": str(self.policy), "BSTACK_FLAGS": str(self.tmp / "flags.yaml"),
                    "BSTACK_CHECKS_STATE": str(self.tmp / "state"), "FAKE_LEDGER_LOG": str(self.ledger_log)}
        self.set_mode("enforce")

    def configure(self, text):
        (self.repo / ".agents" / "checks.yaml").write_text(text + "\n")

    def set_mode(self, mode):
        self.policy.write_text(f"version: 1\nidentity:\n  human: 'tester@github'\nchecks:\n  stop-checks: '{mode}'\n")

    def break_tree(self):
        (self.repo / "ok").write_text("no\n")

    def stop(self, transcript=(EDIT,), session="s1", cwd=None):
        path = self.tmp / f"{session}.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in transcript))
        event = {"session_id": session, "transcript_path": str(path), "cwd": str(cwd or self.repo),
                 "hook_event_name": "Stop", "stop_hook_active": False}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                             text=True, env=self.env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def outcomes(self):
        if not self.ledger_log.exists():
            return []
        calls = [json.loads(line) for line in self.ledger_log.read_text().splitlines()]
        return [json.loads(c[c.index("--data") + 1])["outcome"] for c in calls if c[0] == "append"]

    def test_a_green_tree_stops_quietly(self):
        self.assertIsNone(self.stop())
        self.assertEqual(self.outcomes(), [])

    def test_enforce_sends_a_red_tree_back_with_the_failing_output(self):
        self.break_tree()
        out = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn('failed in repo', out["reason"])
        self.assertIn("send-back 1 of 2", out["reason"])
        self.assertEqual(self.outcomes(), ["deny"])

    def test_after_two_send_backs_the_stop_goes_through_and_says_why(self):
        self.break_tree()
        self.assertEqual(self.stop()["decision"], "block")
        self.assertEqual(self.stop()["decision"], "block", "still red, so it reruns with no new edit")
        self.assertIsNone(self.stop())
        self.assertEqual(self.outcomes(), ["deny", "deny", "let-through"])

    def test_fixing_the_tree_clears_the_count(self):
        self.break_tree()
        self.stop()
        (self.repo / "ok").write_text("yes\n")
        self.assertIsNone(self.stop())
        self.break_tree()
        self.assertIn("send-back 1 of 2", self.stop()["reason"])

    def test_observe_logs_and_lets_the_stop_through_once_per_tree(self):
        self.set_mode("observe")
        self.break_tree()
        self.assertIsNone(self.stop())
        self.assertIsNone(self.stop())
        self.assertEqual(self.outcomes(), ["observe"], "an unchanged red tree is logged once")

    def test_off_runs_nothing(self):
        self.set_mode("off")
        self.break_tree()
        self.assertIsNone(self.stop())
        self.assertEqual(self.outcomes(), [])

    def test_a_session_that_changed_nothing_runs_nothing(self):
        self.break_tree()
        self.assertIsNone(self.stop(transcript=[]), "the red tree predates the session, which only read")
        self.assertEqual(self.outcomes(), [])

    def test_an_edit_outside_the_repo_does_not_judge_it(self):
        self.break_tree()
        elsewhere = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "e2", "name": "Write", "input": {"file_path": str(self.tmp / "notes.md")}}]}}
        self.assertIsNone(self.stop(transcript=(elsewhere,)))

    def test_an_edit_made_from_a_parent_folder_judges_the_repo_it_landed_in(self):
        self.break_tree()
        edit = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "e3", "name": "Edit", "input": {"file_path": str(self.repo / "ok")}}]}}
        self.assertEqual(self.stop(transcript=(edit,), cwd=self.tmp)["decision"], "block")

    def test_a_change_made_through_bash_is_judged(self):
        self.break_tree()
        bash = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "sed -i '' s/yes/no/ ok"}}]}}
        self.assertEqual(self.stop(transcript=(bash,))["decision"], "block")

    def test_a_new_untracked_files_content_moves_the_tree(self):
        self.configure('stop: ["test \\"$(cat new)\\" = fine"]')
        (self.repo / "new").write_text("fine\n")
        self.assertIsNone(self.stop())
        (self.repo / "new").write_text("broken\n")
        self.assertEqual(self.stop()["decision"], "block")

    def test_a_repo_someone_else_owns_runs_nothing(self):
        git(self.repo, "remote", "set-url", "origin", "https://github.com/someone-else/repo.git")
        marker = self.tmp / "ran"
        self.configure(f'stop: ["touch {marker}; exit 1"]')
        self.set_mode("observe")
        self.assertIsNone(self.stop())
        self.assertFalse(marker.exists(), "an untrusted repo's checks.yaml must never run")

    def test_a_later_stop_runs_only_when_the_tree_moved(self):
        self.assertIsNone(self.stop())
        self.configure('stop: ["false"]')
        self.assertEqual(self.stop()["decision"], "block", "checks.yaml changed, so the tree moved")
        git(self.repo, "checkout", "--", ".agents/checks.yaml")
        self.assertIsNone(self.stop(), "a green tree ends the run of send-backs")
        self.assertIsNone(self.stop(), "and an unmoved tree runs nothing")

    def test_a_repo_without_checks_or_outside_git_does_nothing(self):
        (self.repo / ".agents" / "checks.yaml").unlink()
        self.break_tree()
        self.assertIsNone(self.stop())
        outside = self.tmp / "plain"
        outside.mkdir()
        event = {"session_id": "x", "transcript_path": "", "cwd": str(outside)}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                             text=True, env=self.env, timeout=60)
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_block_lists_comments_and_quotes_parse(self):
        sys.path.insert(0, str(HOOKS))
        import stop_checks
        self.configure("# cheap ones\nstop:\n  - 'make check'   # fast\n  - \"echo 'it''s'\"\n  - 'it''s'\n  - exit 1\ntimeout_s: 30")
        self.assertEqual(stop_checks.read_config(self.repo), (["make check", "echo 'it''s'", "it's", "exit 1"], 30))
        self.configure('stop: ["a && b", \'c\']')
        self.assertEqual(stop_checks.read_config(self.repo), (["a && b", "c"], 120))

    def test_a_check_that_hangs_is_cut_off_and_reported(self):
        self.configure('stop: ["sleep 5"]\ntimeout_s: 1')
        out = self.stop()
        self.assertIn("timed out after 1s", out["reason"])

    def test_a_broken_event_fails_open(self):
        out = subprocess.run([sys.executable, str(HOOK)], input="{", capture_output=True, text=True,
                             env=self.env, timeout=60)
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        self.assertIn("skipped", out.stderr)


if __name__ == "__main__":
    unittest.main()
