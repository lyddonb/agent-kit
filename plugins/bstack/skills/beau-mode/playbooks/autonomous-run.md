---
id: autonomous-run
title: Autonomous run
when: "A long task to drive to completion without stopping: \"run until done\", \"going to bed\", \"don't ask me\"."
source: pstack/skills/poteto-mode/playbooks/autonomous-run.md @ ccb5507
---

# Autonomous run

**You own the exit condition. Define done, then drive to it.** Long or multi-phase runs that need their own plan go through **figure-it-out** first; this playbook is the loop.

1. Write the exit condition as a checkable predicate before the first iteration: tests green, repro fixed, zero old callers, all PRs merged. A duration ("work for four hours") is not a predicate.
2. Work in an isolated branch or worktree so the run can't collide with anything else.
3. Each iteration: make the smallest change the evidence justifies, verify it against the predicate, commit if it moved, discard it if it didn't. Changes that "might help" get reverted.
4. Log one row per iteration with **show-me-your-work**: what changed and whether the predicate moved.
5. Fix what you find along the way (flaky checks, broken skills, related bugs) in separate commits or PRs, then return to the predicate. Don't park reversible work for the human.
6. Use whatever keeps you going: your tool's loop or schedule feature if it has one, otherwise keep iterating in this session.
7. Stop when the predicate passes. A plateau means change approach, not stop. Never relax the predicate to declare victory. If you reach a real dead end, stop and write up why.

**Reply:** the predicate, iterations run, what landed, what was discarded, the final predicate state, and the decision-log path with its Attention section.
