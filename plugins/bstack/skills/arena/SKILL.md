---
name: arena
description: Run N parallel candidates at the same task (ideally on different models), have a judge on another model score them against a rubric, pick a base, and graft the best parts of the others into it. Use for /arena, "arena this", "throw it in the arena", or when one attempt at a non-trivial artifact (a design, an API, a doc, a tricky function) would lock in the wrong shape.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack arena @ 11713c6 (MIT, Lauren Tan)"
---

# Arena

Open a todo list with one entry per phase (Frame, Fan out, Cross-judge, Pick, Graft, Verify) before starting anything.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## Phase A: Frame

Every candidate gets the same prompt, so the prompt is the contract.

1. State the artifact each candidate produces.
2. Write the rubric: 3 to 6 concrete, gradeable criteria for success on this task. It is the picker's tool in Phase D. Candidates see only the task, not the rubric.
3. Pick the runners: one candidate per `reviewers` entry for your tool. With fewer than two entries, run one on the current model and one on a different model your tool offers. If you can't choose models, run two on the current model and say in the reply that the candidates came from one model. Add runners when the arena covers several design directions. Repeat one model when the work is mostly generation rather than judgment.
4. Give each candidate its own output location: a git worktree where possible, otherwise `<scratch>/arena-<slug>/candidate-<n>/` (`separate-before-serializing-shared-state`).

## Phase B: Fan out

Start all N subagents at once, in the background if your tool can. Each gets the task, the path to the shared grounding, its own output path, and instructions to produce the artifact plus a short rationale naming the alternatives it considered and rejected.

If a candidate produces nothing, continue with N-1 and note the dropout.

## Phase C: Cross-judge

After every candidate finishes, start one read-only judge on a model different from yours: a `reviewers` entry from another model family if there is one. Otherwise follow the roles rules for "a different model". The judge sees the rubric and the candidates by path label, scores each criterion, and recommends a base with its reasons. Let it run while you read in Phase D. Don't start it while candidates are still writing.

## Phase D: Pick a base

Read every candidate end to end before picking. Score each against the rubric criterion by criterion, not by overall feel, and compare with the judge. Agreement confirms the pick. Disagreement means one of you is biased or the rubric was ambiguous: read both rationales before deciding.

Pick the base a future maintainer can extend most easily without breaking its invariants. When two feel tied, prefer the cleaner boundary or the smaller API (`laziness-protocol`).

## Phase E: Graft

Walk each losing candidate once more for what's worth porting into the base, usually one or two things per candidate. Fold each graft in by hand so the result stays coherent under one mental model (`redesign-from-first-principles`). Don't paste mechanically.

If the candidates converge on one shape, that's strong agreement: note it and ship the shared shape with no graft. If they diverge wildly, Phase A was under-specified. Reframe and rerun rather than averaging.

## Phase F: Verify

Verify the result like any other output (`prove-it-works`, **verify-work**). If verification finds a problem the arena missed, either Phase A was wrong (reframe and rerun) or a candidate caught it and you missed the graft (go back to Phase E). Don't paper over it.

## Output

One synthesized artifact, with a short synthesis note: the base and why, the judge's verdict, each graft and its source candidate, what was rejected and why, any convergence or dropouts, which models ran, and the verification result.
