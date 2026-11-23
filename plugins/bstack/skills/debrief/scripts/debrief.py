#!/usr/bin/env python3
"""Change records: one JSON file per shipped change, in `.changes/` at the repo root.

    debrief.py new SLUG [--date YYYY-MM-DD] [--root DIR]   write an empty record and print its path
    debrief.py check [FILE ...] [--root DIR]               validate records (default: every record)
    debrief.py check --base REF [--observe] [--root DIR]   the pull request check: see below
    debrief.py show [FILE] [--root DIR]                    the brief for one record (default: the newest)
    debrief.py notes [--since YYYY-MM-DD] [--root DIR]     release notes from every record, newest first

A record is `.changes/<yyyy-mm-dd>-<slug>.json`:

    {"version": 1,
     "goal": "what the work was for, in a sentence or two",
     "changed": ["what is different now"],
     "claims": [{"claim": "...", "verdict": "VERIFIED", "check": "the command or steps, and the
                 conditions it ran under", "commit": "<hash the check ran on>",
                 "record": "<https URL, or a path git tracks>", "remaining": "what it leaves unchecked"}],
     "next": [{"item": "...", "source": "ROADMAP.md R32", "why_now": "...", "impact": "..."}],
     "release": {"note": "what a user can now do"}}

Rules `check` holds:

    verdict    VERIFIED, NOT VERIFIED, INCONCLUSIVE or UNCHECKED
    VERIFIED   needs `check`, `commit` (a commit in this repo) and `record`
    the rest   need `remaining`: what still has to be checked
    record     an https URL, or the path of one file git tracks or has staged, as `git ls-files`
               prints it (an ignored or untracked file is gone on the next clone; a pattern or a
               folder names no one file)
    the file   a record is a plain file inside the repo: not a symlink, and mode 100644 if git
               holds it
    next       every item has `source` (where it comes from, or the word `inferred`), `why_now`
               and `impact`; an empty list is allowed
    release    exactly one of {"note": ...}, {"see": ...} (the repo keeps its notes elsewhere:
               name the entry) or {"none": ...} (the reason there is nothing to tell a user)

`check --base REF` is what CI runs on a pull request (`--base origin/main`; the checkout needs
the base branch and full history, `fetch-depth: 0`). It compares HEAD with where it left REF and

    fails   when a file outside the bookkeeping files changed and no record was added
    checks  every record the pull request added or edited

A pull request that touches only bookkeeping files (see BOOKKEEPING) needs no record. With
`--observe` it prints what it would have failed and exits 0, for a repo trying the check out.

A repo can name more paths that need no record in `.changes/exempt`: one path per line,
relative to the repo root, matched literally (a directory covers everything under it), with
`#` starting a comment. Use it for data a scheduled job writes and a person reviews in the
pull request, such as weekly briefs, not for code. The check reads the list from REF, not
from the pull request, so a list a pull request adds or widens applies only after it merges.
A pull request that edits the list fails when its new list has a bad line; a bad list on REF
is ignored with a warning, so every path then needs a record.

Exit code: 0, or 1 when `check` finds a problem or a record can't be read, 2 on bad usage or a
REF git doesn't know.
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import posixpath
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DIR = ".changes"
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.json$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
VERIFIED = "VERIFIED"
VERDICTS = (VERIFIED, "NOT VERIFIED", "INCONCLUSIVE", "UNCHECKED")
RELEASE_KINDS = ("note", "see", "none")
INFERRED = "inferred"
# Records, not source: a pull request that changes only these needs no change record.
# verify-work's receipt.py and scaffold-product's check-product.py have the same list.
BOOKKEEPING = (".audit", ".changes", ".evidence", "docs/phases", "docs/plans", "docs/DECISIONS.md", "ROADMAP.md",
               "HUMAN_TASKS.md", "IDEAS.md")
EXEMPT = f"{DIR}/exempt"

TEMPLATE = {
    "version": 1,
    "goal": "",
    "changed": [""],
    "claims": [{"claim": "", "verdict": "UNCHECKED", "check": "", "commit": "", "record": "", "remaining": ""}],
    "next": [{"item": "", "source": "", "why_now": "", "impact": ""}],
    "release": {"note": ""},
}


@dataclasses.dataclass(frozen=True)
class Claim:
    claim: str
    verdict: str
    check: str
    commit: str
    record: str
    remaining: str


@dataclasses.dataclass(frozen=True)
class NextItem:
    item: str
    source: str
    why_now: str
    impact: str


@dataclasses.dataclass(frozen=True)
class Record:
    path: Path
    date: str
    slug: str
    goal: str
    changed: Tuple[str, ...]
    claims: Tuple[Claim, ...]
    next: Tuple[NextItem, ...]
    release_kind: str
    release_text: str


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _text(obj: Dict, key: str) -> str:
    value = obj.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _tracked(root: Path, path: str) -> List[Tuple[str, str]]:
    """(mode, path) for each index entry `path` matches, read as a literal path, never a pattern."""
    done = git(root, "--literal-pathspecs", "ls-files", "--stage", "-z", "--", path)
    if done.returncode != 0:
        return []
    entries = []
    for line in done.stdout.split("\0"):
        if line:
            meta, name = line.split("\t", 1)
            entries.append((meta.split(" ", 1)[0], name))
    return entries


def _record_pointer_problem(root: Path, pointer: str) -> Optional[str]:
    if pointer.startswith("https://"):
        return None
    entries = _tracked(root, pointer)
    if len(entries) != 1 or entries[0][1] != pointer or entries[0][0] not in ("100644", "100755"):
        return (f"record {pointer!r} is neither an https URL nor a path git tracks: name one file, as git "
                f"ls-files prints it (git add it, or link the run)")
    return None


def _unsafe_record_file(root: Path, path: Path) -> Optional[str]:
    """Why `path` can't be read as a record: it must be a plain file inside `root`, not a link."""
    if path.is_symlink():
        return "is a symlink; a record must be a plain file in the repository"
    real = path.resolve()
    try:
        rel = real.relative_to(root)
    except ValueError:
        return "is outside the repository"
    if not stat.S_ISREG(real.stat().st_mode):
        return "is not a regular file"
    modes = [mode for mode, name in _tracked(root, rel.as_posix()) if name == rel.as_posix()]
    if modes and modes[0] != "100644":
        return f"git holds it as mode {modes[0]}; a record must be a plain file (100644)"
    return None


def _claim(root: Path, i: int, raw: object, errors: List[str]) -> Optional[Claim]:
    where = f"claims[{i}]"
    if not isinstance(raw, dict):
        errors.append(f"{where} must be an object")
        return None
    c = Claim(*(_text(raw, f.name) for f in dataclasses.fields(Claim)))
    if not c.claim:
        errors.append(f"{where} has no claim")
    if c.verdict not in VERDICTS:
        errors.append(f"{where} verdict must be one of {', '.join(VERDICTS)}, got {raw.get('verdict')!r}")
    elif c.verdict == VERIFIED:
        for key in ("check", "commit", "record"):
            if not getattr(c, key):
                errors.append(f"{where} is VERIFIED without {key!r}: say UNCHECKED, or name what proves it")
    elif not c.remaining:
        errors.append(f"{where} is {c.verdict} without 'remaining': say what still has to be checked")
    if c.commit:
        if not COMMIT.match(c.commit):
            errors.append(f"{where} commit {c.commit!r} is not a commit hash")
        elif git(root, "cat-file", "-e", c.commit + "^{commit}").returncode != 0:
            errors.append(f"{where} commit {c.commit} is not in this repository")
    if c.record:
        problem = _record_pointer_problem(root, c.record)
        if problem:
            errors.append(f"{where} {problem}")
    return c


def _next(i: int, raw: object, errors: List[str]) -> Optional[NextItem]:
    where = f"next[{i}]"
    if not isinstance(raw, dict):
        errors.append(f"{where} must be an object")
        return None
    n = NextItem(*(_text(raw, f.name) for f in dataclasses.fields(NextItem)))
    for f in dataclasses.fields(NextItem):
        if not getattr(n, f.name):
            hint = f" (where it comes from, or {INFERRED!r})" if f.name == "source" else ""
            errors.append(f"{where} has no {f.name!r}{hint}")
    return n


def parse(root: Path, path: Path) -> Tuple[Optional[Record], List[str]]:
    """The record at `path` and what is wrong with it. A record with problems is still returned
    when it could be read, so `show` can refuse it with the reasons."""
    errors: List[str] = []
    name = NAME.match(path.name)
    if not name:
        return None, [f"file name must be <yyyy-mm-dd>-<slug>.json, got {path.name!r}"]
    try:
        datetime.date.fromisoformat(name.group(1))
    except ValueError:
        errors.append(f"{name.group(1)} is not a date")
    try:
        unsafe = _unsafe_record_file(root, path)
        if unsafe:
            return None, [unsafe]
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, [f"cannot read it: {e}"]
    if not isinstance(raw, dict):
        return None, ["must be a JSON object"]
    if raw.get("version") != 1:
        errors.append(f"version must be 1, got {raw.get('version')!r}")
    unknown = sorted(set(raw) - set(TEMPLATE))
    if unknown:
        errors.append(f"unknown keys: {', '.join(unknown)}")
    goal = _text(raw, "goal")
    if not goal:
        errors.append("has no goal")
    changed = raw.get("changed")
    if not isinstance(changed, list) or not changed or not all(isinstance(c, str) and c.strip() for c in changed):
        errors.append("'changed' must be a list of one or more lines")
        changed = []
    claims_raw = raw.get("claims")
    if not isinstance(claims_raw, list) or not claims_raw:
        errors.append("'claims' must list at least one claim; a change nobody checked has one UNCHECKED claim")
        claims_raw = []
    claims = [_claim(root, i, c, errors) for i, c in enumerate(claims_raw)]
    next_raw = raw.get("next")
    if not isinstance(next_raw, list):
        errors.append("'next' must be a list (empty when nothing follows)")
        next_raw = []
    nexts = [_next(i, n, errors) for i, n in enumerate(next_raw)]
    release = raw.get("release")
    kind, text = "", ""
    if not isinstance(release, dict) or len(release) != 1 or next(iter(release)) not in RELEASE_KINDS:
        errors.append("'release' must be exactly one of {\"note\": ...}, {\"see\": ...} or {\"none\": ...}")
    else:
        kind = next(iter(release))
        text = _text(release, kind)
        if not text:
            errors.append(f"release.{kind} is empty")
    return Record(path, name.group(1), name.group(2), goal, tuple(c.strip() for c in changed),
                  tuple(c for c in claims if c), tuple(n for n in nexts if n), kind, text), errors


def record_paths(root: Path) -> List[Path]:
    """Every record, newest first (by the date in its name, then by name)."""
    return sorted((p for p in (root / DIR).glob("*.json")), key=lambda p: p.name, reverse=True)


def render_brief(r: Record) -> str:
    out = [f"# {r.slug} ({r.date})", "", f"**Goal.** {r.goal}", "", "## What changed", ""]
    out += [f"- {line}" for line in r.changed]
    out += ["", "## What is proven", ""]
    for c in r.claims:
        out.append(f"- **{c.verdict}**: {c.claim}")
        if c.check:
            out.append(f"  - Check: {c.check}" + (f" (on {c.commit[:12]})" if c.commit else ""))
        if c.record:
            out.append(f"  - Record: {c.record}")
        if c.remaining:
            out.append(f"  - Still unchecked: {c.remaining}")
    out += ["", "## Next", ""]
    if not r.next:
        out.append("Nothing follows from this change.")
    for n in r.next:
        out.append(f"- **{n.item}**")
        out.append(f"  - From: {n.source}")
        out.append(f"  - Why now: {n.why_now}")
        out.append(f"  - Impact: {n.impact}")
    out += ["", "## Release note", ""]
    out.append({"note": r.release_text, "see": f"See {r.release_text}.",
                "none": f"None: {r.release_text}."}[r.release_kind])
    return "\n".join(out) + "\n"


def render_notes(records: List[Record]) -> str:
    out = ["# Release notes", ""]
    by_date: Dict[str, List[Record]] = {}
    for r in records:
        if r.release_kind == "note":
            by_date.setdefault(r.date, []).append(r)
    if not by_date:
        out.append("No change in this range has a release note.")
    for date in sorted(by_date, reverse=True):
        out += [f"## {date}", ""]
        out += [f"- {r.release_text}" for r in by_date[date]]
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _fail(path: Path, errors: List[str]) -> None:
    for e in errors:
        print(f"{path}: {e}", file=sys.stderr)


def cmd_new(args: argparse.Namespace, root: Path) -> int:
    if not SLUG.match(args.slug):
        print(f"slug must be lowercase words joined by hyphens, got {args.slug!r}", file=sys.stderr)
        return 2
    date = args.date or datetime.date.today().isoformat()
    path = root / DIR / f"{date}-{args.slug}.json"
    if not NAME.match(path.name):
        print(f"--date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 2
    if path.exists():
        print(f"{path} already exists", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(TEMPLATE, indent=2) + "\n")
    print(path)
    return 0


def _changed(root: Path, base: str, diff_filter: str, *pathspec: str) -> Optional[List[str]]:
    """Paths HEAD changed since it left `base`, or None when git can't compare them."""
    done = git(root, "diff", "--name-only", "--no-renames", f"--diff-filter={diff_filter}", f"{base}...HEAD", "--", *pathspec)
    return done.stdout.splitlines() if done.returncode == 0 else None


def parse_exempt(text: str) -> Tuple[Tuple[str, ...], List[str]]:
    """The paths a `.changes/exempt` file names, and a problem for each line that can't be one."""
    paths: List[str] = []
    errors: List[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        path = posixpath.normpath(entry)
        if entry.startswith("/") or path == "." or path == ".." or path.startswith("../"):
            errors.append(f"{EXEMPT} line {n}: {entry!r} must name a path inside the repo, not the repo itself or a path outside it")
        else:
            paths.append(path)
    return tuple(paths), errors


def base_exempt(root: Path, base: str) -> Tuple[str, ...]:
    """The exempt paths on `base`. A missing list is empty; a bad one is ignored, loudly."""
    shown = git(root, "show", f"{base}:{EXEMPT}")
    if shown.returncode != 0:
        return ()
    paths, errors = parse_exempt(shown.stdout)
    if errors:
        for e in errors:
            print(f"{base}: {e}", file=sys.stderr)
        print(f"{base}: ignoring {EXEMPT}, so every path outside the bookkeeping files needs a record",
              file=sys.stderr)
        return ()
    if paths:
        print(f"exempt on {base} ({EXEMPT}): {', '.join(paths)}")
    return paths


def head_exempt_problems(root: Path, base: str) -> List[str]:
    """Problems in the exempt list this pull request leaves, when it edited the list."""
    edited = _changed(root, base, "AM", EXEMPT)
    if not edited:
        return []
    shown = git(root, "show", f"HEAD:{EXEMPT}")
    return parse_exempt(shown.stdout)[1] if shown.returncode == 0 else []


def base_paths(root: Path, base: str) -> Tuple[Optional[List[Path]], int]:
    """The records a pull request added or edited, and the exit code so far (1: it owes a record or
    leaves a bad exempt list)."""
    exempt = base_exempt(root, base)
    source = _changed(root, base, "ACDMRT", ".", *(f":(exclude){p}" for p in BOOKKEEPING),
                      *(f":(exclude,literal){p}" for p in exempt))
    added = _changed(root, base, "A", DIR)
    touched = _changed(root, base, "AM", DIR)
    if source is None or added is None or touched is None:
        print(f"cannot compare HEAD with {base!r}: fetch the base branch with full history (fetch-depth: 0)",
              file=sys.stderr)
        return None, 2
    is_record = lambda p: Path(p).parent.name == DIR and NAME.match(Path(p).name)
    rc = 0
    if source and not any(is_record(p) for p in added):
        more = f" and {len(source) - 3} more" if len(source) > 3 else ""
        print(f"this pull request changes {', '.join(source[:3])}{more} and adds no change record: "
              f"write one with the debrief skill (`debrief.py new <slug>`) and commit it", file=sys.stderr)
        rc = 1
    for e in head_exempt_problems(root, base):
        print(f"this pull request leaves a bad {EXEMPT}: {e}", file=sys.stderr)
        rc = 1
    return [root / p for p in touched if is_record(p)], rc


def cmd_check(args: argparse.Namespace, root: Path) -> int:
    owed = 0
    if args.base:
        if args.files:
            print("pass --base or files, not both", file=sys.stderr)
            return 2
        paths, owed = base_paths(root, args.base)
        if paths is None:
            return owed
    elif args.observe:
        print("--observe needs --base", file=sys.stderr)
        return 2
    else:
        paths = [Path(f) for f in args.files] or record_paths(root)
    bad = 0
    for path in paths:
        _, errors = parse(root, path)
        if errors:
            bad += 1
            _fail(path, errors)
    print(f"{len(paths)} record(s) checked, {bad} with problems")
    if args.observe and (bad or owed):
        print("observe: this pull request would have failed the change record check")
        return 0
    return 1 if bad or owed else 0


def cmd_show(args: argparse.Namespace, root: Path) -> int:
    paths = [Path(args.file)] if args.file else record_paths(root)[:1]
    if not paths:
        print(f"no records in {root / DIR}", file=sys.stderr)
        return 1
    record, errors = parse(root, paths[0])
    if errors or record is None:
        _fail(paths[0], errors)
        return 1
    print(render_brief(record), end="")
    return 0


def cmd_notes(args: argparse.Namespace, root: Path) -> int:
    records, bad = [], 0
    for path in record_paths(root):
        record, errors = parse(root, path)
        if errors or record is None:
            bad += 1
            _fail(path, errors)
        elif not args.since or record.date >= args.since:
            records.append(record)
    if bad:
        return 1
    print(render_notes(records), end="")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Change records: write, check and render them.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="write an empty record")
    new.add_argument("slug")
    new.add_argument("--date")
    new.add_argument("--root", default=".")
    check = sub.add_parser("check", help="validate records")
    check.add_argument("files", nargs="*")
    check.add_argument("--base")
    check.add_argument("--observe", action="store_true")
    check.add_argument("--root", default=".")
    show = sub.add_parser("show", help="print the brief for one record")
    show.add_argument("file", nargs="?")
    show.add_argument("--root", default=".")
    notes = sub.add_parser("notes", help="print release notes from every record")
    notes.add_argument("--since")
    notes.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    return {"new": cmd_new, "check": cmd_check, "show": cmd_show, "notes": cmd_notes}[args.cmd](args, root)


if __name__ == "__main__":
    sys.exit(main())
