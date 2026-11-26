#!/usr/bin/env python3
"""Report a diff that weakens Python tests: a test deleted, a skip or a retry added, a timeout or
a tolerance widened, an assertion dropped or traded for a weaker one.

Usage:
    test_guard.py --base REF [--head REF] [--root DIR] [--json]

Run it from the repo root (or pass --root). It compares every changed Python test file as the
merge base of REF and the head has it with the head's copy, function by function. Without --head
the head is the working tree: commits since the merge base, uncommitted edits, and untracked
files git does not ignore. With --head it is that commit and nothing else.

A test file is a `.py` file named `test_*.py` or `*_test.py`, or any `.py` file under a folder
named `tests` or `test`, at the base or at the head, so a file renamed out of the pattern is
still read. Each function is compared with the one of the same name (`Class.method` inside a
class); a class's own decorators and body, and a module's top-level statements, are compared as
`Class` and `<module>`.

What it reports, one line per finding, as `path: name: what`:
- a test that is gone, or `moved to PATH` when another changed test file gained it;
- a skip (`skip`, `skipIf`, `skipUnless`, `skipTest`, `SkipTest`, `expectedFailure`, `xfail`,
  `skipif`), a retry (`flaky`, `retry`, `retries`, `rerun`, `reruns`), a larger `timeout`, or a
  wider `delta`, `abs`, `rel`, `abs_tol`, `rel_tol`, `atol`, `rtol` (or a smaller `places`) than the
  base had in that function;
- fewer assertions in a function (an `assert` statement or a call whose name starts with
  `assert`), and an `assertEqual`, `assertIs` or `assertRaisesRegex` traded for a weaker form;
- a test file this Python cannot parse at the head, with the version and the error: its tests
  were not compared, so run it under the Python the repo's tests use.
A file with a removed test also says which tests it gained, so a rename reads as one.

Each finding is a question for the author, not a verdict: a rename, a split or a test that moved
to a fixture is a fine reason, and the PR says it. What it does not see: changes outside Python
test files (a workflow's `timeout-minutes`, `continue-on-error` or `|| true`), a loosened expected
value or a smaller loop or seed range, a skip reached through a variable, and tests in nested
functions.

Standard output holds the findings and nothing else, so empty output means the script ran and
found nothing. A one-line count goes to standard error. Exit code: 0 when it ran, whatever it
found (it blocks nothing). 2 when it could not run: a bad ref, or a folder that is not the top of
a git work tree.

Standard library only. Python 3.9 or later.
"""
from __future__ import annotations

import argparse
import ast
import collections
import dataclasses
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterator, Optional

SKIPS = {"skip", "skipIf", "skipUnless", "skipTest", "SkipTest", "expectedFailure", "xfail", "skipif"}
RETRIES = {"flaky", "retry", "retries", "rerun", "reruns"}
WIDER = {"timeout", "delta", "abs", "rel", "abs_tol", "rel_tol", "atol", "rtol"}
NARROWER = {"places"}
WEAKER = {
    "assertEqual": {"assertIn", "assertTrue", "assertIsNotNone", "assertGreater", "assertGreaterEqual",
                    "assertLess", "assertLessEqual", "assertCountEqual", "assertAlmostEqual"},
    "assertIs": {"assertTrue", "assertIsNotNone", "assertEqual"},
    "assertRaisesRegex": {"assertRaises"},
}
MODULE = "<module>"
ADDED_NAMES_SHOWN = 5


class Unusable(Exception):
    """The script cannot run: a bad ref, or a folder that is not a work tree's top."""


@dataclasses.dataclass
class Facts:
    is_test: bool
    asserts: int = 0
    calls: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    skips: int = 0
    retries: int = 0
    limits: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class Finding:
    path: str
    name: str
    what: str

    def text(self) -> str:
        return f"{self.path}: {self.name}: {self.what}" if self.name else f"{self.path}: {self.what}"



def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _number(node: ast.AST) -> Optional[float]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    return None


def _limit(facts: Facts, key: str, value: Optional[float]) -> None:
    if value is None:
        return
    pick = min if key in NARROWER else max
    facts.limits[key] = value if key not in facts.limits else pick(facts.limits[key], value)


def _gather(facts: Facts, nodes: list[ast.AST]) -> Facts:
    for top in nodes:
        for n in ast.walk(top):
            if isinstance(n, ast.Assert):
                facts.asserts += 1
            elif isinstance(n, (ast.Name, ast.Attribute)) and _name(n) in SKIPS:
                facts.skips += 1
            elif isinstance(n, ast.Call):
                name = _name(n)
                if name.startswith("assert"):
                    facts.asserts += 1
                    facts.calls[name] += 1
                if name in RETRIES:
                    facts.retries += 1
                if name == "timeout" and n.args:
                    _limit(facts, "timeout", _number(n.args[0]))
                for k in n.keywords:
                    if k.arg in RETRIES:
                        facts.retries += 1
                    if k.arg in WIDER or k.arg in NARROWER:
                        _limit(facts, k.arg, _number(k.value))
    return facts


class Unparsed(Exception):
    """A file this Python cannot parse; the message says where."""


def read_tests(source: str) -> dict[str, Facts]:
    """Every function, class and the module's own statements, by name."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise Unparsed(f"line {e.lineno}: {e.msg}") from None
    except ValueError as e:
        raise Unparsed(str(e)) from None
    out: dict[str, Facts] = {}
    loose: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = _gather(Facts(node.name.startswith("test")), [node])
        elif isinstance(node, ast.ClassDef):
            own: list[ast.AST] = list(node.decorator_list)
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    key = f"{node.name}.{member.name}"
                    out[key] = _gather(Facts(member.name.startswith("test")), [member])
                else:
                    own.append(member)
            out[node.name] = _gather(Facts(False), own)
        else:
            loose.append(node)
    out[MODULE] = _gather(Facts(False), loose)
    return out



def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def compare(path: str, name: str, old: Facts, new: Facts) -> Iterator[Finding]:
    if new.skips > old.skips:
        yield Finding(path, name, "gains a skip")
    if new.retries > old.retries:
        yield Finding(path, name, "gains a retry")
    for key, was in sorted(old.limits.items()):
        now = new.limits.get(key)
        if now is None:
            continue
        if (key in NARROWER and now < was) or (key not in NARROWER and now > was):
            yield Finding(path, name, f"{key} {_fmt(was)} -> {_fmt(now)}")
    if new.asserts < old.asserts:
        yield Finding(path, name, f"assertions {old.asserts} -> {new.asserts}")
    for strong, weak in WEAKER.items():
        if new.calls[strong] < old.calls[strong]:
            gained = sorted(w for w in weak if new.calls[w] > old.calls[w])
            if gained:
                yield Finding(path, name, f"trades {strong} for {', '.join(gained)}")



def git(root: Path, *args: str) -> bytes:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if r.returncode != 0:
        raise Unusable(f"git {' '.join(args)}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


def is_test_path(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    *folders, name = path.split("/")
    return (fnmatch.fnmatchcase(name, "test_*.py") or fnmatch.fnmatchcase(name, "*_test.py")
            or any(f in ("tests", "test") for f in folders))


def changed(root: Path, base: str, head: Optional[str]) -> list[tuple[Optional[str], Optional[str]]]:
    """(old path, new path) for each changed file; None on the side where it does not exist."""
    ends = [head] if head else []
    raw = git(root, "diff", "--name-status", "-z", "-M", base, *ends).decode("utf-8", "replace").split("\0")
    pairs: list[tuple[Optional[str], Optional[str]]] = []
    i = 0
    while i < len(raw) and raw[i]:
        status = raw[i][0]
        if status in "RC":
            old, new = raw[i + 1], raw[i + 2]
            pairs.append((old if status == "R" else None, new))
            i += 3
            continue
        p = raw[i + 1]
        pairs.append((None if status == "A" else p, None if status == "D" else p))
        i += 2
    if not head:
        others = git(root, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8", "replace")
        pairs += [(None, p) for p in others.split("\0") if p]
    return pairs


def _show(root: Path, ref: str, path: str) -> Optional[str]:
    r = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{path}"], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def _working(root: Path, path: str) -> Optional[str]:
    try:
        return (root / path).read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def guard(root: Path, base: str, head: Optional[str]) -> list[Finding]:
    for ref in filter(None, (base, head)):
        if ref.startswith("-"):
            raise Unusable(f"{ref!r} is not a ref")
    top = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != root.resolve():
        raise Unusable(f"{root} is not the top of a git work tree (that is {top})")
    merge_base = git(root, "merge-base", base, head or "HEAD").decode().strip()
    files = []
    why: dict[str, str] = {}
    for old, new in changed(root, merge_base, head):
        if not any(p and is_test_path(p) for p in (old, new)):
            continue
        try:
            before = read_tests(_show(root, merge_base, old) or "") if old else {}
        except Unparsed:
            before = None
        text = (_show(root, head, new) if head else _working(root, new)) if new else None
        try:
            after = read_tests(text) if text is not None else {}
        except Unparsed as e:
            after, why[new] = None, str(e)
        files.append((old, new, before, after))

    gained = {name: new for old, new, before, after in files if new and after
              for name, f in after.items() if f.is_test and (not before or name not in before)}
    findings: list[Finding] = []
    for old, new, before, after in files:
        path = new or old
        if after is None:
            findings.append(Finding(path, "", f"Python {sys.version_info.major}.{sys.version_info.minor} cannot parse it at the head "
                                              f"({why[path]}); its tests were not compared"))
            continue
        if before is None:
            continue
        removed = sorted(n for n, f in before.items() if f.is_test and n not in after)
        for name in removed:
            elsewhere = gained.get(name)
            if elsewhere and elsewhere != path:
                findings.append(Finding(path, name, f"moved to {elsewhere}"))
            else:
                findings.append(Finding(path, name, "removed"))
        for name in sorted(set(before) & set(after)):
            findings.extend(compare(path, name, before[name], after[name]))
        if removed:
            added = sorted(n for n, f in after.items() if f.is_test and n not in before)
            if added:
                shown = ", ".join(added[:ADDED_NAMES_SHOWN]) + (f" and {len(added) - ADDED_NAMES_SHOWN} more" if len(added) > ADDED_NAMES_SHOWN else "")
                findings.append(Finding(path, "", f"gains {len(added)} tests: {shown}"))
    return findings


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base", required=True, help="ref to diff against; the diff starts at its merge base with the head")
    p.add_argument("--head", help="commit to read instead of the working tree")
    p.add_argument("--root", help="repo root (default: the current folder)")
    p.add_argument("--json", action="store_true", help="print a JSON list instead of text")
    args = p.parse_args(argv)
    root = Path(args.root or ".")
    try:
        findings = guard(root, args.base, args.head)
    except Unusable as e:
        print(f"test-guard: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([dataclasses.asdict(f) for f in findings], indent=2))
    else:
        for f in findings:
            print(f.text())
    files = len({f.path for f in findings})
    print(f"test-guard: {len(findings)} findings in {files} test files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
