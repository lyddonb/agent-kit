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
3. Each iteration: make the smallest change the evidence justifies, verify it against the predicate, commit if it moved, discard it if it didn't. Changes that "might help" get reverted. A fix after which the same check still fails is one round: count it, and follow **Round cap** below.
4. Record one ledger entry per iteration with **show-me-your-work**: what changed and whether the predicate moved. If the run spans several PRs or touches a default gate, start it with the **Large work item** playbook instead, and use this loop as its step 7.
5. Fix what you find along the way (flaky checks, broken skills, related bugs) in separate commits or PRs, then return to the predicate. Don't park reversible work for the human.
6. Use whatever keeps you going: your tool's loop or schedule feature if it has one, otherwise keep iterating in this session.
7. Stop when the predicate passes. A plateau means change approach, not stop, except at a gate in the policy or the charter's stop-loss, which do stop the run, and at the round cap, which stops work on that check. Never relax the predicate to declare victory. If you reach a real dead end, stop and write up why.

<!-- BEGIN GENERATED: snippet:round-cap (tools/kitgen.py; edit plugins/bstack/snippets/round-cap.md) -->
**Round cap.** A round is one fix aimed at one failing check, then a run of that check. A check is the smallest thing that names the failure: a test, a CI job, a repro, a step of the predicate. Keep a count per check. The count is yours across every subagent you hand a fix to, so a fresh subagent doesn't start it again.

- A fix that clears one failure and uncovers a different one further on is progress. The new failure starts its own count.
- A failure that comes back keeps its count.

When a check still fails after its third round, stop work on that check:

1. Leave the check as it is. Don't skip, loosen, delete or special-case it, and don't run it again hoping for a pass.
2. Take out your fixes that didn't move it. A fix someone else committed stays: say it didn't move the check and let them decide.
3. Tell the human which check it is, the command and its last output, each fix you tried with what the check said after it, and why you think it is stuck.
4. In a run with a ledger, record the stop as a `gate` entry that names the check, and the human's reply as a `gate-answer` entry.

Independent work continues. "Don't stop" and "run until done" don't lift the cap: a fourth patch on the same check needs the human's answer.
<!-- END GENERATED: snippet:round-cap -->

**Reply:** the predicate, iterations run, what landed, what was discarded, the final predicate state, and the run id with its Attention section.
