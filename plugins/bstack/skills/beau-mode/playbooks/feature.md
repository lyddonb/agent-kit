---
id: feature
title: Feature
when: "New or changed behavior, built from a named data shape."
source: pstack/skills/poteto-mode/playbooks/feature.md @ ccb5507
---

# Feature

**You own the design. Plan, delegate, verify.**

1. Run **how** over the subsystem you are changing.
2. Name the data shape and its organizing structure before any logic (`model-the-domain`, `foundational-thinking`). If the shape is a one-way door (a schema, a public API, a protocol) or has no precedent, run the **architect** skill: it sketches structurally different candidates on different models and picks one before any logic (`exhaust-the-design-space`). For a new package or tool, write its README first with **technical-writing** and build to it. If the work needs more than a few PRs, stop after the design and write a plan with the Multi-phase plan playbook.
3. Write a throughput checkpoint as four todos. Keep each one, marking `n/a: <reason>` when it doesn't apply:
   - **Blocking first steps** that must land before anything fans out.
   - **Independent workstreams** on disjoint files or layers that can run in parallel.
   - **Shared mutable state**: split it rather than coordinate it (`separate-before-serializing-shared-state`).
   - **Smallest safe decomposition**: if one worker is best, say why.
4. Delegate implementation to `code` subagents with precise briefs: file paths, the named shape, and what done means. Review every diff yourself.
5. Verify on the real surface with **verify-work**.
6. Rebase into small ordered commits, each verified before the next (`sequence-verifiable-units`).
7. If the design is contested or the diff is risky, run **interrogate** before shipping.
8. Run **Opening a PR**.

**Reply:** what you built, what you chose and why (a table for design alternatives), the throughput checkpoint, and open decisions.
