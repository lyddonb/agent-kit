# AGENTS.md

Instructions for coding agents building {{product}}. `CLAUDE.md` imports this file; keep it the only instruction file.

## Read before you start

1. [README.md](README.md) for what this is and how to run it.
2. [docs/VISION.md](docs/VISION.md) for the goals (G1, G2, ...) and non-goals.
3. The phase spec you are working on, in `docs/phases/`, and its plan in `docs/plans/` if one exists.
4. [docs/DECISIONS.md](docs/DECISIONS.md) before you change anything it covers. To reverse a decision, add a new one. Don't edit the old one.

## How to work a phase

Use beau-mode's **Product phase** playbook:

```text
/beau-mode advance docs/phases/P1-{{first-slug}}.md
```

- The phase spec is **what** to build and how we know it works. The plan is **how**: small PRs, each with evidence.
- Every PR proves its behavior through the `verify-{{app}}` skill and puts its output in the PR body.
- If the spec is wrong or silent, fix the spec in the same PR and say why. Don't build past a gap.
- Product or preference questions go to a person with options. Settle anything you can observe (behavior, cost, timing) by running something.

## Stack and commands

```bash
{{install command}}
{{test command}}
{{lint and type-check commands}}
{{run command}}
```

## Rules

- {{The rules that, if broken, are bugs whatever the tests say. Start with data safety and secrets.}}
- Secrets come from the environment, never from a tracked file.

## Definition of done (every PR)

- Lint, types and tests pass.
- `verify-{{app}}` passes and its output is in the PR body.
- New behavior has a test. A bug fix has a test that failed first.
- Docs updated in the same PR: the phase spec's acceptance boxes, `ROADMAP.md` status, and `docs/DECISIONS.md` if you made a call.
- `python3 <scaffold-product skill folder>/scripts/check-product.py .` reports 0 problems.
