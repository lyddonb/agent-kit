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


def needs_run(job: Job, timeout: int) -> bool:
    statuses = gh(f"repos/{job.repo.github}/commits/{job.sha}/statuses?per_page=100")
    mine = [s for s in statuses if s["context"] == CONTEXT]  # newest first
    if not mine:
        return True
    latest = mine[0]
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
        with log.open("w") as out:
            proc = subprocess.Popen([str(ci)], cwd=work, env=env, stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                code = None
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


def locked(fn):
    """One run at a time on this machine; a tick that finds the lock taken does nothing."""
    def wrapper(*a, **k):
        state_dir().mkdir(parents=True, exist_ok=True)
        with (state_dir() / "lock").open("w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("another local-ci run holds the lock; skipping")
                return 0
            return fn(*a, **k)
    return wrapper


@locked
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


@locked
def cmd_run(job: Job, timeout: int, force: bool) -> int:
    if not force and not needs_run(job, timeout):
        print(f"{job.label}: already has a finished {CONTEXT} status (pass --force to rerun)")
        return 0
    state = run_job(job, timeout)
    print(f"{job.label}: {state}")
    return 0 if state == "success" else 1


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
    ap.add_argument("command", choices=["tick", "run", "install", "uninstall", "status", "print-plist"])
    ap.add_argument("--repo", action="append", type=Repo.parse, default=[])
    ap.add_argument("--pr", type=int)
    ap.add_argument("--branch")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--interval", type=int, default=300)
    a = ap.parse_args(argv)
    if a.command in ("tick", "install", "print-plist", "run") and not a.repo:
        ap.error(f"{a.command} needs at least one --repo OWNER/NAME=CHECKOUT")
    if a.command == "tick":
        return cmd_tick(a.repo, a.timeout)
    if a.command == "run":
        if len(a.repo) != 1 or (a.pr is None) == (a.branch is None):
            ap.error("run takes one --repo and exactly one of --pr or --branch")
        job = pr_job(a.repo[0], a.pr) if a.pr is not None else branch_job(a.repo[0], a.branch)
        return cmd_run(job, a.timeout, a.force)
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
