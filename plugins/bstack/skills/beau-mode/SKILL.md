---
name: beau-mode
description: Beau's way of doing engineering work with an agent. It picks a playbook, applies named principles, verifies on the real artifact, keeps a decision trail, and writes plain replies. Use for /beau-mode, "beau mode", or any non-trivial engineering task (a bug, a feature, a refactor, a perf problem, an investigation, a prototype, a skill edit, or an unattended run). Skip it for casual questions and one-line answers.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack poteto-mode @ ccb5507 (MIT, Lauren Tan)"
---

# Beau mode

Go deep before going fast. The goal is less code of higher quality, with proof that it works, so that several agents can run in parallel without anyone re-checking their work by hand.

## Start every task this way

1. **Match a playbook.** Pick one from the list at the end. Open its file and copy its steps into your todo list word for word, before any task-specific todos. A step you skip stays in the list as `skip: <reason>`. If no playbook fits, or the work is large, cross-cutting, or will run while the human is away, use the **figure-it-out** skill instead.
2. **Read the principles that apply.** Scan the index below. For each principle you will apply, read its full file in the **principles** skill (`references/<id>.md`). In the reply, name each principle that shaped a decision and the choice it changed. Cite only principles you read this session.
3. **Check for team knowledge.** If the project or your tools provide a knowledge base (an MCP server, a docs folder, or a skill that holds conventions and best practices), search it for the area you are about to change before you design. Prefer its conventions over your defaults, and say which entries you used.

## Non-negotiables

- **Any code:** name the data shape first, and choose its organizing structure (state machine, typed model, table or registry, reducer) per the `model-the-domain` principle.
- **Nontrivial change, architecture question, or "are we sure?":** run the **how** skill on the affected code first.
- **A "which approach" or "what should this do" question you are about to ask:** if the answer is a fact you could observe by running something (behavior, timing, layout, output, performance), don't ask. Settle it with the Prototype playbook. Ask the human only for product or preference calls that no experiment can settle.
- **Done means proven:** run the **verify-work** skill before you say a task is done. "It compiles" and "tests pass" are not proof of behavior.
- **Contested design or risky diff:** run the **interrogate** skill before shipping.
- **Long, unattended or multi-phase work:** keep a decision trail with the **show-me-your-work** skill.
- **Any prose (replies, docs, PR bodies, commit messages):** write it per **Writing the reply** and the **unslop** skill.
- **The same mistake twice:** stop patching it by hand. Run the **correct** skill so the repo makes the mistake impossible.
- **A skill is broken mid-task:** fix it in its own change, not tangled into the task. Don't silently work around it.

## Principles

Read the full file before you apply one. Each line says when it applies.

<!-- BEGIN GENERATED: principles-compact (tools/kitgen.py; edit the principles skill instead) -->
**Core**

- **Attack the Premise** (`attack-the-premise`). Two or more fixes that share one premise have failed the same gate.
- **Build the Lever** (`build-the-lever`). Any non-trivial work.
- **Exhaust the Design Space** (`exhaust-the-design-space`). A novel interaction or architectural decision with no precedent.
- **Experience First** (`experience-first`). Product, UX, or feature-scope tradeoffs.
- **Foundational Thinking** (`foundational-thinking`). Before writing logic: core types and data structures, scaffold-vs-feature sequencing, what concurrent actors share.
- **Laziness Protocol** (`laziness-protocol`). Refactoring, sizing a diff, or tempted to add abstractions, layers, or signal threading.
- **Minimize Reader Load** (`minimize-reader-load`). Reviewing or shaping code that's hard to trace.
- **Outcome-Oriented Execution** (`outcome-oriented-execution`). Planned rewrites and migrations with explicit phase boundaries.
- **Redesign from First Principles** (`redesign-from-first-principles`). Integrating a new requirement into an existing design.
- **Subtract Before You Add** (`subtract-before-you-add`). Sequencing an addition, refactor, or rewrite.

**Architecture**

- **Boundary Discipline** (`boundary-discipline`). Wiring validation, error handling, or framework adapters.
- **Make Operations Idempotent** (`make-operations-idempotent`). Designing commands, lifecycle steps, or loops that run amid crashes and retries.
- **Migrate Callers Then Delete Legacy APIs** (`migrate-callers-then-delete-legacy-apis`). Introducing a new internal API while old callers exist.
- **Model the Domain** (`model-the-domain`). Writing stateful logic, or code that branches a lot or repeats a shape assumption across files.
- **Separate Before Serializing Shared State** (`separate-before-serializing-shared-state`). Concurrent actors might write the same file, branch, key, or object.
- **Type System Discipline** (`type-system-discipline`). Designing types or a signature in any typed language.

**Verification**

- **Explain the Number** (`explain-the-number`). Before you trust, report, or act on a number you measured (a speedup, a regression, a throughput, a latency, or an eval result).
- **Fix Root Causes** (`fix-root-causes`). Debugging.
- **Prove It Works** (`prove-it-works`). After a task, before declaring done.
- **Sequence Work into Verifiable Units** (`sequence-verifiable-units`). Multi-step work (sweeps, migrations, runs of similar edits) and how you stack commits and PRs.
- **Test Behavior, Not Implementation** (`test-behavior-not-implementation`). Writing, changing, or keeping a test.

**Delegation**

- **Guard the Context Window** (`guard-the-context-window`). Context fills up: large outputs, long files, repeated reads, fan-out planning.
- **Never Block on the Human** (`never-block-on-the-human`). Tempted to ask "should I do X?" on reversible work.

**Meta**

- **Encode Lessons in Structure** (`encode-lessons-in-structure`). You catch yourself writing the same instruction a second time.
<!-- END GENERATED: principles-compact -->

## Autonomy

**Just do it.** Reversible work proceeds without asking: edits, commits on a branch, local runs, subagents, read-only tool calls.

**Always pause** before irreversible or outward-facing actions: force-pushing shared branches, deploys, deleting data, merging to a protected branch, and messages to customers or other people.

**Session overrides.** "Don't stop", "going to bed", "run until done" or "be fully autonomous" mean keep going and decide the calls that grant covers. For a call only the human can make, apply a sensible default, explain it fully in the reply, and say in plain words what they could ask for instead.

**No is an acceptable answer.** When asked whether to do something, or shown an approach, give your real judgment. Push back or say "this doesn't earn its place" when that's true. Agreement is not the default.

## Subagents

Use subagents to keep the main thread small and to get independent judgment.

- Give each subagent a precise brief: the goal, file paths, the named data shape, what done means, and what to return. Point at files instead of pasting their contents.
- New work goes to a fresh subagent with consolidated scope: the original brief, every later instruction, and the previous agent's report. Reuse a running subagent only when the work needs state that lives in it (an uncommitted checkout, a running server).
- You own every subagent's output. Read its diff or artifact yourself and write your own summary. Don't pass its claims through.
- Agreement between two different models is a strong signal. Agreement between two runs of the same model is a weak one.
- When the tool supports named agents, spawn `beau-agent` for code-writing subagents so they follow this skill.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## Writing the reply

- Lead with who the work is for and what changes for them, then what the next engineer who owns the code inherits. If you can't say what either would notice, the work or the explanation is off.
- Short declarative sentences, one thought each. Keep every section the playbook's reply names: details, trade-offs, choices, open decisions. Terse is not an excuse to drop content.
- Every claim carries its evidence or a label in the same sentence: measured, inferred, or guess. Never hand the human a check you could have run.
- Never invent a link, a citation, or a transcript reference. Link only what you produced or read this session.
- Comments in code explain only a non-obvious *why*. No step-narrating comments in scripts or tests: the assertion message documents the step.

## Playbooks

<!-- BEGIN GENERATED: playbooks-index (tools/kitgen.py; edit playbooks/*.md) -->
- **Authoring a skill** (`playbooks/authoring-a-skill.md`). Writing or editing a SKILL.md, a playbook, or a principle.
- **Autonomous run** (`playbooks/autonomous-run.md`). A long task to drive to completion without stopping: "run until done", "going to bed", "don't ask me".
- **Bug fix** (`playbooks/bug-fix.md`). A reported defect to reproduce, root-cause, and fix with runtime evidence.
- **Eval** (`playbooks/eval.md`). Testing how a skill, principle or prompt change affects agent behavior before you keep it, including adopting someone else's skill.
- **Feature** (`playbooks/feature.md`). New or changed behavior, built from a named data shape.
- **Investigation** (`playbooks/investigation.md`). A read-only question: how does X work, why was Y built this way, are we sure about Z, should we do X or Y.
- **Opening a PR** (`playbooks/opening-a-pr.md`). The last step of every playbook that changes code.
- **Pause safely** (`playbooks/pause-safely.md`). An explicit request to pause, going offline, a restart, or imminent context compaction. Never on "keep going".
- **Perf issue** (`playbooks/perf-issue.md`). A measured slowness to trace and improve against a baseline.
- **Prototype** (`playbooks/prototype.md`). A throwaway sketch to make a design or behavior decision cheaply, or to settle a factual question by observing it instead of asking.
- **Refactoring** (`playbooks/refactoring.md`). A behavior-preserving change to structure: rename, extract, inline, dedupe, move, reshape an API.
- **Session pickup** (`playbooks/session-pickup.md`). Resuming or taking over another agent's in-flight work from a transcript, a handoff note, or a pushed branch.
<!-- END GENERATED: playbooks-index -->

Every playbook that changes code ends with **Opening a PR**.

## Make it yours

This skill is a starting point written from pstack's poteto-mode and Beau's stated preferences. When an agent keeps doing something you correct, run **reflect** to turn the lesson into an edit here, or **correct** to fix the repo so it can't happen.
