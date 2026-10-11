---
id: bug-fix
title: Bug fix
when: "A reported defect to reproduce, root-cause, and fix with runtime evidence."
source: pstack/skills/poteto-mode/playbooks/bug-fix.md @ ccb5507
---

# Bug fix

**You own the fix. Plan, delegate, verify.** Be scientific: every shipped line traces to runtime evidence. A change that "might help" is a hypothesis, not a fix, and it doesn't ship.

1. Reproduce it yourself on the surface where it happens: drive the browser, CLI, app or API the way a user would. Ask the human to reproduce only after you have driven it as far as your tools go, and say exactly what you can't reach. If it won't fire, synthesize the trigger, tighten the conditions, or add instrumentation until it does.
2. Binary-search the cause. List candidate hypotheses, then rule them out with runtime evidence, taking the split that cuts the most remaining space each time. Use **how** on the affected code and the git history for regressions. When state is unclear, add logging and read it as the code runs. Confirm the mechanism, not just the location, before planning the fix (`fix-root-causes`).
3. Plan the smallest fix the evidence justifies. If it crosses a function boundary, name the shape of the change first. Delegate the implementation to a `code` subagent with a precise brief.
4. Verify on the same surface with **verify-work**. The original repro now passes. Unit tests show branch behavior, not that the bug is gone. "Inconclusive" or the wrong surface is not a pass.
5. Order the commits so the failing test or repro lands before the fix when a cheap local test exists (`sequence-verifiable-units`).
6. Run **Opening a PR**.

**Reply:** what was broken, the root cause, the fix, and how you verified it. Paste the failing-then-passing repro output.
