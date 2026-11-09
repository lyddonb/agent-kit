#!/usr/bin/env python3
"""Check a state machine spec written in the state-machines skill's Markdown format.

Usage:
    python3 check-machine.py MACHINE.md              # check; print problems
    python3 check-machine.py MACHINE.md --mermaid    # also print a Mermaid stateDiagram
    python3 check-machine.py MACHINE.md --matrix     # also print the state x event grid
    python3 check-machine.py MACHINE.md --json       # print the parsed machine as JSON (for table-driven tests)

Problems go to stderr as `file:line: problem`. Exit 0 when clean, 1 with problems, 2 on bad usage.
Format: see ../references/spec-format.md.

Parsing and checking are pure functions of the text; main() is the only part that does IO.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

IGNORE = "(ignore)"
IMPOSSIBLE = "(impossible)"
NON_MOVES = {IGNORE, IMPOSSIBLE}
WILDCARD = "*"
REQUIRED_SECTIONS = ["Invariants", "Interruptions", "Assumptions"]

LIST_LINE = re.compile(r"^(states|events|initial|final):\s*(.*)$")
ROW = re.compile(r"^\|(.+)\|\s*$")
SEPARATOR = re.compile(r"^\|[\s:|-]+\|\s*$")
GUARD = re.compile(r"^(.*?)\s*\[(.+)\]\s*$")
SECTION = re.compile(r"^##\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*[-*]\s+(.+)$")
CODE = re.compile(r"`([^`]+)`")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class Row:
    line: int
    state: str
    event: str
    target: str  # a state name, IGNORE or IMPOSSIBLE
    guard: str | None
    note: str


@dataclass
class Machine:
    name: str = ""
    states: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    initial: str = ""
    final: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    sections: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    decl_lines: dict[str, int] = field(default_factory=dict)


def split_names(raw: str) -> list[str]:
    return [n.strip().strip("`") for n in re.split(r"[,\s]+", raw) if n.strip().strip("`")]


def cells_of(line: str) -> list[str]:
    """Split a table row on unescaped pipes; `\\|` stays a literal pipe inside a cell."""
    parts = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.replace("\\|", "|").strip() for c in parts]


def parse(text: str) -> tuple[Machine, list[tuple[int, str]]]:
    """Parse the spec. Returns the machine and the syntax problems found while parsing.

    The transition table is the table whose header starts | state | event | next |, wherever it
    sits. Other tables are skipped. Declarations are only read before the first `##` heading.
    """
    m = Machine()
    problems: list[tuple[int, str]] = []
    section: str | None = None
    table: str | None = None  # None outside a table, "transitions" or "other" inside one
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not ROW.match(line):
            table = None
        if line.startswith("# ") and not m.name:
            m.name = line[2:].replace("Machine:", "").strip()
            continue
        if (s := SECTION.match(line)):
            section = s.group(1)
            m.sections.setdefault(section, [])
            continue
        if section is None and (d := LIST_LINE.match(line)):
            key, value = d.group(1), d.group(2)
            if key in m.decl_lines:
                problems.append((n, f"`{key}:` declared twice (first on line {m.decl_lines[key]})"))
                continue
            m.decl_lines[key] = n
            names = split_names(value)
            if key == "initial":
                if len(names) != 1:
                    problems.append((n, "initial: names exactly one state"))
                m.initial = names[0] if names else ""
            else:
                setattr(m, key, names)
            continue
        if ROW.match(line):
            if SEPARATOR.match(line):
                continue
            cells = cells_of(line)
            if table is None:
                is_transitions = [c.lower() for c in cells[:3]] == ["state", "event", "next"]
                if is_transitions and m.rows:
                    problems.append((n, "a second transition table; keep one table per machine"))
                table = "transitions" if is_transitions else "other"
                continue
            if table == "other":
                continue
            if len(cells) < 3:
                problems.append((n, "transition row needs state, event and next"))
                continue
            state, event, nxt = (c.strip("`") for c in cells[:3])
            note = cells[3] if len(cells) > 3 else ""
            guard = None
            if (g := GUARD.match(nxt)):
                nxt, guard = g.group(1).strip().strip("`"), g.group(2).strip()
            m.rows.append(Row(n, state, event, nxt, guard, note))
            continue
        if section is not None and (b := BULLET.match(line)):
            m.sections[section].append((n, b.group(1)))
    return m, problems


def reachable(m: Machine) -> set[str]:
    edges: dict[str, set[str]] = {}
    for r in m.rows:
        if r.target not in NON_MOVES:
            edges.setdefault(r.state, set()).add(r.target)
    seen, todo = set(), [m.initial]
    while todo:
        s = todo.pop()
        if s in seen:
            continue
        seen.add(s)
        todo.extend(edges.get(s, ()))
    return seen


def check(m: Machine) -> list[tuple[int, str]]:
    """Every semantic problem with the machine, as (line, message). Pure."""
    out: list[tuple[int, str]] = []
    states, events = set(m.states), set(m.events)
    top = m.decl_lines

    for key in ("states", "events", "initial"):
        if key not in top:
            out.append((1, f"missing `{key}:` declaration"))
    if not m.rows:
        out.append((1, "no transition table: add one whose header starts | state | event | next |"))
    for kind, names in (("state", m.states), ("event", m.events)):
        for name in names:
            if not IDENT.match(name):
                out.append((top.get(kind + "s", 1), f"{kind} `{name}` is not a plain identifier"))
        dupes = {x for x in names if names.count(x) > 1}
        for d in sorted(dupes):
            out.append((top.get(kind + "s", 1), f"{kind} `{d}` declared twice"))
    if m.initial and m.initial not in states:
        out.append((top.get("initial", 1), f"initial state `{m.initial}` is not declared"))
    for f in m.final:
        if f not in states:
            out.append((top.get("final", 1), f"final state `{f}` is not declared"))

    cells: dict[tuple[str, str], list[Row]] = {}
    for r in m.rows:
        if r.state not in states:
            out.append((r.line, f"state `{r.state}` is not declared"))
            continue
        if r.event != WILDCARD and r.event not in events:
            out.append((r.line, f"event `{r.event}` is not declared"))
            continue
        if r.target not in NON_MOVES and r.target not in states:
            out.append((r.line, f"next `{r.target}` is neither a declared state, {IGNORE} nor {IMPOSSIBLE}"))
            continue
        if r.event == WILDCARD:
            if r.target not in NON_MOVES:
                out.append((r.line, f"`*` rows may only say {IGNORE} or {IMPOSSIBLE}; name each real transition"))
            if not r.note:
                out.append((r.line, "`*` row needs a note saying why every remaining event is safe to skip"))
        if r.state in m.final and r.target not in NON_MOVES:
            out.append((r.line, f"final state `{r.state}` has an outgoing transition on `{r.event}`"))
        if r.target == IMPOSSIBLE and not r.note:
            out.append((r.line, f"{IMPOSSIBLE} needs a note naming what prevents `{r.event}` in `{r.state}`"))
        cells.setdefault((r.state, r.event), []).append(r)

    for (state, event), rows in cells.items():
        if len(rows) > 1:
            unguarded = [r for r in rows if r.guard is None]
            if unguarded:
                out.append((rows[0].line, f"`{state}` + `{event}` has {len(rows)} rows but "
                            f"{len(unguarded)} without a [guard]: the machine is nondeterministic"))
            elif not any(r.guard.lower() == "else" for r in rows):
                out.append((rows[0].line, f"`{state}` + `{event}` is guarded but has no [else] row: "
                            "say what happens when no guard holds"))
            guards = [r.guard for r in rows if r.guard]
            for g in {g for g in guards if guards.count(g) > 1}:
                out.append((rows[0].line, f"`{state}` + `{event}` repeats guard [{g}]"))

    # Completeness: every state x event cell is a decision someone made.
    covered_by_wildcard = {r.state for r in m.rows if r.event == WILDCARD}
    for s in m.states:
        if s in covered_by_wildcard:
            continue
        missing = [e for e in m.events if (s, e) not in cells]
        if missing:
            line = min((r.line for r in m.rows if r.state == s), default=top.get("states", 1))
            out.append((line, f"`{s}` has no decision for: {', '.join(f'`{e}`' for e in missing)} "
                        f"(add a row: next state, {IGNORE} or {IMPOSSIBLE})"))

    if m.initial in states:
        unreachable = [s for s in m.states if s not in reachable(m)]
        for s in unreachable:
            out.append((top.get("states", 1), f"`{s}` is unreachable from `{m.initial}`"))
    for s in m.states:
        if s in m.final:
            continue
        exits = [r for r in m.rows if r.state == s and r.target not in NON_MOVES and r.target != s]
        if not exits:
            out.append((top.get("states", 1), f"`{s}` is not final but nothing leaves it (a trap state); "
                        "add an exit or list it in `final:`"))

    for name in REQUIRED_SECTIONS:
        items = m.sections.get(name)
        if not items:
            out.append((1, f"`## {name}` section is missing or has no bullets"))
    for line, text in m.sections.get("Data", []):
        named = CODE.findall(text)
        if not named or named[0] not in states:
            out.append((line, "a `## Data` bullet starts with a declared state in backticks, then its fields"))
    for line, text in m.sections.get("Interruptions", []):
        named = [c for c in CODE.findall(text) if c in events]
        if not named:
            out.append((line, "interruption names no declared event in backticks; model it as an event "
                        "so the table must decide it in every state"))
    return sorted(out)


def mermaid(m: Machine) -> str:
    """Moves between different states only; self-loops and non-moves live in the matrix."""
    lines = ["stateDiagram-v2", f"    [*] --> {m.initial}"]
    for r in m.rows:
        if r.target in NON_MOVES or r.target == r.state:
            continue
        label = r.event + (f" [{r.guard}]" if r.guard else "")
        lines.append(f"    {r.state} --> {r.target}: {label}")
    lines += [f"    {f} --> [*]" for f in m.final]
    return "\n".join(lines)


def matrix(m: Machine) -> str:
    def cell(s: str, e: str) -> str:
        rows = [r for r in m.rows if r.state == s and r.event == e]
        if not rows:
            rows = [r for r in m.rows if r.state == s and r.event == WILDCARD]
        if not rows:
            return "??"
        return " / ".join(r.target + (f" [{r.guard}]" if r.guard else "") for r in rows)
    head = "| state \\ event | " + " | ".join(m.events) + " |"
    sep = "|---" * (len(m.events) + 1) + "|"
    body = ["| " + s + " | " + " | ".join(cell(s, e) for e in m.events) + " |" for s in m.states]
    return "\n".join([head, sep, *body])


def to_json(m: Machine) -> str:
    return json.dumps({
        "name": m.name, "initial": m.initial, "final": m.final,
        "states": m.states, "events": m.events,
        "transitions": [{"state": r.state, "event": r.event, "next": r.target,
                         "guard": r.guard, "note": r.note} for r in m.rows],
    }, indent=2)


def main(argv: list[str]) -> int:
    flags = {a for a in argv[1:] if a.startswith("--")}
    paths = [a for a in argv[1:] if not a.startswith("--")]
    if len(paths) != 1 or flags - {"--mermaid", "--matrix", "--json"}:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(paths[0])
    m, syntax = parse(path.read_text())
    problems = sorted(syntax + check(m))
    if "--json" in flags:
        print(to_json(m))
    if "--matrix" in flags:
        print(matrix(m))
    if "--mermaid" in flags:
        print(mermaid(m))
    for line, msg in problems:
        print(f"{path}:{line}: {msg}", file=sys.stderr)
    print(f"{m.name or path.name}: {len(m.states)} states, {len(m.events)} events, "
          f"{len(m.rows)} rows, {len(problems)} problem(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
