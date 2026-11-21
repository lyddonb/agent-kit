#!/usr/bin/env python3
"""Change records: one JSON file per shipped change, in `.changes/` at the repo root.

    debrief.py new SLUG [--date YYYY-MM-DD] [--root DIR]   write an empty record and print its path
    debrief.py check [FILE ...] [--root DIR]               validate records (default: every record)
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
    record     an https URL, or a path git tracks or has staged (an ignored or untracked file is
               gone on the next clone)
    next       every item has `source` (where it comes from, or the word `inferred`), `why_now`
               and `impact`; an empty list is allowed
    release    exactly one of {"note": ...}, {"see": ...} (the repo keeps its notes elsewhere:
               name the entry) or {"none": ...} (the reason there is nothing to tell a user)

Exit code: 0, or 1 when `check` finds a problem or a record can't be read, 2 on bad usage.
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import re
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


def _record_pointer_problem(root: Path, pointer: str) -> Optional[str]:
    if pointer.startswith("https://"):
        return None
    if git(root, "ls-files", "--error-unmatch", "--", pointer).returncode != 0:
        return f"record {pointer!r} is neither an https URL nor a path git tracks (git add it, or link the run)"
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


def cmd_check(args: argparse.Namespace, root: Path) -> int:
    paths = [Path(f) for f in args.files] or record_paths(root)
    bad = 0
    for path in paths:
        _, errors = parse(root, path)
        if errors:
            bad += 1
            _fail(path, errors)
    print(f"{len(paths)} record(s) checked, {bad} with problems")
    return 1 if bad else 0


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
