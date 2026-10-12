---
name: figure-it-out
description: Design a rigorous, auditable playbook for work no standard playbook fits (a large migration, an ambitious multi-part change, or anything the human will review after stepping away), then run it as a hypothesis loop with a decision trail. Use for "figure it out", large or cross-cutting changes, or overnight and unattended work.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack figure-it-out @ ccb5507 (MIT, Lauren Tan)"
---

# Figure it out

When no playbook fits, design one. The first deliverable is the workflow itself: phases that scale rigor to the stakes, run as experiments, with a trail a human can audit later.

Start a todo list whose first item is to read the principles index in **beau-mode** (or the **principles** skill). Then add the phases below.

## A. Frame

Don't start the run until you can state:

- **Done** as a falsifiable predicate (`prove-it-works`).
- **Scope**, quantified: rough units and effort, plus the blockers you found while grounding.
- **Rigor level**, biased high. One-way doors and wide blast radius get more gates and artifacts; reversible low-stakes steps get fewer.

Present the framing and trade-offs before a multi-hour run. That one checkpoint is worth it; after it, proceed on reversible work (`never-block-on-the-human`).

## B. Design the workflow

Split the work into small units that each land independently. Put the riskiest unknown first, and scaffolding and verification before features (`foundational-thinking`).

- Build the verification harness before the work, with a baseline from the current state, so each check reads "old value versus new value".
- For one-way-door design choices, compare two or three shapes before committing (`exhaust-the-design-space`). Skip that for mechanical work whose shape is already clear.
- Parallelize only across real seams, each worker in its own branch or worktree (`separate-before-serializing-shared-state`).
- Write the phase list down. That list is what the human reviews.

## C. Run the loop

Each unit is an experiment: state the hypothesis, make the smallest change, check it against the predicate on the real artifact, keep it if it moved, revert it if it didn't. Verify each unit before starting the next (`sequence-verifiable-units`).

- Pair delegated work with a check you run yourself. If a worker games the check, reset it and tighten the brief. If the check itself is wrong, fix the check in its own change.
- Verdicts are VERIFIED, NOT VERIFIED or INCONCLUSIVE. Inconclusive is not a pass.

## D. Keep the trail

Log every phase with **show-me-your-work**. Work this ambitious usually deserves a committed trail.

## E. Verify and hand back

Check the whole against the Phase A predicate on the real product, not just the harness. Turn any correction you made twice into a check or script (`encode-lessons-in-structure`).

**Reply:** the playbook you designed, the rigor level and why, the trail path, what is verified against the predicate, and what is still open.
