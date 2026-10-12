---
name: architect
description: Design before code. Ground in the affected systems, sketch types and signatures in at least two structurally different shapes (via arena), pick one, implement against it, and scrap it when friction shows the shape is wrong. Use for /architect, "design this", or work where jumping to code would lock in the wrong shape.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack architect @ 11713c6 (MIT, Lauren Tan)"
---

# Architect

Sketch the types, function signatures, class shapes and module boundaries, with `not implemented` bodies and pseudocode. Compare candidates from different models, then fill in code against the chosen sketch. This is planning with code: the sketch is concrete enough to check, and cheap enough to throw away.

Open a todo list with one entry per phase before starting: Ground, Sketch, Agree, Implement, Scrap.

## Phase A: Ground the problem

Build a real mental model of every system the new code touches. Run the **how** skill over those subsystems; naming a file isn't grounding. If the design changes ownership or layering, also run the **why** skill on the current shape, so its reasons become constraints instead of guesses. Check the knowledge base, if there is one, for conventions in the area.

Skip this phase only for greenfield work with nothing around it to integrate.

## Phase B: Sketch

Run the **arena** skill with the design-sketch task and the Phase A findings. Give each runner [references/runner-prompt.md](references/runner-prompt.md) as its prompt.

- **Design it twice.** Require at least two structurally distinct candidates before synthesis, even when the first looks good enough (`exhaust-the-design-space`). Whole-shape alternatives, not tweaks inside one shape.
- **Screen for red flags.** Check every candidate against [references/design-red-flags.md](references/design-red-flags.md). Assume the next contributor is an agent that sees only the files it opened, copies the nearest example, and takes the shortest path that compiles. Prefer the design where a change that looks right from one file is right for the whole repo.
- **Compare interface depth.** Prefer the design that hides more complexity behind a smaller, simpler public surface.

Arena returns one synthesized design. Its synthesis note fills the rationale's "Synthesis decision" section.

## Phase C: Agree (opt-in)

By default, go straight to implementation with no human checkpoint. Stop for sign-off only when asked: "/architect with checkpoint", "show me before implementing", or similar.

The sketch can ship as its own commit either way (scaffold first, per `foundational-thinking`). Planned breakage while filling it in is fine (`outcome-oriented-execution`). Don't run an adversarial review on an abstract sketch: reviewers invent theoretical risks for code that doesn't exist yet. Settle open questions with a prototype instead, and save **interrogate** for the implemented diff.

If the human pushes back on the shape, treat it as Phase A evidence: re-ground and rerun Phase B before writing more code.

## Phase D: Implement against the sketch

Replace `not implemented` bodies with code and pseudocode with logic. The sketch is the contract. A deviation is a signal to raise, not friction to absorb quietly. If a function needs a parameter the sketch didn't plan for, ask whether the sketch was wrong, the requirement was missed, or the implementation is overreaching.

## Phase E: Scrap when the shape is wrong

If implementation keeps producing friction the sketch can't absorb, throw the sketch out. Don't bolt fixes onto a wrong design (`redesign-from-first-principles`, `fix-root-causes`). The signal is a pattern, not one instance:

- The same workaround showing up across unrelated code.
- Several unrelated edge cases that each need a special branch.
- Types that need escape hatches (`any`, casts, optional fields that are always set) to compile.
- Reaching for a lock when the sketch said the state wasn't shared.
- Callers needing to know the abstraction's internal rules.
- Two or more independent deviations of the same shape in Phase D.

Use judgment. A few edge cases don't condemn a design, and complexity in the data is not complexity in the design.

When you scrap:

1. Rerun **how** over what's been built.
2. Redesign as if the new constraints had been there from day one.
3. Subtract before adding (`subtract-before-you-add`). The new sketch should be smaller than the old one before it grows.
4. Go back to Phase B.

## Output

Write the caller's usage first and derive the type sketch from it. For small changes, one file with the new types and signatures. For larger work, a module map plus type definitions. Ship the rationale next to it, shaped by [references/rationale-template.md](references/rationale-template.md), including the usage sketch and the synthesis decision.
