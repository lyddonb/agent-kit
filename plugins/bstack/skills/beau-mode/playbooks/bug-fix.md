---
id: bug-fix
title: Bug fix
when: "A reported defect to reproduce, root-cause, and fix with runtime evidence."
source: pstack/skills/poteto-mode/playbooks/bug-fix.md @ ccb5507
---

# Bug fix

**You own the fix. Plan, delegate, verify.** Be scientific: every shipped line traces to runtime evidence. A change that "might help" is a hypothesis, not a fix, and it doesn't ship.

1. Restate the problem in your own words, in plain English, before touching anything: what the user saw, what they expected, and what you think the underlying issue is. When the report is a thread, ticket or log, read all of it first. If the restatement is a guess, label it, and let the repro confirm it.
2. Reproduce it yourself on the surface where it happens: drive the browser, CLI, app or API the way a user would. Ask the human to reproduce only after you have driven it as far as your tools go, and say exactly what you can't reach. If it won't fire, synthesize the trigger, tighten the conditions, or add instrumentation until it does.
3. Binary-search the cause. List candidate hypotheses, then rule them out with runtime evidence, taking the split that cuts the most remaining space each time. Use **how** on the affected code and the git history for regressions. When state is unclear, add logging and read it as the code runs. Confirm the mechanism, not just the location, before planning the fix (`fix-root-causes`). When the code is agent-written or unfamiliar, or two theories have already failed, run the **root-cause** skill instead: it reaches the cause from facts, not from reading the code, and hands back a report with the evidence.
   When two fixes haven't held, whoever wrote them, stop patching: a third fix on the same premise is a guess. Go back to the symptom and run **root-cause**. If the fixes are yours, take them out first and give **root-cause** to a fresh subagent whose brief has the symptom and the repro and nothing about the fixes. The fix its report supports is round 3.
4. Plan the smallest fix the evidence justifies. If it crosses a function boundary, name the shape of the change first. Delegate the implementation to a `code` subagent with a precise brief.
5. Verify on the same surface with **verify-work**, through the project's verification skill if it has one. The original repro now passes. Unit tests show branch behavior, not that the bug is gone. "Inconclusive" or the wrong surface is not a pass. A repro that still fails after a fix is one round: count it, and follow **Round cap** below.
6. Order the commits so the failing test or repro lands before the fix when a cheap local test exists (`sequence-verifiable-units`).
7. Run **Opening a PR**.

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

**Reply:** your restatement of the problem, what was broken, the root cause, the fix, and how you verified it. Paste the failing-then-passing repro output.
