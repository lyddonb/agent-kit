#!/usr/bin/env python3
"""List the comments a diff adds to Python files, and fail when there are any.

Usage:
    comments.py --base REF [--head REF] [--root DIR] [--json]

Run it from the repo root (or pass --root). It compares the merge base of REF and the head with
the head. Without --head the head is the working tree: commits since the merge base, uncommitted
edits, and untracked files git does not ignore. With --head it is that commit and nothing else.

A comment is new when the changed files hold more copies of its text at the head than they did
at the merge base. Moving a comment, or the code around it, adds nothing. Editing its words does.

Four kinds of comment are never listed, because a script can decide them:

    shebang     `#!` on line 1
    directive   an encoding line, or a comment a tool reads: noqa, type:, pragma:, pylint:,
                fmt:, isort:, mypy:, pyright:, ruff:, nosec
    license     a comment in the file's opening comment block, when that block says copyright,
                license or SPDX
    link        a comment that carries an http(s) URL, such as an issue or RFC link, and the
                other lines of an unbroken block of whole-line comments that holds one

Every other keep in the no-comments skill needs a reader's judgment. A comment that earns one
names its reason with a link.

Standard output holds one line per new comment and nothing else, so empty output means the
script ran and found none. A one-line count goes to standard error.

Exit code: 0 when the diff adds no comment, 1 when it adds at least one, 2 when the script could
not run (a bad ref, a folder that is not the top of a git work tree, a Python file it cannot
read or tokenize).

Standard library only. Python 3.9 or later.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Iterator, Optional

DIRECTIVE = re.compile(r"#\s*(noqa\b|type:|pragma:|pylint:|fmt:|isort:|mypy:|pyright:|ruff:|nosec\b)")
CODING = re.compile(r"coding[:=]")
LICENSE = re.compile(r"copyright|licen[sc]e|spdx", re.I)
LINK = re.compile(r"https?://\S")
LAYOUT = {tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING, tokenize.INDENT, tokenize.DEDENT}


class Unusable(Exception):
    """The script cannot run: a bad ref, a folder that is not a work tree, an unreadable file."""


@dataclasses.dataclass(frozen=True)
class Comment:
    path: str
    line: int
    text: str


def git(root: Path, *args: str) -> bytes:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if done.returncode != 0:
        said = done.stderr.decode(errors="replace").strip().splitlines()
        raise Unusable(f"git {' '.join(args[:2])}: {said[-1] if said else 'failed'}")
    return done.stdout


def comments(path: str, source: bytes) -> Iterator[Comment]:
    """Every comment in a Python source the keep-list does not decide, in file order."""
    try:
        source.decode(tokenize.detect_encoding(io.BytesIO(source).readline)[0])
        tokens = list(tokenize.tokenize(io.BytesIO(source).readline))
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError) as err:
        raise Unusable(f"{path}: cannot tokenize ({err})")
    licensed = False
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            licensed = licensed or bool(LICENSE.search(tok.string))
        elif tok.type not in LAYOUT:
            break
    linked = linked_lines(tokens)
    opening = True
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            opening = opening and tok.type in LAYOUT
            continue
        text, line = tok.string, tok.start[0]
        kept = (
            (line == 1 and text.startswith("#!"))
            or (line <= 2 and CODING.search(text))
            or DIRECTIVE.match(text)
            or (opening and licensed)
            or line in linked
        )
        if not kept:
            yield Comment(path, line, text)


def linked_lines(tokens: list[tokenize.TokenInfo]) -> set[int]:
    """Lines of every comment that carries a link, or sits in an unbroken run of whole-line comments with one."""
    linked: set[int] = set()
    run: list[tokenize.TokenInfo] = []
    for tok in [t for t in tokens if t.type == tokenize.COMMENT] + [None]:
        whole_line = tok is not None and not tok.line[: tok.start[1]].strip()
        if run and not (whole_line and tok.start[0] == run[-1].start[0] + 1):
            if any(LINK.search(t.string) for t in run):
                linked.update(t.start[0] for t in run)
            run = []
        if tok is not None:
            if whole_line:
                run.append(tok)
            elif LINK.search(tok.string):
                linked.add(tok.start[0])
    return linked


def changed_python(root: Path, base: str, head: Optional[str]) -> tuple[str, list[str], list[str]]:
    """The merge base, the Python files it holds that the diff touches, and the ones the head holds."""
    top = git(root, "rev-parse", "--show-toplevel").decode().strip()
    if Path(top).resolve() != root.resolve():
        raise Unusable(f"{root} is not the top of a git work tree")
    start = git(root, "merge-base", base, head or "HEAD").decode().strip()
    spec = [start, head] if head else [start]
    before, after = [], []
    listed = git(root, "diff", "--no-renames", "--name-status", "-z", *spec, "--", "*.py").split(b"\0")
    for status, name in zip(listed[0::2], listed[1::2]):
        path = name.decode(errors="surrogateescape")
        if status != b"A":
            before.append(path)
        if status != b"D":
            after.append(path)
    if not head:
        untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", "*.py")
        after += [n.decode(errors="surrogateescape") for n in untracked.split(b"\0") if n]
    return start, before, after


def read(root: Path, path: str) -> bytes:
    try:
        return (root / path).read_bytes()
    except OSError as err:
        raise Unusable(f"{path}: cannot read ({err.strerror})")


def added(root: Path, base: str, head: Optional[str]) -> list[Comment]:
    start, before, after = changed_python(root, base, head)
    spare = collections.Counter(
        c.text for path in before for c in comments(path, git(root, "show", f"{start}:{path}"))
    )
    new = []
    for path in sorted(after):
        source = git(root, "show", f"{head}:{path}") if head else read(root, path)
        for c in comments(path, source):
            if spare[c.text] > 0:
                spare[c.text] -= 1
            else:
                new.append(c)
    return new


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", required=True, help="ref to diff against; the diff starts at its merge base with the head")
    p.add_argument("--head", help="commit to read instead of the working tree")
    p.add_argument("--root", help="repo root (default: the current folder)")
    p.add_argument("--json", action="store_true", help="print a JSON list instead of text")
    args = p.parse_args(argv)
    root = Path(args.root or ".")
    try:
        new = added(root, args.base, args.head)
    except Unusable as err:
        print(f"comments: {err}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([dataclasses.asdict(c) for c in new], indent=2))
    else:
        for c in new:
            print(f"{c.path}:{c.line}: {c.text}")
    print(f"comments: the diff adds {len(new)} to Python files", file=sys.stderr)
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
