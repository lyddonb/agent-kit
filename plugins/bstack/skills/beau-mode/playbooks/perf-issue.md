---
id: perf-issue
title: Perf issue
when: "A measured slowness to trace and improve against a baseline."
source: pstack/skills/poteto-mode/playbooks/perf-issue.md @ ccb5507
---

# Perf issue

**You own the measurement story.** Tie every fix to a measurement. Don't read source instead of measuring.

1. Capture a baseline on the real path (profile, trace, or timed end-to-end run). Vet it, and every later number, with the benchmark checklist in the **principles** skill (`references/checklists/benchmark.md`, per `explain-the-number`).
2. Ground hypotheses with **how**. Then try fixes cheapest first, and stop when one meets the target:
   1. Don't do it: stop work whose result nothing uses.
   2. Do it, but don't do it again.
   3. Do it less.
   4. Do it later.
   5. Do it when the user isn't waiting.
   6. Do it concurrently.
   7. Do it cheaper.
3. Plan the fix from the evidence and delegate it to a `code` subagent. Verify each attempt before the next (`sequence-verifiable-units`). Capture a post-fix measurement the same way as the baseline.
4. Compare the artifacts directly. "Inconclusive" is not a pass.
5. Run **Opening a PR** with one primary number in the description.

**Reply:** baseline, post-fix number, delta, the limiter, and where the artifacts are.
