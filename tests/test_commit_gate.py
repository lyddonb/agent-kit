"""Tests for bstack's commit gate hook (plugins/bstack/hooks/commit_gate.py), run as Claude Code
runs it: JSON on stdin, a transcript on disk, and a fake `ledger` on PATH."""
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugins/bstack/hooks/commit_gate.py"

FAKE_LEDGER = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LEDGER_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
"""


def use(uid, name, **args):
    return {"type": "assistant", "message": {"model": "claude-opus-5-5", "content": [
        {"type": "tool_use", "id": uid, "name": name, "input": args}]}}


def result(uid, error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "is_error": error}]}}


COMMIT = "git add -A && git commit -m 'feat: x'"


class CommitGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.policy = self.tmp / "policy.yaml"
        self.flags_root = self.tmp / "flags"
        (self.flags_root / ".audit" / "runs").mkdir(parents=True)
        (self.tmp / "flags.yaml").write_text(f"root: '{self.flags_root}'\nmachine: 'test-mac'\n")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "ledger").write_text(FAKE_LEDGER)
        (bin_dir / "ledger").chmod(0o755)
        self.ledger_log = self.tmp / "ledger.log"
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "BSTACK_POLICY": str(self.policy), "BSTACK_FLAGS": str(self.tmp / "flags.yaml"),
                    "BSTACK_CHECKS_STATE": str(self.tmp / "state"), "FAKE_LEDGER_LOG": str(self.ledger_log)}
        self.set_policy("observe")

    def set_policy(self, mode, human="tester@github"):
        lines = ["version: 1", "identity:", f"  human: '{human}'", "approvers: {}"]
        if mode:
            lines += ["checks:", f"  commit-gate: '{mode}'"]
        self.policy.write_text("\n".join(lines) + "\n")

    def run_hook(self, transcript, command=COMMIT, session="sess-1", tool="Bash"):
        path = self.tmp / (re.sub(r"[^A-Za-z0-9-]", "_", session) + ".jsonl")
        path.write_text("".join(json.dumps(e) + "\n" for e in transcript))
        event = {"session_id": session, "transcript_path": str(path), "cwd": str(self.repo),
                 "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                             text=True, env=self.env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout.strip() else None, out.stderr

    def logged(self):
        if not self.ledger_log.exists():
            return []
        calls = [json.loads(line) for line in self.ledger_log.read_text().splitlines()]
        return [json.loads(c[c.index("--data") + 1]) for c in calls if c[0] == "append"]

    def assert_denied(self, out):
        self.assertIsNotNone(out, "an enforced gate denies a commit nothing verified")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_observe_logs_one_would_block_and_allows_the_commit(self):
        out, _ = self.run_hook([use("t1", "Edit", file_path="a.py")])
        self.assertIsNone(out, "observe never blocks")
        [entry] = self.logged()
        self.assertEqual((entry["kind"], entry["check"], entry["outcome"], entry["repo"]),
                         ("would-block", "commit-gate", "observe", "repo"))

    def test_a_policy_without_checks_observes(self):
        self.set_policy(None)
        self.assertIsNone(self.run_hook([])[0])
        self.assertEqual([e["outcome"] for e in self.logged()], ["observe"])

    def test_off_does_nothing(self):
        self.set_policy("off")
        self.assertIsNone(self.run_hook([])[0])
        self.assertEqual(self.logged(), [])

    def test_enforce_denies_twice_then_lets_the_third_through_and_records_why(self):
        self.set_policy("enforce")
        transcript = [use("t1", "Edit", file_path="a.py")]
        for n in (1, 2):
            out, _ = self.run_hook(transcript)
            self.assert_denied(out)
            self.assertIn(f"stop {n} of 2", out["hookSpecificOutput"]["permissionDecisionReason"])
            transcript += [use(f"c{n}", "Bash", command=COMMIT), result(f"c{n}", error=True)]
        self.assertIsNone(self.run_hook(transcript)[0], "the third attempt goes through")
        self.assertEqual([e["outcome"] for e in self.logged()], ["deny", "deny", "let-through"])
        self.assertIn("let through after 2 stops", self.logged()[-1]["reason"])

    def test_the_count_starts_again_after_a_commit_goes_through(self):
        self.set_policy("enforce")
        self.assert_denied(self.run_hook([])[0])
        self.assert_denied(self.run_hook([])[0])
        self.assertIsNone(self.run_hook([])[0])
        landed = [use("c3", "Bash", command=COMMIT), result("c3")]
        self.assert_denied(self.run_hook(landed)[0])

    def test_each_kind_of_verification_clears_the_gate(self):
        self.set_policy("enforce")
        kinds = {
            "verify-work skill": use("v", "Skill", skill="bstack:verify-work"),
            "a verify-app skill": use("v", "Skill", skill="verify-curator"),
            "interrogate": use("v", "Skill", skill="bstack:interrogate"),
            "code-review": use("v", "Skill", skill="code-review"),
            "a review subagent": use("v", "Agent", subagent_type="pr-review-toolkit:code-reviewer", prompt="x"),
            "a second opinion": use("v", "Bash", command="python3 scripts/second_opinion.py --reviewer x"),
            "a typed /verify-work": {"type": "user", "message": {"content":
                                     "<command-name>/bstack:verify-work</command-name>"}},
        }
        for name, entry in kinds.items():
            with self.subTest(name):
                self.assertIsNone(self.run_hook([entry], session=name.replace(" ", "-"))[0])
        self.assertEqual(self.logged(), [])

    def test_verification_before_the_last_commit_does_not_count_for_the_next(self):
        self.set_policy("enforce")
        transcript = [use("v", "Skill", skill="bstack:verify-work"),
                      use("c1", "Bash", command=COMMIT), result("c1"), use("e", "Edit", file_path="b.py")]
        self.assert_denied(self.run_hook(transcript)[0])

    def test_unrelated_skills_and_subagents_do_not_count(self):
        self.set_policy("enforce")
        transcript = [use("a", "Skill", skill="bstack:beau-mode"), use("b", "Agent", subagent_type="Explore")]
        self.assert_denied(self.run_hook(transcript)[0])

    def test_only_git_commit_is_judged(self):
        self.set_policy("enforce")
        for command in ("git status", "git log --oneline", "echo commit", "git commit-tree x", "ls commit/"):
            with self.subTest(command):
                self.assertIsNone(self.run_hook([], command=command)[0])
        self.assertIsNone(self.run_hook([], tool="Edit")[0])
        for command in ("git -C repo commit -m x", "cd a && git commit -am x", "GIT_EDITOR=true git commit",
                        "git -c user.name=x commit -m y", "git commit"):
            with self.subTest(command):
                self.assert_denied(self.run_hook([], command=command, session=command)[0])

    def test_a_repo_policy_can_raise_the_mode_but_not_lower_it(self):
        (self.repo / ".agents").mkdir()
        (self.repo / ".agents" / "policy.yaml").write_text("checks:\n  commit-gate: enforce\n")
        self.assert_denied(self.run_hook([])[0])
        self.set_policy("enforce")
        (self.repo / ".agents" / "policy.yaml").write_text("checks:\n  commit-gate: off\n")
        self.assert_denied(self.run_hook([], session="s2")[0])

    def test_a_missing_identity_still_gates_and_says_it_could_not_log(self):
        self.set_policy("enforce", human="not an id")
        out, err = self.run_hook([])
        self.assert_denied(out)
        self.assertIn("not logged", err)
        self.assertEqual(self.logged(), [])

    def test_a_broken_event_fails_open(self):
        out = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True,
                             env=self.env, timeout=30)
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        self.assertIn("skipped", out.stderr)

    def test_a_missing_transcript_counts_as_unverified(self):
        self.set_policy("enforce")
        event = {"session_id": "x", "transcript_path": str(self.tmp / "nope.jsonl"), "cwd": str(self.repo),
                 "tool_name": "Bash", "tool_input": {"command": COMMIT}}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True,
                             text=True, env=self.env, timeout=30)
        self.assertEqual(json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_the_weekly_flags_run_is_started_once_then_reused(self):
        self.run_hook([])
        calls = [json.loads(line) for line in self.ledger_log.read_text().splitlines()]
        self.assertEqual([c[0] for c in calls], ["init", "append"])
        self.assertIn("flags-test-mac", calls[0])
        run = calls[1][calls[1].index("--run") + 1]
        (self.flags_root / ".audit" / "runs" / run).mkdir()
        self.run_hook([], session="s2")
        calls = [json.loads(line) for line in self.ledger_log.read_text().splitlines()]
        self.assertEqual([c[0] for c in calls], ["init", "append", "append"])
        actor = json.loads(calls[1][calls[1].index("--actor") + 1])
        self.assertEqual((actor["on_behalf_of"], actor["model"], actor["id"]),
                         ("tester@github", "unknown", "bstack-commit-gate@claude-code#sess-1"))


if __name__ == "__main__":
    unittest.main()
