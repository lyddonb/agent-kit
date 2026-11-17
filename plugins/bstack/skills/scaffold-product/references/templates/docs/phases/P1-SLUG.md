# P1. {{First slice}}

**Outcome.** {{What a user will notice when this ships, in one or two sentences.}}

**Serves.** {{G1}}. **Depends on.** {{Nothing, or a phase or human task.}}

## Ideal state

1. **Done.** {{The least a user would accept as finished.}}
2. **Good.** {{What makes it clearly worth having.}}
3. **Surprising.** {{What would make a user say "I didn't know it could do that". A direction to aim at, not a gate.}}

**Confirmed.** {{Not yet. Or: levels 1 and 2 by whom, when and where, for example "Beau, 2026-11-16, PR #12".}}

## Scope

In:

- {{The smallest slice that delivers the outcome end to end. The first PR sets up the project skeleton and the verify-APP skill.}}

Out (later phases): {{what this phase deliberately leaves out}}.

## Behavior

{{Numbered steps or rules precise enough to test. Commands, inputs, outputs, error cases.}}

## Cost

{{Model calls, services or other spend per run, or "None".}}

## Criteria

Small, testable statements of done. Each names the probe that would prove it false. Check a box only with its evidence.

- [ ] **C1.** {{A statement a user would agree means done.}} Probe: {{the run, test or measurement that would show it is false}}.
- [ ] **C2.** `ROADMAP.md` marks P1 done. Probe: `check-product.py` reports 0 problems.

## Anti-criteria

What must never happen, whatever the criteria say. Each names the probe that would catch it.

- [ ] **A1.** {{Something that must never happen, for example "an import never writes a row twice".}} Probe: {{how you would catch it happening}}.

## Suggested PR slices

The plan decides, but roughly: (1) skeleton, CI and the verify skill; (2) {{...}}.
