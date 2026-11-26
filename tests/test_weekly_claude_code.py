"""End-to-end tests for weekly-claude-code.sh against a local bare repo and stub `gh` and `vercel`."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/cfo/skills/cfo-books/scripts/weekly-claude-code.sh"
BOOKS = ROOT / "tests/fixtures/books"
REPO = "owner/books"
QREPO = "owner/quality"
QUALITY_BOOKS_FIXTURE = ROOT / "tests/fixtures/quality/books"
SKILL_HEADER = "week,skill,source,version,tool,how,calls,searches,errors,verdict,use\n"

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
elif args[:2] == ["api", "repos/owner/quality/pulls?state=open&per_page=100"]:
    print(open(os.environ["STUB_QUALITY_PULLS"]).read())
elif args[:2] == ["api", "repos/owner/quality/pulls"] and "-f" in args:
    print("https://example.invalid/owner/quality/pull/4")
else:
    sys.exit(f"stub gh: unexpected call {args}")
"""

TEAM_ID = "team_FAKEID123"  # invented; the tests check it never leaves the request

# A fake Vercel CLI. STUB_VERCEL_MODE: ok, logged-out, two-teams, api-fail or truncated (the last day
# missing). `api` returns one FOCUS row per Pacific day between `from` and `to`, $1.25 on the first.
STUB_VERCEL = r"""#!/usr/bin/env python3
import datetime, json, os, sys, urllib.parse
from zoneinfo import ZoneInfo
args = sys.argv[1:]
mode = os.environ.get("STUB_VERCEL_MODE", "ok")
with open(os.environ["STUB_VERCEL_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\n")
team = {"id": "team_FAKEID123", "slug": "s", "name": "S", "plan": "pro", "current": False}
if args == ["whoami"]:
    sys.exit(1 if mode == "logged-out" else 0)
elif args == ["teams", "ls", "--json"]:
    teams = [team, {**team, "id": "team_OTHER456"}] if mode == "two-teams" else [team]
    print(json.dumps({"teams": teams, "pagination": {"count": len(teams), "next": None, "prev": 0}}))
elif args[:1] == ["api"] and args[2:] == ["--method", "GET"]:
    url = urllib.parse.urlsplit(args[1])
    q = dict(urllib.parse.parse_qsl(url.query))
    if url.path != "/v1/billing/charges" or q.get("teamId") != team["id"]:
        sys.exit(f"stub vercel: unexpected request {args[1]}")
    if mode == "api-fail":
        sys.exit(f"Error: 500 Internal Server Error for {args[1]}")
    pacific = ZoneInfo("America/Los_Angeles")
    edge = lambda v: datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(pacific).date()
    first, end = edge(q["from"]), edge(q["to"])
    n = (end - first).days - (1 if mode == "truncated" else 0)
    print("> Fetching billing charges")
    for i in range(n):
        d = first + datetime.timedelta(days=i)
        start = datetime.datetime(d.year, d.month, d.day, tzinfo=pacific)
        stop = start + datetime.timedelta(days=1)
        stop = datetime.datetime(stop.year, stop.month, stop.day, tzinfo=pacific)
        cost = "1.25" if i == 0 else "0"
        print('{"BilledCost": %s, "ChargePeriodStart": "%s", "ChargePeriodEnd": "%s", "BillingCurrency": "USD",'
              ' "ChargeCategory": "Usage", "ServiceName": "Fast Data Transfer", "SkuId": "fdt", "RegionId": "iad1",'
              ' "BillingAccountId": "%s", "Tags": {}}' % (cost, start.isoformat(), stop.isoformat(), team["id"]))
else:
    sys.exit(f"stub vercel: unexpected call {args}")
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


def vercel_week() -> str:
    """The week the job fetches: Monday to Monday, ending on the last Monday before yesterday (UTC)."""
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    return week(end - timedelta(days=end.weekday() + 7))


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
        (bin_dir / "vercel").write_text(STUB_VERCEL.replace("/usr/bin/env python3", sys.executable))
        (bin_dir / "vercel").chmod(0o755)
        self.vercel_calls = self.tmp / "vercel-calls.jsonl"
        self.notes = self.tmp / "notes.txt"
        self.calls = self.tmp / "calls.jsonl"
        self.pulls = self.tmp / "pulls.json"
        self.pulls.write_text("[]")
        self.quality_pulls = self.tmp / "quality-pulls.json"
        self.quality_pulls.write_text("[]")
        inherited = {k: v for k, v in os.environ.items() if not k.startswith(("QUALITY_", "AGENTFILES_", "CFO_"))}
        self.env = {**inherited, "HOME": str(self.home), "STUB_QUALITY_PULLS": str(self.quality_pulls), "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "STUB_CALLS": str(self.calls), "STUB_PULLS": str(self.pulls),
                    "CFO_CLONE_URL": str(self.tmp / "origin.git"), "CFO_LOGS": str(self.tmp / "logs"),
                    "CFO_PYTHON": sys.executable, "CFO_TZ": TZ, "STUB_NOTES": str(self.notes),
                    "STUB_VERCEL_CALLS": str(self.vercel_calls), "STUB_VERCEL_MODE": "ok",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        seed = self.tmp / "seed"
        shutil.copytree(BOOKS, seed)
        self.git(seed, "init", "-q", "-b", "main")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-q", "-m", "seed")
        self.git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.tmp / "origin.git"))
        self.main_sha = self.rev("main")

    def make_quality(self, skills_csv: bool = True) -> Path:
        """A bare quality books repo from the small fixture; the skill-use book holds only its header."""
        seed = self.tmp / "qseed"
        shutil.copytree(QUALITY_BOOKS_FIXTURE, seed / "books")
        if skills_csv:
            (seed / "books/skill-uses.csv").write_text(SKILL_HEADER)
        self.git(seed, "init", "-q", "-b", "main")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-q", "-m", "seed")
        bare = self.tmp / "quality.git"
        self.git(self.tmp, "clone", "-q", "--bare", str(seed), str(bare))
        self.env["QUALITY_CLONE_URL"] = str(bare)
        return bare

    def write_skill_transcript(self):
        """One use of demo:alpha last week: a Skill call, then a tool result. Invented names only."""
        stamp = f"{self.last_week.isoformat()}T10:00:00.000Z"
        records = [
            {"type": "assistant", "timestamp": stamp, "isSidechain": False, "uuid": "u1",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "toolu_01", "name": "Skill", "input": {"skill": "demo:alpha"}}]}},
            {"type": "user", "timestamp": stamp, "isSidechain": False, "uuid": "u2",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "toolu_02", "is_error": False, "content": "x"}]}},
        ]
        (self.logs / "skills.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    def quality_git(self, *args) -> str:
        return self.git(self.tmp / "quality.git", *args)

    def quality_branches(self) -> list[str]:
        return sorted(self.quality_git("for-each-ref", "--format=%(refname:short)", "refs/heads").split())

    def quality_rows(self, ref: str) -> list[str]:
        return self.quality_git("show", f"{ref}:books/skill-uses.csv").splitlines()[1:]

    def quality_run(self, *extra) -> subprocess.CompletedProcess:
        return self.run_job("--quality-repo", QREPO, *extra)

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

    def test_without_repo_or_books_it_names_both_fixes(self):
        env = {k: v for k, v in self.env.items() if k != "CFO_BOOKS"}
        r = subprocess.run(["bash", str(SCRIPT), "--print-plist"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("CFO_BOOKS isn't set", r.stderr, "no home-folder guess: the books location must be explicit")
        self.assertIn("--repo", r.stderr)

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

    def vercel_api_calls(self) -> list[list[str]]:
        if not self.vercel_calls.exists():
            return []
        return [c for c in map(json.loads, self.vercel_calls.read_text().splitlines()) if c[:1] == ["api"]]

    def all_history(self) -> str:
        """Every commit message and diff on every branch of origin."""
        return self.git(self.tmp / "origin.git", "log", "-p", "--all")

    def test_last_weeks_vercel_billing_is_booked_and_ids_stay_out(self):
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        branch = f"cfo/brief-{this_sunday().isoformat()}"
        ledger = self.ledger(branch)
        vrows = [line for line in ledger.splitlines() if ",vercel-focus," in line]
        self.assertEqual(len(vrows), 1, ledger)
        self.assertIn(",1.25,USD,,shared,", vrows[0])
        self.assertIn(f"vercel-focus:{vercel_week()}:shared", vrows[0])
        self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", ledger, "Claude Code rows still land")
        self.assertIn(f"Vercel usage for {vercel_week()}", self.all_history())
        self.assertEqual(len(self.vercel_api_calls()), 1)
        for where, text in (("stdout", r.stdout), ("stderr", r.stderr), ("history", self.all_history()),
                            ("gh calls", json.dumps(self.gh_calls()))):
            self.assertNotIn("FAKEID123", text, f"team id leaked into {where}")

    def test_vercel_week_runs_monday_to_monday_at_midnight_pacific(self):
        cases = [  # UTC run date -> from, to
            ("2026-07-12", "2026-06-29T07:00:00.000Z", "2026-07-06T07:00:00.000Z"),  # summer time
            ("2026-01-11", "2025-12-29T08:00:00.000Z", "2026-01-05T08:00:00.000Z"),  # winter time
            ("2026-11-08", "2026-10-26T07:00:00.000Z", "2026-11-02T08:00:00.000Z"),  # ends Sunday Nov 1
            ("2026-03-15", "2026-03-02T08:00:00.000Z", "2026-03-09T07:00:00.000Z"),  # starts Sunday Mar 8
            ("2026-11-09", "2026-10-26T07:00:00.000Z", "2026-11-02T08:00:00.000Z"),  # Monday: last week isn't closed
        ]
        for today, frm, to in cases:
            with self.subTest(today=today):
                self.vercel_calls.unlink(missing_ok=True)
                self.env["CFO_UTC_TODAY"] = today
                r = self.run_job("--dry-run")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                [call] = self.vercel_api_calls()
                q = dict(p.split("=", 1) for p in call[1].split("?", 1)[1].split("&"))
                self.assertEqual((q["from"], q["to"]), (frm, to))
                monday = date.fromisoformat(frm[:10]) + timedelta(days=1 if frm[11:13] == "07" else 0)
                self.assertIn(f"Vercel weeks: {week(monday)} | incomplete: none", r.stdout,
                              "the stub's 23- or 25-hour day still makes a whole week")
        self.assertEqual(self.branches(), ["main"])

    def test_vercel_missing_or_logged_out_skips_only_vercel(self):
        for case in ("logged-out", "missing"):
            with self.subTest(case=case):
                if case == "missing":
                    (self.tmp / "bin/vercel").unlink()
                    self.env["PATH"] = f"{self.tmp / 'bin'}:/usr/bin:/bin"
                else:
                    self.env["STUB_VERCEL_MODE"] = case
                r = self.run_job()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("skipping Vercel billing", r.stdout)
                ledger = self.ledger(f"cfo/brief-{this_sunday().isoformat()}")
                self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", ledger)
                self.assertNotIn(",vercel-focus,", ledger)
                self.assertFalse(self.notes.exists(), "a skip is logged, not notified")
                self.assertEqual(self.vercel_api_calls(), [])

    def test_vercel_problems_book_nothing_and_fail_after_claude_code(self):
        cases = [("api-fail", "vercel api exited 1"), ("truncated", "books.py vercel exited 1"),
                 ("two-teams", "couldn't pick the Vercel team")]
        for mode, message in cases:
            with self.subTest(mode=mode):
                self.notes.unlink(missing_ok=True)
                self.env["STUB_VERCEL_MODE"] = mode
                r = self.run_job()
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn(message, r.stderr)
                if mode == "truncated":
                    self.assertIn(f"incomplete weeks: {vercel_week()}", r.stderr)
                ledger = self.ledger(f"cfo/brief-{this_sunday().isoformat()}")
                self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", ledger, "Claude Code rows pushed first")
                self.assertNotIn(",vercel-focus,", ledger)
                self.assertEqual(len(self.notes.read_text().splitlines()), 1, self.notes.read_text())
                self.assertNotIn("FAKEID123", r.stdout + r.stderr, "the failed request's URL is redacted")
                self.assertEqual(r.stderr.count("FAILED"), 1, r.stderr)

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
        self.assertEqual(plist["ProgramArguments"], ["/bin/bash", str(SCRIPT), "--repo", REPO, "--scheduled"],
                         "repo from the books' remote")
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
        self.assertEqual(plist["ProgramArguments"], ["/bin/bash", str(SCRIPT), "--repo", REPO, "--scheduled"])
        self.assertEqual(plist["StartCalendarInterval"], {"Minute": 0})

    def test_skill_uses_are_pushed_to_a_quality_brief_branch_with_a_pr(self):
        self.make_quality()
        self.write_skill_transcript()
        main_before = self.quality_git("rev-parse", "main")
        r = self.quality_run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        branch = f"quality/brief-{this_sunday().isoformat()}"
        self.assertEqual(self.quality_branches(), sorted(["main", branch]))
        self.assertEqual(self.quality_git("rev-parse", "main"), main_before, "main must never move")
        [row] = self.quality_rows(branch)
        self.assertTrue(row.startswith(f"{week(self.last_week)},alpha,"), row)
        self.assertEqual(self.quality_git("log", "-1", "--format=%s", branch), f"Skill uses for {week(self.last_week)}")
        self.assertEqual(self.quality_git("diff", "--name-only", "main", branch), "books/skill-uses.csv")
        creates = [c for c in self.gh_calls() if "-f" in c and c[1] == f"repos/{QREPO}/pulls"]
        self.assertEqual(len(creates), 1, self.gh_calls())
        self.assertIn(f"head={branch}", creates[0])
        self.assertIn(f"title=Quality brief {this_sunday().isoformat()}: skill uses (brief pending)", creates[0])
        self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", self.ledger(f"cfo/brief-{this_sunday().isoformat()}"),
                      "the cfo rows land as before")
        for where, text in (("stdout", r.stdout), ("stderr", r.stderr), ("gh calls", json.dumps(self.gh_calls()))):
            self.assertNotIn("alpha", text, f"a skill name leaked into {where}")
            self.assertNotIn("demo", text, f"a plugin name leaked into {where}")

    def test_second_run_books_no_skill_uses_again(self):
        self.make_quality()
        self.write_skill_transcript()
        self.assertEqual(self.quality_run().returncode, 0)
        branch = f"quality/brief-{this_sunday().isoformat()}"
        after_first = self.quality_git("rev-parse", branch)
        r = self.quality_run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no new skill uses", r.stdout)
        self.assertEqual(self.quality_git("rev-parse", branch), after_first)
        self.assertEqual(len([c for c in self.gh_calls() if "-f" in c and c[1] == f"repos/{QREPO}/pulls"]), 1)

    def test_open_quality_pr_takes_the_rows_and_no_new_pr_is_opened(self):
        bare = self.make_quality()
        self.write_skill_transcript()
        seed = self.tmp / "qpr"
        self.git(self.tmp, "clone", "-q", str(bare), str(seed))
        self.git(seed, "checkout", "-q", "-b", "quality/brief-2026-01-04")
        (seed / "note.md").write_text("an earlier brief\n")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-q", "-m", "earlier brief")
        self.git(seed, "push", "-q", "origin", "quality/brief-2026-01-04")
        self.quality_pulls.write_text(json.dumps([
            {"head": {"ref": "quality/brief-2026-01-04", "repo": {"full_name": QREPO}}, "created_at": "2026-01-02T00:00:00Z"},
            {"head": {"ref": "quality/brief-2026-01-11", "repo": {"full_name": "fork/quality"}}, "created_at": "2026-01-01T00:00:00Z"}]))
        r = self.quality_run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.quality_branches(), ["main", "quality/brief-2026-01-04"])
        self.assertEqual(len(self.quality_rows("quality/brief-2026-01-04")), 1)
        self.assertEqual([c for c in self.gh_calls() if "-f" in c and c[1] == f"repos/{QREPO}/pulls"], [])

    def test_rejected_quality_push_is_retried_once(self):
        bare = self.make_quality()
        self.write_skill_transcript()
        hook = bare / "hooks/pre-receive"
        flag = self.tmp / "q-rejected-once"
        hook.write_text(f"#!/bin/sh\n[ -e {flag} ] && exit 0\ntouch {flag}\necho simulated race >&2\nexit 1\n")
        hook.chmod(0o755)
        r = self.quality_run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("retrying once", r.stdout)
        self.assertEqual(len(self.quality_rows(f"quality/brief-{this_sunday().isoformat()}")), 1)

    def test_without_a_quality_repo_the_quality_books_are_never_touched(self):
        bare = self.make_quality()
        self.write_skill_transcript()
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skipping skill uses", r.stdout)
        self.assertEqual(self.quality_branches(), ["main"])
        self.assertFalse([c for c in self.gh_calls() if "quality" in json.dumps(c)], self.gh_calls())
        self.assertEqual(self.branches(), sorted(["main", f"cfo/brief-{this_sunday().isoformat()}"]))
        self.assertEqual(r.stderr, "")

    def test_quality_repo_defaults_from_the_quality_books_remote(self):
        checkout = self.tmp / "quality-checkout"
        self.git(self.tmp, "init", "-q", str(checkout))
        self.git(checkout, "remote", "add", "origin", "git@github.com:owner/quality.git")
        self.env["QUALITY_BOOKS"] = str(checkout)
        import plistlib
        plist = plistlib.loads(self.run_job("--print-plist").stdout.encode())
        self.assertEqual(plist["ProgramArguments"], ["/bin/bash", str(SCRIPT), "--repo", REPO, "--quality-repo", QREPO, "--scheduled"])

    def test_plist_carries_the_quality_repo_only_when_set(self):
        import plistlib
        with_flag = plistlib.loads(self.quality_run("--print-plist").stdout.encode())
        self.assertEqual(with_flag["ProgramArguments"],
                         ["/bin/bash", str(SCRIPT), "--repo", REPO, "--quality-repo", QREPO, "--scheduled"])
        without = plistlib.loads(self.run_job("--print-plist").stdout.encode())
        self.assertEqual(without["ProgramArguments"], ["/bin/bash", str(SCRIPT), "--repo", REPO, "--scheduled"])
        self.assertEqual([k for k in without.get("EnvironmentVariables", {}) if "QUALITY" in k], [],
                         "no quality setting reaches the job's environment either")

    def make_lock(self) -> Path:
        lock = self.tmp / "profiles" / "agentfiles.lock"
        lock.parent.mkdir(exist_ok=True)
        lock.write_text(json.dumps({"version": 1, "sources": {}, "items": {
            "plugin:mine:@demo": {"commit": "c" * 40, "hash": "sha256:0"}}}))
        return lock

    def test_the_installed_job_carries_the_lock_because_its_environment_has_none(self):
        import plistlib
        lock = self.make_lock().resolve()
        want = ["/bin/bash", str(SCRIPT), "--repo", REPO, "--quality-repo", QREPO, "--agentfiles-lock", str(lock), "--scheduled"]
        cases = {"the flag": (["--agentfiles-lock", str(lock)], {}),
                 "AGENTFILES_LOCK": ([], {"AGENTFILES_LOCK": str(lock)}),
                 "AGENTFILES_HOME": ([], {"AGENTFILES_HOME": str(lock.parent)})}
        for case, (flags, env) in cases.items():
            with self.subTest(case=case), unittest.mock.patch.dict(self.env, env):
                plist = plistlib.loads(self.quality_run(*flags, "--print-plist").stdout.encode())
                self.assertEqual(plist["ProgramArguments"], want)
        with unittest.mock.patch.dict(self.env, {"AGENTFILES_LOCK": str(lock)}):
            no_pass = plistlib.loads(self.run_job("--print-plist").stdout.encode())
        self.assertEqual(no_pass["ProgramArguments"], ["/bin/bash", str(SCRIPT), "--repo", REPO, "--scheduled"],
                         "no pass, no lock")

    def test_a_lock_that_is_not_a_file_is_refused(self):
        r = self.quality_run("--agentfiles-lock", str(self.tmp / "nope.lock"), "--print-plist")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("Not a file", r.stderr)

    def test_rows_take_their_version_from_the_lock_the_job_was_given(self):
        self.make_quality()
        self.write_skill_transcript()
        r = self.quality_run("--agentfiles-lock", str(self.make_lock()))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [row] = self.quality_rows(f"quality/brief-{this_sunday().isoformat()}")
        self.assertEqual(row.split(",")[1:4], ["alpha", "mine:@demo", "c" * 40])
        self.assertNotIn("skill versions will be empty", r.stdout)

    def test_a_malformed_quality_repo_is_refused(self):
        r = self.run_job("--quality-repo", "not a repo")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("Not a GitHub OWNER/NAME", r.stderr)
        self.assertIn("--agentfiles-lock FILE", r.stderr)
        self.assertNotIn("set -Eeuo", r.stderr, "usage prints the usage lines, not the script")

    def test_books_without_skill_uses_csv_skip_the_pass(self):
        self.make_quality(skills_csv=False)
        self.write_skill_transcript()
        r = self.quality_run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skill-uses.csv is not in the quality books yet; skipping", r.stdout)
        self.assertEqual(self.quality_branches(), ["main"])
        self.assertEqual([c for c in self.gh_calls() if "-f" in c and c[1] == f"repos/{QREPO}/pulls"], [])
        self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", self.ledger(f"cfo/brief-{this_sunday().isoformat()}"))

    def test_missing_quality_py_skips_the_pass(self):
        self.make_quality()
        self.env["QUALITY_PY"] = str(self.tmp / "no-such-quality.py")
        r = self.quality_run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skipping skill uses", r.stdout)
        self.assertEqual(self.quality_branches(), ["main"])

    def test_a_failing_pass_still_pushes_the_cfo_rows_then_fails(self):
        self.make_quality()
        failing = self.tmp / "failing_quality.py"
        failing.write_text("import sys\nprint('1 problems; refusing')\nsys.exit(1)\n")
        broken_clone = self.tmp / "no-such-quality.git"
        for case in ("quality.py exits 1", "clone fails"):
            with self.subTest(case=case):
                self.notes.unlink(missing_ok=True)
                if case == "clone fails":
                    self.env["QUALITY_CLONE_URL"] = str(broken_clone)
                else:
                    self.env["QUALITY_PY"] = str(failing)
                r = self.quality_run()
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("skill uses", r.stderr.split("FAILED")[-1])
                self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", self.ledger(f"cfo/brief-{this_sunday().isoformat()}"),
                              "the cfo rows are pushed first")
                self.assertEqual(self.quality_branches(), ["main"])
                self.assertEqual(len(self.notes.read_text().splitlines()), 1, self.notes.read_text())

    def test_a_vercel_problem_and_a_skills_problem_are_both_reported(self):
        self.make_quality()
        failing = self.tmp / "failing_quality.py"
        failing.write_text("import sys\nsys.exit(1)\n")
        self.env.update(QUALITY_PY=str(failing), STUB_VERCEL_MODE="api-fail")
        r = self.quality_run()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        final = r.stderr.split("FAILED:")[-1]
        self.assertIn("Vercel: vercel api exited 1", final)
        self.assertIn("skill uses", final)
        self.assertEqual(len(self.notes.read_text().splitlines()), 1)

    def test_dry_run_pushes_nothing_to_the_quality_repo(self):
        self.make_quality()
        self.write_skill_transcript()
        r = self.quality_run("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would book 1 skill uses", r.stdout)
        self.assertIn(f"would push skill uses to quality/brief-{this_sunday().isoformat()}", r.stdout)
        self.assertEqual(self.quality_branches(), ["main"])
        self.assertEqual(self.branches(), ["main"])
        self.assertEqual([c for c in self.gh_calls() if "-f" in c], [])


    SUNDAY = "2026-11-22"
    FULL_WAKE = "CPU Graphics Audio Network"
    DARK_WAKE = "CPU Network"
    NO_REPO = "no-such-repo.git"

    def schedule(self, wake: str = FULL_WAKE):
        self.stamp = self.tmp / "state/cfo-claude-code.done"
        pmset = self.tmp / "pmset"
        pmset.write_text(f"#!/bin/sh\necho 'System-wide power settings:'\n"
                         f"echo 'Current System Capabilities are: {wake}'\n")
        pmset.chmod(0o755)
        self.env.update(CFO_STATE_DIR=str(self.stamp.parent), CFO_PMSET=str(pmset), CFO_NOW=f"{self.SUNDAY}T07:00")

    def scheduled(self, now: str | None = None) -> subprocess.CompletedProcess:
        if now:
            self.env["CFO_NOW"] = now
        return self.run_job("--scheduled")

    def write_stamp(self, key: str):
        self.stamp.parent.mkdir(parents=True)
        self.stamp.write_text(key + "\n")

    def test_a_dark_wake_books_nothing_and_tries_again_next_hour(self):
        self.schedule(self.DARK_WAKE)
        self.env["CFO_CLONE_URL"] = str(self.tmp / self.NO_REPO)
        r = self.scheduled()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "cfo-claude-code: dark wake (CPU Network); trying again next hour\n")
        self.assertEqual(r.stderr, "")
        self.assertEqual(self.gh_calls(), [])
        self.assertFalse(self.vercel_calls.exists())
        self.assertFalse(self.stamp.exists())

    def test_a_failed_run_is_retried_then_a_finished_week_is_left_alone(self):
        self.schedule()
        branch = f"cfo/brief-{this_sunday().isoformat()}"
        good_url = self.env["CFO_CLONE_URL"]
        self.env["CFO_CLONE_URL"] = str(self.tmp / self.NO_REPO)
        failed = self.scheduled()
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertFalse(self.stamp.exists(), "a failed run leaves no stamp")
        self.assertEqual(self.branches(), ["main"])

        self.env["CFO_CLONE_URL"] = good_url
        retried = self.scheduled("2026-11-22T08:00")
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn(f"claude-code:{week(self.last_week)}:unassigned", self.ledger(branch))
        self.assertEqual(self.stamp.read_text().strip(), self.SUNDAY)

        pushed, gh_before = self.rev(branch), len(self.gh_calls())
        self.env["CFO_CLONE_URL"] = str(self.tmp / self.NO_REPO)
        again = self.scheduled("2026-11-22T09:00")
        self.assertEqual((again.returncode, again.stdout, again.stderr), (0, "", ""))
        self.assertEqual(len(self.gh_calls()), gh_before, "no clone, no gh call")
        self.assertEqual(self.rev(branch), pushed)

    def test_the_window_runs_from_sunday_0600_to_monday_2359(self):
        self.schedule(self.DARK_WAKE)
        cases = {"2026-11-22T05:59": False, "2026-11-22T06:00": True, "2026-11-23T23:59": True,
                 "2026-11-24T00:00": False, "2026-11-25T07:00": False, "2026-11-21T12:00": False}
        for now, inside in cases.items():
            with self.subTest(now=now):
                r = self.scheduled(now)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual("dark wake" in r.stdout, inside, r.stdout)
                self.assertEqual(r.stderr, "")
                if not inside:
                    self.assertEqual(r.stdout, "")

    def test_outside_the_window_nothing_runs(self):
        self.schedule()
        self.env["CFO_CLONE_URL"] = str(self.tmp / self.NO_REPO)
        r = self.scheduled("2026-11-25T07:00")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.gh_calls(), [])
        self.assertFalse(self.vercel_calls.exists())

    def test_monday_belongs_to_the_window_that_began_on_sunday(self):
        self.schedule()
        self.write_stamp(self.SUNDAY)
        self.env["CFO_CLONE_URL"] = str(self.tmp / self.NO_REPO)
        r = self.scheduled("2026-11-23T10:00")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.gh_calls(), [])

    def test_the_next_weeks_window_is_not_blocked_by_an_old_stamp(self):
        self.schedule()
        self.write_stamp(self.SUNDAY)
        r = self.scheduled("2026-11-29T07:00")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.stamp.read_text().strip(), "2026-11-29")

    def test_a_missing_pmset_does_not_block_the_run(self):
        self.schedule()
        self.env["CFO_PMSET"] = str(self.tmp / "no-pmset")
        r = self.scheduled()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.stamp.read_text().strip(), self.SUNDAY)

    def test_a_plain_run_ignores_the_window_the_stamp_and_the_wake_state(self):
        self.schedule(self.DARK_WAKE)
        self.env["CFO_NOW"] = "2026-11-25T07:00"
        self.write_stamp(self.SUNDAY)
        r = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("dark wake", r.stdout)
        self.assertIn(f"cfo/brief-{this_sunday().isoformat()}", self.branches())
        self.assertEqual(self.stamp.read_text().strip(), self.SUNDAY, "a plain run never writes the stamp")


if __name__ == "__main__":
    unittest.main()
