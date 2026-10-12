#!/usr/bin/env python3
"""Check a plan written with beau-mode's Multi-phase plan playbook.

Usage:
    python3 check-plan.py PLAN.md

Prints one summary line per PR section, then one `file:line: problem` line per problem on stderr.
Exit code 0 when the plan has no problems, 1 when it has some, 2 on bad usage.

Ported from pstack's check-plan.mjs (MIT, Lauren Tan) and adapted to the tool-neutral skeleton:
the live block names its lane count and verification skill, and a perf block may say
"Not perf-sensitive." with a reason instead of the four perf boxes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RULE = ("Tests alone are not sufficient verification. A PR is verified only when its unit, live, "
        "and perf boxes are all checked.")
SUB_BLOCKS = ["Depends on.", "Files.", "Build.", "You see.", "Verify, unit.", "Verify, live.",
              "Verify, perf.", "Review gate.", "Merge."]
PROGRAM_H3 = ["Before you start", "Order and boundaries", "For every PR"]
HOW_TO_READ_MARKERS = ["One box is one unit of work", "names the evidence",
                       "Check a box only when its evidence exists", "playbook", RULE]
PERF_ITEMS = ["Metric.", "Probe.", "Baseline.", "Rule."]
LANES = re.compile(r"(\d+) lanes at the PR head through `[^`<>]+`")
BOX = re.compile(r"^\s*- \[[ xX]\] (.*)$")
PLACEHOLDER = re.compile(r"<[A-Za-z][^<>]*>")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
MIN_LANES, MAX_LANES = 3, 10


class Line:
    def __init__(self, n: int, text: str, code: bool):
        self.n, self.text, self.code = n, text, code


def prose_of(text: str) -> str:
    text = re.sub(r"`[^`]*`", "`", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    return re.sub(r"\]\([^)]*\)", "]", text)


def boxes(lines: list[Line]) -> list[tuple[int, str]]:
    out = []
    for l in lines:
        m = None if l.code else BOX.match(l.text)
        if m:
            out.append((l.n, m.group(1)))
    return out


def check(path: Path) -> tuple[list[str], list[str]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    problems: list[str] = []

    def fail(n: int, msg: str) -> None:
        problems.append(f"{path}:{n}: {msg}")

    start = 0
    if raw and raw[0] == "---":
        try:
            start = raw.index("---", 1) + 1
        except ValueError:
            fail(1, "front matter never closes")

    lines: list[Line] = []
    fence = ""   # the marker that opened the current fenced block, or "" outside one
    for i in range(start, len(raw)):
        text, n = raw[i], i + 1
        m = FENCE.match(text)
        is_fence = bool(m) and (not fence or (m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)))
        if is_fence:
            fence = "" if fence else m.group(1)
        lines.append(Line(n, text, bool(fence) or is_fence))
        if fence or is_fence:
            continue
        prose = prose_of(text)
        if re.search("[–—]", prose):
            fail(n, "long dash")
        if re.search("[‘’“”]", prose):
            fail(n, "curly quote")
        if re.search(r": \S", prose):
            fail(n, "mid-sentence colon")
        if PLACEHOLDER.search(prose):
            fail(n, f"unfilled placeholder {PLACEHOLDER.search(prose).group(0)}")

    sections: list[dict] = []
    for l in lines:
        if not l.code and l.text.startswith("## "):
            sections.append({"title": l.text[3:].strip(), "n": l.n, "body": []})
        elif sections:
            sections[-1]["body"].append(l)

    def find(title: str):
        return next((s for s in sections if s["title"] == title), None)

    def body_text(s) -> str:
        return "\n".join(l.text for l in s["body"])

    h1 = next((i for i, l in enumerate(lines) if not l.code and l.text.startswith("# ")), None)
    if h1 is None:
        fail(1, "no H1 title")
    how = find("How to read this")
    if not how:
        fail(1, 'no "## How to read this" section')
    if h1 is not None and how:
        intro = [l for l in lines[h1 + 1:] if l.n < how["n"] and l.text.strip()]
        if len(intro) >= 10:
            fail(lines[h1].n, f"intro is {len(intro)} lines, under ten required")
        for marker in HOW_TO_READ_MARKERS:
            if marker not in body_text(how):
                fail(how["n"], f'How to read this lacks "{marker}"')

    program = find("Program checklist")
    if not program:
        fail(1, 'no "## Program checklist" section')
    else:
        h3s = [l.text[4:].strip() for l in program["body"] if not l.code and l.text.startswith("### ")]
        cursor = 0
        for name in PROGRAM_H3:
            at = next((i for i in range(cursor, len(h3s)) if h3s[i].startswith(name)), None)
            if at is None:
                fail(program["n"], f'Program checklist lacks "### {name}" in order')
            else:
                cursor = at + 1

    close = find("Close the program")
    if not close:
        fail(1, 'no "## Close the program" section')
    # When an anchor is missing, still check the PR sections around it so one missing heading
    # doesn't hide every other problem.
    known = {"How to read this", "Program checklist", "Close the program"}
    first_appendix = next((i for i, s in enumerate(sections) if s["title"].startswith("Appendix")), len(sections))
    pi = sections.index(program) if program else -1
    ci = sections.index(close) if close else -1
    lo = pi + 1 if pi != -1 else 0
    hi = ci if ci != -1 else first_appendix
    prs = [s for s in sections[lo:hi] if s["title"] not in known]
    if not prs and program and close:
        fail(1, "no PR sections between Program checklist and Close the program")

    report = []
    for pr in prs:
        title = pr["title"]
        heads: list[dict] = []
        for l in pr["body"]:
            if l.code:
                continue
            m = re.match(r"^\*\*([^*]+)\*\*(.*)$", l.text)
            if m and m.group(1) in SUB_BLOCKS:
                heads.append({"name": m.group(1), "n": l.n, "rest": m.group(2).strip(), "lines": []})
            elif heads:
                heads[-1]["lines"].append(l)
        names = [h["name"] for h in heads]
        if names != SUB_BLOCKS:
            fail(pr["n"], f"{title}: sub-blocks are [{', '.join(names)}], expected [{', '.join(SUB_BLOCKS)}]")
        block = {h["name"]: h for h in heads}
        counts = {h["name"]: len(boxes(h["lines"])) for h in heads}

        dep = block.get("Depends on.")
        if dep and not dep["rest"]:
            fail(dep["n"], f"{title}: Depends on names nothing")
        for name in ["Files.", "Build.", "You see.", "Verify, unit.", "Merge."]:
            b = block.get(name)
            if b and not boxes(b["lines"]):
                fail(b["n"], f"{title}: {name} has no box")
        for name in ["Verify, unit.", "Verify, live.", "Verify, perf."]:
            b = block.get(name)
            if b and not b["rest"].startswith(RULE):
                fail(b["n"], f"{title}: {name} does not open with the rule")

        live = block.get("Verify, live.")
        if live:
            m = LANES.search(live["rest"])
            if not m:
                fail(live["n"], f"{title}: Verify, live lacks \"<N> lanes at the PR head through `<verification skill>`\"")
            lanes = [(n, t, re.match(r"^Lane (\d+)\. ", t)) for n, t in boxes(live["lines"])]
            numbers = sorted(int(x.group(1)) for _, _, x in lanes if x)
            if m and not MIN_LANES <= int(m.group(1)) <= MAX_LANES:
                fail(live["n"], f"{title}: {m.group(1)} lanes, expected {MIN_LANES} to {MAX_LANES}")
            want = list(range(1, (int(m.group(1)) if m else len(numbers)) + 1))
            if not numbers or numbers != want:
                fail(live["n"], f"{title}: lanes are {numbers}, expected 1 to {len(want) or 'N'}")
            for n, text, lm in lanes:
                if not lm:
                    fail(n, f"{title}: live box is not a lane")
                elif not re.search(r"Save `[^`]+`", text):
                    fail(n, f"{title}: lane {lm.group(1)} names no screenshot or transcript")
                elif "Pass when" not in text:
                    fail(n, f"{title}: lane {lm.group(1)} has no pass predicate")
                if lm and lm.group(1) == "1" and "Regression lane against trunk" not in text:
                    fail(n, f"{title}: lane 1 is not the regression lane against trunk")

        perf = block.get("Verify, perf.")
        if perf:
            items = [t.split(" ")[0] for _, t in boxes(perf["lines"])]
            exempt = perf["rest"][len(RULE):].strip().startswith("Not perf-sensitive.")
            if exempt:
                if items:
                    fail(perf["n"], f"{title}: perf says Not perf-sensitive but has boxes")
                elif perf["rest"][len(RULE):].strip() == "Not perf-sensitive.":
                    fail(perf["n"], f"{title}: Not perf-sensitive needs a reason")
            elif items != PERF_ITEMS:
                fail(perf["n"], f"{title}: perf boxes are [{', '.join(items)}], expected [{', '.join(PERF_ITEMS)}] or Not perf-sensitive")

        gate = block.get("Review gate.")
        if gate:
            gb = boxes(gate["lines"])
            if gate["rest"].startswith("None."):
                if gb:
                    fail(gate["n"], f"{title}: Review gate says None but has boxes")
            else:
                text = "\n".join(l.text for l in gate["lines"]).lower()
                if not gb:
                    fail(gate["n"], f"{title}: Review gate has no box")
                for word in ["screenshot", "video", "human"]:
                    if word not in text:
                        fail(gate["n"], f'{title}: Review gate lacks "{word}"')

        total = len(boxes(pr["body"]))
        cells = " ".join(f"{re.sub(r'[ ,.]+', '-', s).strip('-').lower()}={counts.get(s, 0)}"
                         for s in SUB_BLOCKS if s != "Depends on.")
        report.append(f"{title}  boxes={total}  {cells}")

    if ci != -1:
        tail = sections[ci + 1:]
        for s in tail:
            if not s["title"].startswith("Appendix"):
                fail(s["n"], f'"## {s["title"]}" after Close the program is not an appendix')
        if not any("Prototype evidence" in s["title"] for s in tail):
            fail(close["n"], 'no "## Appendix ... Prototype evidence" section')

    report.append(f"{len(prs)} PR sections, {len(problems)} problems")
    return report, problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python3 check-plan.py PLAN.md", file=sys.stderr)
        return 2
    report, problems = check(Path(argv[1]))
    for line in report:
        print(line)
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
