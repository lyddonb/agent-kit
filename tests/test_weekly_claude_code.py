"""End-to-end tests for weekly-claude-code.sh against a local bare repo and a stub `gh`."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/cfo/skills/cfo-books/scripts/weekly-claude-code.sh"
BOOKS = ROOT / "tests/fixtures/books"
REPO = "owner/books"

STUB_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:2] == ["auth", "status"]:
    pass
elif args[:2] == ["api", "repos/owner/books/pulls?state=open&per_page=100"]:
    print(open(os.environ["STUB_PULLS"]).read())
elif args[:2] == ["api", "repos/owner/books/pulls"] and "-f" in args:
    print("https://example.invalid/owner/books/pull/9")
else:
    sys.exit(f"stub gh: unexpected call {args}")
"""

TZ = "America/Denver"

STUB_RECORDER = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$STUB_NOTES"
"""

STUB_OSASCRIPT = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_NOTES"
"""


def denver_today() -> date:
    return datetime.now(ZoneInfo(TZ)).date()


def this_sunday() -> date:
    today = denver_today()
    return today + timedelta(days=(6 - today.weekday()) % 7)


def log_line(day: date, msg_id: str) -> str:
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 0, "speed": "standard", "service_tier": "standard"}
    return json.dumps({"type": "assistant", "timestamp": f"{day.isoformat()}T12:00:00.000Z", "cwd": "/work/x",
                       "requestId": msg_id, "message": {"id": msg_id, "model": "claude-sonnet-5-5",
                                                        "role": "assistant", "usage": usage}})


def week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


class WeeklyJob(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.logs = self.tmp / "logs/proj"
        self.logs.mkdir(parents=True)
        utc_today = datetime.now(timezone.utc).date()
        monday = utc_today - timedelta(days=utc_today.weekday())
        self.utc_today = utc_today
        self.last_week = monday - timedelta(days=5)   # a Wednesday in the last complete week
        self.old_week = monday - timedelta(days=47)   # a Wednesday about seven weeks back
        lines = [log_line(self.last_week, "m1"), log_line(self.old_week, "m2")]
        # one message a day near the default retention edge (30 days), to catch a partial first week
        lines += [log_line(utc_today - timedelta(days=d), f"edge{d}") for d in range(26, 36)]
        (self.logs / "s.jsonl").write_text("\n".join(lines) + "\n")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(STUB_GH)
        (bin_dir / "gh").chmod(0o755)
        (bin_dir / "osascript").write_text(STUB_OSASCRIPT)
        (bin_dir / "osascript").chmod(0o755)
        self.notes = self.tmp / "notes.txt"
        self.calls = self.tmp / "calls.jsonl"
        self.pulls = self.tmp / "pulls.json"
        self.pulls.write_text("[]")
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "STUB_CALLS": str(self.calls), "STUB_PULLS": str(self.pulls),
                    "CFO_CLONE_URL": str(self.tmp / "origin.git"), "CFO_LOGS": str(self.tmp / "logs"),
                    "CFO_PYTHON": sys.executable, "CFO_TZ": TZ, "STUB_NOTES": str(self.notes),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        seed = self.tmp / "seed"
        shutil.copytree(BOOKS, seed)
        self.git(seed, "init", "-q", "-b", "main")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-q", "-m", "seed")
        self.git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.tmp / "origin.git"))
        self.main_sha = self.rev("main")

    def git(self, cwd, *args) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def rev(self, ref: str) -> str:
        return self.git(self.tmp / "origin.git", "rev-parse", ref)

    def branches(self) -> list[str]:
        out = self.git(self.tmp / "origin.git", "for-each-ref", "--format=%(refname:short)", "refs/heads")
        return sorted(out.split())

    def ledger(self, ref: str) -> str:
        return self.git(self.tmp / "origin.git", "show", f"{ref}:ledger/charges.csv")

    def run_job(self, *extra) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), "--repo", REPO, *extra], env=self.env, capture_output=True,
                              text=True)

    def gh_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def open_pr(self, branch: str):
        seed = self.tmp / "pr"
        self.git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(seed))
        self.git(seed, "checkout", "-q", "-b", branch)
        (seed / "briefs").mkdir(exist_ok=True)
        (seed / "briefs/old.md").write_text("an earlier brief\n")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-q", "-m", "earlier brief")
        self.git(seed, "push", "-q", "origin", branch)
        self.pulls.write_text(json.dumps([{"head": {"ref": "feature/other", "repo": {"full_name": REPO}},
                                           "created_at": "2026-01-01T00:00:00Z"},
                                          {"head": {"ref": branch, "repo": {"full_name": REPO}},
                                           "created_at": "2026-01-02T00:00:00Z"}]))

    def test_no_open_pr_opens_one_on_a_new_brief_branch(self):
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        branch = f"cfo/brief-{this_sunday().isoformat()}"
        self.assertEqual(self.branches(), sorted(["main", branch]))
        self.assertEqual(self.rev("main"), self.main_sha, "main must never move")
        self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", self.ledger(branch))
        create = [c for c in self.gh_calls() if "-f" in c]
        self.assertEqual(len(create), 1, self.gh_calls())
        self.assertIn(f"head={branch}", create[0])
        self.assertIn("base=main", create[0])

    def test_after_this_sundays_brief_merged_the_branch_is_for_next_sunday(self):
        sunday = this_sunday()
        seed = self.tmp / "merged"
        self.git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(seed))
        (seed / "briefs").mkdir(exist_ok=True)
        (seed / f"briefs/{sunday.isoformat()}.md").write_text("this Sunday's brief, merged\n")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-q", "-m", "merged brief")
        self.git(seed, "push", "-q", "origin", "main")
        self.main_sha = self.rev("main")
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.branches(), sorted(["main", f"cfo/brief-{(sunday + timedelta(days=7)).isoformat()}"]))

    def test_open_brief_pr_gets_the_rows_and_no_new_pr(self):
        self.open_pr("cfo/brief-2026-01-04")
        before = self.rev("cfo/brief-2026-01-04")
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.branches(), ["cfo/brief-2026-01-04", "main"])
        self.assertEqual(self.git(self.tmp / "origin.git", "rev-parse", "cfo/brief-2026-01-04~1"), before,
                         "one fast-forward commit on top of the PR branch")
        self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", self.ledger("cfo/brief-2026-01-04"))
        self.assertEqual(self.rev("main"), self.main_sha)
        self.assertEqual([c for c in self.gh_calls() if "-f" in c], [])

    def test_second_run_pushes_nothing(self):
        self.open_pr("cfo/brief-2026-01-04")
        self.assertEqual(self.run_job().returncode, 0)
        after_first = self.rev("cfo/brief-2026-01-04")
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to push", r.stdout)
        self.assertEqual(self.rev("cfo/brief-2026-01-04"), after_first)

    def test_weeks_outside_log_retention_are_not_written(self):
        self.open_pr("cfo/brief-2026-01-04")
        self.assertEqual(self.run_job().returncode, 0)
        ledger = self.ledger("cfo/brief-2026-01-04")
        self.assertNotIn(f"claude-code:{week(self.old_week)}:", ledger, "default 30-day retention")

    def test_longer_retention_widens_the_window(self):
        (self.home / ".claude/settings.json").write_text('{"cleanupPeriodDays": 120}')
        self.open_pr("cfo/brief-2026-01-04")
        self.assertEqual(self.run_job().returncode, 0)
        self.assertIn(f"claude-code:{week(self.old_week)}:unassigned", self.ledger("cfo/brief-2026-01-04"))

    def test_dry_run_pushes_nothing(self):
        r = self.run_job("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertEqual(self.branches(), ["main"])
        self.assertEqual([c for c in self.gh_calls() if "-f" in c], [])

    def test_books_failing_against_main_push_nothing(self):
        self.open_pr("cfo/brief-2026-01-04")
        before = self.rev("cfo/brief-2026-01-04")
        bad = self.tmp / "bad"
        self.git(self.tmp, "clone", "-q", "-b", "cfo/brief-2026-01-04", str(self.tmp / "origin.git"), str(bad))
        ledger = bad / "ledger/charges.csv"
        ledger.write_text(ledger.read_text().replace(",20.00,USD,,shared,", ",25.00,USD,,shared,", 1))
        self.git(bad, "commit", "-q", "-am", "rewrite a past amount (passes alone, fails against main)")
        self.git(bad, "push", "-q", "origin", "cfo/brief-2026-01-04")
        broken = self.rev("cfo/brief-2026-01-04")
        r = self.run_job()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("books check failed", r.stderr)
        self.assertEqual(self.rev("cfo/brief-2026-01-04"), broken)
        self.assertNotEqual(broken, before)

    def test_no_week_starts_before_the_retention_window(self):
        self.assertEqual(self.run_job().returncode, 0)
        branch = f"cfo/brief-{this_sunday().isoformat()}"
        earliest = self.utc_today - timedelta(days=28)
        for line in self.ledger(branch).splitlines()[1:]:
            cells = line.split(",")
            if cells[11] == "claude-code-logs":
                self.assertGreaterEqual(date.fromisoformat(cells[1]), earliest, line)

    def test_failure_notifies_once(self):
        self.env["CFO_LOGS"] = str(self.tmp / "missing")
        r = self.run_job()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("claude-code failed", r.stderr)
        self.assertEqual(len(self.notes.read_text().splitlines()), 1, self.notes.read_text())

    def test_failure_inside_a_function_notifies_once(self):
        self.env["STUB_PULLS"] = str(self.tmp / "no-such-file")  # the stub gh exits non-zero
        r = self.run_job()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAILED", r.stderr)
        self.assertEqual(len(self.notes.read_text().splitlines()), 1, r.stderr)

    def test_unmerged_branch_without_a_pr_is_reused_and_gets_its_pr(self):
        branch = f"cfo/brief-{this_sunday().isoformat()}"
        seed = self.tmp / "orphan"
        self.git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(seed))
        self.git(seed, "checkout", "-q", "-b", branch)
        (seed / "briefs").mkdir(exist_ok=True)
        (seed / "briefs/wip.md").write_text("pushed before its PR was opened\n")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-q", "-m", "wip")
        self.git(seed, "push", "-q", "origin", branch)
        before = self.rev(branch)
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.branches(), sorted(["main", branch]), "no -2 branch")
        self.assertEqual(self.git(self.tmp / "origin.git", "rev-parse", f"{branch}~1"), before)
        self.assertEqual(len([c for c in self.gh_calls() if "-f" in c]), 1)

    def test_rejected_push_is_retried_once_from_the_new_tip(self):
        self.open_pr("cfo/brief-2026-01-04")
        hook = self.tmp / "origin.git/hooks/pre-receive"
        flag = self.tmp / "rejected-once"
        hook.write_text(f"#!/bin/sh\n[ -e {flag} ] && exit 0\ntouch {flag}\necho simulated race >&2\nexit 1\n")
        hook.chmod(0o755)
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("retrying once", r.stdout)
        self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", self.ledger("cfo/brief-2026-01-04"))

    def test_install_status_uninstall(self):
        import plistlib
        bin_dir = self.tmp / "bin"
        for tool in ("launchctl", "plutil", "uv"):
            (bin_dir / tool).write_text(STUB_RECORDER)
            (bin_dir / tool).chmod(0o755)
        books_dir = self.tmp / "books-checkout"
        self.git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(books_dir))
        self.git(books_dir, "remote", "set-url", "origin", "git@github.com:owner/books.git")
        settings = self.home / ".claude/settings.json"
        settings.write_text('{"model": "opus", "cleanupPeriodDays": 30}')
        self.env.update(CFO_BOOKS=str(books_dir), CFO_JOB_PATH=f"{bin_dir}:/usr/bin:/bin")
        r = subprocess.run(["bash", str(SCRIPT), "--install"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plist = plistlib.loads((self.home / "Library/LaunchAgents/dev.agent-kit.cfo-claude-code.plist").read_bytes())
        self.assertEqual(plist["ProgramArguments"], ["/bin/bash", str(SCRIPT), "--repo", REPO], "repo from the books' remote")
        self.assertEqual(json.loads(settings.read_text()), {"model": "opus", "cleanupPeriodDays": 120})
        self.assertEqual(json.loads(Path(str(settings) + ".bak").read_text())["cleanupPeriodDays"], 30)
        self.assertIn("launchctl bootstrap gui/", self.notes.read_text())
        r = subprocess.run(["bash", str(SCRIPT), "--install"], env=self.env, capture_output=True, text=True)
        self.assertIn("left as is", r.stdout)
        r = subprocess.run(["bash", str(SCRIPT), "--uninstall"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.home / "Library/LaunchAgents/dev.agent-kit.cfo-claude-code.plist").exists())
        self.assertIn("launchctl bootout gui/", self.notes.read_text())

    def test_plist_is_valid_and_points_at_this_script(self):
        r = self.run_job("--print-plist")
        self.assertEqual(r.returncode, 0, r.stderr)
        import plistlib
        plist = plistlib.loads(r.stdout.encode())
        self.assertEqual(plist["ProgramArguments"], ["/bin/bash", str(SCRIPT), "--repo", REPO])
        self.assertEqual(plist["StartCalendarInterval"], {"Weekday": 0, "Hour": 6, "Minute": 0})


if __name__ == "__main__":
    unittest.main()
