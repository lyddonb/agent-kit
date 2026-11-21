#!/usr/bin/env python3
"""Print the reliability checklist items whose trigger matches a diff.

Usage:
    checklist.py --base REF [--head REF] [--file PATH] [--root DIR] [--json]

Run it from the repo root (or pass --root). It reads `.agents/checklist.json` (or --file) and
prints one block per item whose trigger matches what changed since the merge base of REF and
the head. Without --head the head is the working tree: commits since the merge base, uncommitted
edits, and untracked files git does not ignore. With --head it is that commit and nothing else.

A trigger matches when a changed file fits one of its `paths` globs and, when it has a `pattern`,
that regular expression is found in a line the diff adds or removes in such a file. Each block
says which file and line fired the item.

Standard output holds the matching items and nothing else, so empty output means the script ran
and nothing matched. A one-line count goes to standard error. `references/checklist.md` in this
skill has the file format.

Exit code: 0 when it ran, whatever matched: the items are checks for you to run, and the script
blocks nothing. 2 when it could not run (a bad ref, a checklist file that does not parse or
breaks the format, --file naming a file that is not there, a folder that is not the top of a
git work tree). A repo with no
`.agents/checklist.json` is not an error: it has no checklist, and the script says so on
standard error and exits 0.

Standard library only. Python 3.9 or later.
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
from typing import Iterator, Optional, Union

DEFAULT_FILE = ".agents/checklist.json"
FORMAT_VERSION = 1
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
ITEM_KEYS = {"id", "trigger", "check", "source", "added", "review_by"}
SHOWN = 160  # characters of a matched line a block prints


class Unusable(Exception):
    """The script cannot run: a bad ref, or a checklist file that breaks the format."""


@dataclasses.dataclass(frozen=True)
class Trigger:
    paths: tuple[str, ...]
    pattern: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class Command:
    command: str


@dataclasses.dataclass(frozen=True)
class Question:
    question: str
    probe: str


@dataclasses.dataclass(frozen=True)
class Item:
    id: str
    trigger: Trigger
    check: Union[Command, Question]
    source: str
    added: datetime.date
    review_by: datetime.date


@dataclasses.dataclass(frozen=True)
class Line:
    """One line a diff adds (`+`, numbered in the new file) or removes (`-`, numbered in the old)."""
    sign: str
    number: int
    text: str


@dataclasses.dataclass(frozen=True)
class Fired:
    """Why an item matched: the first file that fits, and the line when the trigger has a pattern."""
    item: Item
    path: str
    line: Optional[Line]
    more_paths: int


# --- the checklist file ---------------------------------------------------------------------

def glob_regex(glob: str) -> re.Pattern:
    """`**` crosses folders, `*` and `?` stay inside one, and `**/` also matches no folder at all."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out))


def _text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Unusable(f"{where}: `{key}` must be a non-empty string")
    return value


def _date(obj: dict, key: str, where: str) -> datetime.date:
    value = _text(obj, key, where)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise Unusable(f"{where}: `{key}` must be a date like 2026-11-21, got {value!r}")


def _keys(obj: object, allowed: set[str], where: str) -> dict:
    if not isinstance(obj, dict):
        raise Unusable(f"{where}: must be an object")
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise Unusable(f"{where}: unknown key {unknown[0]!r} (allowed: {', '.join(sorted(allowed))})")
    return obj


def _trigger(raw: object, where: str) -> Trigger:
    obj = _keys(raw, {"paths", "pattern"}, where)
    paths = obj.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p.strip() for p in paths):
        raise Unusable(f"{where}: `paths` must be a non-empty list of globs (use [\"**\"] for every file)")
    pattern = obj.get("pattern")
    if pattern is not None:
        _text(obj, "pattern", where)
        try:
            re.compile(pattern)
        except re.error as e:
            raise Unusable(f"{where}: `pattern` is not a regular expression: {e}")
    return Trigger(tuple(paths), pattern)


def _check(raw: object, where: str) -> Union[Command, Question]:
    obj = _keys(raw, {"command", "question", "probe"}, where)
    if set(obj) == {"command"}:
        return Command(_text(obj, "command", where))
    if set(obj) == {"question", "probe"}:
        return Question(_text(obj, "question", where), _text(obj, "probe", where))
    raise Unusable(f"{where}: must be either {{\"command\"}} or {{\"question\", \"probe\"}}")


def parse_checklist(text: str, name: str) -> list[Item]:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise Unusable(f"{name}:{e.lineno}:{e.colno}: not JSON: {e.msg}")
    doc = _keys(doc, {"version", "items"}, name)
    if doc.get("version") != FORMAT_VERSION:
        raise Unusable(f"{name}: `version` must be {FORMAT_VERSION}, got {doc.get('version')!r}")
    if not isinstance(doc.get("items"), list):
        raise Unusable(f"{name}: `items` must be a list")
    items: list[Item] = []
    for n, raw in enumerate(doc["items"], 1):
        where = f"{name}: item {n}"
        obj = _keys(raw, ITEM_KEYS, where)
        missing = sorted(ITEM_KEYS - set(obj))
        if missing:
            raise Unusable(f"{where}: missing `{missing[0]}`")
        item_id = _text(obj, "id", where)
        where = f"{name}: item {n} ({item_id})"
        if not ID.match(item_id):
            raise Unusable(f"{where}: `id` must be lowercase words joined by hyphens")
        if any(i.id == item_id for i in items):
            raise Unusable(f"{where}: `id` is used twice")
        item = Item(item_id, _trigger(obj["trigger"], f"{where}: trigger"), _check(obj["check"], f"{where}: check"),
                    _text(obj, "source", where), _date(obj, "added", where), _date(obj, "review_by", where))
        if item.review_by < item.added:
            raise Unusable(f"{where}: `review_by` is before `added`")
        items.append(item)
    return items


# --- the diff -------------------------------------------------------------------------------

def git(root: Path, *args: str) -> bytes:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if done.returncode != 0:
        raise Unusable(f"git {' '.join(args[:2])} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


@dataclasses.dataclass(frozen=True)
class Diff:
    """What changed between a merge base and a head. `head` None means the working tree."""
    root: Path
    base: str
    head: Optional[str]
    paths: tuple[str, ...]
    untracked: frozenset[str]

    def lines(self, path: str) -> Iterator[Line]:
        if path in self.untracked:
            try:
                data = (self.root / path).read_bytes()
            except OSError:
                return
            if b"\0" in data:
                return
            for n, raw in enumerate(data.splitlines(), 1):
                yield Line("+", n, raw.decode("utf-8", "replace"))
            return
        ends = [self.head] if self.head else []
        yield from parse_hunks(git(self.root, "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
                                   self.base, *ends, "--", path))


def parse_hunks(patch: bytes) -> Iterator[Line]:
    """Changed lines of a one-file `git diff -U0`. Lines are counted from each hunk header, so a
    removed line that itself starts with `--` is never read as a file header."""
    rows = iter(patch.split(b"\n"))
    for row in rows:
        m = HUNK.match(row)
        if not m:
            continue
        old, new = int(m.group(1)), int(m.group(3))
        left = {"-": int(m.group(2) or 1), "+": int(m.group(4) or 1)}
        while left["-"] or left["+"]:
            body = next(rows, None)
            if body is None:
                return
            sign = body[:1].decode("ascii", "replace")
            if sign not in left or not left[sign]:
                continue  # "\ No newline at end of file"
            left[sign] -= 1
            yield Line(sign, old if sign == "-" else new, body[1:].decode("utf-8", "replace").rstrip("\r"))
            if sign == "-":
                old += 1
            else:
                new += 1


def read_diff(root: Path, base: str, head: Optional[str]) -> Diff:
    for ref in filter(None, (base, head)):
        if ref.startswith("-"):
            raise Unusable(f"{ref!r} is not a ref")
    merge_base = git(root, "merge-base", base, head or "HEAD").decode().strip()
    ends = [head] if head else []
    names = git(root, "diff", "--name-only", "-z", "--no-renames", merge_base, *ends).decode("utf-8", "replace")
    paths = [p for p in names.split("\0") if p]
    untracked: list[str] = []
    if not head:
        others = git(root, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8", "replace")
        untracked = [p for p in others.split("\0") if p]
    return Diff(root, merge_base, head, tuple(sorted(set(paths) | set(untracked))), frozenset(untracked))


# --- matching -------------------------------------------------------------------------------

def fire(item: Item, diff: Diff) -> Optional[Fired]:
    globs = [glob_regex(g) for g in item.trigger.paths]
    paths = [p for p in diff.paths if any(g.fullmatch(p) for g in globs)]
    if not paths:
        return None
    if item.trigger.pattern is None:
        return Fired(item, paths[0], None, len(paths) - 1)
    pattern = re.compile(item.trigger.pattern)
    hits = [(p, line) for p in paths for line in [next((l for l in diff.lines(p) if pattern.search(l.text)), None)]
            if line]
    if not hits:
        return None
    return Fired(item, hits[0][0], hits[0][1], len(hits) - 1)


def matching(items: list[Item], diff: Diff) -> list[Fired]:
    return [f for f in (fire(item, diff) for item in items) if f]


# --- output ---------------------------------------------------------------------------------

def _shown(text: str) -> str:
    text = "".join(c if c.isprintable() else "?" for c in text.strip())
    return text if len(text) <= SHOWN else text[:SHOWN] + "..."


def where_fired(f: Fired) -> str:
    more = f" (and {f.more_paths} more file{'s' if f.more_paths != 1 else ''})" if f.more_paths else ""
    if f.line is None:
        return f"{f.path}{more}"
    return f"{f.path}:{f.line.number}: {f.line.sign}{_shown(f.line.text)}{more}"


def as_text(f: Fired, today: datetime.date) -> str:
    item = f.item
    rows = [f"{item.id}", f"  fired on: {where_fired(f)}"]
    if isinstance(item.check, Command):
        rows.append(f"  command: {item.check.command}")
    else:
        rows += [f"  question: {item.check.question}", f"  probe: {item.check.probe}"]
    overdue = " (overdue: confirm it still earns its place, or delete it)" if item.review_by < today else ""
    rows += [f"  source: {item.source}", f"  added {item.added}, review by {item.review_by}{overdue}"]
    return "\n".join(rows)


def as_dict(f: Fired, today: datetime.date) -> dict:
    item = f.item
    fired = {"path": f.path, "more_paths": f.more_paths}
    if f.line is not None:
        fired.update(line=f.line.number, sign=f.line.sign, text=_shown(f.line.text))
    return {"id": item.id, "fired": fired, "check": dataclasses.asdict(item.check), "source": item.source,
            "added": str(item.added), "review_by": str(item.review_by), "overdue": item.review_by < today}


def main(argv: list[str], today: Optional[datetime.date] = None) -> int:
    p = argparse.ArgumentParser(prog="checklist.py", description="Print the checklist items whose trigger matches a diff.")
    p.add_argument("--base", required=True, help="ref to diff against; the diff starts at its merge base with the head")
    p.add_argument("--head", help="commit to read instead of the working tree")
    p.add_argument("--file", help=f"checklist file (default: {DEFAULT_FILE} under the root)")
    p.add_argument("--root", help="repo root (default: the current folder)")
    p.add_argument("--json", action="store_true", help="print a JSON list instead of text")
    args = p.parse_args(argv)
    today = today or datetime.date.today()
    root = Path(args.root or ".").resolve()
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode != 0:
            raise Unusable(f"{root} is not inside a git repo")
        if Path(top.stdout.strip()).resolve() != root:
            raise Unusable(f"run it from the repo root ({top.stdout.strip()}), or pass --root")
        file = Path(args.file).resolve() if args.file else root / DEFAULT_FILE
        if not file.is_file():
            if args.file:
                raise Unusable(f"no checklist file at {args.file}")
            print(f"checklist: no {DEFAULT_FILE} in {root}; this repo has no checklist", file=sys.stderr)
            if args.json:
                print("[]")
            return 0
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Unusable(f"cannot read {file}: {e}")
        items = parse_checklist(text, args.file or DEFAULT_FILE)
        diff = read_diff(root, args.base, args.head)
        fired = matching(items, diff)
    except Unusable as e:
        print(f"checklist.py: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([as_dict(f, today) for f in fired], indent=2))
    elif fired:
        print("\n\n".join(as_text(f, today) for f in fired))
    print(f"checklist: {len(fired)} of {len(items)} items match {diff.base[:7]}..{args.head or 'working tree'} "
          f"({len(diff.paths)} changed file{'s' if len(diff.paths) != 1 else ''})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
