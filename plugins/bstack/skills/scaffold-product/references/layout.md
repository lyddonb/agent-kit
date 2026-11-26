# Product repo layout

Each file has one job. `scripts/check-product.py` checks the rules marked **checked**.

| File | Job | Rules |
|---|---|---|
| `AGENTS.md` | What a coding agent reads first: read order, how to work a phase, stack and commands, rules, definition of done. `CLAUDE.md` contains exactly `@AGENTS.md`. | Names the project's `verify-<app>` skill, and that skill exists (**checked**) |
| `README.md` | What the product is and how to run it, for a person | Exists (**checked**) |
| `docs/VISION.md` | The problem, goals, non-goals, principles | Goals table with `G1`, `G2`... rows, each with "good looks like" (**checked**). Each goal also has a Measure (how you read where it stands today), a Lever (what you can change that moves the measure) and a First move, and none is empty (**checked** once the table has the columns; an older table without them gets a note). A `## Non-goals` section (**checked**) |
| `docs/DECISIONS.md` | Decision records, `D1`, `D2`... | Numbered in order, never reused (**checked**). A status line under each heading that starts `*Accepted YYYY-MM-DD.*`, `*Proposed YYYY-MM-DD.*`, `*Superseded YYYY-MM-DD by D<n>.*` or `*Rejected YYYY-MM-DD.*`, optionally followed by a note such as the commit (**checked**). Never edit an accepted one: add a new one that supersedes it |
| `docs/phases/P<n>-<slug>.md` | The ideal state for one slice of product: what done looks like and the probes that prove it. It stays after the phase is done | An `**Outcome.**` line (**checked**). A `**Serves.**` line naming the goals it serves; every goal id it names exists in VISION.md (**checked**). A `**Lever.**` sentence beside it saying which of those goals' levers the phase pulls. An `## Ideal state` section with the three levels **Done**, **Good** and **Surprising**, and a `**Confirmed.**` line (**checked**). A `## Criteria` section with at least one `- [ ] **C<n>.**` box and an `## Anti-criteria` section with at least one `- [ ] **A<n>.**` box (**checked**). Every criterion and anti-criterion names its `Probe:` (**checked**), ids are unique in the spec (**checked**), and a checked box carries `Evidence:` (**checked**). While a phase is Planned, Building, In progress or Gated, its `**Confirmed.**` line names who confirmed levels 1 and 2, not "Not yet" or a draft (**checked**). A Done phase has no unchecked box (**checked**). A box checked in the same diff that wrote its `Probe:` carries a `**Confirmed.**` line in the item naming who accepted that probe (observed with `--base`, never failed) |
| `docs/plans/<phase>-<slug>.md` | The how-to for a phase: small PRs, each with evidence. Written by beau-mode's Multi-phase plan playbook | Temporary. Delete it when its phase is done (**checked**) |
| `ROADMAP.md` | One row per phase: status and the gate to start the next | Every row has a spec and every spec has a row (**checked**). Status starts with Not started, Specced, Planned, Building, In progress, Gated, Done or Parked (**checked**) |
| `REVIEW.md` | What a reviewer of this code should look at. **interrogate** gives it to every adversary and Claude Code Review reads it, neither from the change under review, so a change can't rewrite the guide it is reviewed by | Optional. No unfilled placeholder when it exists (**checked**). A change to it takes effect when it merges |
| `HUMAN_TASKS.md` | What only a person can do (accounts, approvals, real data), as `H1`, `H2`..., with what each unblocks | Exists (**checked**) |
| `IDEAS.md` | Maybe-later ideas, no commitment | Exists (**checked**) |
| `.agents/skills/verify-<app>/` | Drives the real app and captures evidence. Made by **create-verification-skill** | See AGENTS.md row |
| `.agentfiles.yaml` | The project's agentfiles profile (skills and tools for this repo) | Optional |
| Other `docs/*.md` | Architecture, API reference, runbooks | Linked from AGENTS.md's read order |

## Phase lifecycle

```text
Not started ─► Specced ─► Planned ─► Building ─► Gated ─► Done
   (idea)     (spec in   (levels 1   (PRs land)  (every build   (ROADMAP row says Done,
               phases/)   and 2                   box checked;   plan deleted, spec stays)
                          confirmed,              gate period         │
                          plan in                 running)            │ new criteria added
                          plans/)                                     ▼
                                                                  Building
Parked: deliberately stopped; the ROADMAP row says why and what would restart it.
```

A phase is done only when every criterion and anti-criterion box is checked with its evidence, not when its PRs merge. Gates that need time (a week of clean runs) are criteria too.

## The spec is the ideal state, and it outlives the work

A phase spec says what done looks like, not how to build it. The plan in `docs/plans/` is the how, and it is deleted when the phase is done. The spec stays.

- **Three levels.** **Done** is the least a user would accept. **Good** is what makes it clearly worth having. **Surprising** is what would make a user say "I didn't know it could do that". A person confirms Done and Good before any build starts, and the `**Confirmed.**` line records who, when and where. Surprising is a direction to aim at, never a gate.
- **Criteria** are small statements of done (`C1`, `C2`...). **Anti-criteria** are things that must never happen (`A1`, `A2`...). Each names the probe that would prove it false: a test, a `verify-<app>` journey, a query, a measurement. A criterion you can't probe isn't finished being written.
- **Cite ids across the repo** as `P1-C3` or `P1-A1`: in PR bodies, commits, test names and verify output. A PR says which criteria it moves and gives the evidence for each.
- **Adding a feature means adding criteria that don't pass yet.** If the new work extends a phase's outcome, add unchecked criteria to that spec and move its ROADMAP row back to Building. If it is a new outcome, it is a new phase.
- **Done phases are regression probes.** A change in an area a done phase covers reruns that phase's probes.
- **Ids are never reused.** A criterion that no longer applies loses its box and is struck through with a reason, `- ~~**C4.** old text~~ Dropped: <why>.`, so its id stays taken.

## Drafts

A statement no person has confirmed carries `(draft, from <source>)`. The checker counts these markers and doesn't fail on them; the human confirms drafts in PR review and a follow-up removes the markers.

## What goes where

- A product or preference call: ask the human with options, then record it as a decision.
- A fact you can observe (behavior, cost, timing): settle it by running something (beau-mode's Prototype playbook), then record it as a decision if it constrains the design.
- A spec that is wrong or silent: fix the spec in the same PR and say why in the PR body. Don't build past a gap.
- Anything a person must do: `HUMAN_TASKS.md`, with the phase or PR it blocks.
- A good idea outside the current phase: `IDEAS.md`.
