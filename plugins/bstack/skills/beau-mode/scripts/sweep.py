#!/usr/bin/env python3
"""List the watched repos that hold an artifact the kit generated, so a breaking format change can sweep them.

Usage:
    python3 sweep.py BOOKS_DIR --artifact NAME [--artifact NAME ...] [--containing REGEX] [--at YYYY-MM-DD]
                     [--public-only] [--json]

BOOKS_DIR is the quality books folder. Its books/watched.csv (`repo,github,workflow`) names the repos to look in, and
books/repos.csv (`seen,repo,github,visibility`) says which are public. Each repo's file tree is read through the `gh`
CLI (`gh api` only, found at $SWEEP_GH or on PATH), at the default branch's head, or with --at at the newest commit on
that branch up to the end of that day. That is how to replay a past format change: pass the day before it.

--containing keeps only the files whose content matches the regular expression (searched per line, `^` and `$` match at
line breaks). Without it no file content is fetched.

Prints one line per repo that holds an artifact, then a count line:
    REPO (GITHUB): ARTIFACT: N file(s): path, path, ...
    sweep: H of W watched repos hold ARTIFACTS
--json prints the holders as a list instead, and the count line goes to standard error.

--public-only names no private repo and prints no path from one: it says only how many private repos hold an artifact.
A repo is public only when its latest row in repos.csv says `public` and no row ever said `private` or `internal`;
a repo with no row is private. It needs books/repos.csv.

Exit code 0 when it ran, 1 when a repo could not be read (`FAILED REPO: why` on standard error; the other repos are
still listed), 2 on bad usage, missing books files, or no gh.

Everything gh returns is untrusted: sizes and counts are capped, and control characters never reach the output.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from typing import Dict, List, NamedTuple, Optional, Set, Tuple
from urllib.parse import quote

# What a kit-generated artifact looks like inside a repo: a name, and the path globs that find it.
ARTIFACTS: Dict[str, Tuple[str, ...]] = {
    "phase-spec": ("docs/phases/*.md",),
    "verify-skill": (".claude/skills/verify-*/SKILL.md", ".agents/skills/verify-*/SKILL.md"),
    "review": ("REVIEW.md",),
}

WATCHED = "books/watched.csv"
REPOS = "books/repos.csv"
WATCHED_HEADER = ["repo", "github", "workflow"]
REPOS_HEADER = ["seen", "repo", "github", "visibility"]
# Books that link a run in an `evidence` column; quality.py counts the slugs in them (repo_slugs).
EVIDENCE_BOOKS = ("books/runs.csv", "books/failures.csv", "books/jobs.csv", "books/steps.csv")
LINK_SLUG = re.compile(r"https://[^/\s]+/([^/\s]+/[^/\s]+)/actions/runs/")
SLUG = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
SHA = re.compile(r"[0-9a-f]{40}")
CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\u200b-\u200d\ufeff]")

GH_TIMEOUT_SECONDS = 120
MAX_BOOK_BYTES = 64 * 1024 * 1024
MAX_BOOK_ROWS = 2_000_000
MAX_WATCHED = 500
MAX_GH_BYTES = 32 * 1024 * 1024
MAX_TREE_ENTRIES = 200_000
MAX_PATH_CHARS = 500
MAX_FILES_PER_HOLDER = 1000
MAX_CANDIDATES = 200  # files fetched per repo for --containing
MAX_FILE_CHARS = 1024 * 1024
MAX_SHOWN_PATHS = 20
MAX_WHY_CHARS = 300


class Watched(NamedTuple):
    repo: str
    github: str
    visibility: str  # "public" or "private", by the rule in is_public


class Holder(NamedTuple):
    watched: Watched
    artifact: str
    paths: Tuple[str, ...]


class Failure(NamedTuple):
    watched: Watched
    why: str


class Usage(Exception):
    """Bad arguments or missing books files: exit 2."""


class GhError(Exception):
    """A gh call or an answer from it that cannot be used."""


def printable(text: str, limit: int = MAX_WHY_CHARS) -> str:
    text = CONTROL.sub("?", text)
    return text if len(text) <= limit else text[:limit] + "..."


def glob_regex(glob: str):
    return re.compile("".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in glob))


ARTIFACT_PATTERNS = {name: [glob_regex(g) for g in globs] for name, globs in ARTIFACTS.items()}


# ---- the books ---------------------------------------------------------------------------------------------------

def read_rows(books_dir: str, rel: str, header: Optional[List[str]]) -> Optional[List[Dict[str, str]]]:
    """The rows of one book as dicts, or None when the file is not there. A header that is not the expected one, an
    unreadable file or one over the caps is a Usage error."""
    path = os.path.join(books_dir, rel)
    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) > MAX_BOOK_BYTES:
        raise Usage(f"{rel} is larger than {MAX_BOOK_BYTES // (1024 * 1024)} MB")
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            first = next(reader, None)
            if first is None or (header is not None and first != header):
                raise Usage(f"{rel} must start with the header {','.join(header or [])}")
            rows = []
            for n, cells in enumerate(reader):
                if n >= MAX_BOOK_ROWS:
                    raise Usage(f"{rel} has more than {MAX_BOOK_ROWS} rows")
                if len(cells) == len(first):
                    rows.append(dict(zip(first, cells)))
            return rows
    except (OSError, csv.Error) as e:
        raise Usage(f"cannot read {rel}: {type(e).__name__}") from None


def private_repos(books_dir: str, watched: List[Dict[str, str]], repo_rows: List[Dict[str, str]]) -> Set[str]:
    """quality.py's rule (private_repos), for the watched repos: public only when repos.csv has a row, the latest row
    says `public`, no row ever said `private` or `internal`, and the books tie the name to one OWNER/NAME only."""
    history: Dict[str, List[str]] = {}
    for row in sorted(repo_rows, key=lambda r: r.get("seen", "")):  # stable: a sorted file keeps its order
        history.setdefault(row["repo"], []).append(row["visibility"])
    slugs: Dict[str, Set[str]] = {}
    for row in watched + repo_rows:
        if row.get("github"):
            slugs.setdefault(row["repo"], set()).add(row["github"].lower())
    for rel in EVIDENCE_BOOKS:
        for row in read_rows(books_dir, rel, None) or []:
            found = LINK_SLUG.match(row.get("evidence", ""))
            if found and "repo" in row:
                slugs.setdefault(row["repo"], set()).add(found[1].lower())
    names = {r["repo"] for r in watched}
    return {n for n in names
            if not history.get(n) or history[n][-1] != "public"
            or any(v in ("private", "internal") for v in history[n]) or len(slugs.get(n, ())) > 1}


def load_watched(books_dir: str, need_visibility: bool) -> List[Watched]:
    rows = read_rows(books_dir, WATCHED, WATCHED_HEADER)
    if rows is None:
        raise Usage(f"{WATCHED} is not in {books_dir}")
    repo_rows = read_rows(books_dir, REPOS, REPOS_HEADER)
    if repo_rows is None:
        if need_visibility:
            raise Usage(f"--public-only needs {REPOS}: visibility is not booked, so no repo can be called public")
        repo_rows = []
    if len(rows) > MAX_WATCHED:
        raise Usage(f"{WATCHED} lists more than {MAX_WATCHED} repos")
    private = private_repos(books_dir, rows, repo_rows)
    seen: Set[str] = set()
    out = []
    for r in rows:
        if r["repo"] in seen:
            continue
        seen.add(r["repo"])
        out.append(Watched(r["repo"], r["github"], "private" if r["repo"] in private else "public"))
    return out


# ---- gh ---------------------------------------------------------------------------------------------------------

def find_gh() -> Optional[str]:
    """SWEEP_GH when set (tests point it at a fake), else `gh` on PATH."""
    return shutil.which(os.environ.get("SWEEP_GH") or "gh")


class Gh:
    def __init__(self, exe: str):
        self.exe = exe

    def api(self, endpoint: str):
        """The JSON `gh api ENDPOINT` prints. Never `gh auth status`: it fails where `gh api` works."""
        try:
            done = subprocess.run([self.exe, "api", endpoint], capture_output=True, timeout=GH_TIMEOUT_SECONDS,
                                  env={**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"})
        except (OSError, subprocess.SubprocessError) as e:
            raise GhError(f"gh could not run: {type(e).__name__}") from None
        if done.returncode != 0:
            raise GhError("gh api failed: " + (printable(done.stderr.decode("utf-8", "replace").strip()) or f"exit {done.returncode}"))
        if len(done.stdout) > MAX_GH_BYTES:
            raise GhError("gh api answered with more than 32 MB")
        try:
            return json.loads(done.stdout.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            raise GhError("gh api did not answer with JSON") from None


def head_sha(gh: Gh, slug: str, at: Optional[date]) -> Optional[str]:
    """The commit to read: the default branch's head, or the newest commit at or before the end of `at`.
    None when the branch had no commit by then."""
    info = gh.api(f"repos/{slug}")
    branch = info.get("default_branch") if isinstance(info, dict) else None
    if not isinstance(branch, str) or not branch or len(branch) > 255 or CONTROL.search(branch):
        raise GhError("gh did not name a default branch")
    if at is None:
        return branch
    until = f"{at.isoformat()}T23:59:59Z"
    commits = gh.api(f"repos/{slug}/commits?sha={quote(branch, safe='')}&until={until}&per_page=1")
    if not isinstance(commits, list):
        raise GhError("gh did not answer with a commit list")
    if not commits:
        return None
    sha = commits[0].get("sha") if isinstance(commits[0], dict) else None
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise GhError("gh did not name a commit")
    return sha


def list_files(gh: Gh, slug: str, ref: str) -> List[str]:
    tree = gh.api(f"repos/{slug}/git/trees/{quote(ref, safe='')}?recursive=1")
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        raise GhError("gh did not answer with a file tree")
    if tree.get("truncated") is True:
        raise GhError("the file tree is too big for GitHub to list whole (truncated)")
    if len(tree["tree"]) > MAX_TREE_ENTRIES:
        raise GhError(f"the file tree has more than {MAX_TREE_ENTRIES} entries")
    return [e["path"] for e in tree["tree"]
            if isinstance(e, dict) and e.get("type") == "blob" and isinstance(e.get("path"), str)
            and len(e["path"]) <= MAX_PATH_CHARS]


def file_matches(gh: Gh, slug: str, ref: str, path: str, pattern) -> bool:
    got = gh.api(f"repos/{slug}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}")
    if not isinstance(got, dict) or got.get("type") != "file" or got.get("encoding") != "base64" \
            or not isinstance(got.get("content"), str):
        raise GhError(f"{printable(path, 100)} could not be read (a file over 1 MB cannot be)")
    try:
        text = base64.b64decode(got["content"]).decode("utf-8", "replace")[:MAX_FILE_CHARS]
    except ValueError:
        raise GhError(f"{printable(path, 100)} is not valid base64") from None
    return pattern.search(text) is not None


# ---- the sweep ---------------------------------------------------------------------------------------------------

def sweep_repo(gh: Gh, w: Watched, artifacts: List[str], at: Optional[date], containing) -> List[Holder]:
    if not SLUG.fullmatch(w.github):
        raise GhError("the books name no valid OWNER/NAME for it")
    ref = head_sha(gh, w.github, at)
    if ref is None:
        return []
    files = list_files(gh, w.github, ref)
    found = []
    for name in artifacts:
        paths = sorted(p for p in files if any(rx.fullmatch(p) for rx in ARTIFACT_PATTERNS[name]))
        found.append((name, paths))
    if containing is not None:
        candidates = {p for _, paths in found for p in paths}
        if len(candidates) > MAX_CANDIDATES:
            raise GhError(f"{len(candidates)} files to read for --containing, over the {MAX_CANDIDATES} cap")
        hits = {p for p in sorted(candidates) if file_matches(gh, w.github, ref, p, containing)}
        found = [(name, [p for p in paths if p in hits]) for name, paths in found]
    return [Holder(w, name, tuple(paths[:MAX_FILES_PER_HOLDER])) for name, paths in found if paths]


def run_sweep(gh: Gh, watched: List[Watched], artifacts: List[str], at: Optional[date], containing):
    holders: List[Holder] = []
    failures: List[Failure] = []
    for w in watched:
        try:
            holders.extend(sweep_repo(gh, w, artifacts, at, containing))
        except GhError as e:
            failures.append(Failure(w, str(e)))
        except Exception as e:  # hostile input must end in a message, never a traceback
            failures.append(Failure(w, f"unexpected {type(e).__name__}"))
    return holders, failures


# ---- output ------------------------------------------------------------------------------------------------------

def holder_line(h: Holder) -> str:
    shown = [printable(p, MAX_PATH_CHARS) for p in h.paths[:MAX_SHOWN_PATHS]]
    more = f", ... and {len(h.paths) - MAX_SHOWN_PATHS} more" if len(h.paths) > MAX_SHOWN_PATHS else ""
    return (f"{printable(h.watched.repo, 100)} ({printable(h.watched.github, 100)}): {h.artifact}: "
            f"{len(h.paths)} file(s): {', '.join(shown)}{more}")


def failure_line(f: Failure, public_only: bool) -> str:
    if public_only and f.watched.visibility != "public":
        return "FAILED a private repo: it could not be read"
    return f"FAILED {printable(f.watched.repo, 100)}: {printable(f.why)}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sweep.py", description="List the watched repos that hold an artifact the kit generated.")
    p.add_argument("books_dir", metavar="BOOKS_DIR", help="the quality books folder (books/watched.csv, books/repos.csv)")
    p.add_argument("--artifact", action="append", required=True, choices=sorted(ARTIFACTS), metavar="NAME",
                   help="an artifact kind to look for; repeat for several: " + ", ".join(sorted(ARTIFACTS)))
    p.add_argument("--containing", metavar="REGEX", help="keep only files whose content matches (fetches each candidate file)")
    p.add_argument("--at", metavar="YYYY-MM-DD", help="read each repo as it was at the end of this day")
    p.add_argument("--public-only", action="store_true", help="name no private repo and print none of its paths; needs books/repos.csv")
    p.add_argument("--json", action="store_true", help="print the holders as a JSON list; the count line goes to standard error")
    return p


def parse_args(argv: List[str]):
    args = build_parser().parse_args(argv)
    at = None
    if args.at is not None:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.at):
                raise ValueError
            at = date.fromisoformat(args.at)
        except ValueError:
            raise Usage(f"--at must be a real day like 2026-11-16, got {printable(args.at, 40)!r}") from None
    pattern = None
    if args.containing is not None:
        try:
            pattern = re.compile(args.containing, re.MULTILINE)
        except re.error as e:
            raise Usage(f"--containing is not a regular expression: {e}") from None
    args.artifact = list(dict.fromkeys(args.artifact))
    return args, at, pattern


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args, at, pattern = parse_args(sys.argv[1:] if argv is None else argv)
        if not os.path.isdir(args.books_dir):
            raise Usage(f"not a directory: {args.books_dir}")
        watched = load_watched(args.books_dir, args.public_only)
        exe = find_gh()
        if exe is None:
            raise Usage("cannot find the gh CLI (put it on PATH, or set SWEEP_GH to its path)")
    except Usage as e:
        print(f"sweep.py: {e}", file=sys.stderr)
        return 2
    holders, failures = run_sweep(Gh(exe), watched, args.artifact, at, pattern)
    private_holders = {h.watched.repo for h in holders if h.watched.visibility != "public"} if args.public_only else set()
    if args.public_only:
        holders = [h for h in holders if h.watched.visibility == "public"]
        watched = [w for w in watched if w.visibility == "public"]
    for f in failures:
        print(failure_line(f, args.public_only), file=sys.stderr)
    held = len({h.watched.repo for h in holders})
    names = ", ".join(args.artifact)
    counted = "public watched" if args.public_only else "watched"
    summary = f"sweep: {held} of {len(watched)} {counted} repos hold {names}"
    note = (f"{len(private_holders)} private repo(s) hold one; run without --public-only to see them"
            if private_holders else None)
    out = sys.stderr if args.json else sys.stdout
    if args.json:
        print(json.dumps([{"repo": printable(h.watched.repo), "github": printable(h.watched.github), "artifact": h.artifact,
                           "count": len(h.paths), "files": [printable(p, MAX_PATH_CHARS) for p in h.paths]} for h in holders],
                         indent=2))
    else:
        for h in holders:
            print(holder_line(h))
    print(summary, file=out)
    if note:
        print(note, file=out)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
