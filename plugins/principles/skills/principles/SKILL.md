---
name: principles
description: Named engineering principles (prove it works, fix root causes, subtract before you add, build the lever, and 20 more) that steer how an agent designs, builds and verifies. Use when a task or the user names a principle, when beau-mode tells you to apply one, or when deciding how much to build, where state and validation live, or what counts as proof.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack @ ccb5507 (MIT, Lauren Tan)"
---

# Principles

Each principle is one short rule with a trigger. They exist so that a person can steer an agent with a name ("apply prove it works") and so that an agent can say exactly which rule changed which decision.

## How to use them

1. Find the principles whose **When** matches the work in the index below.
2. Read the full file for each one you apply, from `references/<id>.md`. The index line is a reminder, not the rule.
3. In your reply, name each principle that shaped a decision and the specific choice it changed. Cite only principles whose file you read in this session. A citation with no decision behind it is name-dropping.
4. When the user names a principle mid-task, read it and redo the affected step under it.

Groups: **core** (how much to build, when to rethink), **architecture** (where state, validation and compatibility live), **verification** (what counts as proof), **delegation** (parallel work and autonomy), **meta** (turning lessons into structure).

## Index

<!-- BEGIN GENERATED: principles-index (tools/kitgen.py; edit references/*.md instead) -->
| Principle | Group | When | Rule |
|---|---|---|---|
| [Attack the Premise](references/attack-the-premise.md) (`attack-the-premise`) | core | Two or more fixes that share one premise have failed the same gate. | Take a census of which actors hold the imbalance before the next fix, then question the premise instead of writing another fix that assumes it. |
| [Build the Lever](references/build-the-lever.md) (`build-the-lever`) | core | Any non-trivial work. | Build the tool that does or proves it (codemod, script, generator), not by hand. The tool is the artifact a reviewer reruns. |
| [Exhaust the Design Space](references/exhaust-the-design-space.md) (`exhaust-the-design-space`) | core | A novel interaction or architectural decision with no precedent. | Build 2-3 competing prototypes and compare before committing. |
| [Experience First](references/experience-first.md) (`experience-first`) | core | Product, UX, or feature-scope tradeoffs. | Choose user delight over implementation convenience. |
| [Foundational Thinking](references/foundational-thinking.md) (`foundational-thinking`) | core | Before writing logic: core types and data structures, scaffold-vs-feature sequencing, what concurrent actors share. | Get the data structures right so downstream code becomes obvious. |
| [Laziness Protocol](references/laziness-protocol.md) (`laziness-protocol`) | core | Refactoring, sizing a diff, or tempted to add abstractions, layers, or signal threading. | Bias to deletion and the smallest change that solves the problem. |
| [Minimize Reader Load](references/minimize-reader-load.md) (`minimize-reader-load`) | core | Reviewing or shaping code that's hard to trace. | Count layers and hidden state, collapse one-caller wrappers, shrink mutable scope. |
| [Outcome-Oriented Execution](references/outcome-oriented-execution.md) (`outcome-oriented-execution`) | core | Planned rewrites and migrations with explicit phase boundaries. | Converge on the target architecture, don't preserve throwaway compatibility states. |
| [Redesign from First Principles](references/redesign-from-first-principles.md) (`redesign-from-first-principles`) | core | Integrating a new requirement into an existing design. | Redesign as if it had been foundational from day one. |
| [Subtract Before You Add](references/subtract-before-you-add.md) (`subtract-before-you-add`) | core | Sequencing an addition, refactor, or rewrite. | Remove dead weight first, then build on the simpler base. |
| [Boundary Discipline](references/boundary-discipline.md) (`boundary-discipline`) | architecture | Wiring validation, error handling, or framework adapters. | Guards at system boundaries, trust internal types, keep business logic pure. |
| [Make Operations Idempotent](references/make-operations-idempotent.md) (`make-operations-idempotent`) | architecture | Designing commands, lifecycle steps, or loops that run amid crashes and retries. | Converge to the same end state. |
| [Migrate Callers Then Delete Legacy APIs](references/migrate-callers-then-delete-legacy-apis.md) (`migrate-callers-then-delete-legacy-apis`) | architecture | Introducing a new internal API while old callers exist. | Migrate and delete in one wave. |
| [Model the Domain](references/model-the-domain.md) (`model-the-domain`) | architecture | Writing stateful logic, or code that branches a lot or repeats a shape assumption across files. | Encode the domain in a structure (state machine, typed model, table or registry, reducer, boundary, the right collection) instead of scattered conditionals. |
| [Separate Before Serializing Shared State](references/separate-before-serializing-shared-state.md) (`separate-before-serializing-shared-state`) | architecture | Concurrent actors might write the same file, branch, key, or object. | Eliminate the sharing first. |
| [Type System Discipline](references/type-system-discipline.md) (`type-system-discipline`) | architecture | Designing types or a signature in any typed language. | Make illegal states unrepresentable, brand primitives, parse external data at boundaries. |
| [Explain the Number](references/explain-the-number.md) (`explain-the-number`) | verification | Before you trust, report, or act on a number you measured (a speedup, a regression, a throughput, a latency, or an eval result). | Find what limits it, and rule out that it measured something other than the work you think. |
| [Fix Root Causes](references/fix-root-causes.md) (`fix-root-causes`) | verification | Debugging. | Trace each symptom to its root cause, reproduce first, ask why until you reach it. |
| [Prove It Works](references/prove-it-works.md) (`prove-it-works`) | verification | After a task, before declaring done. | Verify against the real artifact, not a proxy or "it compiles". |
| [Sequence Work into Verifiable Units](references/sequence-verifiable-units.md) (`sequence-verifiable-units`) | verification | Multi-step work (sweeps, migrations, runs of similar edits) and how you stack commits and PRs. | Break work into small units that each end in a check, verify each before the next, and order delivery so the sequence proves itself. |
| [Test Behavior, Not Implementation](references/test-behavior-not-implementation.md) (`test-behavior-not-implementation`) | verification | Writing, changing, or keeping a test. | Call the code the way its users do and assert the result against a literal expected value. If the test would still pass when every imported function returns `undefined`, rewrite the assertion or delete the test. |
| [Guard the Context Window](references/guard-the-context-window.md) (`guard-the-context-window`) | delegation | Context fills up: large outputs, long files, repeated reads, fan-out planning. | Route bulk to subagents, keep summaries in the main thread. |
| [Never Block on the Human](references/never-block-on-the-human.md) (`never-block-on-the-human`) | delegation | Tempted to ask "should I do X?" on reversible work. | Proceed, present the result, let the human course-correct. |
| [Encode Lessons in Structure](references/encode-lessons-in-structure.md) (`encode-lessons-in-structure`) | meta | You catch yourself writing the same instruction a second time. | Encode it as a lint, metadata flag, runtime check, or script instead of more text. |
<!-- END GENERATED: principles-index -->

## Supporting checklists

- [Benchmark checklist](references/checklists/benchmark.md): seven questions to answer before you trust or report a measured number.

## Provenance

The first 24 principles are adapted from Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT). Each file's `source` field records the upstream path and commit. Edits here are ours. See `docs/UPSTREAM.md` in agent-kit for how upstream changes are reviewed.
