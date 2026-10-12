---
id: prototype
title: Prototype
when: "A throwaway sketch to make a design or behavior decision cheaply, or to settle a factual question by observing it instead of asking."
source: pstack/skills/poteto-mode/playbooks/prototype.md @ ccb5507
---

# Prototype

**You own the decision, not the code.** The prototype is a throwaway instrument. Speed beats polish here: no tests, no abstractions, no production framework. The real build follows the Feature playbook.

1. Name the decision the prototype exists to make (which layout, which interaction, which behavior or timing). No decision means no prototype.
2. When the design space is open, gather prior art and let the human pick directions before building. Skip this when the direction is set.
3. Build in a scratch directory outside production code, with the lightest stack that shows the idea: plain HTML/CSS/JS for visuals, the smallest script for behavior or timing.
4. When comparing alternatives, put them behind one switcher with labeled variants (`exhaust-the-design-space`).
5. Observe the thing you are deciding: screenshot each variant and drive the interaction, or log the timing and print the output.
6. Don't run an adversarial review on the idea before the prototype answers it: reviewers of abstract plans invent risks. Let the evidence settle it.
7. Present the variants, evidence, trade-offs and a recommendation. Hand the chosen direction to Feature.

**Reply:** the variants, the evidence (screenshots or observed output), trade-offs, your recommendation, and the scratch path. Say plainly that the prototype is throwaway.
