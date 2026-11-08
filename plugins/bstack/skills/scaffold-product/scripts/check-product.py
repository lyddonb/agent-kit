#!/usr/bin/env python3
"""Check that a repo follows the product layout from bstack's scaffold-product skill.

Usage:
    python3 check-product.py [REPO_DIR]

Prints one `file:line: problem` line per problem on stderr and a summary on stdout.
Exit code 0 when there are no problems, 1 when there are some, 2 on bad usage.

The layout (see the skill's references/layout.md):
  AGENTS.md, README.md, ROADMAP.md, HUMAN_TASKS.md, IDEAS.md
  docs/VISION.md      goals table with G ids, and non-goals
  docs/DECISIONS.md   numbered decisions, append-only
  docs/phases/<id>-<slug>.md   one spec per phase, with an acceptance checklist
  docs/plans/         temporary plans; deleted when their phase is done
  a verify-<app> skill that AGENTS.md names
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_FILES = ["AGENTS.md", "README.md", "ROADMAP.md", "HUMAN_TASKS.md", "IDEAS.md",
                  "docs/VISION.md", "docs/DECISIONS.md"]
ACCEPTANCE = re.compile(r"^#{2,3} Acceptance\b", re.M)
STATUSES = ("not started", "specced", "planned", "building", "in progress", "gated", "done", "parked")
DECISION = re.compile(r"^### D(\d+)\.\s+\S")
DECISION_STATUS = re.compile(r"^\*(Accepted|Proposed|Superseded|Rejected)\b")
GOAL_ROW = re.compile(r"^\|\s*G\d+\s*\|")
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
        goals = {m.group(1) for l in text if (m := re.match(r"^\|\s*(G\d+)\s*\|", l))}
        if not any(GOAL_ROW.match(l) for l in text):
            out.append("docs/VISION.md:1: no goals table with G1, G2, ... rows; goals need ids that phases can cite")
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
            text = spec.read_text(encoding="utf-8")
            if "**Outcome.**" not in text:
                out.append(f"docs/phases/{spec.name}:1: no `**Outcome.**` line saying what a user will notice when it ships")
            for i, l in enumerate(text.splitlines()):
                if l.startswith("**Serves.**"):
                    cited = re.findall(r"\bG\d+\b", l.split("**Depends on.**")[0])
                    for g in cited:
                        if goals and g not in goals:
                            out.append(f"docs/phases/{spec.name}:{i + 1}: serves {g}, which is not a goal in docs/VISION.md")
            parts = ACCEPTANCE.split(text)
            if len(parts) == 1:
                out.append(f"docs/phases/{spec.name}:1: no '## Acceptance' section")
            elif not any(BOX.match(l) for part in parts[1:] for l in part.splitlines()):
                out.append(f"docs/phases/{spec.name}:1: Acceptance has no '- [ ]' boxes; each criterion must be checkable")

    roadmap = repo / "ROADMAP.md"
    in_roadmap: dict[str, str] = {}
    if roadmap.is_file():
        for i, l in enumerate(lines(roadmap)):
            m = ROADMAP_ROW.match(l)
            if not m:
                continue
            pid, status = m.group(1), m.group(2).strip().strip("*").strip().lower()
            in_roadmap[pid] = status
            if not status.startswith(STATUSES):
                out.append(f"ROADMAP.md:{i + 1}: {pid} status '{m.group(2).strip()[:40]}' should start with one of: "
                           + ", ".join(s.capitalize() for s in STATUSES))
            if specs and pid not in specs:
                out.append(f"ROADMAP.md:{i + 1}: {pid} has no spec in docs/phases/")
        for pid, spec in specs.items():
            if pid not in in_roadmap:
                out.append(f"docs/phases/{spec.name}: {pid} is not in ROADMAP.md's phase table")

    plans = repo / "docs/plans"
    if plans.is_dir():
        for plan in sorted(plans.glob("*.md")):
            pid = re.match(r"^(P\d+[a-z]?)", plan.name)
            if pid and in_roadmap.get(pid.group(1), "").startswith("done"):
                out.append(f"docs/plans/{plan.name}: {pid.group(1)} is done; delete its plan (plans don't stay in the repo)")

    layout_files = [repo / rel for rel in REQUIRED_FILES] + list(specs.values())
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


def drafts(repo: Path) -> int:
    """Statements no person has confirmed yet. Counted, not failed: the human confirms them in review."""
    files = [repo / "docs/VISION.md", repo / "docs/DECISIONS.md", repo / "ROADMAP.md"]
    files += sorted((repo / "docs/phases").glob("*.md")) if (repo / "docs/phases").is_dir() else []
    return sum(f.read_text(encoding="utf-8").count("(draft") for f in files if f.is_file())


def main(argv: list[str]) -> int:
    if len(argv) > 2 or (len(argv) == 2 and argv[1] in ("-h", "--help")):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    repo = Path(argv[1] if len(argv) == 2 else ".").resolve()
    if not repo.is_dir():
        print(f"not a directory: {repo}", file=sys.stderr)
        return 2
    problems = check(repo)
    for p in problems:
        print(p, file=sys.stderr)
    print(f"check-product: {repo.name}: {len(problems)} problem(s), {drafts(repo)} draft marker(s) awaiting confirmation")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
