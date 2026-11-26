#!/usr/bin/env python3
"""waiting.py - list everything across your repos that waits on you. Read-only: it sends nothing.

  python3 waiting.py PATH [PATH ...] [--github OWNER/NAME ...] [--json]

Each PATH is a git repo, or a folder whose direct subfolders are git repos (hidden ones are
skipped). For every repo it reads:

  tasks      open items in HUMAN_TASKS.md, blockers first with what each blocks
  gates      `gate` ledger entries with no later `gate-answer`, in unsealed runs under
             .audit/runs/ in the repo and each of its git worktrees
  pulls      open pull requests that are not drafts (`gh pr list`), with their check state
  questions  bullets under `## Open` in questions.md that carry no `Answer:` line

--github adds a repo by its GitHub name for its pull requests only. Every item carries a link
to its source: a GitHub URL when the local file matches the remote default branch, else
PATH:LINE. Anything it cannot read is listed under "Could not read" and the exit code is 1.

Test hook: WAITING_GH names the gh binary (default: gh on PATH).
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SECTIONS = ("blocker", "gate", "pull", "task", "question")
HEADINGS = {
    "blocker": "Blockers",
    "gate": "Open ledger gates",
    "pull": "Pull requests waiting on review or merge",
    "task": "Human tasks",
    "question": "Open questions",
}
GITHUB_REMOTE = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
OPEN_BULLET = re.compile(r"^\s*[-*]\s+\*\*([A-Z]+\d+)\b[.:]?\s*(.*?)\*\*")
FAILING = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PENDING = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}


@dataclass
class Item:
    kind: str
    repo: str
    id: str
    title: str
    link: str
    state: str = ""
    blocks: str = ""


@dataclass
class Problem:
    repo: str
    source: str
    message: str


@dataclass
class Repo:
    name: str
    path: Path | None
    slug: str | None


@dataclass
class Report:
    repos: list[Repo] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def git(path: Path, *args: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def github_slug(path: Path) -> str | None:
    url = git(path, "remote", "get-url", "origin")
    match = GITHUB_REMOTE.search(url or "")
    return f"{match.group(1)}/{match.group(2)}" if match else None


def find_repos(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        root = Path(raw).expanduser().resolve()
        candidates = [root]
        if root.is_dir():
            candidates += sorted(c for c in root.iterdir() if c.is_dir() and not c.name.startswith("."))
        for c in candidates:
            if (c / ".git").exists() and c not in found:
                found.append(c)
    return found


def file_link(repo: Repo, path: Path, line: int) -> str:
    base = github_blob(repo.path, repo.slug, path) if repo.slug and repo.path else None
    return f"{base}#L{line}" if base else f"{path}:{line}"


@functools.lru_cache(maxsize=None)
def github_blob(root: Path, slug: str, path: Path) -> str | None:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None
    default = git(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD") or "origin/main"
    remote_blob = git(root, "rev-parse", "-q", "--verify", f"{default}:{rel}")
    if not remote_blob or remote_blob != git(root, "hash-object", str(path)):
        return None
    return f"https://github.com/{slug}/blob/{default.split('/', 1)[1]}/{rel}"


def clean(text: str) -> str:
    text = re.sub(r"[*`]", "", text)
    return re.sub(r"^[^\w\[]+", "", text.strip()).strip()


def split_row(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def open_bullets(lines: list[str]) -> list[tuple[int, str, str, str]]:
    found = []
    in_open = False
    current: list | None = None
    for n, line in enumerate(lines, 1):
        if line.startswith("#"):
            in_open = line.startswith("## ") and line[3:].strip().lower() == "open"
            current = None
            continue
        if not in_open:
            continue
        match = OPEN_BULLET.match(line)
        if match:
            current = [n, match.group(1), clean(match.group(2)).rstrip("."), line]
            found.append(current)
        elif current is not None and line.strip():
            current[3] += "\n" + line
    return [tuple(c) for c in found]


def has_open_section(lines: list[str]) -> bool:
    return any(line.startswith("## ") and line[3:].strip().lower() == "open" for line in lines)


def parse_tasks(text: str) -> tuple[list[dict], bool]:
    lines = text.splitlines()
    tasks: list[dict] = []
    shaped = False
    header: list[str] | None = None
    for n, line in enumerate(lines, 1):
        if not line.strip().startswith("|"):
            header = None
            continue
        cells = split_row(line)
        if header is None:
            if cells and re.sub(r"[*`\s]", "", cells[0]).lower() in ("#", "id"):
                header = [c.lower() for c in cells]
                shaped = True
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        row = dict(zip(header, cells))
        task_id = clean(cells[0])
        status_key = next((h for h in header if "status" in h), None)
        done_key = next((h for h in header if h == "done"), None)
        unblocks_key = next((h for h in header if "unblock" in h), None)
        if done_key is not None:
            status = row.get(done_key, "")
            closed = bool(re.search(r"\[x\]", status, re.I))
        else:
            status = row.get(status_key or header[-1], "")
            closed = clean(status).lower().startswith(("done", "skipped"))
        if closed:
            continue
        flat = clean(re.sub(r"^\s*\[ \]\s*", "", status))
        blocker = "BLOCKER" in flat
        blocks = clean(row.get(unblocks_key, "")) if unblocks_key else ""
        if blocker and not blocks:
            match = re.search(r"BLOCKER\s*(?:for\s+)?(.*)", flat)
            blocks = match.group(1).strip() if match else ""
        title = clean(row.get("task", cells[1] if len(cells) > 1 else ""))
        tasks.append({"line": n, "id": task_id, "title": title, "state": flat, "blocker": blocker, "blocks": blocks})
    shaped = shaped or has_open_section(lines)
    for n, task_id, title, body in open_bullets(lines):
        flat = clean(body.replace("\n", " "))
        match = re.search(r"Unblocks\s+([^.;]+)", flat)
        tasks.append({
            "line": n, "id": task_id, "title": title, "state": "",
            "blocker": "BLOCKER" in flat, "blocks": match.group(1).strip() if match else "",
        })
    return tasks, shaped


def read_tasks(repo: Repo, report: Report) -> None:
    path = repo.path / "HUMAN_TASKS.md"
    if not path.is_file():
        return
    tasks, shaped = parse_tasks(path.read_text(encoding="utf-8"))
    if not shaped:
        report.problems.append(Problem(repo.name, str(path), "no task table (a `#` or `ID` column) and no `## Open` section"))
        return
    for t in tasks:
        report.items.append(Item(
            kind="blocker" if t["blocker"] else "task", repo=repo.name, id=t["id"], title=t["title"],
            link=file_link(repo, path, t["line"]), state=t["state"], blocks=t["blocks"],
        ))


def read_questions(repo: Repo, report: Report) -> None:
    path = repo.path / "questions.md"
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if not has_open_section(lines):
        report.problems.append(Problem(repo.name, str(path), "no `## Open` section"))
        return
    for n, qid, title, body in open_bullets(lines):
        if re.search(r"(?m)^\s*Answer:|\*\*Answered\b", body):
            continue
        title = re.sub(r"^\(?\d{4}-\d{2}-\d{2}\)\s*", "", title)
        report.items.append(Item("question", repo.name, qid, title, file_link(repo, path, n)))


def worktrees(path: Path) -> list[Path]:
    out = git(path, "worktree", "list", "--porcelain") or ""
    trees = [Path(line[len("worktree "):]) for line in out.splitlines() if line.startswith("worktree ")]
    return trees or [path]


def read_gates(repo: Repo, report: Report) -> None:
    runs: dict[str, list[tuple[Path, list[tuple[int, dict]]]]] = {}
    for tree in worktrees(repo.path):
        for ledger in sorted(tree.glob(".audit/runs/*/ledger.jsonl")):
            entries = []
            for n, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    report.problems.append(Problem(repo.name, f"{ledger}:{n}", "not a JSON ledger entry"))
                    continue
                if isinstance(entry, dict):
                    entries.append((n, entry))
            runs.setdefault(ledger.parent.name, []).append((ledger, entries))
    for run_id, copies in sorted(runs.items()):
        if any(e.get("type") == "seal" for _, entries in copies for _, e in entries):
            continue
        ledger, entries = max(copies, key=lambda c: len(c[1]))
        answered_after = max((e.get("seq", 0) for _, e in entries if e.get("type") == "gate-answer"), default=0)
        for n, e in entries:
            if e.get("type") == "gate" and e.get("seq", 0) > answered_after:
                gate = (e.get("data") or {}).get("gate", "")
                report.items.append(Item(
                    "gate", repo.name, f"{run_id}#{e.get('seq')}", e.get("summary", ""),
                    f"{ledger}:{n}", state=gate,
                ))


def check_state(rollup: list[dict]) -> str:
    states = {(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in rollup or []}
    if not states:
        return "no checks"
    if states & FAILING:
        return "checks failing"
    if states & PENDING or "" in states:
        return "checks pending"
    return "checks passing"


def read_pulls(repos: list[Repo], report: Report) -> None:
    targets = [r for r in repos if r.slug]
    if not targets:
        return
    gh = shutil.which(os.environ.get("WAITING_GH") or "gh")
    if not gh:
        report.problems.append(Problem("*", "gh", "cannot find the gh CLI, so no pull requests were read"))
        return
    fields = "number,title,url,isDraft,reviewDecision,statusCheckRollup"
    for repo in targets:
        proc = subprocess.run(
            [gh, "pr", "list", "--repo", repo.slug, "--state", "open", "--limit", "200", "--json", fields],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            message = (proc.stderr.strip().splitlines() or [f"gh exited {proc.returncode}"])[-1]
            report.problems.append(Problem(repo.name, f"gh pr list --repo {repo.slug}", message))
            continue
        try:
            pulls = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            report.problems.append(Problem(repo.name, f"gh pr list --repo {repo.slug}", "output is not JSON"))
            continue
        for p in sorted(pulls, key=lambda p: p.get("number", 0)):
            if p.get("isDraft"):
                continue
            state = check_state(p.get("statusCheckRollup"))
            if p.get("reviewDecision"):
                state += f", review {p['reviewDecision'].lower().replace('_', ' ')}"
            report.items.append(Item("pull", repo.name, f"#{p.get('number')}", p.get("title", ""), p.get("url", ""), state))


def collect(paths: list[str], slugs: list[str]) -> Report:
    github_blob.cache_clear()
    report = Report()
    for path in find_repos(paths):
        report.repos.append(Repo(path.name, path, github_slug(path)))
    known = {r.slug for r in report.repos}
    for slug in slugs:
        if slug not in known:
            report.repos.append(Repo(slug.split("/")[-1], None, slug))
            known.add(slug)
    for repo in report.repos:
        if repo.path is None:
            continue
        read_tasks(repo, report)
        read_gates(repo, report)
        read_questions(repo, report)
    read_pulls(report.repos, report)
    report.items.sort(key=lambda i: SECTIONS.index(i.kind))
    return report


def render(report: Report) -> str:
    out = ["# Waiting on you", ""]
    names = ", ".join(r.name for r in report.repos) or "none"
    out += [f"Read {len(report.repos)} repos: {names}.", ""]
    for kind in SECTIONS:
        items = [i for i in report.items if i.kind == kind]
        out.append(f"## {HEADINGS[kind]} ({len(items)})")
        out.append("")
        for i in items:
            extra = []
            if i.state and kind in ("task", "pull", "gate"):
                extra.append(i.state)
            if i.blocks:
                extra.append(f"blocks {i.blocks}" if kind == "blocker" else f"unblocks {i.blocks}")
            suffix = f" ({'; '.join(extra)})" if extra else ""
            out.append(f"- {i.repo} {i.id}: {i.title}{suffix} <{i.link}>")
        if not items:
            out.append("None.")
        out.append("")
    if report.problems:
        out += [f"## Could not read ({len(report.problems)})", ""]
        out += [f"- {p.repo}: {p.source}: {p.message}" for p in report.problems]
        out.append("")
    return "\n".join(out)


def as_json(report: Report) -> str:
    return json.dumps({
        "repos": [{"name": r.name, "path": str(r.path) if r.path else None, "github": r.slug} for r in report.repos],
        "items": [asdict(i) for i in report.items],
        "problems": [asdict(p) for p in report.problems],
    }, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List everything across your repos that waits on you.")
    parser.add_argument("paths", nargs="+", metavar="PATH", help="a git repo, or a folder of git repos")
    parser.add_argument("--github", action="append", default=[], metavar="OWNER/NAME",
                        help="also list this GitHub repo's pull requests (repeatable)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    args = parser.parse_args(argv)
    report = collect(args.paths, args.github)
    print(as_json(report) if args.json else render(report))
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
