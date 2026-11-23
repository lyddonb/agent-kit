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

Test records. Each run gets two variables: LOCAL_CI_RECORD, a path outside the worktree, and
QUALITY_PY, the qualitydirector's quality.py next to this skill. A scripts/ci that writes a test
record there (quality.py record-junit --out "$LOCAL_CI_RECORD" -- pytest ...) has it published,
with a manifest.json local_ci.py writes itself, to the ref refs/local-ci/records of the repo:
runs/<sha>/<started>/manifest.json and test-results.jsonl, one commit per run. A ref outside
refs/heads starts no workflow. The quality books' fetch reads it. A record that fails to publish
is retried on every tick; the status never depends on it. The record is the repo's own code's
output, so it is published only when it is a regular file under RECORD_LIMIT whose first line is a
recorder header.

Options: --timeout SECONDS (default 1800) per run. Needs git and gh (logged in).
Test hooks: LOCAL_CI_GH (the gh binary), LOCAL_CI_STATE (state folder, default
~/Library/Caches/local-ci), LOCAL_CI_HOST (the name in status descriptions).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

CONTEXT = "local-ci"
RECORDS_REF = "refs/local-ci/records"
RECORD_LIMIT = 8 << 20
QUALITY_PY = Path(__file__).resolve().parents[2] / "qualitydirector" / "scripts" / "quality.py"
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
    head_branch: str = ""  # the PR's head branch; for a branch job, the branch

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
    jobs.append(Job(repo, head["sha"], f"refs/heads/{default}", default, None, default))
    for pr in gh_list(f"repos/{repo.github}/pulls?state=open&per_page=100"):
        if pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != repo.github:
            continue  # a fork's code never runs here
        jobs.append(Job(repo, pr["head"]["sha"], f"refs/pull/{pr['number']}/head",
                        pr["base"]["ref"], pr["number"], pr["head"].get("ref") or ""))
    return jobs


def pr_job(repo: Repo, number: int) -> Job:
    pr = gh(f"repos/{repo.github}/pulls/{number}")
    return Job(repo, pr["head"]["sha"], f"refs/pull/{number}/head", pr["base"]["ref"], number,
               pr["head"].get("ref") or "")


def branch_job(repo: Repo, branch: str) -> Job:
    head = gh(f"repos/{repo.github}/commits/{branch}")
    return Job(repo, head["sha"], f"refs/heads/{branch}", branch, None, branch)


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


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def records_dir(repo: Repo) -> Path:
    """Runs kept for publishing, as <sha>/<started>/. scripts/ci is never pointed here."""
    return state_dir() / "records" / repo.github.replace("/", "__")


def scratch_dir(repo: Repo, sha: str) -> Path:
    """Where scripts/ci is told to write its record; emptied before and after each run."""
    return state_dir() / "scratch" / repo.github.replace("/", "__") / sha


_SHA = re.compile(r"[0-9a-f]{40}")
_STARTED = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def read_record(path: Path) -> "tuple[Optional[bytes], str]":
    """The record bytes and "", or None and why it is not published. Never follows a link or blocks on
    a FIFO, and the bytes are read once from the file checked, so a later swap of the path changes nothing."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, "no record"
    except OSError as e:
        return None, f"cannot open the record ({e.strerror})"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None, "the record is not a regular file"
        chunks, size = [], 0
        while chunk := os.read(fd, 1 << 16):
            size += len(chunk)
            if size > RECORD_LIMIT:
                return None, f"the record is over {RECORD_LIMIT >> 20} MB"
            chunks.append(chunk)
    except OSError as e:
        return None, f"cannot read the record ({e.strerror})"
    finally:
        os.close(fd)
    data = b"".join(chunks)
    try:
        header = json.loads(data.split(b"\n", 1)[0])
    except ValueError:
        return None, "the record's first line is not JSON"
    if not isinstance(header, dict) or header.get("v") != 1:
        return None, "the record's first line is not a recorder header"
    return data, ""


def keep_record(job: Job, scratch: Path, started: str, completed: str, code: Optional[int]) -> None:
    """Copy a record worth publishing from the scratch folder into records_dir with a manifest."""
    data, why = read_record(scratch / "test-results.jsonl")
    if data is None:
        if why != "no record":  # a repo whose scripts/ci records nothing is the common case, and quiet
            print(f"{job.label}: {why}; nothing to publish", file=sys.stderr)
        return
    manifest = {"v": 1, "github": job.repo.github, "sha": job.sha,
                "event": "pull_request" if job.pr is not None else "push", "pr": job.pr,
                "head_branch": job.head_branch, "base": job.base, "started": started,
                "completed": completed, "exit_code": code, "host": host_name()}
    run_dir = records_dir(job.repo) / job.sha / started
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    (run_dir / "test-results.jsonl").write_bytes(data)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def kept_run(run_dir: Path, github: str) -> "tuple[Optional[dict], str]":
    """The two files of a kept run as bytes, read without following links, or None and why it is
    skipped. Its folder names and its manifest must agree, so a folder planted by other code is not published."""
    sha, started = run_dir.parent.name, run_dir.name
    if not _SHA.fullmatch(sha) or not _STARTED.fullmatch(started):
        return None, "not a run folder"
    record, why = read_record(run_dir / "test-results.jsonl")
    if record is None:
        return None, why
    try:
        fd = os.open(run_dir / "manifest.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None, "the manifest is not a regular file"
            raw = os.read(fd, 1 << 16)
        finally:
            os.close(fd)
        manifest = json.loads(raw)
    except (OSError, ValueError) as e:
        return None, f"unreadable manifest ({e})"
    if not isinstance(manifest, dict) or manifest.get("sha") != sha or manifest.get("started") != started \
            or manifest.get("github") != github:
        return None, "the manifest does not match its folder"
    return {"manifest.json": raw, "test-results.jsonl": record}, ""


def publish_records(repo: Repo) -> int:
    """Add every kept run to RECORDS_REF in one commit and push it, then delete the published runs.
    A run already in the ref's tree (an earlier push that landed) is only deleted. A bad folder is
    skipped with a line and never blocks the others. Returns the runs published."""
    root = records_dir(repo)
    pending = sorted(p for p in root.glob("*/*") if p.is_dir() and not p.is_symlink())
    if not pending:
        return 0
    checkout = repo.checkout
    fetched = subprocess.run(["git", "-C", str(checkout), "fetch", "--quiet", "--no-tags", "origin",
                              f"+{RECORDS_REF}:refs/local-ci/records-origin"], capture_output=True, text=True)
    parent = git(checkout, "rev-parse", "refs/local-ci/records-origin") if fetched.returncode == 0 else None
    index = state_dir() / f"records-index-{os.getpid()}"
    env = dict(os.environ, GIT_INDEX_FILE=str(index), GIT_AUTHOR_NAME="local-ci", GIT_COMMITTER_NAME="local-ci",
               GIT_AUTHOR_EMAIL=f"local-ci@{host_name()}.invalid", GIT_COMMITTER_EMAIL=f"local-ci@{host_name()}.invalid")

    def run(*args: str, stdin: Optional[bytes] = None) -> str:
        p = subprocess.run(["git", "-C", str(checkout), *args], input=stdin, capture_output=True, env=env)
        if p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr.decode(errors='replace').strip()}")
        return p.stdout.decode().strip()

    done: List[Path] = []
    added = 0
    try:
        index.unlink(missing_ok=True)
        if parent:
            run("read-tree", parent)
        have = set(run("ls-files").splitlines()) if parent else set()
        for run_dir in pending:
            prefix = f"runs/{run_dir.parent.name}/{run_dir.name}"
            if f"{prefix}/manifest.json" in have:
                done.append(run_dir)
                continue
            files, why = kept_run(run_dir, repo.github)
            if files is None:
                print(f"{repo.github}: skipped {run_dir.relative_to(root)}: {why}", file=sys.stderr)
                continue
            for name, data in files.items():
                blob = run("hash-object", "-w", "--no-filters", "--stdin", stdin=data)
                run("update-index", "--add", "--cacheinfo", f"100644,{blob},{prefix}/{name}")
            done.append(run_dir)
            added += 1
        if added:
            tree = run("write-tree")
            message = f"local-ci: {added} test record{'s' * (added != 1)} from {host_name()}"
            commit = run("commit-tree", tree, *(["-p", parent] if parent else []), "-m", message)
            pushed = subprocess.run(["git", "-C", str(checkout), "push", "--quiet", "--no-verify", "origin",
                                     f"{commit}:{RECORDS_REF}"], capture_output=True, text=True)
            if pushed.returncode != 0:
                raise RuntimeError(f"git push {RECORDS_REF}: {pushed.stderr.strip()}")
    finally:
        index.unlink(missing_ok=True)
    for run_dir in done:
        shutil.rmtree(run_dir, ignore_errors=True)
        with contextlib.suppress(OSError):
            run_dir.parent.rmdir()  # the sha folder, once its last run is gone
    return added


def publish_quietly(repo: Repo) -> None:
    try:
        count = publish_records(repo)
    except RuntimeError as e:
        print(f"{repo.github}: test records not published, retried next tick: {e}", file=sys.stderr)
        return
    if count:
        print(f"{repo.github}: published {count} test record{'s' * (count != 1)} to {RECORDS_REF}")


def run_job(job: Job, timeout: int) -> str:
    """Run one job and post its result. Returns the final state."""
    work = state_dir() / "work" / job.repo.github.replace("/", "__") / job.sha
    logs = state_dir() / "logs" / job.repo.github.replace("/", "__")
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{job.sha}.log"
    started = time.monotonic()
    started_at = utc_stamp()
    scratch = scratch_dir(job.repo, job.sha)
    code: Optional[int] = None
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
        try:
            shutil.rmtree(scratch, ignore_errors=True)
            scratch.mkdir(parents=True)
            env.update(LOCAL_CI_RECORD=str(scratch / "test-results.jsonl"), QUALITY_PY=str(QUALITY_PY))
        except OSError as e:  # the run goes on without a record; its status never depends on one
            print(f"{job.label}: no record this run, cannot make {scratch}: {e}", file=sys.stderr)
        code = execute(ci, work, env, log, timeout)
        if "LOCAL_CI_RECORD" in env:
            try:
                keep_record(job, scratch, started_at, utc_stamp(), code)
            except OSError as e:
                print(f"{job.label}: test record not kept: {e}", file=sys.stderr)
            shutil.rmtree(scratch, ignore_errors=True)
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
        publish_quietly(repo)
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
    publish_quietly(job.repo)
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
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return None
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)  # nothing scripts/ci started outlives it to touch its record
        return code


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
