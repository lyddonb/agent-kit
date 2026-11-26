Skills here are files on disk, not tools. The beau-mode skill's folder is <kit>/skills/beau-mode, and paths such as `playbooks/bug-fix.md` are relative to it. Every other skill it names is at <kit>/skills/<name>/SKILL.md, and the principle files are at <kit>/skills/principles/references/<id>.md. The beau-mode skill follows.

---
name: beau-mode
description: Beau's way of doing engineering work with an agent. It picks a playbook, applies named principles, verifies on the real artifact, keeps a decision trail, and writes plain replies. Use for /beau-mode, "beau mode", or any non-trivial engineering task (a bug, a feature, a refactor, a perf problem, an investigation, a prototype, a skill edit, or an unattended run). Skip it for casual questions and one-line answers.
license: MIT
metadata:
  author: lyddonb
  version: "0.3.0"
  upstream: "pstack poteto-mode @ ccb5507, playbooks updated from 11713c6, goal handoff from 246bc50 (MIT, Lauren Tan)"
---

# Beau mode

Go deep before going fast. The goal is less code of higher quality, with proof that it works, so that several agents can run in parallel without anyone re-checking their work by hand.

## Start every task this way

1. **Restate the task.** In one or two plain sentences, say the user's goal, the problem it solves, and what done looks like. If the task ships a change, name the smallest change you expect to meet the goal. When the request points at a thread, ticket or log, read all of it first. Don't wait for confirmation: this catches a wrong reading before it costs anything, and the user can redirect. If the evidence rules out the change the user asked for, show it and stop. Carry the goal forward: restate it in every subagent brief, at the top of each PR's `## Why`, and at the top of your final reply (skip that for a fully specified one-line edit).
2. **Match a playbook.** Pick one from the list at the end. Open its file and copy its steps into your todo list word for word, before any task-specific todos. A step you skip stays in the list as `skip: <reason>`. Work that spans several PRs, runs while the human is away, or touches a default gate goes to **Large work item** first: a human approves its charter before any work starts. If no playbook fits, or the work is large and cross-cutting with no standard shape, use the **figure-it-out** skill, which frames itself with Large work item.
3. **Read the principles the playbook names.** For each principle id the playbook names, read its full file in the **principles** skill (`references/<id>.md`). Read no other principles.

## Playbooks

<!-- BEGIN GENERATED: playbooks-index (tools/kitgen.py; edit playbooks/*.md) -->
- **Authoring a skill** (`playbooks/authoring-a-skill.md`). Writing or editing a SKILL.md, a playbook, or a principle.
- **Autonomous run** (`playbooks/autonomous-run.md`). A long task to drive to completion without stopping: "run until done", "going to bed", "don't ask me".
- **Bug fix** (`playbooks/bug-fix.md`). A reported defect to reproduce, root-cause, and fix with runtime evidence.
- **Eval** (`playbooks/eval.md`). Testing how a skill, principle or prompt change affects agent behavior before you keep it, including adopting someone else's skill.
- **Feature** (`playbooks/feature.md`). New or changed behavior, built from a named data shape.
- **Investigation** (`playbooks/investigation.md`). A read-only question: how does X work, why was Y built this way, are we sure about Z, should we do X or Y.
- **Large work item** (`playbooks/large-work-item.md`). Work that spans several PRs, runs while the human is away, or touches a default gate (migration, public API, deploy, auth, a new dependency, secrets, deleting data). The human approves a charter before work starts, and every decision lands in a ledger.
- **Multi-phase plan** (`playbooks/multi-phase-plan.md`). Turning an agreed design into a tactical execution plan of small, verifiable PRs: "turn this design into a plan", a migration, or any change too big for one PR.
- **Opening a PR** (`playbooks/opening-a-pr.md`). The last step of every playbook that changes code.
- **Pause safely** (`playbooks/pause-safely.md`). An explicit request to pause, going offline, a restart, or imminent context compaction. Never on "keep going".
- **Perf issue** (`playbooks/perf-issue.md`). A measured slowness to trace and improve against a baseline.
- **Product phase** (`playbooks/product-phase.md`). Product work in a repo with docs/VISION.md and docs/phases/: specifying the next phase, advancing one, adding a feature to a phase that is done, or closing it at its gate. Also the entry point for starting a product.
- **Prototype** (`playbooks/prototype.md`). A throwaway sketch to make a design or behavior decision cheaply, or to settle a factual question by observing it instead of asking.
- **Refactoring** (`playbooks/refactoring.md`). A behavior-preserving change to structure: rename, extract, inline, dedupe, move, reshape an API.
- **Session pickup** (`playbooks/session-pickup.md`). Resuming or taking over another agent's in-flight work from a transcript, a handoff note, or a pushed branch.
<!-- END GENERATED: playbooks-index -->

Every playbook that changes code ends with **Opening a PR**.
