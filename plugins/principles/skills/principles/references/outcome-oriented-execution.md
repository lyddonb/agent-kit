---
id: outcome-oriented-execution
title: Outcome-Oriented Execution
group: core
when: "Planned rewrites and migrations with explicit phase boundaries."
rule: "Converge on the target architecture, don't preserve throwaway compatibility states."
source: pstack/skills/principle-outcome-oriented-execution @ ccb5507 (MIT, Lauren Tan)
---
# Outcome-Oriented Execution

Optimize for the intended, verifiable end state rather than preserving smooth intermediate states.

**Why:** Keeping every intermediate step fully stable often creates temporary compatibility code that becomes long-lived debt. Converge on the target architecture and prove correctness at explicit verification boundaries.

**Core rule:**
- Prioritize end-state integrity over transitional stability
- Intermediate breakage is acceptable when it is planned, scoped, and reversible

**Guardrails:**
- Use this for planned rewrites and migrations with explicit phase boundaries
- Declare where temporary breakage is acceptable
- Keep high-signal checks for actively touched areas while migrating
- Require full static and runtime verification at plan completion
