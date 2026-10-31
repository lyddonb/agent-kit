#!/usr/bin/env python3
"""Check the CFO's books (the private repo that holds the ledger, projects, budgets and renewals).

Usage:
    python3 books.py check BOOKS_DIR [--base REF]

Prints one `path:line: message` line per problem (path relative to BOOKS_DIR), then
`ok, N rows, 0 problems` or `N problems`. Exit 0 when clean, 1 when there are problems,
2 on bad usage. Standard library only; runs on Python 3.9.

Shape: `Books` is loaded once (CSV rows with line numbers, parsed YAML, text of every
tracked file). Each entry in `CHECKS` takes a `Books` and yields `Problem`s. A new check is a
new entry in that registry.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

SCHEMA = ("charge_date", "period_start", "period_end", "provider", "service", "charge_type",
          "billed_cost", "currency", "api_equivalent_cost", "project", "status", "source",
          "evidence")
CHARGE_TYPES = frozenset({"subscription", "usage", "prepaid", "adjustment", "usage-equivalent"})
STATUSES = frozenset({"verified", "unknown"})
CURRENCIES = frozenset({"USD"})

LEDGER = "ledger/charges.csv"
YAML_KEYS = {
    "projects.yaml": ("version", "projects"),
    "budgets.yaml": ("version", "monthly_envelope", "alerts"),
    "renewals.yaml": ("version", "renewals"),
}


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass
class Row:
    line: int
    end_line: int
    cells: Dict[str, str]


@dataclass
class Books:
    dir: Path
    base: Optional[str]
    header: Optional[List[str]] = None
    rows: List[Row] = field(default_factory=list)
    yaml: Dict[str, Any] = field(default_factory=dict)  # file name -> parsed value, or None if unreadable
    texts: Dict[str, str] = field(default_factory=dict)  # relative path -> text of each text file
    load_problems: List[Problem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# YAML subset reader
# ---------------------------------------------------------------------------

class YamlError(Exception):
    def __init__(self, line: int, message: str):
        super().__init__(message)
        self.line = line
        self.message = message


def _strip_comment(s: str) -> str:
    quote = None
    i = 0
    while i < len(s):
        ch = s[i]
        prev = s[i - 1] if i else " "
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'" and (prev in " \t[{,"):
            quote = ch
        elif ch == "#" and prev in " \t":
            return s[:i]
        i += 1
    return s


_INT = re.compile(r"[-+]?\d+\Z")
_FLOAT = re.compile(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?\Z")


def _plain(text: str) -> Any:
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if _INT.match(text):
        return int(text)
    if _FLOAT.match(text):
        return float(text)
    return text


def _quoted(text: str, start: int, n: int) -> Tuple[str, int]:
    """Parse a quoted string at text[start]; return (value, index after the closing quote)."""
    q = text[start]
    out: List[str] = []
    i = start + 1
    while i < len(text):
        ch = text[i]
        if q == '"' and ch == "\\" and i + 1 < len(text):
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(text[i + 1], "\\" + text[i + 1]))
            i += 2
            continue
        if q == "'" and ch == "'" and text[i + 1:i + 2] == "'":
            out.append("'")
            i += 2
            continue
        if ch == q:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise YamlError(n, "unterminated quoted string")


class _Flow:
    def __init__(self, text: str, n: int):
        self.s, self.i, self.n = text, 0, n

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self) -> Any:
        self.ws()
        if self.i >= len(self.s):
            raise YamlError(self.n, "unterminated flow collection")
        ch = self.s[self.i]
        if ch == "{":
            return self.mapping()
        if ch == "[":
            return self.sequence()
        if ch in "\"'":
            v, self.i = _quoted(self.s, self.i, self.n)
            return v
        if ch in "&*!|>":
            raise YamlError(self.n, "unsupported YAML: anchors, tags and block markers inside flow collections")
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in ",]}":
            self.i += 1
        return _plain(self.s[start:self.i].strip())

    def sequence(self) -> List[Any]:
        self.i += 1
        out: List[Any] = []
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise YamlError(self.n, "unterminated flow list")
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def mapping(self) -> Dict[str, Any]:
        self.i += 1
        out: Dict[str, Any] = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise YamlError(self.n, "unterminated flow mapping")
            if self.s[self.i] == "}":
                self.i += 1
                return out
            if self.s[self.i] in "\"'":
                key, self.i = _quoted(self.s, self.i, self.n)
            else:
                start = self.i
                while self.i < len(self.s) and self.s[self.i] not in ":,}":
                    self.i += 1
                key = self.s[start:self.i].strip()
            self.ws()
            if self.i >= len(self.s) or self.s[self.i] != ":" or not key:
                raise YamlError(self.n, "unsupported YAML: flow mapping entry without 'key: value'")
            self.i += 1
            self.ws()
            if self.i < len(self.s) and self.s[self.i] in ",}":
                out[key] = None
            else:
                out[key] = self.value()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1


def _inline(text: str, n: int) -> Any:
    text = text.strip()
    if text[:1] in ("{", "["):
        flow = _Flow(text, n)
        v = flow.value()
        flow.ws()
        if flow.i != len(text):
            raise YamlError(n, "unsupported YAML: text after a flow collection")
        return v
    if text[:1] in ("\"", "'"):
        v, end = _quoted(text, 0, n)
        if text[end:].strip():
            raise YamlError(n, "unsupported YAML: text after a quoted string")
        return v
    if text[:1] in ("&", "*", "!", "|", ">", "@", "`", "%"):
        raise YamlError(n, "unsupported YAML: anchors, aliases, tags or block scalars here")
    return _plain(text)


def _split_key(text: str) -> Optional[Tuple[str, str]]:
    """Split `key: rest` (rest may be empty). None when the text is not a mapping entry."""
    if text[:1] in ("\"", "'"):
        try:
            key, end = _quoted(text, 0, 0)
        except YamlError:
            return None
        after = text[end:]
        if after.startswith(":") and (len(after) == 1 or after[1] == " "):
            return key, after[1:].strip()
        return None
    m = re.search(r":(?: |\Z)", text)
    if not m or m.start() == 0:
        return None
    return text[:m.start()].strip(), text[m.end():].strip()


def _is_seq(text: str) -> bool:
    return text == "-" or text.startswith("- ")


class _Yaml:
    def __init__(self, text: str):
        self.raw = text.splitlines()
        self.entries: List[Tuple[int, int, str]] = []  # (line number, indent, stripped content)
        for n, line in enumerate(self.raw, 1):
            content = _strip_comment(line).rstrip()
            if not content.strip():
                continue
            lead = content[:len(content) - len(content.lstrip())]
            if "\t" in lead:
                raise YamlError(n, "unsupported YAML: tab indentation")
            self.entries.append((n, len(lead), content.strip()))
        self.pos = 0

    def parse(self) -> Any:
        if not self.entries:
            return None
        n, indent, text = self.entries[0]
        if text.startswith("---") or text.startswith("..."):
            raise YamlError(n, "unsupported YAML: document markers")
        value = self.node(indent)
        if self.pos < len(self.entries):
            n, _, _ = self.entries[self.pos]
            raise YamlError(n, "unsupported YAML: unexpected indentation")
        return value

    def node(self, indent: int) -> Any:
        return self.seq(indent) if _is_seq(self.entries[self.pos][2]) else self.map(indent)

    def peek_deeper(self, indent: int) -> bool:
        return self.pos < len(self.entries) and self.entries[self.pos][1] > indent

    def map(self, indent: int) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        while self.pos < len(self.entries):
            n, ind, text = self.entries[self.pos]
            if ind != indent or _is_seq(text):
                break
            pair = _split_key(text)
            if pair is None:
                raise YamlError(n, "unsupported YAML: expected 'key: value'")
            key, rest = pair
            if key in out:
                raise YamlError(n, f"unsupported YAML: duplicate key '{key}'")
            self.pos += 1
            if rest in (">", ">-", "|", "|-"):
                out[key] = self.block_scalar(n, indent, rest)
            elif rest == "":
                if self.peek_deeper(indent):
                    out[key] = self.node(self.entries[self.pos][1])
                elif (self.pos < len(self.entries) and self.entries[self.pos][1] == indent
                      and _is_seq(self.entries[self.pos][2])):
                    out[key] = self.seq(indent)
                else:
                    out[key] = None
            else:
                out[key] = _inline(rest, n)
        self.reject_leftover(indent)
        return out

    def seq(self, indent: int) -> List[Any]:
        out: List[Any] = []
        while self.pos < len(self.entries):
            n, ind, text = self.entries[self.pos]
            if ind != indent or not _is_seq(text):
                break
            item = text[1:].strip()
            self.pos += 1
            if item == "":
                out.append(self.node(self.entries[self.pos][1]) if self.peek_deeper(indent) else None)
                continue
            pair = None if item[:1] in ("{", "[", "\"", "'") else _split_key(item)
            if pair is not None:
                key, rest = pair
                if rest == "" or rest in (">", ">-", "|", "|-") or self.peek_deeper(indent):
                    raise YamlError(n, "unsupported YAML: multi-line mapping inside a list item")
                out.append({key: _inline(rest, n)})
            else:
                out.append(_inline(item, n))
        self.reject_leftover(indent)
        return out

    def reject_leftover(self, indent: int) -> None:
        if self.pos < len(self.entries):
            n, ind, text = self.entries[self.pos]
            if ind > indent:
                raise YamlError(n, "unsupported YAML: unexpected indentation")
            if ind == indent:
                raise YamlError(n, "unsupported YAML: list item and mapping key at the same level")

    def block_scalar(self, n: int, key_indent: int, style: str) -> str:
        lines: List[str] = []
        last = n
        for j in range(n, len(self.raw)):  # raw index j is line j + 1
            line = self.raw[j]
            if line.strip() == "":
                lines.append("")
                continue
            if len(line) - len(line.lstrip(" ")) <= key_indent:
                break
            lines.append(line.strip())
            last = j + 1
        while self.pos < len(self.entries) and self.entries[self.pos][0] <= last:
            self.pos += 1
        content = [l for l in lines[:max(0, last - n)] if l != ""]
        joiner = " " if style.startswith(">") else "\n"
        text = joiner.join(content)
        return text if style.endswith("-") else text + "\n"


def parse_yaml(text: str) -> Any:
    """Parse the YAML subset the books use. Raises YamlError with a line number otherwise."""
    return _Yaml(text).parse()


# ---------------------------------------------------------------------------
# Loading (the boundary: parse once, checks trust the result)
# ---------------------------------------------------------------------------

def _git(books_dir: Path, *args: str) -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run(["git", "-C", str(books_dir)] + list(args), capture_output=True)


def _text_files(books_dir: Path) -> List[str]:
    rels: List[str] = []
    try:
        inside = _git(books_dir, "rev-parse", "--is-inside-work-tree")
    except OSError:
        inside = None
    if inside is not None and inside.returncode == 0:
        out = _git(books_dir, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if out.returncode == 0:
            rels = [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
    else:
        for p in sorted(books_dir.rglob("*")):
            if ".git" in p.relative_to(books_dir).parts or not p.is_file():
                continue
            rels.append(p.relative_to(books_dir).as_posix())
    return sorted(set(rels))


def _read_text(path: Path) -> Optional[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def load(books_dir: Path, base: Optional[str] = None) -> Books:
    books = Books(dir=books_dir, base=base)
    for rel in _text_files(books_dir):
        text = _read_text(books_dir / rel)
        if text is not None:
            books.texts[rel] = text

    ledger = _read_text(books_dir / LEDGER)
    if ledger is None:
        books.load_problems.append(Problem(LEDGER, 1, "missing file"))
    else:
        reader = csv.reader(io.StringIO(ledger, newline=""))
        while True:
            before = reader.line_num
            try:
                record = next(reader)
            except StopIteration:
                break
            except csv.Error as e:
                books.load_problems.append(Problem(LEDGER, before + 1, f"unreadable CSV: {e}"))
                break
            start, end = before + 1, reader.line_num
            if books.header is None:
                books.header = record
            elif len(record) != len(SCHEMA):
                books.load_problems.append(
                    Problem(LEDGER, start, f"row has {len(record)} columns, expected {len(SCHEMA)}"))
            else:
                books.rows.append(Row(start, end, dict(zip(SCHEMA, record))))

    for name in YAML_KEYS:
        text = _read_text(books_dir / name)
        if text is None:
            books.yaml[name] = None
            books.load_problems.append(Problem(name, 1, "missing file"))
            continue
        try:
            books.yaml[name] = parse_yaml(text)
        except YamlError as e:
            books.yaml[name] = None
            books.load_problems.append(Problem(name, e.line, e.message if e.message.startswith("unsupported YAML") else f"unsupported YAML: {e.message}"))
    return books


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

Check = Callable[[Books], Iterable[Problem]]


def check_load(books: Books) -> Iterator[Problem]:
    yield from books.load_problems


def check_header(books: Books) -> Iterator[Problem]:
    if books.header is not None and tuple(books.header) != SCHEMA:
        yield Problem(LEDGER, 1, "header does not match the schema: expected " + ",".join(SCHEMA))


def _is_date(s: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return True


def _decimal(s: str) -> bool:
    try:
        return Decimal(s).is_finite()
    except InvalidOperation:
        return False


def project_keys(books: Books) -> Optional[frozenset]:
    doc = books.yaml.get("projects.yaml")
    if isinstance(doc, dict) and isinstance(doc.get("projects"), dict):
        return frozenset(doc["projects"])
    return None


def check_rows(books: Books) -> Iterator[Problem]:
    if books.header is None or tuple(books.header) != SCHEMA:
        return
    projects = project_keys(books)
    for row in books.rows:
        c, n = row.cells, row.line

        def bad(msg: str) -> Problem:
            return Problem(LEDGER, n, msg)

        if not _is_date(c["charge_date"]):
            yield bad("charge_date is not a YYYY-MM-DD date")
        if not _is_date(c["period_start"]):
            yield bad("period_start is required and must be a YYYY-MM-DD date")
        if c["period_end"] and not _is_date(c["period_end"]):
            yield bad("period_end is not empty and not a YYYY-MM-DD date")
        if _is_date(c["period_start"]) and _is_date(c["period_end"]) and c["period_start"] > c["period_end"]:
            yield bad("period_start is after period_end")
        for col, known in (("charge_type", CHARGE_TYPES), ("status", STATUSES), ("currency", CURRENCIES)):
            if c[col] not in known:
                yield bad(f"{col} '{c[col]}' is not one of: {', '.join(sorted(known))}")
        if c["status"] == "unknown" and c["billed_cost"] != "":
            yield bad("billed_cost must be empty when status is unknown")
        elif c["status"] == "verified" and c["billed_cost"] == "":
            yield bad("billed_cost is empty but status is not unknown")
        if c["billed_cost"] != "" and not _decimal(c["billed_cost"]):
            yield bad("billed_cost is not a decimal number")
        if c["api_equivalent_cost"] != "" and not _decimal(c["api_equivalent_cost"]):
            yield bad("api_equivalent_cost is not empty and not a decimal number")
        if not c["evidence"].strip():
            yield bad("evidence is empty")
        if projects is not None and c["project"] != "unassigned" and c["project"] not in projects:
            yield bad(f"project '{c['project']}' is not a key in projects.yaml and not 'unassigned'")


def check_yaml(books: Books) -> Iterator[Problem]:
    for name, keys in YAML_KEYS.items():
        doc = books.yaml.get(name)
        if doc is None:
            continue  # unreadable or missing: load already reported it
        if not isinstance(doc, dict):
            yield Problem(name, 1, "top level must be a mapping")
            continue
        for key in keys:
            if key not in doc:
                yield Problem(name, 1, f"missing top-level key '{key}'")
    doc = books.yaml.get("projects.yaml")
    if isinstance(doc, dict) and "projects" in doc and not isinstance(doc["projects"], dict):
        yield Problem("projects.yaml", 1, "'projects' must be a mapping of project names")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_CARD_RUN = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_CARD_GROUPED = [
    re.compile(r"(?<!\d)\d{4}([ -])\d{4}\1\d{4}\1\d{4}(?:\1\d{1,3})?(?!\d)"),
    re.compile(r"(?<!\d)\d{4}([ -])\d{6}\1\d{5}(?!\d)"),
]
_ACCOUNT = [
    re.compile(r"(?<!\d)\d{12}(?!\d)"),
    re.compile(r"(?<![\d#])(?<!\d-)\d{4}-\d{4}-\d{4}(?!\d|-\d)"),
]
_SECRETS = [
    ("Anthropic API key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}")),
    ("API key (sk-)", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}")),
    ("AWS access key ID", re.compile(r"(?<![A-Za-z0-9])AKIA[A-Z0-9]{16}(?![A-Za-z0-9])")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_])ghp_[A-Za-z0-9]{36}(?![A-Za-z0-9])")),
    ("GitHub fine-grained token", re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{22,}")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
]


def scan_line(text: str, account_text: Optional[str] = None) -> List[str]:
    """Return what kinds of forbidden content `text` holds. `account_text` is the part of the
    line the 12-digit rule applies to (default: all of it). Never returns the matched text."""
    found: List[str] = []
    seen_spans = set()
    for pat in [_CARD_RUN] + _CARD_GROUPED:
        for m in pat.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits) and m.span() not in seen_spans:
                seen_spans.add(m.span())
                found.append(f"looks like a card number (Luhn-valid, {len(digits)} digits)")
    target = text if account_text is None else account_text
    if any(p.search(target) for p in _ACCOUNT):
        found.append("looks like a 12-digit cloud account ID")
    for label, pat in _SECRETS:
        if pat.search(text):
            found.append(f"looks like a secret ({label} shape)")
    # sk-ant- keys also match the plain sk- rule; keep the specific one
    if any("Anthropic" in f for f in found):
        found = [f for f in found if "(sk-)" not in f]
    return found


def check_forbidden(books: Books) -> Iterator[Problem]:
    rows_by_line = {r.line: r for r in books.rows}
    for rel, text in books.texts.items():
        for n, line in enumerate(text.split("\n"), 1):
            account_text = None
            if rel == LEDGER and n in rows_by_line:
                cells = rows_by_line[n].cells
                account_text = ",".join(v for k, v in cells.items() if k != "evidence")
            for kind in scan_line(line, account_text):
                yield Problem(rel, n, f"forbidden content: {kind}")


def _lines(text: str) -> List[str]:
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def check_append_only(books: Books) -> Iterator[Problem]:
    ref = books.base
    if ref is None:
        return
    try:
        if _git(books.dir, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode != 0:
            yield Problem(LEDGER, 1, f"cannot check against {ref}: not a commit here (is this a git repo, and is the ref fetched?)")
            return
        listed = _git(books.dir, "ls-tree", "--name-only", ref, "--", LEDGER)
        if listed.returncode != 0:
            yield Problem(LEDGER, 1, f"cannot check against {ref}: git ls-tree failed")
            return
        if not listed.stdout.strip():
            return  # the ledger did not exist at the base
        shown = _git(books.dir, "show", f"{ref}:./{LEDGER}")
    except OSError as e:
        yield Problem(LEDGER, 1, f"cannot check against {ref}: git could not run ({e})")
        return
    if shown.returncode != 0:
        yield Problem(LEDGER, 1, f"cannot check against {ref}: git show failed")
        return
    old = _lines(shown.stdout.decode("utf-8", "replace"))
    new = _lines(books.texts.get(LEDGER, ""))
    for i, line in enumerate(old):
        if i >= len(new):
            yield Problem(LEDGER, i + 1, f"removed since {ref}")
        elif new[i] != line:
            yield Problem(LEDGER, i + 1, f"changed since {ref}")


CHECKS: Tuple[Tuple[str, Check], ...] = (
    ("load", check_load),
    ("header", check_header),
    ("rows", check_rows),
    ("yaml", check_yaml),
    ("forbidden", check_forbidden),
    ("append-only", check_append_only),
)


def run_checks(books: Books) -> List[Problem]:
    problems = [p for _, check in CHECKS for p in check(books)]
    return sorted(set(problems), key=lambda p: (p.path, p.line, p.message))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    books_dir = Path(args.books_dir)
    if not books_dir.is_dir():
        print(f"books.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    books = load(books_dir, args.base)
    problems = run_checks(books)
    for p in problems:
        print(p)
    if problems:
        print(f"{len(problems)} problems")
        return 1
    print(f"ok, {len(books.rows)} rows, 0 problems")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="books.py", description="Work with the CFO's books.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate the books")
    check.add_argument("books_dir", metavar="BOOKS_DIR")
    check.add_argument("--base", metavar="REF", help="fail if a ledger line at REF changed or was removed")
    check.set_defaults(func=cmd_check)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
