#!/usr/bin/env python3
"""Check the CFO's books (the private repo that holds the ledger, projects, budgets and renewals).

Usage:
    python3 books.py check BOOKS_DIR [--base REF]
    python3 books.py append BOOKS_DIR ROWS_CSV
    python3 books.py summary BOOKS_DIR --month YYYY-MM [--as-of YYYY-MM-DD] [--json]

`check` prints one `path:line: message` line per problem (path relative to BOOKS_DIR), then
`ok, N rows, 0 problems` or `N problems`. Exit 0 when clean, 1 when there are problems,
2 on bad usage. `append` adds rows to the ledger only if the whole result passes every check.
`summary` reports one month, and only for books that pass the checks. Standard library only;
runs on Python 3.9.

Shape: `Books` is loaded once (CSV rows with line numbers, parsed YAML, text of every
tracked file). Each entry in `CHECKS` takes a `Books` and yields `Problem`s. A new check is a
new entry in that registry.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
    yaml: Dict[str, Any] = field(default_factory=dict)  # file name -> parsed value; absent if load reported it
    ledger_bytes: bytes = b""
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


_INT = re.compile(r"[-+]?(0|[1-9]\d*)\Z")  # a leading zero (012) stays a string
_FLOAT = re.compile(r"[-+]?((0|[1-9]\d*)\.\d*|\.\d+|(0|[1-9]\d*))([eE][-+]?\d+)?\Z")


def _plain(text: str, n: int) -> Any:
    if text.startswith("- ") or text == "-" or text[:1] in "]},":
        raise YamlError(n, "unsupported YAML: plain value starts with '" + text[:1] + "'")
    if ": " in text or text.endswith(":"):
        raise YamlError(n, "unsupported YAML: ': ' inside a plain value (quote it)")
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
            esc = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(text[i + 1])
            if esc is None:
                raise YamlError(n, "unsupported YAML: escape \\" + text[i + 1] + " (only \\n \\t \\\" \\\\ are supported)")
            out.append(esc)
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
        return _plain(self.s[start:self.i].strip(), self.n)

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
            if self.s[self.i] == ",":
                raise YamlError(self.n, "unsupported YAML: empty element in a flow list")
            quoted = self.s[self.i] in "\"'"
            item = self.value()
            if not quoted and isinstance(item, str) and re.search(r"\s", item):
                raise YamlError(self.n, "unsupported YAML: quote flow list items that contain spaces")
            out.append(item)
            self.separator("]")

    def separator(self, closer: str) -> None:
        self.ws()
        if self.i >= len(self.s):
            raise YamlError(self.n, "unterminated flow collection")
        if self.s[self.i] == ",":
            self.i += 1
        elif self.s[self.i] != closer:
            raise YamlError(self.n, f"unsupported YAML: expected ',' or '{closer}' in a flow collection")

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
            if key in out:
                raise YamlError(self.n, f"unsupported YAML: duplicate key '{key}'")
            self.i += 1
            self.ws()
            if self.i < len(self.s) and self.s[self.i] in ",}":
                out[key] = None
            else:
                out[key] = self.value()
            self.separator("}")


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
    return _plain(text, n)


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
        content: List[str] = []
        first_indent = None
        last = n
        blank_seen = False
        for j in range(n, len(self.raw)):  # raw index j is line j + 1
            line = self.raw[j]
            if line.strip() == "":
                blank_seen = True
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= key_indent:
                break
            if blank_seen:
                raise YamlError(n, "unsupported YAML: blank line inside a block scalar")
            if first_indent is None:
                first_indent = indent
            elif indent != first_indent:
                raise YamlError(n, "unsupported YAML: block scalar lines must share one indentation")
            content.append(line.strip())
            last = j + 1
        while self.pos < len(self.entries) and self.entries[self.pos][0] <= last:
            self.pos += 1
        text = (" " if style.startswith(">") else "\n").join(content)
        return text if style.endswith("-") else text + "\n"


def parse_yaml(text: str) -> Any:
    """Parse the YAML subset the books use. Raises YamlError with a line number otherwise."""
    return _Yaml(text).parse()


# ---------------------------------------------------------------------------
# Loading (the boundary: parse once, checks trust the result)
# ---------------------------------------------------------------------------

def _git(books_dir: Path, *args: str) -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run(["git", "-C", str(books_dir)] + list(args), capture_output=True)


def _text_files(books_dir: Path) -> Tuple[List[str], List[Problem]]:
    rels: List[str] = []
    problems: List[Problem] = []
    try:
        inside = _git(books_dir, "rev-parse", "--is-inside-work-tree")
    except OSError:
        inside = None
    if inside is not None and inside.returncode == 0:
        out = _git(books_dir, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if out.returncode == 0:
            rels = [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
        else:
            problems.append(Problem(".", 1, "git ls-files failed, so the scan of tracked files did not run: "
                                    + out.stderr.decode("utf-8", "replace").strip()[:200]))
    else:
        for p in sorted(books_dir.rglob("*")):
            if ".git" in p.relative_to(books_dir).parts or not p.is_file():
                continue
            rels.append(p.relative_to(books_dir).as_posix())
    return sorted(set(rels)), problems


def _decode(data: bytes) -> Optional[str]:
    """Text of a file, or None when it is binary. UTF-16 and UTF-8 files with a BOM are text."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8-sig", "replace")


def _read(books_dir: Path, rel: str) -> Tuple[Optional[str], bytes, Optional[Problem]]:
    """(text, raw bytes, problem). Exactly one of text and problem is set."""
    try:
        data = (books_dir / rel).read_bytes()
    except FileNotFoundError:
        return None, b"", Problem(rel, 1, "missing file")
    except OSError as e:
        return None, b"", Problem(rel, 1, f"unreadable file ({e.strerror or type(e).__name__})")
    text = _decode(data)
    if text is None:
        return None, data, Problem(rel, 1, "binary file; the books hold text only")
    return text, data, None


def load(books_dir: Path, base: Optional[str] = None, ledger_override: Optional[bytes] = None) -> Books:
    """Load the books. `ledger_override` replaces the ledger's bytes, so a candidate ledger can be
    checked in memory before anything is written."""
    books = Books(dir=books_dir, base=base)
    rels, problems = _text_files(books_dir)
    books.load_problems.extend(problems)
    for rel in rels:
        if not (books_dir / rel).is_file():
            continue  # listed by git but deleted from disk
        text, _, problem = _read(books_dir, rel)
        if problem:
            books.load_problems.append(problem)
        else:
            books.texts[rel] = text

    if ledger_override is None:
        ledger, books.ledger_bytes, problem = _read(books_dir, LEDGER)
    else:
        books.ledger_bytes = ledger_override
        ledger = _decode(ledger_override)
        problem = Problem(LEDGER, 1, "binary file; the books hold text only") if ledger is None else None
        if ledger is not None:
            books.texts[LEDGER] = ledger
    if problem:
        books.load_problems.append(problem)
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
            elif end != start:
                books.load_problems.append(
                    Problem(LEDGER, start, "row spans more than one line (embedded newline or unclosed quote)"))
            elif len(record) != len(SCHEMA):
                books.load_problems.append(
                    Problem(LEDGER, start, f"row has {len(record)} columns, expected {len(SCHEMA)}"))
            else:
                books.rows.append(Row(start, end, dict(zip(SCHEMA, record))))

    for name in YAML_KEYS:
        text, _, problem = _read(books_dir, name)
        if problem:
            books.load_problems.append(problem)
            continue
        try:
            doc = parse_yaml(text)
        except YamlError as e:
            msg = e.message if e.message.startswith("unsupported YAML") else f"unsupported YAML: {e.message}"
            books.load_problems.append(Problem(name, e.line, msg))
            continue
        if doc is None:
            books.load_problems.append(Problem(name, 1, "empty file"))
            continue
        books.yaml[name] = doc  # only files that parsed to something are here
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


def project_keys(books: Books) -> frozenset:
    """Project names; empty when projects.yaml is unusable, so the project rule never switches off."""
    doc = books.yaml.get("projects.yaml")
    if isinstance(doc, dict) and isinstance(doc.get("projects"), dict):
        return frozenset(doc["projects"])
    return frozenset()


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
        if c["project"] != "unassigned" and c["project"] not in projects:
            yield bad(f"project '{c['project']}' is not a key in projects.yaml and not 'unassigned'")


def check_yaml(books: Books) -> Iterator[Problem]:
    for name, keys in YAML_KEYS.items():
        if name not in books.yaml:
            continue  # load already reported it
        doc = books.yaml[name]
        if not isinstance(doc, dict):
            yield Problem(name, 1, "top level must be a mapping")
            continue
        for key in keys:
            if key not in doc:
                yield Problem(name, 1, f"missing top-level key '{key}'")
    doc = books.yaml.get("projects.yaml")
    if isinstance(doc, dict) and "projects" in doc and not isinstance(doc["projects"], dict):
        yield Problem("projects.yaml", 1, "'projects' must be a mapping of project names")
    elif isinstance(doc, dict) and "projects" in doc:
        for name, entry in doc["projects"].items():
            paths = entry.get("paths") if isinstance(entry, dict) else None
            if paths is not None and not (isinstance(paths, list) and all(isinstance(p, str) and p for p in paths)):
                yield Problem("projects.yaml", 1, f"project '{name}': 'paths' must be a list of directory paths")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


# Separators allowed between digit groups: space, dot, hyphen, no-break space, Unicode hyphens and dashes.
_SEP = "[ .\\- ‐-―]"
_CARD_RUN = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_CARD_4444 = re.compile(r"(?<!\d)\d{4}{S}\d{4}{S}\d{4}{S}\d{4}(?:{S}\d{1,3})?(?!\d)".replace("{S}", _SEP))
_CARD_465 = re.compile(r"(?<!\d)\d{4}{S}\d{6}{S}\d{5}(?!\d)".replace("{S}", _SEP))
_ACCOUNT_RUN = re.compile(r"(?<![\d.])\d{12}(?!\d)")
_ACCOUNT_GROUPED = re.compile(r"(?<!\d)(?<!\d[ -])\d{4}([ -])\d{4}\1\d{4}(?!\d|[ -]\d{4})")
_SECRETS = [
    ("Anthropic API key", re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{20,}")),
    ("API key (sk-)", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("Stripe key", re.compile(r"(?<![A-Za-z0-9])sk_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("AWS access key ID", re.compile(r"(?<![A-Za-z0-9])A(?:KIA|SIA)[A-Z0-9]{16}(?![A-Za-z0-9])")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained token", re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{22,}")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9])xox[abeprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
]


def _account_ids(text: str) -> bool:
    if _ACCOUNT_RUN.search(text):
        return True
    for m in _ACCOUNT_GROUPED.finditer(text):
        start = m.start()
        if start > 0 and text[start - 1] == "#":
            # "#1234-5678-9012" is a receipt number unless the text just before says account
            if not re.search(r"account|acct", text[max(0, start - 21):start - 1], re.I):
                continue
        return True
    return False


def scan_line(text: str, account_text: Optional[str] = None) -> List[str]:
    """Return what kinds of forbidden content `text` holds. `account_text` is the part of the
    line the 12-digit rule applies to (default: all of it). Never returns the matched text."""
    found: List[str] = []
    for pat in (_CARD_RUN, _CARD_4444, _CARD_465):
        for m in pat.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            # a 4-4-4-4 group may be followed by a CVV, expiry or amount: try the first 16 digits too
            for candidate in ([digits[:16], digits] if pat is _CARD_4444 else [digits]):
                if 13 <= len(candidate) <= 19 and _luhn(candidate):
                    msg = f"looks like a card number (Luhn-valid, {len(candidate)} digits)"
                    if msg not in found:
                        found.append(msg)
                    break
    if _account_ids(text if account_text is None else account_text):
        found.append("looks like a 12-digit cloud account ID")
    for label, pat in _SECRETS:
        if pat.search(text):
            found.append(f"looks like a secret ({label} shape)")
    # sk-ant- keys also match the plain sk- rule; keep the specific one
    if any("Anthropic" in f for f in found):
        found = [f for f in found if "(sk-)" not in f]
    return found


def _ledger_account_text(line: str) -> Optional[str]:
    """For a ledger line that parses as a row, the line without its evidence cell."""
    try:
        cells = next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return None
    return ",".join(cells[:-1]) if len(cells) == len(SCHEMA) else None


def check_forbidden(books: Books) -> Iterator[Problem]:
    rows_by_line = {r.line: r for r in books.rows}
    for rel, text in books.texts.items():
        for kind in scan_line(rel):
            yield Problem(rel, 1, f"forbidden content in file name: {kind}")
        for n, line in enumerate(text.split("\n"), 1):
            account_text = None
            if rel == LEDGER and n in rows_by_line:
                cells = rows_by_line[n].cells
                account_text = ",".join(v for k, v in cells.items() if k != "evidence")
            for kind in scan_line(line, account_text):
                yield Problem(rel, n, f"forbidden content: {kind}")


def _base_problem(books: Books) -> Optional[Problem]:
    ref = books.base
    try:
        if _git(books.dir, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode != 0:
            return Problem(LEDGER, 1, f"cannot check against {ref}: not a commit here (is this a git repo, and is the ref fetched?)")
    except OSError as e:
        return Problem(LEDGER, 1, f"cannot check against {ref}: git could not run ({e})")
    return None


def _lines(data: bytes) -> List[bytes]:
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts.pop()
    return parts


def check_append_only(books: Books) -> Iterator[Problem]:
    ref = books.base
    if ref is None:
        return
    problem = _base_problem(books)
    if problem:
        yield problem
        return
    listed = _git(books.dir, "ls-tree", "--name-only", ref, "--", LEDGER)
    if listed.returncode != 0:
        yield Problem(LEDGER, 1, f"cannot check against {ref}: git ls-tree failed")
        return
    if not listed.stdout.strip():
        return  # the ledger did not exist at the base
    shown = _git(books.dir, "show", f"{ref}:./{LEDGER}")
    if shown.returncode != 0:
        yield Problem(LEDGER, 1, f"cannot check against {ref}: git show failed")
        return
    old, new = _lines(shown.stdout), _lines(books.ledger_bytes)
    for i, line in enumerate(old):
        if i >= len(new):
            yield Problem(LEDGER, i + 1, f"removed since {ref}")
        elif new[i] != line:
            yield Problem(LEDGER, i + 1, f"changed since {ref}")


_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def check_history(books: Books) -> Iterator[Problem]:
    """Scan every line added in base..HEAD, so a secret committed and then removed still fails."""
    ref = books.base
    if ref is None:
        return
    problem = _base_problem(books)
    if problem:
        yield problem
        return
    log = _git(books.dir, "-c", "core.quotepath=off", "log", "-p", "-U0", "--no-color",
               "--format=commit:%H", f"{ref}..HEAD", "--")
    if log.returncode != 0:
        yield Problem(LEDGER, 1, f"cannot scan history since {ref}: git log failed")
        return
    sha, path, new_line, old_left, new_left = "", "", 0, 0, 0
    for raw in log.stdout.decode("utf-8", "replace").split("\n"):
        if old_left or new_left:
            if raw.startswith("+"):
                new_left -= 1
                account_text = _ledger_account_text(raw[1:]) if path == LEDGER else None
                for kind in scan_line(raw[1:], account_text):
                    yield Problem(path, new_line, f"forbidden content in commit {sha[:7]}: {kind}")
                new_line += 1
                continue
            if raw.startswith("-"):
                old_left -= 1
                continue
            if raw.startswith("\\"):
                continue
        if raw.startswith("commit:"):
            sha = raw[len("commit:"):]
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else ""
        elif raw.startswith("Binary files "):
            m = re.search(r" and b/(.*) differ$", raw)
            if m:
                yield Problem(m.group(1), 1, f"binary file changed in commit {sha[:7]}; the books hold text only")
        else:
            m = _HUNK.match(raw)
            if m:
                old_left = int(m.group(1)) if m.group(1) is not None else 1
                new_line = int(m.group(2))
                new_left = int(m.group(3)) if m.group(3) is not None else 1


QUESTIONS = "questions.md"
_QUESTION = re.compile(r"- \*\*Q(\d+) \((\d{4}-\d{2}-\d{2})\) [^*]*[^*\s]\.\*\*(?: |$)")
_ANSWERED = re.compile(r"\*\*Answered (\d{4}-\d{2}-\d{2}):\*\*")


def _valid_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def check_questions(books: Books) -> Iterator[Problem]:
    text = books.texts.get(QUESTIONS)
    if text is None:
        yield Problem(QUESTIONS, 1, "missing; the CFO keeps its open and answered questions here")
        return
    lines = text.splitlines()
    headings = {ln.strip(): n for n, ln in enumerate(lines, 1) if ln.startswith("## ")}
    for name in ("## Open", "## Answered"):
        if name not in headings:
            yield Problem(QUESTIONS, 1, f"missing heading '{name}'")
    section: Optional[str] = None
    seen: Dict[str, int] = {}
    bullets: List[Tuple[int, str, str]] = []  # (line, section, text incl. continuation lines)
    for n, ln in enumerate(lines, 1):
        if ln.startswith("## "):
            section = ln.strip()[3:]
        elif ln.startswith("- **Q"):
            bullets.append((n, section or "", ln))
        elif bullets and ln.startswith((" ", "\t")) and ln.strip():
            first = bullets[-1]
            bullets[-1] = (first[0], first[1], first[2] + " " + ln.strip())
    for n, sec, bullet in bullets:
        m = _QUESTION.match(bullet)
        if not m:
            yield Problem(QUESTIONS, n, "question must start '- **Q<n> (YYYY-MM-DD) <title>.**' then the question text")
            continue
        if not _valid_date(m.group(2)):
            yield Problem(QUESTIONS, n, f"{m.group(2)} is not a real date")
        qid = "Q" + m.group(1)
        if qid in seen:
            yield Problem(QUESTIONS, n, f"{qid} is already used on line {seen[qid]}; ids are unique across Open and Answered")
        else:
            seen[qid] = n
        if sec == "Answered":
            a = _ANSWERED.search(bullet)
            if not a:
                yield Problem(QUESTIONS, n, f"{qid} is under Answered but has no '**Answered YYYY-MM-DD:**'")
            elif not _valid_date(a.group(1)):
                yield Problem(QUESTIONS, n, f"{a.group(1)} is not a real date")
        elif sec != "Open":
            yield Problem(QUESTIONS, n, f"{qid} is not under '## Open' or '## Answered'")


CHECKS: Tuple[Tuple[str, Check], ...] = (
    ("load", check_load),
    ("header", check_header),
    ("rows", check_rows),
    ("yaml", check_yaml),
    ("forbidden", check_forbidden),
    ("append-only", check_append_only),
    ("history", check_history),
    ("questions", check_questions),
)


@dataclass(frozen=True)
class Warn:
    """Worth reading, never a failure: `check` still exits 0."""
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: warning: {self.message}"


PRICING_MAX_AGE_DAYS = 90
PRICING_REL = "scripts/pricing.json"


def warn_pricing_age(books: Books, today: date) -> Iterator[Warn]:
    try:
        text = PRICING_FILE.read_text()
        as_of = json.loads(text)["as_of"]
        if not _is_date(as_of):
            raise ValueError("as_of is not a YYYY-MM-DD date")
    except (OSError, ValueError, KeyError, TypeError) as e:
        yield Warn(PRICING_REL, 1, f"cannot read the pricing date ({type(e).__name__}); API-equivalent costs may be stale")
        return
    age = (today - date.fromisoformat(as_of)).days
    if age > PRICING_MAX_AGE_DAYS:
        line = next((i for i, ln in enumerate(text.split("\n"), 1) if '"as_of"' in ln), 1)
        yield Warn(PRICING_REL, line, f"pricing is from {as_of}, {age} days old (limit {PRICING_MAX_AGE_DAYS});"
                   " check the source URL and update the table")


WarnCheck = Callable[[Books, date], Iterable[Warn]]
WARNINGS: Tuple[Tuple[str, WarnCheck], ...] = (
    ("pricing-age", warn_pricing_age),
)


def run_warnings(books: Books, today: date) -> List[Warn]:
    return sorted({w for _, check in WARNINGS for w in check(books, today)},
                  key=lambda w: (w.path, w.line, w.message))


def run_checks(books: Books) -> List[Problem]:
    problems = [p for _, check in CHECKS for p in check(books)]
    return sorted(set(problems), key=lambda p: (p.path, p.line, p.message))

# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------

class UsageError(Exception):
    pass


def _read_new_rows(path: Path) -> List[Dict[str, str]]:
    """Rows of ROWS_CSV as full SCHEMA dicts; columns not in the file stay empty."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError(f"cannot read {path}: {getattr(e, 'strerror', None) or type(e).__name__}")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, None)
        if header is None:
            raise UsageError(f"{path} is empty; it needs a header row with at least 'evidence'")
        header = [h.strip() for h in header]
        unknown = [h for h in header if h not in SCHEMA]
        if unknown:
            raise UsageError("unknown column(s) in the rows file: " + ", ".join(repr(h) for h in unknown)
                             + "; allowed: " + ", ".join(SCHEMA))
        if len(set(header)) != len(header):
            raise UsageError("duplicate column in the rows file header")
        if "evidence" not in header:
            raise UsageError("the rows file needs an 'evidence' column")
        out: List[Dict[str, str]] = []
        for record in reader:
            if not record:
                continue
            if len(record) != len(header):
                raise UsageError(f"{path} line {reader.line_num}: {len(record)} values, header has {len(header)}")
            cells = {k: "" for k in SCHEMA}
            cells.update(zip(header, record))
            cells["evidence"] = cells["evidence"].strip()
            out.append(cells)
    except csv.Error as e:
        raise UsageError(f"unreadable CSV in {path}: {e}")
    return out


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".charges-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(str(path), tmp)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_cells(books_dir: Path, incoming: List[Dict[str, str]],
                 write: bool = True) -> Tuple[int, List[Dict[str, str]], int]:
    """The one path that adds rows to the ledger: skip evidence already there, run the full check on
    the ledger as it would be after the append, then write atomically. Returns (exit code, rows
    added or that would be added, rows skipped). Prints the problems and "refused" itself.
    `write=False` runs every step except the write."""
    books = load(books_dir)
    before = run_checks(books)  # the books must be clean before and after
    if before:
        for p in before:
            print(p)
        print("refused, ledger unchanged")
        return 1, [], 0

    seen = {r.cells["evidence"].strip() for r in books.rows}
    fresh: List[Dict[str, str]] = []
    skipped = 0
    for cells in incoming:
        if cells["evidence"] in seen:
            skipped += 1
        else:
            seen.add(cells["evidence"])
            fresh.append(cells)
    if not fresh:
        return 0, [], skipped

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for cells in fresh:
        writer.writerow([cells[k] for k in SCHEMA])
    old = books.ledger_bytes
    candidate = old + (b"" if not old or old.endswith(b"\n") else b"\n") + buf.getvalue().encode("utf-8")

    problems = run_checks(load(books_dir, ledger_override=candidate))
    if problems:
        for p in problems:
            print(p)
        print("refused, ledger unchanged")
        return 1, [], skipped
    if write:
        _write_atomic(books_dir / LEDGER, candidate)
    return 0, fresh, skipped


def cmd_append(args: argparse.Namespace) -> int:
    books_dir = Path(args.books_dir)
    if not books_dir.is_dir():
        print(f"books.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    try:
        incoming = _read_new_rows(Path(args.rows_csv))
    except UsageError as e:
        print(f"books.py: {e}", file=sys.stderr)
        return 2
    code, fresh, skipped = append_cells(books_dir, incoming)
    if code == 0:
        print(f"added {len(fresh)}, skipped {skipped} (evidence already in the ledger)")
    return code


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

CENT = Decimal("0.01")
MONTH_DAYS = Decimal("30.4375")
RENEWAL_WINDOW_DAYS = 30


def _q(d: Decimal) -> Decimal:
    q = d.quantize(CENT, rounding=ROUND_HALF_UP)
    return Decimal("0.00") if q == 0 else q  # no "-0.00"


def _m(d: Decimal) -> str:
    return str(_q(d))


def _yaml_decimal(v: Any) -> Optional[Decimal]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str) and _decimal(v.strip()):
        return Decimal(v.strip())
    return None


def _add(totals: Dict[str, Decimal], key: str, amount: Decimal) -> None:
    totals[key] = totals.get(key, Decimal(0)) + amount


def _money_map(totals: Dict[str, Decimal]) -> Dict[str, str]:
    return {k: _m(totals[k]) for k in sorted(totals)}


def _month_bounds(month: str) -> Tuple[date, date]:
    start = date(int(month[:4]), int(month[5:7]), 1)
    nxt = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def _envelope(books: Books, spent: Decimal) -> Optional[Dict[str, Any]]:
    budgets = books.yaml.get("budgets.yaml")
    env = budgets.get("monthly_envelope") if isinstance(budgets, dict) else None
    usd = _yaml_decimal(env.get("usd")) if isinstance(env, dict) else None
    if usd is None:
        return None
    alerts = budgets.get("alerts")
    warn = alerts.get("envelope_warning_pct") if isinstance(alerts, dict) else None
    warn = warn if isinstance(warn, (int, float)) and not isinstance(warn, bool) else None
    pct = spent / usd * 100 if usd > 0 else None
    return {
        "usd": _m(usd), "status": env.get("status"), "spent": _m(spent),
        "pct": None if pct is None else str(pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
        "warning_pct": warn,
        "over_warning": bool(pct is not None and warn is not None and pct > Decimal(str(warn))),
        "over_envelope": spent > usd,
    }


def _monthly_equivalent(books: Books, first: date, last: date) -> Dict[str, Any]:
    """Run-rate for the month. A subscription renewed in the month has two rows covering it;
    only the latest row per (provider, service) counts, so a monthly plan is not counted twice."""
    latest: Dict[Tuple[str, str], Row] = {}
    for r in books.rows:
        c = r.cells
        if c["charge_type"] != "subscription" or c["status"] != "verified":
            continue
        start = date.fromisoformat(c["period_start"])
        end = date.fromisoformat(c["period_end"]) if c["period_end"] else None
        if start > last or (end is not None and end < first):
            continue
        key = (c["provider"], c["service"])
        rank = (c["period_start"], r.line)
        if key not in latest or rank > (latest[key].cells["period_start"], latest[key].line):
            latest[key] = r
    total = Decimal(0)
    lines: List[Dict[str, Any]] = []
    for key in sorted(latest):
        c = latest[key].cells
        cost = Decimal(c["billed_cost"])
        months = 1
        if c["period_end"]:
            days = (date.fromisoformat(c["period_end"]) - date.fromisoformat(c["period_start"])).days + 1
            months = max(1, int((Decimal(days) / MONTH_DAYS).quantize(Decimal(1), rounding=ROUND_HALF_UP)))
        monthly = cost / months
        total += monthly
        if months >= 2:
            lines.append({"provider": c["provider"], "service": c["service"], "billed_cost": _m(cost),
                          "period_start": c["period_start"], "period_end": c["period_end"],
                          "months": months, "monthly": _m(monthly)})
    return {"total": _m(total), "lines": lines}


def _renewals(books: Books, as_of: date) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    doc = books.yaml.get("renewals.yaml")
    entries = doc.get("renewals") if isinstance(doc, dict) else None
    due: List[Tuple[date, Dict[str, Any]]] = []
    undated: List[Dict[str, Any]] = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        nxt = e.get("next")
        if not (isinstance(nxt, str) and _is_date(nxt)):  # null, or a value we cannot read as a date
            undated.append({"vendor": e.get("vendor"), "plan": e.get("plan")})
            continue
        days = (date.fromisoformat(nxt) - as_of).days
        if 0 <= days <= RENEWAL_WINDOW_DAYS:
            amount = _yaml_decimal(e.get("amount_usd"))
            due.append((date.fromisoformat(nxt), {
                "vendor": e.get("vendor"), "plan": e.get("plan"),
                "amount_usd": None if amount is None else _m(amount),
                "cadence": e.get("cadence"), "next": nxt, "days": days}))
    due.sort(key=lambda t: t[0])
    return [d for _, d in due], undated


def summarize(books: Books, month: str, as_of: date) -> Dict[str, Any]:
    first, last = _month_bounds(month)
    cash_total = Decimal(0)
    by_provider: Dict[str, Decimal] = {}
    by_project: Dict[str, Decimal] = {}
    api_total = Decimal(0)
    api_by_project: Dict[str, Decimal] = {}
    cash_rows = 0
    unknown: List[Dict[str, Any]] = []
    for r in books.rows:
        c = r.cells
        in_month = c["charge_date"].startswith(month)
        if c["status"] == "unknown":
            unknown.append({"line": r.line, "charge_date": c["charge_date"], "provider": c["provider"],
                            "service": c["service"], "evidence": c["evidence"]})
        elif in_month and c["status"] == "verified" and c["charge_type"] != "usage-equivalent":
            amount = Decimal(c["billed_cost"])
            cash_total += amount
            cash_rows += 1
            _add(by_provider, c["provider"], amount)
            _add(by_project, c["project"], amount)
        if in_month and c["api_equivalent_cost"] != "":
            api = Decimal(c["api_equivalent_cost"])
            api_total += api
            _add(api_by_project, c["project"], api)
    renewals, undated = _renewals(books, as_of)
    return {
        "month": month, "as_of": as_of.isoformat(), "currency": "USD",
        "cash": {"total": _m(cash_total), "by_provider": _money_map(by_provider),
                 "by_project": _money_map(by_project), "rows": cash_rows},
        "envelope": _envelope(books, cash_total),
        "monthly_equivalent": _monthly_equivalent(books, first, last),
        "renewals": renewals,
        "renewals_undated": undated,
        "unknown": unknown,
        "api_equivalent": {"total": _m(api_total), "by_project": _money_map(api_by_project)},
    }


def render_summary(s: Dict[str, Any]) -> str:
    out: List[str] = []
    cash = s["cash"]
    out.append(f"Cash for {s['month']}: ${cash['total']} ({cash['rows']} verified rows)")
    out.append("  By provider:")
    out.extend(f"    {k}: ${v}" for k, v in cash["by_provider"].items())
    out.append("  By project:")
    out.extend(f"    {k}: ${v}" for k, v in cash["by_project"].items())
    out.append("")
    e = s["envelope"]
    if e is None:
        out.append("Envelope: none set in budgets.yaml")
    else:
        pct = "n/a" if e["pct"] is None else e["pct"] + "%"
        warn = "no warning level set" if e["warning_pct"] is None else f"warning at {e['warning_pct']}%"
        flags = (", OVER WARNING" if e["over_warning"] else "") + (", OVER ENVELOPE" if e["over_envelope"] else "")
        out.append(f"Envelope: ${e['spent']} of ${e['usd']} ({pct}), {warn}, status {e['status']}{flags}")
    out.append("")
    me = s["monthly_equivalent"]
    out.append(f"Monthly equivalent (run-rate): ${me['total']} a month")
    for ln in me["lines"]:
        out.append(f"  {ln['provider']} {ln['service']}: ${ln['billed_cost']} over {ln['months']} months"
                   f" = ${ln['monthly']} a month ({ln['period_start']} to {ln['period_end']})")
    out.append("")
    out.append(f"Renewals in the next {RENEWAL_WINDOW_DAYS} days (as of {s['as_of']}):")
    if not s["renewals"]:
        out.append("  none")
    for r in s["renewals"]:
        amount = "unknown amount" if r["amount_usd"] is None else f"${r['amount_usd']}"
        out.append(f"  {r['next']} (in {r['days']} days): {r['vendor']} {r['plan']}, {amount}, {r['cadence']}")
    for r in s["renewals_undated"]:
        out.append(f"  no date: {r['vendor']} {r['plan']}")
    out.append("")
    out.append("Unknown amounts (open until resolved):")
    if not s["unknown"]:
        out.append("  none")
    for u in s["unknown"]:
        out.append(f"  ledger line {u['line']}: {u['charge_date']} {u['provider']} {u['service']} ({u['evidence']})")
    out.append("")
    api = s["api_equivalent"]
    out.append(f"API-equivalent for {s['month']} (not cash): ${api['total']}")
    out.extend(f"  {k}: ${v}" for k, v in api["by_project"].items())
    return "\n".join(out)


def cmd_summary(args: argparse.Namespace) -> int:
    books_dir = Path(args.books_dir)
    if not books_dir.is_dir():
        print(f"books.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
        print(f"books.py: --month must look like 2026-10, got {args.month!r}", file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = date.today()
    elif _is_date(args.as_of):
        as_of = date.fromisoformat(args.as_of)
    else:
        print(f"books.py: --as-of must look like 2026-10-31, got {args.as_of!r}", file=sys.stderr)
        return 2
    books = load(books_dir)
    problems = run_checks(books)
    if problems:
        for p in problems:
            print(p)
        print(f"{len(problems)} problems; no summary from unchecked books")
        return 1
    result = summarize(books, args.month, as_of)
    print(json.dumps(result, indent=2) if args.json else render_summary(result))
    return 0


# ---------------------------------------------------------------------------
# claude-code: price local Claude Code session logs at API rates
# ---------------------------------------------------------------------------

PRICING_FILE = Path(__file__).resolve().parent / "pricing.json"
PRICE_KINDS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")
MILLION = Decimal(1000000)
UNASSIGNED = "unassigned"


@dataclass(frozen=True)
class Pricing:
    source: str
    as_of: str
    models: Dict[str, Dict[str, Decimal]]  # model id -> kind -> USD per million tokens
    fast_multiplier: Dict[str, Decimal]    # only models with a documented fast-mode price


def load_pricing(path: Path) -> Pricing:
    try:
        doc = json.loads(path.read_text())
        models: Dict[str, Dict[str, Decimal]] = {}
        fast: Dict[str, Decimal] = {}
        for model, entry in doc["models"].items():
            models[model] = {k: Decimal(str(entry[k])) for k in PRICE_KINDS}
            if "fast_multiplier" in entry:
                fast[model] = Decimal(str(entry["fast_multiplier"]))
        if not _is_date(doc["as_of"]):
            raise ValueError("as_of is not a YYYY-MM-DD date")
        return Pricing(str(doc["source"]), doc["as_of"], models, fast)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as e:
        raise UsageError(f"cannot use {path.name}: {type(e).__name__}: {e}")


@dataclass
class Tokens:
    input: int = 0
    output: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0

    def add(self, other: "Tokens") -> None:
        for k in PRICE_KINDS:
            setattr(self, k, getattr(self, k) + getattr(other, k))

    def as_dict(self) -> Dict[str, int]:
        return {k: getattr(self, k) for k in PRICE_KINDS}


@dataclass(frozen=True)
class Message:
    model: str
    day: date  # UTC
    cwd: str
    speed: str
    tokens: Tokens


def _int(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _message(d: Any) -> Optional[Tuple[Tuple[str, Optional[str]], Message]]:
    """The few fields the pricing needs, or None for a line that is not a priced assistant message.
    Nothing else in the line is read, so no prompt or tool text can leave this function."""
    msg = d.get("message") if isinstance(d, dict) else None
    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
        return None
    usage = msg["usage"]
    mid, model, ts = msg.get("id"), msg.get("model"), d.get("timestamp")
    if not (isinstance(mid, str) and isinstance(model, str) and isinstance(ts, str)) or model == "<synthetic>":
        return None
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    split = usage.get("cache_creation")
    w5 = w1 = 0
    if isinstance(split, dict):
        w5, w1 = _int(split.get("ephemeral_5m_input_tokens")), _int(split.get("ephemeral_1h_input_tokens"))
    w5 += max(0, _int(usage.get("cache_creation_input_tokens")) - w5 - w1)  # unsplit writes price as 5m
    tokens = Tokens(_int(usage.get("input_tokens")), _int(usage.get("output_tokens")), w5, w1,
                    _int(usage.get("cache_read_input_tokens")))
    cwd = d.get("cwd") if isinstance(d.get("cwd"), str) else ""
    speed = usage.get("speed") if isinstance(usage.get("speed"), str) else "standard"
    request = d.get("requestId") if isinstance(d.get("requestId"), str) else None
    return (mid, request), Message(model, when.date(), cwd, speed, tokens)


def read_logs(logs: Path) -> Tuple[List[Message], int]:
    """Unique messages under `logs` and the number of duplicate lines dropped. The same message is
    written on several lines; of a repeated (message id, request id) the line with the most output
    tokens wins, because a streamed message's early lines are partial."""
    unique: Dict[Tuple[str, Optional[str]], Message] = {}
    duplicates = 0
    for path in sorted(logs.glob("**/*.jsonl")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        found = _message(json.loads(line))
                    except ValueError:
                        continue
                    if found is None:
                        continue
                    key, m = found
                    if key in unique:
                        duplicates += 1
                        if m.tokens.output <= unique[key].tokens.output:
                            continue
                    unique[key] = m
        except OSError:
            continue
    return list(unique.values()), duplicates


def project_paths(books: Books) -> List[Tuple[str, str]]:
    """(directory, project) pairs from the `paths:` lists in projects.yaml, longest directory first."""
    doc = books.yaml.get("projects.yaml")
    projects = doc.get("projects") if isinstance(doc, dict) else None
    pairs: List[Tuple[str, str]] = []
    for name, entry in (projects.items() if isinstance(projects, dict) else []):
        for p in entry.get("paths") or [] if isinstance(entry, dict) else []:
            pairs.append((os.path.normpath(os.path.expanduser(p)), name))
    return sorted(pairs, key=lambda t: (-len(t[0]), t[1]))


def project_for(cwd: str, pairs: List[Tuple[str, str]]) -> str:
    cwd = os.path.normpath(cwd) if cwd else ""
    for path, name in pairs:
        if cwd == path or cwd.startswith(path.rstrip("/") + "/"):
            return name
    return UNASSIGNED


def price(m: Message, pricing: Pricing) -> Decimal:
    p = pricing.models[m.model]
    cost = sum((Decimal(getattr(m.tokens, k)) * p[k] for k in PRICE_KINDS), Decimal(0)) / MILLION
    if m.speed == "fast" and m.model in pricing.fast_multiplier:
        cost *= pricing.fast_multiplier[m.model]
    return cost


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week(monday: date) -> str:
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def price_weeks(messages: List[Message], pricing: Pricing, pairs: List[Tuple[str, str]],
                first: date, until: date) -> Dict[str, Any]:
    """Cost per (week, project) for whole weeks that start on or after `first` and end before `until`."""
    cells: Dict[Tuple[date, str], Dict[str, Any]] = {}
    unpriced: Dict[str, Tokens] = {}
    counted = outside = 0
    speeds: Dict[str, int] = {}
    fast_at_standard = 0
    for m in messages:
        monday = _monday(m.day)
        if monday < first or monday + timedelta(days=6) >= until:
            outside += 1
            continue
        counted += 1
        speeds[m.speed] = speeds.get(m.speed, 0) + 1
        if m.model not in pricing.models:
            unpriced.setdefault(m.model, Tokens()).add(m.tokens)
            continue
        if m.speed != "standard" and m.model not in pricing.fast_multiplier:
            fast_at_standard += 1
        cell = cells.setdefault((monday, project_for(m.cwd, pairs)), {"tokens": Tokens(), "cost": Decimal(0)})
        cell["tokens"].add(m.tokens)
        cell["cost"] += price(m, pricing)
    return {"cells": cells, "unpriced": unpriced, "counted": counted, "outside": outside,
            "speeds": speeds, "nonstandard_at_standard_price": fast_at_standard}


def claude_code_rows(cells: Dict[Tuple[date, str], Dict[str, Any]]) -> List[Dict[str, str]]:
    rows = []
    for (monday, project), cell in sorted(cells.items()):
        sunday = monday + timedelta(days=6)
        row = {k: "" for k in SCHEMA}
        row.update(charge_date=sunday.isoformat(), period_start=monday.isoformat(), period_end=sunday.isoformat(),
                   provider="Anthropic", service="Claude Code (API-equivalent)", charge_type="usage-equivalent",
                   billed_cost="0", currency="USD", api_equivalent_cost=str(_q(cell["cost"])), project=project,
                   status="verified", source="claude-code-logs", evidence=f"claude-code:{_week(monday)}:{project}")
        rows.append(row)
    return rows


def cmd_claude_code(args: argparse.Namespace) -> int:
    books_dir = Path(args.books_dir)
    if not books_dir.is_dir():
        print(f"books.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    until = date.today() if args.until is None else None
    for flag, value in (("--since", args.since), ("--until", args.until)):
        if value is not None and not _is_date(value):
            print(f"books.py: {flag} must look like 2026-10-19, got {value!r}", file=sys.stderr)
            return 2
    if args.until is not None:
        until = date.fromisoformat(args.until)
    first = _monday(date.fromisoformat(args.since))
    logs = Path(os.path.expanduser(args.logs))
    if not logs.is_dir():
        print(f"books.py: not a directory: {args.logs}", file=sys.stderr)
        return 2
    try:
        pricing = load_pricing(PRICING_FILE)
    except UsageError as e:
        print(f"books.py: {e}", file=sys.stderr)
        return 2

    books = load(books_dir)
    problems = run_checks(books)
    if problems:
        for p in problems:
            print(p)
        print(f"{len(problems)} problems; no Claude Code rows from unchecked books")
        return 1

    messages, duplicates = read_logs(logs)
    result = price_weeks(messages, pricing, project_paths(books), first, until)
    rows = claude_code_rows(result["cells"])
    code, fresh, skipped = append_cells(books_dir, rows, write=not args.dry_run)
    if code != 0:
        return code

    weeks = sorted({monday for monday, _ in result["cells"]})
    summary = {
        "weeks": [_week(w) for w in weeks], "messages_counted": result["counted"],
        "duplicates_dropped": duplicates, "messages_outside_weeks": result["outside"],
        "unpriced_models": {k: v.as_dict() for k, v in sorted(result["unpriced"].items())},
        "speeds": dict(sorted(result["speeds"].items())),
        "nonstandard_speed_priced_at_standard": result["nonstandard_at_standard_price"],
        "pricing_as_of": pricing.as_of, "dry_run": bool(args.dry_run),
        "totals": [{"week": _week(monday), "project": project, "tokens": cell["tokens"].as_dict(),
                    "api_equivalent_cost": str(_q(cell["cost"]))}
                   for (monday, project), cell in sorted(result["cells"].items())],
        "rows_added": len(fresh), "rows_skipped": skipped, "rows": fresh,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    print(render_claude_code(summary))
    return 0


def render_claude_code(s: Dict[str, Any]) -> str:
    out = [f"Claude Code API-equivalent cost (not cash), pricing as of {s['pricing_as_of']}",
           "Weeks covered: " + (", ".join(s["weeks"]) if s["weeks"] else "none (no complete week with priced usage)")]
    for t in s["totals"]:
        k = t["tokens"]
        out.append(f"  {t['week']} {t['project']}: ${t['api_equivalent_cost']}  (input {k['input']}, output {k['output']},"
                   f" cache write 5m {k['cache_write_5m']}, cache write 1h {k['cache_write_1h']}, cache read {k['cache_read']})")
    out.append(f"Messages counted after dedupe: {s['messages_counted']}; duplicates dropped: {s['duplicates_dropped']};"
               f" messages outside the weeks: {s['messages_outside_weeks']}")
    if s["unpriced_models"]:
        out.append("Unpriced models (tokens listed, cost EXCLUDED from every total above):")
        for model, k in s["unpriced_models"].items():
            out.append(f"  {model}: input {k['input']}, output {k['output']}, cache write 5m {k['cache_write_5m']},"
                       f" cache write 1h {k['cache_write_1h']}, cache read {k['cache_read']}")
    else:
        out.append("Unpriced models: none")
    speeds = ", ".join(f"{k} {v}" for k, v in s["speeds"].items()) or "none"
    out.append(f"Speed of counted messages: {speeds}; non-standard speed priced at standard rates:"
               f" {s['nonstandard_speed_priced_at_standard']}")
    verb = "would add" if s["dry_run"] else "added"
    out.append(f"Rows {verb}: {s['rows_added']}, skipped: {s['rows_skipped']} (evidence already in the ledger)")
    if s["dry_run"] and s["rows"]:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in s["rows"]:
            w.writerow([r[k] for k in SCHEMA])
        out.append(",".join(SCHEMA))
        out.append(buf.getvalue().rstrip("\n"))
    return "\n".join(out)


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
    if args.today is None:
        today = date.today()
    elif _is_date(args.today):
        today = date.fromisoformat(args.today)
    else:
        print(f"books.py: --today must look like 2026-10-31, got {args.today!r}", file=sys.stderr)
        return 2
    warnings = run_warnings(books, today)
    for p in problems:
        print(p)
    for w in warnings:
        print(w)
    if problems:
        print(f"{len(problems)} problems" + (f", {len(warnings)} warning{'s' * (len(warnings) != 1)}" if warnings else ""))
        return 1
    note = f", {len(warnings)} warning{'s' * (len(warnings) != 1)}" if warnings else ""
    print(f"ok, {len(books.rows)} rows, 0 problems{note}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="books.py", description="Work with the CFO's books.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate the books")
    check.add_argument("books_dir", metavar="BOOKS_DIR")
    check.add_argument("--base", metavar="REF", help="fail if a ledger line at REF changed or was removed")
    check.add_argument("--today", metavar="YYYY-MM-DD", help=argparse.SUPPRESS)  # tests fix the date
    check.set_defaults(func=cmd_check)
    append = sub.add_parser("append", help="add ledger rows that are not already there, if the result passes check")
    append.add_argument("books_dir", metavar="BOOKS_DIR")
    append.add_argument("rows_csv", metavar="ROWS_CSV")
    append.set_defaults(func=cmd_append)
    summary = sub.add_parser("summary", help="report one month: cash, envelope, run-rate, renewals, unknowns")
    summary.add_argument("books_dir", metavar="BOOKS_DIR")
    summary.add_argument("--month", required=True, metavar="YYYY-MM")
    summary.add_argument("--as-of", metavar="YYYY-MM-DD", help="today by default; fixes the renewals window")
    summary.add_argument("--json", action="store_true")
    summary.set_defaults(func=cmd_summary)
    cc = sub.add_parser("claude-code", help="price local Claude Code usage at API rates, one row per project per ISO week")
    cc.add_argument("books_dir", metavar="BOOKS_DIR")
    cc.add_argument("--since", required=True, metavar="YYYY-MM-DD", help="rounded down to its Monday")
    cc.add_argument("--logs", default="~/.claude/projects", metavar="DIR")
    cc.add_argument("--until", metavar="YYYY-MM-DD", help="today by default; only weeks ending before it are written")
    cc.add_argument("--dry-run", action="store_true", help="print totals and the rows, write nothing")
    cc.add_argument("--json", action="store_true")
    cc.set_defaults(func=cmd_claude_code)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
