#!/usr/bin/env python3
"""inflight.py - list the work in flight across your repos, and check whether candidate items
would collide with it. Read-only: it sends nothing and edits nothing.

  python3 inflight.py PATH [PATH ...] [--sessions FILE] [--candidates FILE] [--json]

Each PATH is a git repo, or a folder whose direct subfolders are git repos (hidden ones are
skipped), read the same way as waiting-on-me's waiting.py. A claim is one line of work in flight:

  worktree   a linked git worktree; its paths are the files changed since the merge base with
             the remote default branch, plus uncommitted and untracked files
  checkout   the main checkout, only when it has uncommitted or untracked files
  pull       an open pull request, drafts included; one on a worktree's branch joins that claim
  session    an agent session from --sessions; it claims only the roadmap ids in its title

A claim with no changed files yet has an unknown footprint: something may be about to write
anywhere in that repo. It shows the hours since its HEAD last moved. Roadmap ids (R42, M3, H18) in a branch name or a pull request title are
the claim's ids; a dotted id (P2.3) is kept whole. A file touched by at least 40% of the last 30 commits on the default branch (in
a repo with at least 10 of them) is a hot file (changelogs, manifests, version files); an overlap only on hot files means a rebase,
not a conflict. A worktree folder under .worktrees/ or .claude/worktrees/ whose git link is
broken is listed as stale.

--sessions FILE is a JSON list of {"title", "cwd", "running", "last_active", "pr_state"} from your
tool's session list: running is true or false, last_active is ISO 8601, and pr_state is the pull
request's state or null. Claude Code desktop's raw list_sessions output works as it is: a row with a
sessionId is read through its isRunning, lastActivityAt and prState. Any other row must have exactly
those five keys. A row with a key missing or unknown, or a value it cannot read, stops the run with
exit 1 before anything is reported, since a row read wrong makes busy work look free. A session counts while it is running, or while its
pull request is not merged or closed and it was active in the last 72 hours. A session whose cwd is
inside one repo claims ids in that repo; one in a folder that holds other repos claims them in all.
A worktree of a repo that holds other repos (a workspace) is where a session lives while it edits
those repos, so its branch's ids are claimed in all of them too.

--candidates FILE is a JSON list, best first, of {"id", "repo", "paths"}: the folder name of the
repo, and the files or fnmatch globs the item is expected to touch. Each gets a state:

  taken     a claim in that repo carries its id
  conflict  it overlaps a claim, or a better candidate kept above it, on a file that is not hot
  unknown   it is clear of every known footprint, but the repo has a claim with an unknown one
  rebase    it overlaps only on hot files
  clear     no overlap

Anything it cannot read is listed under "Could not read" and the exit code is 1.

Test hook: INFLIGHT_GH names the gh binary (default: gh on PATH).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "waiting-on-me" / "scripts"))
try:
    from waiting import find_repos, git, github_slug
except ImportError:
    sys.exit("inflight.py: needs the waiting-on-me skill installed beside parallel-next (it reads repos with its waiting.py)")

HOT_WINDOW = 30
HOT_SHARE = 0.4
HOT_MIN_COMMITS = 10
SESSION_WINDOW_HOURS = 72
ENDED_PULLS = {"MERGED", "CLOSED"}
STATES = ("taken", "conflict", "unknown", "rebase", "clear")
ID_IN_TITLE = re.compile(r"\b([A-Z]{1,2}\d+(?:\.\d+)*)\b")
SESSION_KEYS = ("title", "cwd", "running", "last_active", "pr_state")
RAW_SESSION_MARKER = "sessionId"
RAW_SESSION_KEYS = {"title": "title", "cwd": "cwd", "running": "isRunning", "last_active": "lastActivityAt",
                    "pr_state": "prState"}
RAW_SESSION_OPTIONAL = {"pr_state"}
ID_IN_BRANCH = re.compile(r"(?<![a-z0-9.])([a-z]{1,2}\d+(?:\.\d+)*)(?![a-z0-9])", re.IGNORECASE)
WORKTREE_HOMES = (".worktrees", ".claude/worktrees")


@dataclass
class Claim:
    repo: str
    kind: str
    ref: str
    where: str
    ids: list[str] = field(default_factory=list)
    paths: list[str] | None = None
    links: list[str] = field(default_factory=list)
    idle_hours: int | None = None


@dataclass(frozen=True)
class Session:
    title: str
    cwd: str
    running: bool
    last_active: datetime
    pr_state: str | None


class SessionListError(ValueError):
    pass


@dataclass
class Verdict:
    id: str
    repo: str
    state: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class Problem:
    repo: str
    source: str
    message: str


@dataclass
class RepoState:
    name: str
    path: Path
    default: str | None
    hot: set[str]
    tracked: list[str]


@dataclass
class Report:
    repos: list[RepoState] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def ids_in_branch(branch: str) -> list[str]:
    return sorted({m.upper() for m in ID_IN_BRANCH.findall(branch)})


def ids_in_title(title: str) -> list[str]:
    return sorted(set(ID_IN_TITLE.findall(title)))


def default_ref(path: Path) -> str | None:
    ref = git(path, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref
    for guess in ("origin/main", "origin/master"):
        if git(path, "rev-parse", "-q", "--verify", guess):
            return guess
    return None


def hot_files(path: Path, default: str) -> set[str]:
    out = git(path, "log", "--first-parent", "-n", str(HOT_WINDOW), "--diff-merges=first-parent",
              "--name-only", "--format=format:@@", default) or ""
    commits, counts = 0, {}
    for line in out.splitlines():
        if line == "@@":
            commits += 1
        elif line:
            counts[line] = counts.get(line, 0) + 1
    if commits < HOT_MIN_COMMITS:
        return set()
    return {f for f, n in counts.items() if n / commits >= HOT_SHARE}


def idle_hours(tree: Path) -> int | None:
    match = re.fullmatch(r"HEAD@\{(\d+)\}", git(tree, "log", "-g", "-1", "--format=%gd", "--date=unix", "HEAD") or "")
    return int((time.time() - int(match.group(1))) // 3600) if match else None


def dirty_paths(tree: Path) -> list[str] | None:
    proc = subprocess.run(["git", "-C", str(tree), "status", "--porcelain", "-z", "--untracked-files=all"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    paths, fields = [], proc.stdout.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        if not any(entry[3:].startswith(home + "/") for home in WORKTREE_HOMES):
            paths.append(entry[3:])
        if entry[0] in "RC":
            i += 1
    return paths


def worktree_entries(path: Path) -> list[dict]:
    out = git(path, "worktree", "list", "--porcelain") or ""
    entries, current = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if current:
                entries.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value or True
    return entries


def read_worktrees(repo: RepoState, report: Report) -> None:
    for n, entry in enumerate(worktree_entries(repo.path)):
        tree = Path(entry["worktree"])
        branch = str(entry.get("branch", "")).removeprefix("refs/heads/")
        ref = branch or f"detached at {str(entry.get('HEAD', ''))[:7]}"
        if entry.get("prunable"):
            report.stale.append(f"{repo.name}: {tree} (git lists it as prunable: {entry['prunable']})")
            continue
        dirty = dirty_paths(tree)
        if dirty is None:
            report.problems.append(Problem(repo.name, f"git status in {tree}", "could not read the worktree"))
            continue
        if n == 0:
            if dirty:
                report.claims.append(Claim(repo.name, "checkout", ref, str(tree), ids_in_branch(branch),
                                           sorted(set(dirty))))
            continue
        committed: list[str] = []
        if repo.default:
            base = git(tree, "merge-base", repo.default, "HEAD")
            if base:
                committed = (git(tree, "diff", "--name-only", base, "HEAD") or "").splitlines()
        paths = sorted(set(committed) | set(dirty))
        report.claims.append(Claim(repo.name, "worktree", ref, str(tree), ids_in_branch(branch),
                                   paths or None, idle_hours=None if paths else idle_hours(tree)))


def read_stale(roots: list[Path], report: Report) -> None:
    seen: set[Path] = set()
    for root in roots:
        for home in WORKTREE_HOMES:
            folder = root / home
            if not folder.is_dir():
                continue
            for tree in sorted(folder.iterdir()):
                link = tree / ".git"
                if tree in seen or not link.is_file():
                    continue
                seen.add(tree)
                text = link.read_text(errors="replace").strip()
                gitdir = Path(text.removeprefix("gitdir:").strip())
                if not gitdir.is_absolute():
                    gitdir = (tree / gitdir).resolve()
                if not gitdir.exists():
                    report.stale.append(f"{tree} (its git link points at {gitdir}, which does not exist)")


def read_pulls(repo: RepoState, slug: str | None, report: Report) -> None:
    if not slug:
        return
    gh = shutil.which(os.environ.get("INFLIGHT_GH") or "gh")
    if not gh:
        report.problems.append(Problem(repo.name, "gh", "cannot find the gh CLI, so no pull requests were read"))
        return
    proc = subprocess.run([gh, "pr", "list", "--repo", slug, "--state", "open", "--limit", "200",
                           "--json", "number,title,url,headRefName,isDraft,files"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        message = (proc.stderr.strip().splitlines() or [f"gh exited {proc.returncode}"])[-1]
        report.problems.append(Problem(repo.name, f"gh pr list --repo {slug}", message))
        return
    try:
        pulls = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        report.problems.append(Problem(repo.name, f"gh pr list --repo {slug}", "output is not JSON"))
        return
    by_branch = {c.ref: c for c in report.claims if c.repo == repo.name and c.kind == "worktree"}
    for p in sorted(pulls, key=lambda p: p.get("number", 0)):
        branch = p.get("headRefName", "")
        files = [f["path"] for f in p.get("files") or [] if f.get("path")]
        ids = sorted(set(ids_in_branch(branch)) | set(ids_in_title(p.get("title", ""))))
        link = p.get("url", "")
        if p.get("isDraft"):
            link += " (draft)"
        claim = by_branch.get(branch)
        if claim:
            claim.ids = sorted(set(claim.ids) | set(ids))
            claim.paths = sorted(set(claim.paths or []) | set(files)) or None
            claim.links.append(link)
            continue
        report.claims.append(Claim(repo.name, "pull", branch, f"#{p.get('number')} {p.get('title', '')}",
                                   ids, sorted(set(files)) or None, [link]))


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def read_session_row(row: dict) -> Session | list[str]:
    raw = RAW_SESSION_MARKER in row
    names = RAW_SESSION_KEYS if raw else {k: k for k in SESSION_KEYS}
    missing = [src for key, src in names.items() if src not in row and not (raw and key in RAW_SESSION_OPTIONAL)]
    unknown = [] if raw else sorted(set(row) - set(SESSION_KEYS))
    errors = []
    if missing:
        errors.append("missing " + ", ".join(missing))
    if unknown:
        errors.append("unknown " + ", ".join(unknown))
    if errors:
        return errors
    value = {key: row.get(src) for key, src in names.items()}
    last_active = parse_time(value["last_active"])
    for key, ok in (("title", isinstance(value["title"], str)), ("cwd", isinstance(value["cwd"], str)),
                    ("running", isinstance(value["running"], bool)), ("last_active", last_active is not None),
                    ("pr_state", value["pr_state"] is None or isinstance(value["pr_state"], str))):
        if not ok:
            errors.append(f"{names[key]} is {json.dumps(value[key])}")
    if errors:
        return errors
    return Session(value["title"], value["cwd"], value["running"], last_active, value["pr_state"])


def read_session_list(rows: list[dict]) -> list[Session]:
    sessions, errors = [], []
    for n, row in enumerate(rows, 1):
        read = read_session_row(row)
        if isinstance(read, Session):
            sessions.append(read)
            continue
        title = row.get("title")
        name = f"row {n}" + (f" ({json.dumps(title)})" if isinstance(title, str) else "")
        errors.append(f"  {name}: {'; '.join(read)}")
    if errors:
        keys = ", ".join(f'"{k}"' for k in SESSION_KEYS)
        raise SessionListError("\n".join(errors + [
            f"Each row needs exactly {{{keys}}}: running is true or false, last_active is ISO 8601, "
            "pr_state is the pull request's state or null.",
            "Claude Code desktop's raw list_sessions output works as it is: rows with a sessionId are read "
            "through isRunning, lastActivityAt and prState."]))
    return sessions


def session_live(s: Session, now: datetime) -> bool:
    if s.running:
        return True
    if (s.pr_state or "").upper() in ENDED_PULLS:
        return False
    return (now - s.last_active).total_seconds() <= SESSION_WINDOW_HOURS * 3600


def session_repo(cwd: str, repos: list[RepoState]) -> str | None:
    try:
        where = Path(cwd).expanduser().resolve()
    except OSError:
        return None
    homes = []
    for r in repos:
        roots = [r.path] + [Path(e["worktree"]) for e in worktree_entries(r.path)[1:]]
        if any(where == root or root in where.parents for root in roots):
            homes.append(r)
    if not homes:
        return None
    home = max(homes, key=lambda r: len(r.path.parts))
    holds_others = any(home.path in r.path.parents for r in repos if r is not home)
    return "*" if holds_others else home.name


def read_sessions(sessions: list[Session], report: Report, now: datetime) -> None:
    for s in sessions:
        if not session_live(s, now):
            continue
        repo = session_repo(s.cwd, report.repos)
        if repo is None:
            continue
        state = "running" if s.running else f"last active {s.last_active.isoformat()}"
        report.claims.append(Claim(repo, "session", s.title, f"{s.cwd} ({state})", ids_in_title(s.title), []))


def matches(pattern: str, path: str) -> bool:
    pattern = pattern.rstrip("/")
    return path == pattern or path.startswith(pattern + "/") or fnmatchcase(path, pattern)


def expand(patterns: list[str], universe: list[str]) -> set[str]:
    out = {p.rstrip("/") for p in patterns if not any(ch in p for ch in "*?[")}
    for path in universe:
        if any(matches(p, path) for p in patterns):
            out.add(path)
    return out


def describe(files: set[str]) -> str:
    shown = sorted(files)
    return ", ".join(shown[:4]) + (f" and {len(shown) - 4} more" if len(shown) > 4 else "")


def check(candidates: list[dict], report: Report) -> None:
    repos = {r.name: r for r in report.repos}
    kept: list[tuple[dict, set[str]]] = []
    for cand in candidates:
        cid, name, patterns = str(cand.get("id", "")), str(cand.get("repo", "")), cand.get("paths") or []
        repo = repos.get(name)
        if repo is None:
            report.problems.append(Problem(name or "?", f"candidate {cid}", "no repo of that name was read"))
            continue
        claims = [c for c in report.claims if c.repo in (name, "*")]
        universe = sorted(set(repo.tracked) | {p for c in claims for p in c.paths or []})
        mine = expand(patterns, universe)
        verdict = Verdict(cid, name, "clear")
        hits: list[str] = []
        for c in claims:
            label = f"{c.kind} {c.ref}"
            if cid and cid.upper() in c.ids:
                verdict.reasons.append(f"taken by {label}")
                hits.append("taken")
            if c.kind == "session" or c.repo == "*":
                continue
            if c.paths is None:
                idle = f", idle {c.idle_hours}h" if c.idle_hours is not None else ""
                verdict.reasons.append(f"{label} in {c.where} has no changes yet{idle}, so its footprint is unknown")
                hits.append("unknown")
                continue
            shared = mine & set(c.paths)
            if shared - repo.hot:
                verdict.reasons.append(f"overlaps {label} on {describe(shared - repo.hot)}")
                hits.append("conflict")
            elif shared:
                verdict.reasons.append(f"overlaps {label} only on hot files: {describe(shared)}")
                hits.append("rebase")
        for other, files in kept:
            if other["repo"] != name:
                continue
            shared = mine & files
            if shared - repo.hot:
                verdict.reasons.append(f"overlaps candidate {other['id']} on {describe(shared - repo.hot)}")
                hits.append("conflict")
            elif shared:
                verdict.reasons.append(f"overlaps candidate {other['id']} only on hot files: {describe(shared)}")
                hits.append("rebase")
        if not patterns:
            verdict.reasons.append("no paths given, so nothing was checked")
            hits.append("unknown")
        verdict.state = min(hits, key=STATES.index) if hits else "clear"
        report.verdicts.append(verdict)
        if verdict.state not in ("taken", "conflict"):
            kept.append(({"id": cid, "repo": name}, mine))


def collect(paths: list[str], candidates: list[dict] | None, sessions: list[Session] | None = None,
            now: datetime | None = None) -> Report:
    report = Report()
    roots = [Path(p).expanduser().resolve() for p in paths]
    for path in find_repos(paths):
        default = default_ref(path)
        if default is None:
            report.problems.append(Problem(path.name, "git", "no origin default branch, so committed changes "
                                           "and hot files were not read"))
        tracked = (git(path, "ls-files") or "").splitlines()
        repo = RepoState(path.name, path, default, hot_files(path, default) if default else set(), tracked)
        report.repos.append(repo)
        read_worktrees(repo, report)
        read_pulls(repo, github_slug(path), report)
    read_stale(roots + [r.path for r in report.repos], report)
    for home in report.repos:
        if any(home.path in r.path.parents for r in report.repos if r is not home):
            report.claims += [Claim("*", c.kind, c.ref, c.where, c.ids, [], c.links)
                              for c in report.claims if c.repo == home.name and c.ids]
    if sessions:
        read_sessions(sessions, report, now or datetime.now(timezone.utc))
    if candidates is not None:
        check(candidates, report)
    return report


def render(report: Report) -> str:
    out = ["# Work in flight", ""]
    out += [f"Read {len(report.repos)} repos: {', '.join(r.name for r in report.repos) or 'none'}.", ""]
    out += [f"## Claims ({len(report.claims)})", ""]
    for c in report.claims:
        ids = f" [{', '.join(c.ids)}]" if c.ids else ""
        if c.kind == "session" or c.repo == "*":
            footprint = "ids only"
        elif c.paths is None:
            idle = f", idle {c.idle_hours}h" if c.idle_hours is not None else ""
            footprint = f"footprint unknown (no changes yet{idle})"
        else:
            footprint = f"{len(c.paths)} files: {describe(set(c.paths))}"
        links = f" <{'> <'.join(c.links)}>" if c.links else ""
        out.append(f"- {c.repo} {c.kind} {c.ref}{ids}: {footprint}. {c.where}{links}")
    if not report.claims:
        out.append("None.")
    out.append("")
    hot = [r for r in report.repos if r.hot]
    if hot:
        out += ["## Hot files (an overlap on these means a rebase)", ""]
        out += [f"- {r.name}: {', '.join(sorted(r.hot))}" for r in hot]
        out.append("")
    if report.verdicts:
        out += [f"## Candidates ({len(report.verdicts)})", ""]
        for v in report.verdicts:
            why = f": {'; '.join(v.reasons)}" if v.reasons else ""
            out.append(f"- {v.repo} {v.id}: {v.state}{why}")
        out.append("")
    if report.stale:
        out += [f"## Stale worktree folders ({len(report.stale)})", ""]
        out += [f"- {s}" for s in report.stale]
        out.append("")
    if report.problems:
        out += [f"## Could not read ({len(report.problems)})", ""]
        out += [f"- {p.repo}: {p.source}: {p.message}" for p in report.problems]
        out.append("")
    return "\n".join(out)


def as_json(report: Report) -> str:
    return json.dumps({
        "repos": [{"name": r.name, "path": str(r.path), "default": r.default, "hot": sorted(r.hot)}
                  for r in report.repos],
        "claims": [asdict(c) for c in report.claims],
        "verdicts": [asdict(v) for v in report.verdicts],
        "stale": report.stale,
        "problems": [asdict(p) for p in report.problems],
    }, indent=2)


def load_list(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list) or not all(isinstance(c, dict) for c in data):
        raise ValueError("it must be a JSON list of objects")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List the work in flight and check candidates against it.")
    parser.add_argument("paths", nargs="+", metavar="PATH", help="a git repo, or a folder of git repos")
    parser.add_argument("--sessions", metavar="FILE",
                        help='JSON list of {"title", "cwd", "running", "last_active", "pr_state"}, '
                             "or Claude Code desktop's raw list_sessions output")
    parser.add_argument("--candidates", metavar="FILE",
                        help='JSON list, best first, of {"id", "repo", "paths"} to check against the claims')
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    args = parser.parse_args(argv)
    loaded = {}
    for flag in ("sessions", "candidates"):
        source = getattr(args, flag)
        try:
            loaded[flag] = load_list(source) if source else None
        except (OSError, ValueError) as exc:
            print(f"inflight.py: cannot read --{flag} {source}: {exc}", file=sys.stderr)
            return 2
    sessions = None
    if loaded["sessions"] is not None:
        try:
            sessions = read_session_list(loaded["sessions"])
        except SessionListError as exc:
            print(f"inflight.py: cannot read --sessions {args.sessions}, so nothing was checked:\n{exc}",
                  file=sys.stderr)
            return 1
    report = collect(args.paths, loaded["candidates"], sessions)
    print(as_json(report) if args.json else render(report))
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
