---
name: swarm
description: Fan out N parallel workers (local subagents, or cloud agents where your tool has them), wait for all of them, and return one consolidated report. Use for /swarm, "swarm this", parallel coverage of many slices, races of N attempts at one brief, live-verification lanes, fuzzing, or collecting enough perf samples to trust a number.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack swarm @ 11713c6 (MIT, Lauren Tan)"
---

# Swarm

Start N parallel workers. They cover separate slices, race the same brief, or both. You wait, aggregate, and return one report.

Open a todo list with one entry per phase before starting anything: Frame, Fan out, Aggregate, Report.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## Phase A: Frame

1. State the done predicate and the report the swarm returns.
2. Choose the shape: split the work into slices, race N workers on identical briefs, or mix both. For a race, declare the selection rule before starting: `first pass`, `rank all` or `best-of`.
3. Set N from the user, or derive it from the shape. N is the total number of workers, not how many run at once.
4. Pick the worker role: `explorer` for workers that read, drive or measure, `code` for workers that write code. For a model race, name each arm's model up front.
5. Give each worker that writes its own worktree or output folder (`separate-before-serializing-shared-state`). When workers verify or measure commits, each brief names the exact SHAs. A measurement brief also names the method: sample count, what one sample is, and the order (interleave baseline and change). The worker records both in its result.

Uses that earn a swarm:

- **Perf sample size.** One run of a benchmark is an anecdote. Ten lanes, each interleaving baseline and change, give a distribution (`explain-the-number`).
- **Fuzzing and gauntlets.** Each lane drives the app through the project's verification skill with a different scenario or input family, trying to break it.
- **Live verification lanes.** One lane per user scenario at a PR head, each saving a screenshot and checking a pass predicate.
- **Coverage.** One lane per package, route or feature file.

## Phase B: Fan out

Start all N workers at once, in the background if your tool can. Where your tool offers cloud or remote agents, prefer them for workers that run the app or a build, so lanes don't fight over ports and CPU on one machine. Use local workers when the job needs something only on the user's machine.

Every brief stands alone: the goal, the scope, the exact slice or race arm, how to verify, and what to report. Reports use `PASS`, `ISSUES` or `BLOCKED` with evidence. A worker that can prove a defect reports `ISSUES` and lists every issue it can prove, not only the first.

If a worker drops out, continue with N-1 and note it.

## Phase C: Aggregate

Read every final result. Drop a result that doesn't record the SHAs and method its brief named, and restart that worker once. After a second miss, record a gap. A gap is not a pass. For coverage, every slice needs a result. For a race, apply the rule you declared. Don't paste raw worker output.

## Phase D: Report

One consolidated report: a compact result table, one line per proven issue with its evidence, gaps and dropouts, the race rule if used, and which models and environments ran the lanes.
