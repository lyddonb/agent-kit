---
id: product-phase
title: Product phase
when: "Product work in a repo with docs/VISION.md and docs/phases/: specifying the next phase, advancing one, or closing it at its gate. Also the entry point for starting a product."
---

# Product phase

**You own the phase from spec to gate.** A phase is a slice of product that serves a goal in `docs/VISION.md` and is done only when its acceptance boxes are checked with evidence. The layout and lifecycle are in the **scaffold-product** skill's `references/layout.md`.

1. **Orient.** Read `AGENTS.md`, `docs/VISION.md`, `ROADMAP.md`, `HUMAN_TASKS.md`, the phase spec and its plan. Run **recall** on the phase if someone worked it recently. If the repo has no `docs/VISION.md`, run **scaffold-product** first and stop at its PR.
2. **Find where the phase is** in the lifecycle (Not started, Specced, Planned, Building, Gated, Done) and do only the next step:
   - **Not started → Specced.** Write `docs/phases/P<n>-<slug>.md` from the template: outcome, the goals it serves, scope in and out, behavior, cost, acceptance boxes. Settle facts by running something (the Prototype playbook). Put product and preference calls to the human as options, and record each answer in `docs/DECISIONS.md`. Stop for the human to accept the spec.
   - **Specced → Planned.** Run the Multi-phase plan playbook with the spec as the design. The plan lives at `docs/plans/P<n>-<slug>.md` and its live lanes go through the project's `verify-<app>` skill. Stop for the human's go.
   - **Planned → Building.** Work the plan's next PR with the Feature, Bug fix or Refactoring playbook. Each PR ticks the spec's boxes it proves and updates `ROADMAP.md`.
   - **Building → Gated.** When every build box is checked, the remaining boxes are gates that take time or the human (a week of clean runs, a review). Move the row to Gated and put each gate the human owns in `HUMAN_TASKS.md`.
   - **Gated → Done.** When every box is checked with evidence, mark the row Done, delete the plan, and update the spec's goals if what you learned changes them.
3. **Keep the spec true.** If the spec is wrong or silent, fix it in the same PR and say why in the PR body. Don't build past a gap. A reversed decision gets a new entry that supersedes the old one.
4. **Check the repo** with `python3 <scaffold-product skill folder>/scripts/check-product.py .` before each PR, and fix every line it prints.
5. Run **Opening a PR** for any change.

**Reply:** the phase, where it moved in the lifecycle and the evidence that moved it, decisions made or waiting on the human, and the next step.
