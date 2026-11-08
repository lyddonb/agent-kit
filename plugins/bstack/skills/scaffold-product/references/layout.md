# Product repo layout

Each file has one job. `scripts/check-product.py` checks the rules marked **checked**.

| File | Job | Rules |
|---|---|---|
| `AGENTS.md` | What a coding agent reads first: read order, how to work a phase, stack and commands, rules, definition of done. `CLAUDE.md` contains exactly `@AGENTS.md`. | Names the project's `verify-<app>` skill, and that skill exists (**checked**) |
| `README.md` | What the product is and how to run it, for a person | Exists (**checked**) |
| `docs/VISION.md` | The problem, goals, non-goals, principles | Goals table with `G1`, `G2`... rows, each with "good looks like" (**checked**). A `## Non-goals` section (**checked**) |
| `docs/DECISIONS.md` | Decision records, `D1`, `D2`... | Numbered in order, never reused (**checked**). A status line under each heading that starts `*Accepted YYYY-MM-DD.*`, `*Proposed YYYY-MM-DD.*`, `*Superseded YYYY-MM-DD by D<n>.*` or `*Rejected YYYY-MM-DD.*`, optionally followed by a note such as the commit (**checked**). Never edit an accepted one: add a new one that supersedes it |
| `docs/phases/P<n>-<slug>.md` | The spec for one phase: what to build and how we know it works | An `**Outcome.**` line (**checked**). An `## Acceptance` section with `- [ ]` boxes (**checked**). A `**Serves.**` line naming the goals it serves; every goal id it names exists in VISION.md (**checked**) |
| `docs/plans/<phase>-<slug>.md` | The how-to for a phase: small PRs, each with evidence. Written by beau-mode's Multi-phase plan playbook | Temporary. Delete it when its phase is done (**checked**) |
| `ROADMAP.md` | One row per phase: status and the gate to start the next | Every row has a spec and every spec has a row (**checked**). Status starts with Not started, Specced, Planned, Building, In progress, Gated, Done or Parked (**checked**) |
| `HUMAN_TASKS.md` | What only a person can do (accounts, approvals, real data), as `H1`, `H2`..., with what each unblocks | Exists (**checked**) |
| `IDEAS.md` | Maybe-later ideas, no commitment | Exists (**checked**) |
| `.agents/skills/verify-<app>/` | Drives the real app and captures evidence. Made by **create-verification-skill** | See AGENTS.md row |
| `.agentfiles.yaml` | The project's agentfiles profile (skills and tools for this repo) | Optional |
| Other `docs/*.md` | Architecture, API reference, runbooks | Linked from AGENTS.md's read order |

## Phase lifecycle

```text
Not started ─► Specced ─► Planned ─► Building ─► Gated ─► Done
   (idea)     (spec in   (plan in   (PRs land)  (acceptance    (ROADMAP row says Done,
               phases/)   plans/)               boxes all      plan deleted)
                                                checked; gate
                                                period running)
Parked: deliberately stopped; the ROADMAP row says why and what would restart it.
```

A phase is done only when every acceptance box is checked with its evidence, not when its PRs merge. Gates that need time (a week of clean runs) are part of acceptance.

## Drafts

A statement no person has confirmed carries `(draft, from <source>)`. The checker counts these markers and doesn't fail on them; the human confirms drafts in PR review and a follow-up removes the markers.

## What goes where

- A product or preference call: ask the human with options, then record it as a decision.
- A fact you can observe (behavior, cost, timing): settle it by running something (beau-mode's Prototype playbook), then record it as a decision if it constrains the design.
- A spec that is wrong or silent: fix the spec in the same PR and say why in the PR body. Don't build past a gap.
- Anything a person must do: `HUMAN_TASKS.md`, with the phase or PR it blocks.
- A good idea outside the current phase: `IDEAS.md`.
