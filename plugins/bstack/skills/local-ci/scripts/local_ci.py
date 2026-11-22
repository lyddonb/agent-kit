#!/usr/bin/env python3
"""Run a repo's CI on this machine and report it to GitHub as a commit status.

Each repo declares its CI as one executable, `scripts/ci`, run from the repo root. local_ci.py
checks out a commit into a throwaway worktree, runs that file, and posts the result as the commit
status `local-ci` on the commit (PR checks show it). A failing run on a pull request also writes
one comment on the PR with the end of the log, edited in place on later runs.

A job is (repo, sha, PR number or branch). Its status on GitHub is its state:
none -> pending (posted when the run starts) -> success | failure | error. `error` means the run
could not start (no scripts/ci, the checkout failed); `failure` means scripts/ci exited non-zero or
timed out. A tick skips a sha that already has a finished `local-ci` status, and re-runs one whose
`pending` is older than the timeout (a run that died), so ticks can repeat safely.

Usage:
  local_ci.py tick    --repo OWNER/NAME=CHECKOUT [--repo ...]   # every open PR head and the default branch head
  local_ci.py run     --repo OWNER/NAME=CHECKOUT (--pr N | --branch NAME) [--force]
  local_ci.py install --repo OWNER/NAME=CHECKOUT [--repo ...] [--interval SECONDS]   # launchd agent, macOS
  local_ci.py uninstall | status | print-plist --repo ...
  local_ci.py fallback --repo OWNER/NAME=CHECKOUT (--pr N | --branch NAME) [--job NAME ...] [--dry-run]

`fallback` is for jobs that stay on GitHub Actions. For each Actions job on the commit that GitHub
never started (no steps and no runner: a spending limit, a failed payment, an outage), it runs
`scripts/fallback/<job name>` and posts the commit status `<job name> (local fallback)`. A job that
ran on GitHub, passed or failed, is never replaced. The script comes from the base branch (for a
PR) or the branch itself (for --branch), never from the PR, and gets the commit to check as a
separate checkout in $LOCAL_CI_TARGET (for a PR, GitHub's merge commit), so a branch can't change
what checks it. A script with the line `# local-ci: explicit` (a deploy) runs only when named with
--job. --dry-run sets LOCAL_CI_DRY_RUN=1 for the script.

CHECKOUT is a local clone of the repo with an `origin` remote; local_ci.py only fetches into it and
adds worktrees under its own state folder, so the clone's working tree is never touched.

Options: --timeout SECONDS (default 1800) per run. Needs git and gh (logged in).
Test hooks: LOCAL_CI_GH (the gh binary), LOCAL_CI_STATE (state folder, default
~/Library/Caches/local-ci), LOCAL_CI_HOST (the name in status descriptions).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

CONTEXT = "local-ci"
MARKER = "<!-- local-ci -->"
LABEL = "dev.agent-kit.local-ci"
LOG_TAIL_LINES = 80
COMMENT_LIMIT = 60000
DESCRIPTION_LIMIT = 140
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def state_dir() -> Path:
    return Path(os.environ.get("LOCAL_CI_STATE") or Path.home() / "Library/Caches/local-ci")


def host_name() -> str:
    return os.environ.get("LOCAL_CI_HOST") or socket.gethostname().split(".")[0]


@dataclass(frozen=True)
class Repo:
    github: str
    checkout: Path

    @staticmethod
    def parse(spec: str) -> "Repo":
        name, sep, path = spec.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) or not path:
            raise argparse.ArgumentTypeError(f"--repo takes OWNER/NAME=CHECKOUT, got {spec!r}")
        return Repo(name, Path(path).expanduser().resolve())


@dataclass(frozen=True)
class Job:
    repo: Repo
    sha: str
    ref: str  # what to fetch: refs/pull/N/head or refs/heads/NAME
    base: str  # the branch scripts/ci compares against (the PR base, or the branch itself)
    pr: Optional[int]

    @property
    def label(self) -> str:
        where = f"#{self.pr}" if self.pr else ":" + self.ref.rsplit("/", 1)[-1]
        return f"{self.repo.github}{where}@{self.sha[:7]}"


class GhError(RuntimeError):
    pass


def gh(*args: str, body: Optional[dict] = None) -> object:
    cmd = [os.environ.get("LOCAL_CI_GH", "gh"), "api", *args]
    if body is not None:
        cmd += ["--input", "-"]
    p = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise GhError(f"gh api {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
    return json.loads(p.stdout) if p.stdout.strip() else None


def gh_list(path: str) -> list:
    pages = gh(path, "--paginate", "--slurp")
    return [item for page in pages for item in page]


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


def discover(repo: Repo) -> List[Job]:
    meta = gh(f"repos/{repo.github}")
    default = meta["default_branch"]
    jobs = []
    head = gh(f"repos/{repo.github}/commits/{default}")
    jobs.append(Job(repo, head["sha"], f"refs/heads/{default}", default, None))
    for pr in gh_list(f"repos/{repo.github}/pulls?state=open&per_page=100"):
        if pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != repo.github:
            continue  # a fork's code never runs here
        jobs.append(Job(repo, pr["head"]["sha"], f"refs/pull/{pr['number']}/head",
                        pr["base"]["ref"], pr["number"]))
    return jobs


def pr_job(repo: Repo, number: int) -> Job:
    pr = gh(f"repos/{repo.github}/pulls/{number}")
    return Job(repo, pr["head"]["sha"], f"refs/pull/{number}/head", pr["base"]["ref"], number)


def branch_job(repo: Repo, branch: str) -> Job:
    head = gh(f"repos/{repo.github}/commits/{branch}")
    return Job(repo, head["sha"], f"refs/heads/{branch}", branch, None)


def latest_status(job: Job, context: str = CONTEXT) -> Optional[dict]:
    statuses = gh(f"repos/{job.repo.github}/commits/{job.sha}/statuses?per_page=100")
    mine = [s for s in statuses if s["context"] == context]  # newest first
    return mine[0] if mine else None


def needs_run(job: Job, timeout: int) -> bool:
    latest = latest_status(job)
    if latest is None:
        return True
    if latest["state"] != "pending":
        return False
    started = dt.datetime.fromisoformat(latest["updated_at"].replace("Z", "+00:00"))
    age = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
    return age > timeout + 300


def post_status(job: Job, state: str, description: str) -> None:
    gh(f"repos/{job.repo.github}/statuses/{job.sha}", "-X", "POST",
       body={"state": state, "context": CONTEXT, "description": description[:DESCRIPTION_LIMIT]})


def upsert_comment(job: Job, text: str, create: bool) -> None:
    """Edit this PR's local-ci comment, or add one when `create` (only failures open one)."""
    comments = gh_list(f"repos/{job.repo.github}/issues/{job.pr}/comments?per_page=100")
    existing = [c for c in comments if MARKER in (c.get("body") or "")]
    body = f"{MARKER}\n{text}"
    if existing:
        gh(f"repos/{job.repo.github}/issues/comments/{existing[-1]['id']}", "-X", "PATCH",
           body={"body": body})
    elif create:
        gh(f"repos/{job.repo.github}/issues/{job.pr}/comments", "-X", "POST", body={"body": body})


def log_tail(log: Path) -> str:
    if not log.exists():
        return ""
    lines = ANSI.sub("", log.read_text(errors="replace")).splitlines()
    tail = "\n".join(lines[-LOG_TAIL_LINES:]).replace("```", "'''")
    return tail[-COMMENT_LIMIT:]


def last_line(log: Path) -> str:
    if not log.exists():
        return ""
    for line in reversed(ANSI.sub("", log.read_text(errors="replace")).splitlines()):
        if line.strip():
            return line.strip()
    return ""


def took(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def record(result: dict) -> None:
    path = state_dir() / "results.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(result) + "\n")


def run_job(job: Job, timeout: int) -> str:
    """Run one job and post its result. Returns the final state."""
    work = state_dir() / "work" / job.repo.github.replace("/", "__") / job.sha
    logs = state_dir() / "logs" / job.repo.github.replace("/", "__")
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{job.sha}.log"
    started = time.monotonic()
    git(job.repo.checkout, "fetch", "--quiet", "--no-tags", "origin",
        f"+{job.ref}:refs/local-ci/head",
        f"+refs/heads/{job.base}:refs/remotes/origin/{job.base}")
    fetched = git(job.repo.checkout, "rev-parse", "refs/local-ci/head")
    if fetched != job.sha:
        return "superseded"  # the branch moved since discovery; the next tick runs the new head
    post_status(job, "pending", f"running on {host_name()}")
    state, description = "error", ""
    try:
        try:
            if work.exists():
                shutil.rmtree(work)
            git(job.repo.checkout, "worktree", "prune")
            git(job.repo.checkout, "worktree", "add", "--quiet", "--detach", str(work), job.sha)
        except RuntimeError as e:
            log.write_text(f"{e}\n")
            description = f"could not check out: {e}"
            return state
        ci = work / "scripts" / "ci"
        if not os.access(ci, os.X_OK):
            log.write_text("scripts/ci is missing or not executable\n")
            description = "no executable scripts/ci at this commit"
            return state
        env = dict(os.environ, CI="1", LOCAL_CI="1", LOCAL_CI_REPO=job.repo.github,
                   LOCAL_CI_SHA=job.sha, LOCAL_CI_BASE=f"origin/{job.base}")
        code = execute(ci, work, env, log, timeout)
        elapsed = took(time.monotonic() - started)
        if code == 0:
            state, description = "success", f"passed in {elapsed} on {host_name()}"
        elif code is None:
            state, description = "failure", f"timed out after {took(timeout)} on {host_name()}"
        else:
            state = "failure"
            description = f"failed in {elapsed} on {host_name()}: {last_line(log)}"
        return state
    finally:
        if not description:
            description = "local-ci crashed; see the log on the machine that ran it"
        post_status(job, state, description)
        if job.pr is not None:
            if state == "success":
                upsert_comment(job, f"**local-ci** passed on `{job.sha[:7]}` ({description}).",
                               create=False)
            else:
                upsert_comment(job, (f"**local-ci** {state} on `{job.sha[:7]}`: {description}\n\n"
                                     f"Last {LOG_TAIL_LINES} lines:\n\n```\n{log_tail(log)}\n```\n"
                                     f"Run it yourself: `./scripts/ci` from the repo root."),
                               create=True)
        record({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "repo": job.repo.github, "sha": job.sha, "pr": job.pr, "state": state,
                "description": description, "log": str(log)})
        if work.exists():
            subprocess.run(["git", "-C", str(job.repo.checkout), "worktree", "remove", "--force",
                            str(work)], capture_output=True)
            shutil.rmtree(work, ignore_errors=True)


def locked(wait: bool):
    """One run at a time on this machine. A tick that finds the lock taken does nothing; `run`
    waits for it, so it never reports on a sha another run on this machine is still working on."""
    def deco(fn):
        def wrapper(*a, **k):
            state_dir().mkdir(parents=True, exist_ok=True)
            with (state_dir() / "lock").open("w") as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    print("another local-ci run holds the lock; skipping")
                    return 0
                return fn(*a, **k)
        return wrapper
    return deco


@locked(wait=False)
def cmd_tick(repos: List[Repo], timeout: int) -> int:
    bad = 0
    for repo in repos:
        try:
            jobs = discover(repo)
        except GhError as e:
            print(f"{repo.github}: {e}", file=sys.stderr)
            bad += 1
            continue
        for job in jobs:
            try:
                if not needs_run(job, timeout):
                    continue
                print(f"{job.label}: {run_job(job, timeout)}")
            except (GhError, RuntimeError) as e:
                print(f"{job.label}: {e}", file=sys.stderr)
                bad += 1
    return 1 if bad else 0


@locked(wait=True)
def cmd_run(job: Job, timeout: int, force: bool) -> int:
    """Exit 0 only when the sha's verdict is success, whether this call ran it or found it."""
    latest = None if force else latest_status(job)
    if latest is not None and latest["state"] != "pending":
        # Holding the lock, a pending can only be from a run that died or another machine: rerun it.
        print(f"{job.label}: {latest['state']} (existing: {latest.get('description', '')}; "
              f"pass --force to rerun)")
        return 0 if latest["state"] == "success" else 1
    state = run_job(job, timeout)
    print(f"{job.label}: {state}")
    return 0 if state == "success" else 1


@dataclass(frozen=True)
class HostedJob:
    name: str
    workflow: str
    event: str
    status: str
    conclusion: Optional[str]
    started: bool

    @property
    def refused(self) -> bool:
        """GitHub finished it without ever starting it: no runner picked it up and no step ran."""
        return (self.status == "completed" and not self.started
                and self.conclusion in ("failure", "cancelled", "startup_failure"))

    @property
    def verdict(self) -> str:
        return self.conclusion or self.status


def hosted_jobs(repo: Repo, sha: str) -> List[HostedJob]:
    """The newest run of each Actions job on the commit, skipped jobs left out."""
    runs = gh(f"repos/{repo.github}/actions/runs?head_sha={sha}&per_page=100")["workflow_runs"]
    newest = {}
    for run in sorted(runs, key=lambda r: r["created_at"]):
        jobs = gh(f"repos/{repo.github}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
        for j in jobs:
            if j.get("conclusion") == "skipped":
                continue
            newest[j["name"]] = HostedJob(j["name"], run["name"], run["event"], j["status"],
                                          j.get("conclusion"), bool(j.get("steps") or j.get("runner_name")))
    return list(newest.values())


def execute(script: Path, cwd: Path, env: dict, log: Path, timeout: int) -> Optional[int]:
    """Run script, output to log. Returns its exit code, or None if it timed out and was killed."""
    with log.open("w") as out:
        proc = subprocess.Popen([str(script)], cwd=cwd, env=env, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return None


def fallback_context(job: str) -> str:
    return f"{job} (local fallback)"


@locked(wait=True)
def cmd_fallback(repo: Repo, pr: Optional[int], branch: Optional[str], only: List[str],
                 timeout: int, dry_run: bool, force: bool, checker_ref: Optional[str]) -> int:
    if pr is not None:
        info = gh(f"repos/{repo.github}/pulls/{pr}")
        sha, base = info["head"]["sha"], info["base"]["ref"]
        target_ref, event = f"refs/pull/{pr}/merge", "pull_request"
    else:
        sha = gh(f"repos/{repo.github}/commits/{branch}")["sha"]
        base, target_ref, event = branch, f"refs/heads/{branch}", "push"
    label = f"{repo.github}{'#' + str(pr) if pr is not None else ':' + branch}@{sha[:7]}"
    jobs = hosted_jobs(repo, sha)
    if only:
        missing = sorted(set(only) - {j.name for j in jobs})
        if missing:
            print(f"{label}: no Actions job named {', '.join(missing)} on this commit "
                  f"(jobs: {', '.join(sorted(j.name for j in jobs)) or 'none'})")
            return 1
        jobs = [j for j in jobs if j.name in only]
    for j in jobs:
        if not j.refused:
            print(f"{label}: {j.name} ran on GitHub ({j.verdict}); no fallback")

    refused = [j for j in jobs if j.refused]
    if not refused:
        return 0
    git(repo.checkout, "fetch", "--quiet", "--no-tags", "origin",
        f"+{target_ref}:refs/local-ci/target",
        f"+refs/heads/{base}:refs/remotes/origin/{base}")
    target_sha = git(repo.checkout, "rev-parse", "refs/local-ci/target")
    if pr is not None:
        merged_head = git(repo.checkout, "rev-parse", "refs/local-ci/target^2")
        if merged_head != sha:
            print(f"{label}: GitHub's merge commit still holds {merged_head[:7]}, not the head; "
                  "try again in a minute", file=sys.stderr)
            return 1
    elif target_sha != sha:
        print(f"{label}: {branch} moved to {target_sha[:7]}; run it again", file=sys.stderr)
        return 1
    checker = checker_ref or f"refs/remotes/origin/{base}"
    checker_sha = git(repo.checkout, "rev-parse", checker)

    root = state_dir() / "fallback" / repo.github.replace("/", "__") / sha
    logs = state_dir() / "logs" / repo.github.replace("/", "__")
    logs.mkdir(parents=True, exist_ok=True)
    trusted, target = root / "checker", root / "target"
    worst = 0
    try:
        if root.exists():
            shutil.rmtree(root)
        git(repo.checkout, "worktree", "prune")
        git(repo.checkout, "worktree", "add", "--quiet", "--detach", str(trusted), checker_sha)
        git(repo.checkout, "worktree", "add", "--quiet", "--detach", str(target), target_sha)
        for j in refused:
            script = trusted / "scripts" / "fallback" / j.name
            if not os.access(script, os.X_OK):
                print(f"{label}: {j.name} was not started by GitHub and has no scripts/fallback/{j.name} "
                      f"at {checker_sha[:7]}; nothing to run")
                worst = 1
                continue
            if "# local-ci: explicit" in script.read_text(errors="replace") and j.name not in only:
                print(f"{label}: {j.name} was not started by GitHub; its fallback runs only when named "
                      f"(--job {j.name})")
                continue
            context = fallback_context(j.name)
            if not force and not dry_run:
                latest = latest_status(Job(repo, sha, target_ref, base, pr), context)
                if latest is not None and latest["state"] == "success":
                    print(f"{label}: {j.name} already passed locally ({latest.get('description', '')})")
                    continue
            log = logs / f"{sha}.{j.name}.log"
            env = dict(os.environ, CI="1", LOCAL_CI="1", LOCAL_CI_REPO=repo.github, LOCAL_CI_SHA=sha,
                       LOCAL_CI_TARGET=str(target), LOCAL_CI_EVENT=event,
                       LOCAL_CI_BASE=f"origin/{base}", LOCAL_CI_BASE_BRANCH=base,
                       LOCAL_CI_DRY_RUN="1" if dry_run else "0")
            started = time.monotonic()
            from_note = "" if checker_ref is None else f", checker from {checker_sha[:7]}"
            if not dry_run:
                gh(f"repos/{repo.github}/statuses/{sha}", "-X", "POST",
                   body={"state": "pending", "context": context,
                         "description": f"GitHub didn't start it; running on {host_name()}"})
            code = execute(script, trusted, env, log, timeout)
            elapsed = took(time.monotonic() - started)
            if code == 0:
                state, desc = "success", f"GitHub didn't start it; passed on {host_name()} in {elapsed}{from_note}"
            elif code is None:
                state, desc = "failure", f"timed out after {took(timeout)} on {host_name()}{from_note}"
            else:
                state, desc = "failure", f"failed on {host_name()}{from_note}: {last_line(log)}"
            print(f"{label}: {j.name} {'dry run ' if dry_run else ''}{state}: {desc}\n  log: {log}")
            if not dry_run:
                gh(f"repos/{repo.github}/statuses/{sha}", "-X", "POST",
                   body={"state": state, "context": context, "description": desc[:DESCRIPTION_LIMIT]})
            if state != "success":
                worst = 1
    finally:
        for wt in (trusted, target):
            if wt.exists():
                subprocess.run(["git", "-C", str(repo.checkout), "worktree", "remove", "--force", str(wt)],
                               capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
    return worst


def plist(repos: List[Repo], interval: int, timeout: int) -> bytes:
    args = [sys.executable, str(Path(__file__).resolve()), "tick", "--timeout", str(timeout)]
    for r in repos:
        args += ["--repo", f"{r.github}={r.checkout}"]
    log = str(Path.home() / "Library/Logs/local-ci.log")
    return plistlib.dumps({
        "Label": LABEL, "ProgramArguments": args, "StartInterval": interval,
        "RunAtLoad": True, "StandardOutPath": log, "StandardErrorPath": log,
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "ProcessType": "Background", "LowPriorityIO": True,
    })


def plist_path() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def cmd_install(repos: List[Repo], interval: int, timeout: int) -> int:
    for r in repos:
        git(r.checkout, "remote", "get-url", "origin")
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    launchctl("bootout", f"{domain}/{LABEL}")
    path.write_bytes(plist(repos, interval, timeout))
    p = launchctl("bootstrap", domain, str(path))
    if p.returncode != 0:
        print(f"launchctl bootstrap failed: {p.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"installed {path}: ticks every {interval}s for {', '.join(r.github for r in repos)}")
    return 0


def cmd_uninstall() -> int:
    launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    plist_path().unlink(missing_ok=True)
    print(f"removed {plist_path()}")
    return 0


def cmd_status() -> int:
    p = launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    print("agent: " + ("loaded" if p.returncode == 0 else "not loaded"))
    results = state_dir() / "results.jsonl"
    if results.exists():
        for line in results.read_text().splitlines()[-10:]:
            r = json.loads(line)
            where = f"#{r['pr']}" if r["pr"] else " branch head"
            print(f"{r['at']} {r['repo']}{where} {r['sha'][:7]} {r['state']}: {r['description']}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["tick", "run", "fallback", "install", "uninstall", "status",
                                        "print-plist"])
    ap.add_argument("--repo", action="append", type=Repo.parse, default=[])
    ap.add_argument("--pr", type=int)
    ap.add_argument("--branch")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--job", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--checker-ref", help="fallback: take scripts/fallback from this ref instead of "
                    "the base branch (only to try a fallback script before it merges)")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--interval", type=int, default=300)
    a = ap.parse_args(argv)
    if a.command in ("tick", "install", "print-plist", "run", "fallback") and not a.repo:
        ap.error(f"{a.command} needs at least one --repo OWNER/NAME=CHECKOUT")
    if a.command == "tick":
        return cmd_tick(a.repo, a.timeout)
    if a.command == "run":
        if len(a.repo) != 1 or (a.pr is None) == (a.branch is None):
            ap.error("run takes one --repo and exactly one of --pr or --branch")
        job = pr_job(a.repo[0], a.pr) if a.pr is not None else branch_job(a.repo[0], a.branch)
        return cmd_run(job, a.timeout, a.force)
    if a.command == "fallback":
        if len(a.repo) != 1 or (a.pr is None) == (a.branch is None):
            ap.error("fallback takes one --repo and exactly one of --pr or --branch")
        return cmd_fallback(a.repo[0], a.pr, a.branch, a.job, a.timeout, a.dry_run, a.force,
                            a.checker_ref)
    if a.command == "install":
        return cmd_install(a.repo, a.interval, a.timeout)
    if a.command == "print-plist":
        sys.stdout.write(plist(a.repo, a.interval, a.timeout).decode())
        return 0
    if a.command == "uninstall":
        return cmd_uninstall()
    return cmd_status()


if __name__ == "__main__":
    sys.exit(main())
