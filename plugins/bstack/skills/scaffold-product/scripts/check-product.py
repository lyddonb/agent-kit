#!/usr/bin/env python3
"""Check that a repo follows the product layout from bstack's scaffold-product skill.

Usage:
    python3 check-product.py [REPO_DIR] [--base REF] [--receipts RUN_ID]

Prints one `file:line: problem` line per problem on stderr and a summary on stdout.
Exit code 0 when there are no problems, 1 when there are some, 2 on bad usage.
A `note: file:line: ...` line on stderr is not a problem and never changes the exit code: it names
a format this checker will hold the repo to once the repo adopts it.

With --receipts RUN_ID, every box this branch newly checked (`- [x]` in a phase spec now, not
`[x]` in the same file at REF, default origin/main) must be backed by a receipt: the run's last
`verification` entry for that criterion in .audit/runs/RUN_ID/ledger.jsonl (written by
verify-work's receipt.py) says VERIFIED, names this spec, hashes to the spec at its commit, and
the criterion's own text is unchanged since that commit, and no source has changed since it
(bookkeeping files don't count: .audit/, .changes/, .evidence/, docs/phases/, docs/plans/, docs/DECISIONS.md,
ROADMAP.md, HUMAN_TASKS.md, IDEAS.md).
Needs `ledger` on PATH; exit 2 when it, the run folder or REF is missing.

With --base REF, or with --receipts, each box this branch newly checked is also compared with REF.
A criterion whose `Probe:` text differs from REF's, or that REF doesn't have, was judged by a probe
written in the same diff that checks it. It prints an `observe: file:line: ...` line on stderr unless
its item gains a `**Confirmed.**` line it didn't have at REF, saying who accepted the new probe. An
`observe:` line never changes the exit code. Exit 2 when REF is missing.

The layout (see the skill's references/layout.md):
  AGENTS.md, README.md, ROADMAP.md, HUMAN_TASKS.md, IDEAS.md
  docs/VISION.md      goals table with G ids, each with a measure, a lever and a first move; non-goals
  docs/DECISIONS.md   numbered decisions, append-only
  docs/phases/<id>-<slug>.md   one spec per phase: ideal state, criteria and anti-criteria with probes
  docs/plans/         temporary plans; deleted when their phase is done
  a verify-<app> skill that AGENTS.md names
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_FILES = ["AGENTS.md", "README.md", "ROADMAP.md", "HUMAN_TASKS.md", "IDEAS.md",
                  "docs/VISION.md", "docs/DECISIONS.md"]
LEGACY_ACCEPTANCE = re.compile(r"^#{2,3} Acceptance\b", re.M)
HEADING = re.compile(r"^#{2,3} (.+?)\s*$")
LEVEL = re.compile(r"^\s*\d\.\s+\*\*(Done|Good|Surprising)\.\*\*")
CONFIRMED = re.compile(r"^\*\*Confirmed\.\*\*(.*)$")
ITEM_ID = re.compile(r"^\s*- (?:\[[ xX]\] )?(?:~~)?\*\*([A-Z]\d+)\.\*\*")
STRUCK = re.compile(r"^\s*- ~~\*\*[A-Z]\d+\.\*\*")
PROBE = re.compile(r"\bProbe:", re.I)
EVIDENCE = re.compile(r"\bEvidence:", re.I)
NEEDS_CONFIRMATION = ("planned", "building", "in progress", "gated")
STATUSES = ("not started", "specced", "planned", "building", "in progress", "gated", "done", "parked")
DECISION = re.compile(r"^### D(\d+)\.\s+\S")
DECISION_STATUS = re.compile(r"^\*(Accepted|Proposed|Superseded|Rejected)\b")
GOAL_ROW = re.compile(r"^\|\s*(G\d+)\s*\|")
# What each goal row says besides the goal: how you read where it stands, what you can change that
# moves that reading, and the first thing to do with it.
GOAL_COLUMNS = {"measure": "say how you read where this goal stands today",
                "lever": "say what you can change that moves the measure",
                "first move": "say the first thing to do with that lever"}
EMPTY_CELL = ("", "-", "--", "—", "–", "?", "tbd", "todo", "n/a")
BOX = re.compile(r"^\s*- \[[ xX]\] ")
PHASE_FILE = re.compile(r"^(P\d+[a-z]?)-[a-z0-9-]+\.md$")
ROADMAP_ROW = re.compile(r"^\|\s*(P\d+[a-z]?)(?![\w.])[^|]*\|([^|]*)\|")
VERIFY_NAME = re.compile(r"\bverify-[a-z0-9-]+")


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def check(repo: Path) -> list[str]:
    out: list[str] = []
    for rel in REQUIRED_FILES:
        if not (repo / rel).is_file():
            out.append(f"{rel}: missing (scaffold-product writes a starting version)")

    vision = repo / "docs/VISION.md"
    goals: set[str] = set()
    if vision.is_file():
        text = lines(vision)
        goals = {m.group(1) for l in text if (m := GOAL_ROW.match(l))}
        if not goals:
            out.append("docs/VISION.md:1: no goals table with G1, G2, ... rows; goals need ids that phases can cite")
        out += goal_columns(text)[0]
        if not any(l.strip().lower().startswith("## non-goals") for l in text):
            out.append("docs/VISION.md:1: no '## Non-goals' section")

    decisions = repo / "docs/DECISIONS.md"
    if decisions.is_file():
        text = lines(decisions)
        seen: list[int] = []
        for i, l in enumerate(text):
            m = DECISION.match(l)
            if not m:
                continue
            n = int(m.group(1))
            if n in seen:
                out.append(f"docs/DECISIONS.md:{i + 1}: D{n} is used twice; decisions are append-only, supersede instead")
            elif seen and n != max(seen) + 1:
                out.append(f"docs/DECISIONS.md:{i + 1}: D{n} follows D{max(seen)}; number decisions in order")
            seen.append(n)
            nxt = next((t for t in text[i + 1:i + 4] if t.strip()), "")
            if not DECISION_STATUS.match(nxt.strip()):
                out.append(f"docs/DECISIONS.md:{i + 1}: D{n} has no status line (*Accepted YYYY-MM-DD.*) under its heading")

    roadmap = repo / "ROADMAP.md"
    in_roadmap: dict[str, str] = {}
    roadmap_lines: dict[str, int] = {}
    if roadmap.is_file():
        for i, l in enumerate(lines(roadmap)):
            m = ROADMAP_ROW.match(l)
            if not m:
                continue
            pid, status = m.group(1), m.group(2).strip().strip("*").strip().lower()
            in_roadmap[pid] = status
            roadmap_lines[pid] = i + 1
            if not status.startswith(STATUSES):
                out.append(f"ROADMAP.md:{i + 1}: {pid} status '{m.group(2).strip()[:40]}' should start with one of: "
                           + ", ".join(s.capitalize() for s in STATUSES))

    phases_dir = repo / "docs/phases"
    specs: dict[str, Path] = {}
    if not phases_dir.is_dir() or not any(phases_dir.glob("*.md")):
        out.append("docs/phases/: no phase specs; write at least the first one (P1-<slug>.md)")
    else:
        for spec in sorted(phases_dir.glob("*.md")):
            m = PHASE_FILE.match(spec.name)
            if not m:
                out.append(f"docs/phases/{spec.name}: name it P<n>-<slug>.md (for example P1-first-slice.md)")
                continue
            specs[m.group(1)] = spec
            out += check_spec(spec, goals, in_roadmap.get(m.group(1), ""))

    for pid, line in roadmap_lines.items():
        if specs and pid not in specs:
            out.append(f"ROADMAP.md:{line}: {pid} has no spec in docs/phases/")
    if roadmap.is_file():
        for pid, spec in specs.items():
            if pid not in in_roadmap:
                out.append(f"docs/phases/{spec.name}: {pid} is not in ROADMAP.md's phase table")

    plans = repo / "docs/plans"
    if plans.is_dir():
        for plan in sorted(plans.glob("*.md")):
            pid = re.match(r"^(P\d+[a-z]?)", plan.name)
            if pid and in_roadmap.get(pid.group(1), "").startswith("done"):
                out.append(f"docs/plans/{plan.name}: {pid.group(1)} is done; delete its plan (plans don't stay in the repo)")

    layout_files = [repo / rel for rel in [*REQUIRED_FILES, "REVIEW.md"]] + list(specs.values())
    for f in layout_files:
        if f.is_file():
            for i, l in enumerate(lines(f)):
                if "{{" in l and "}}" in l:
                    out.append(f"{f.relative_to(repo)}:{i + 1}: unfilled template placeholder")
                    break

    agents = repo / "AGENTS.md"
    if agents.is_file():
        named = sorted(set(VERIFY_NAME.findall(agents.read_text(encoding="utf-8"))))
        if not named:
            out.append("AGENTS.md:1: names no verify-<app> skill; every PR proves its behavior through one")
        for name in named:
            if not any((repo / d / name / "SKILL.md").is_file() for d in (".agents/skills", ".claude/skills", "skills")):
                out.append(f"AGENTS.md:1: names {name}, but no {name}/SKILL.md under .agents/skills, .claude/skills or skills")
    return out


def cells(row: str) -> list[str]:
    """A table row's cells. A `\\|`, or a `|` inside a code span, is text and not a column break."""
    found, cell, in_code, i = [], "", False, 0
    while i < len(row):
        c = row[i]
        if c == "\\" and row[i + 1:i + 2] == "|":
            cell, i = cell + "|", i + 2
            continue
        if c == "`":
            in_code = not in_code
        if c == "|" and not in_code:
            found.append(cell.strip())
            cell = ""
        else:
            cell += c
        i += 1
    found.append(cell.strip())
    return found[1:-1] if row.strip().endswith("|") else found[1:]


def goal_columns(text: list[str]) -> tuple[list[str], list[str]]:
    """(problems, notes) for the goals table: the first table in VISION.md with G rows.

    A table with all of Measure, Lever and First move fails each goal row that leaves one empty. A
    table with some of them fails once. A table with none predates the columns: that is a note.
    """
    first = next((i for i, l in enumerate(text) if GOAL_ROW.match(l)), None)
    if first is None:
        return [], []
    top = first
    while top > 0 and text[top - 1].lstrip().startswith("|"):
        top -= 1
    if top == first:
        return [], []
    end = first
    while end < len(text) and text[end].lstrip().startswith("|"):
        end += 1
    header = [c.strip("*_` ").lower() for c in cells(text[top])]
    where = f"docs/VISION.md:{top + 1}"
    have = [c for c in GOAL_COLUMNS if c in header]
    missing = [c for c in GOAL_COLUMNS if c not in header]
    names = lambda cs: " or ".join(c.capitalize() for c in cs)
    if not have:
        return [], [f"{where}: goals table has no Measure, Lever and First move columns. Nothing fails until it "
                    f"has them. A person supplies them: see scaffold-product's 'Add measure, lever and first move "
                    f"to the goals'"]
    if missing:
        return [f"{where}: goals table has a {names(have).replace(' or ', ' and ')} column but no {names(missing)} "
                f"column; a goal needs all of Measure, Lever and First move"], []
    out = []
    for i in range(first, end):
        m = GOAL_ROW.match(text[i])
        if not m:
            continue
        row = cells(text[i])
        for column, ask in GOAL_COLUMNS.items():
            at = header.index(column)
            if at >= len(row) or row[at].strip("*_` ").lower() in EMPTY_CELL:
                out.append(f"docs/VISION.md:{i + 1}: {m.group(1)} has no {column.capitalize()}; {ask}")
    return out, []


def notes(repo: Path) -> list[str]:
    """What the checker will hold this repo to once it adopts a newer format. Printed, never failed."""
    vision = repo / "docs/VISION.md"
    return goal_columns(lines(vision))[1] if vision.is_file() else []


def sections(text: list[str]) -> dict[str, tuple[int, list[str]]]:
    """Each `## Heading` (lowercased) mapped to (its line number, the lines under it)."""
    found: dict[str, tuple[int, list[str]]] = {}
    current = None
    for i, l in enumerate(text):
        m = HEADING.match(l)
        if m:
            current = m.group(1).lower()
            found[current] = (i + 1, [])
        elif current:
            found[current][1].append(l)
    return found


def items(start: int, body: list[str]) -> list[tuple[int, str]]:
    """Top-level list items with their line numbers; an indented line continues the item above it."""
    found: list[tuple[int, str]] = []
    for i, l in enumerate(body):
        if l.startswith("- "):
            found.append((start + i + 1, l))
        elif found and l.startswith((" ", "\t")) and l.strip():
            found[-1] = (found[-1][0], found[-1][1] + " " + l.strip())
    return found


def check_spec(spec: Path, goals: set[str], status: str) -> list[str]:
    """A phase spec: outcome, goals served, ideal state, criteria and anti-criteria with probes."""
    out: list[str] = []
    name = f"docs/phases/{spec.name}"
    text = spec.read_text(encoding="utf-8")
    body = text.splitlines()
    if "**Outcome.**" not in text:
        out.append(f"{name}:1: no `**Outcome.**` line saying what a user will notice when it ships")
    for i, l in enumerate(body):
        if l.startswith("**Serves.**"):
            for g in re.findall(r"\bG\d+\b", l.split("**Depends on.**")[0]):
                if goals and g not in goals:
                    out.append(f"{name}:{i + 1}: serves {g}, which is not a goal in docs/VISION.md")
    if LEGACY_ACCEPTANCE.search(text):
        line = next(i + 1 for i, l in enumerate(body) if LEGACY_ACCEPTANCE.match(l))
        out.append(f"{name}:{line}: older spec format ('## Acceptance'); upgrade it to an ideal state, criteria and "
                   f"anti-criteria (scaffold-product's 'Upgrade a repo on the older spec format')")
        return out
    parts = sections(body)

    ideal = parts.get("ideal state")
    if not ideal:
        out.append(f"{name}:1: no '## Ideal state' section with the levels Done, Good and Surprising")
    else:
        levels = {m.group(1) for l in ideal[1] if (m := LEVEL.match(l))}
        missing = [lv for lv in ("Done", "Good", "Surprising") if lv not in levels]
        if missing:
            out.append(f"{name}:{ideal[0]}: ideal state has no level " + ", ".join(f"**{lv}.**" for lv in missing))
        confirmed = next(((ideal[0] + i + 1, m.group(1).strip()) for i, l in enumerate(ideal[1])
                          if (m := CONFIRMED.match(l.strip()))), None)
        if confirmed is None:
            out.append(f"{name}:{ideal[0]}: ideal state has no `**Confirmed.**` line "
                       f"(write 'Not yet' until a person confirms levels 1 and 2)")
        elif status.startswith(NEEDS_CONFIRMATION):
            line, said = confirmed
            if not said or said.lower().startswith("not yet") or "(draft" in said:
                out.append(f"{name}:{line}: the phase is {next(s for s in NEEDS_CONFIRMATION if status.startswith(s)).capitalize()} but no person has confirmed "
                           f"levels 1 and 2 of its ideal state; get that before building")

    seen: dict[str, int] = {}
    unchecked = 0
    for section, prefix, word in (("criteria", "C", "criterion"), ("anti-criteria", "A", "anti-criterion")):
        part = parts.get(section)
        if not part:
            out.append(f"{name}:1: no '## {section.capitalize()}' section")
            continue
        boxes = 0
        for line, item in items(*part):
            m = ITEM_ID.match(item)
            if STRUCK.match(item):
                if m:
                    seen.setdefault(m.group(1), line)
                continue
            if not BOX.match(item):
                continue
            boxes += 1
            if not m:
                out.append(f"{name}:{line}: {word} has no id; start it with **{prefix}<n>.**")
                continue
            cid = m.group(1)
            if not cid.startswith(prefix):
                out.append(f"{name}:{line}: {cid} is under {section.capitalize()}; ids there start with {prefix}")
            if cid in seen:
                out.append(f"{name}:{line}: {cid} is used twice in this spec (first at line {seen[cid]}); ids are never reused")
            seen.setdefault(cid, line)
            if not PROBE.search(item):
                out.append(f"{name}:{line}: {cid} names no 'Probe:' (the run, test or measurement that would prove it false)")
            checked = item.startswith(("- [x]", "- [X]"))
            if checked and not EVIDENCE.search(item):
                out.append(f"{name}:{line}: {cid} is checked without 'Evidence:'")
            unchecked += not checked
        if boxes == 0:
            out.append(f"{name}:{part[0]}: {section.capitalize()} has no '- [ ] **{prefix}1.**' boxes")
    if status.startswith("done") and unchecked:
        out.append(f"{name}:1: the phase is Done but {unchecked} box(es) are unchecked; prove them, or move the "
                   f"ROADMAP row back to Building")
    return out


def drafts(repo: Path) -> int:
    """Statements no person has confirmed yet. Counted, not failed: the human confirms them in review."""
    files = [repo / "docs/VISION.md", repo / "docs/DECISIONS.md", repo / "ROADMAP.md"]
    files += sorted((repo / "docs/phases").glob("*.md")) if (repo / "docs/phases").is_dir() else []
    return sum(f.read_text(encoding="utf-8").count("(draft") for f in files if f.is_file())


CHECKED_ITEM = re.compile(r"^\s*- \[[xX]\] \*\*([A-Z]\d+)\.\*\*")
ITEM_CONFIRMED = re.compile(r"\*\*Confirmed\.\*\*")
ANY_ITEM = re.compile(r"^\s*- (?:\[[ xX]\] )?(?:~~)?\*\*([A-Z]\d+)\.\*\*")
# What the Product phase playbook edits alongside a ticked box. These are records, not source, so a
# change to one doesn't make a receipt stale. verify-work's receipt.py has the same list.
BOOKKEEPING = (".audit", ".changes", ".evidence", "docs/phases", "docs/plans", "docs/DECISIONS.md", "ROADMAP.md",
               "HUMAN_TASKS.md", "IDEAS.md")


class UsageError(Exception):
    pass


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace")


def checked_ids(text: str) -> dict[str, int]:
    """Each checked item id mapped to the line it is first checked on."""
    found: dict[str, int] = {}
    for i, l in enumerate(text.splitlines()):
        m = CHECKED_ITEM.match(l)
        if m:
            found.setdefault(m.group(1), i + 1)
    return found


def item_block(text: str, cid: str) -> str | None:
    """An item's lines up to the next item, blank line or heading, joined on spaces."""
    block: list[str] | None = None
    for l in text.splitlines():
        m = ANY_ITEM.match(l)
        if block is None:
            if m and m.group(1) == cid:
                block = [l]
        elif m or not l.strip() or l.startswith("#"):
            break
        else:
            block.append(l)
    return None if block is None else " ".join(x.strip() for x in block)


def criterion_text(text: str, cid: str) -> str | None:
    """What an item claims: its block without the box state, `Evidence:` or `**Confirmed.**`, which
    are written about the claim after it is made."""
    block = item_block(text, cid)
    if block is None:
        return None
    claim = re.sub(r"^- \[[ xX]\] ", "- ", block)
    claim = EVIDENCE.split(claim, 1)[0]
    return " ".join(ITEM_CONFIRMED.split(claim, 1)[0].split())


def probe_text(claim: str) -> str:
    parts = PROBE.split(claim, 1)
    return parts[1].strip() if len(parts) == 2 else ""


def confirmations(text: str, cid: str) -> set[str]:
    """Each `**Confirmed.**` statement in an item's block."""
    block = item_block(text, cid) or ""
    return {" ".join(part.split()) for part in ITEM_CONFIRMED.split(block)[1:]}


def base_specs(repo: Path, base: str) -> dict[str, str]:
    """Phase id -> that phase's spec text at base. Keyed by phase id, so a renamed spec still matches."""
    found: dict[str, str] = {}
    for name in git(repo, "ls-tree", "--name-only", f"{base}:docs/phases").stdout.splitlines():
        m = PHASE_FILE.match(name)
        if m:
            found[m.group(1)] = git(repo, "show", f"{base}:docs/phases/{name}").stdout
    return found


def newly_checked(repo: Path, base: str) -> list[tuple[Path, str, str, int]]:
    """(spec, phase id, item id, line) for each item checked now and not checked in that phase's
    spec at base. Keyed by phase id, not file name, so renaming a spec makes nothing new."""
    before = {(phase, cid) for phase, text in base_specs(repo, base).items() for cid in checked_ids(text)}
    out = []
    for spec in sorted((repo / "docs/phases").glob("*.md")) if (repo / "docs/phases").is_dir() else []:
        m = PHASE_FILE.match(spec.name)
        if not m:
            continue
        for cid, line in checked_ids(spec.read_text(encoding="utf-8", errors="replace")).items():
            if (m.group(1), cid) not in before:
                out.append((spec, m.group(1), cid, line))
    return out


def last_receipts(ledger_file: Path) -> dict[str, dict]:
    """criterion -> the verification entry's data of the last receipt for it."""
    found: dict[str, dict] = {}
    for raw in ledger_file.read_text(encoding="utf-8").splitlines():
        entry = json.loads(raw)
        data = entry.get("data")
        receipt = data.get("receipt") if isinstance(data, dict) else None
        if entry.get("type") == "verification" and isinstance(receipt, dict) and isinstance(receipt.get("criterion"), str):
            found[receipt["criterion"]] = data
    return found


def receipt_problems(repo: Path, rel: str, line: int, crit: str, data: dict | None) -> list[str]:
    where = f"{rel}:{line}: {crit}"
    if data is None:
        return [f"{where} is checked but has no receipt in the run's ledger (run verify-work's receipt.py for it)"]
    receipt = data["receipt"]
    verdict = data.get("verdict")
    if verdict != "VERIFIED":
        return [f"{where}: its last receipt says {verdict}, not VERIFIED"]
    if receipt.get("spec") != rel:
        return [f"{where}: its receipt names spec {receipt.get('spec')}, not {rel}"]
    commit = str(receipt.get("commit"))
    if git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        return [f"{where}: its receipt's commit {commit[:12]} is not in this clone (history was rewritten after the "
                f"probe ran, or the clone is shallow); re-run its probe"]
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{rel}"], capture_output=True)
    if shown.returncode != 0:
        return [f"{where}: its receipt's commit {commit[:12]} has no {rel} in this repo"]
    out = []
    if hashlib.sha256(shown.stdout).hexdigest() != receipt.get("spec_sha256"):
        out.append(f"{where}: {rel} at receipt commit {commit[:12]} does not match the receipt's spec_sha256")
    cid = crit.split("-", 1)[1]
    now = criterion_text((repo / rel).read_text(encoding="utf-8", errors="replace"), cid)
    if now != criterion_text(shown.stdout.decode("utf-8", "replace"), cid):
        out.append(f"{where}: the criterion's text or probe changed after its receipt at {commit[:12]}; "
                   f"the receipt is for the old claim (re-run its probe)")
    excludes = ["--", ".", *(f":(exclude){p}" for p in BOOKKEEPING)]
    if git(repo, "diff", "--quiet", commit, "HEAD", *excludes).returncode != 0:
        out.append(f"{where}: its receipt is stale; source changed after commit {commit[:12]} (re-run its probe)")
    elif git(repo, "status", "--porcelain", "--untracked-files=no", *excludes).stdout.strip():
        out.append(f"{where}: its receipt is stale; tracked files have uncommitted changes (commit them, then re-run its probe)")
    return out


def require_base(repo: Path, base: str) -> None:
    if git(repo, "rev-parse", "--git-dir").returncode != 0:
        raise UsageError(f"{repo} is not inside a git repo; --base reads git history")
    if git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        raise UsageError(f"base ref {base} does not exist here (fetch it, or pass --base)")


def probe_changes(repo: Path, base: str) -> list[str]:
    """Observations for newly checked boxes whose probe this branch wrote, unless a person confirmed it."""
    before = base_specs(repo, base)
    out = []
    for spec, phase, cid, line in newly_checked(repo, base):
        rel = f"docs/phases/{spec.name}"
        now = spec.read_text(encoding="utf-8", errors="replace")
        then = before.get(phase, "")
        old = criterion_text(then, cid)
        if old is not None and probe_text(old) == probe_text(criterion_text(now, cid) or ""):
            continue
        if confirmations(now, cid) - confirmations(then, cid):
            continue
        what = (f"{phase}-{cid} is new in this diff and checked in it" if old is None
                else f"{phase}-{cid}'s Probe: changed in the diff that checks it")
        out.append(f"{rel}:{line}: {what}; the change judged itself. Add a `**Confirmed.**` line to the item "
                   f"saying who accepted the probe, or check the box in a later PR")
    return out


def check_receipts(repo: Path, run_id: str, base: str) -> tuple[list[str], int, int]:
    """Problems for newly checked boxes without a current receipt, how many are new, how many backed."""
    if shutil.which("ledger") is None:
        raise UsageError("`ledger` is not on PATH; --receipts needs agent-ledger")
    require_base(repo, base)
    run_dir = repo / ".audit/runs" / run_id
    if not (run_dir / "ledger.jsonl").is_file():
        raise UsageError(f"no ledger for run {run_id} at .audit/runs/{run_id}/ledger.jsonl")
    new = newly_checked(repo, base)
    if subprocess.run(["ledger", "verify", f".audit/runs/{run_id}"], cwd=repo, capture_output=True).returncode != 0:
        return ["the run's ledger fails verify"], len(new), 0
    receipts = last_receipts(run_dir / "ledger.jsonl")
    problems: list[str] = []
    backed = 0
    for spec, phase, cid, line in new:
        found = receipt_problems(repo, f"docs/phases/{spec.name}", line, f"{phase}-{cid}", receipts.get(f"{phase}-{cid}"))
        problems += found
        backed += not found
    return problems, len(new), backed


def parse(argv: list[str]) -> tuple[str, str | None, str | None]:
    """(repo dir, receipts run id, base ref or None when neither flag is given), or UsageError."""
    positional: list[str] = []
    opts: dict[str, str] = {}
    it = iter(argv[1:])
    for a in it:
        if a in ("-h", "--help"):
            raise UsageError("")
        if a in ("--receipts", "--base"):
            value = next(it, None)
            if value is None or value.startswith("--"):
                raise UsageError(f"{a} needs a value")
            opts[a] = value
        else:
            positional.append(a)
    if len(positional) > 1:
        raise UsageError("")
    base = opts.get("--base", "origin/main" if "--receipts" in opts else None)
    return (positional[0] if positional else "."), opts.get("--receipts"), base


def main(argv: list[str]) -> int:
    try:
        repo_arg, run_id, base = parse(argv)
    except UsageError as e:
        print(f"{e}\n{__doc__.strip()}".strip(), file=sys.stderr)
        return 2
    repo = Path(repo_arg).resolve()
    if not repo.is_dir():
        print(f"not a directory: {repo}", file=sys.stderr)
        return 2
    problems = check(repo)
    receipt_line = ""
    observed: list[str] = []
    try:
        if base is not None:
            require_base(repo, base)
            observed = probe_changes(repo, base)
        if run_id is not None:
            more, new, backed = check_receipts(repo, run_id, base)
            problems += more
            receipt_line = f", receipts: {new} newly checked, {backed} backed"
    except UsageError as e:
        print(f"check-product: {e}", file=sys.stderr)
        return 2
    for p in problems:
        print(p, file=sys.stderr)
    for o in observed:
        print(f"observe: {o}", file=sys.stderr)
    noted = notes(repo)
    for n in noted:
        print(f"note: {n}", file=sys.stderr)
    note_line = f", {len(noted)} note(s)" if noted else ""
    note_line += f", {len(observed)} self-judged probe(s) observed" if observed else ""
    print(f"check-product: {repo.name}: {len(problems)} problem(s), {drafts(repo)} draft marker(s) awaiting confirmation"
          f"{note_line}{receipt_line}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
