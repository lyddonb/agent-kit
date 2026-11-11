---
name: state-machines
description: Find the implicit state machines in a codebase (lifecycles spread across booleans, status strings, nullable fields, effects and handlers), show which states conflict with exact lines, then make them explicit as a checked spec and a pure transition function with IO at the edge. Use for "find all the implicit state machines in my app", "which states can conflict", "make this state explicit", "model this as a state machine", "review this state machine", or before an agent builds anything with a lifecycle (loading/error, forms, modals, auth, checkout, uploads, jobs, sync, agent loops).
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# State machines

Apps are full of state machines: "in this state, when this event happens, go to that state." When that logic is spread across flags and handlers, nobody can list the possible states, so states that should be impossible ship. Tests and review pass because they cover the paths someone thought of. Making a machine explicit does not make it correct. It makes the whole logic enumerable, so types, tests and model checks can enforce it.

Pick the modes the request needs. "Find them" is Hunt alone. "Fix this one" is Formalize then Make explicit. Building something new with a lifecycle starts at Formalize.

## 1. Hunt

1. Run `scripts/find-candidates.sh <dir>` for ranked leads. It only greps. Read every file before calling it a machine.
2. Read [references/signals.md](references/signals.md). For each machine, find every place its state lives and every writer, then run the conflict probes. For a large repo, start one `explorer` subagent per area with signals.md and the candidate list for that area.
3. A finding is a concrete event sequence, the exact lines that allow it, and the bad state it reaches. Label each one **confirmed**, **latent** or **suspected** as signals.md defines them. Reproduce anything whose outcome depends on framework scheduling; traces of React batching and router reuse are often wrong. Never change code on a suspected finding.
4. Report one table of all machines, ranked by risk, as signals.md shows. Hunt mode stops here and offers to formalize the top machine.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## 2. Formalize

Write the machine as a spec before touching code, following [references/spec-format.md](references/spec-format.md): declared states and events, a transition table where every state x event cell is a decision, plus invariants, interruptions and assumptions. Model today's behavior first, including its bugs (mark the invariants it violates), then the intended one, so the diff between the two tables is the fix list. Filling every cell is where new findings come from: each one you could not answer from the code is a probe to run.

Run `scripts/check-machine.py SPEC.md --matrix` until it reports no problems. Every `??` cell, unreachable state and trap state is a question the code never answered.

Show the human the matrix, the Mermaid diagram (`--mermaid`), the confirmed findings and the assumptions list. Their verdict on each assumption goes into the spec word for word. When the change alters behavior, wait for this review before writing code: rejecting a row is cheap now and expensive after.

## 3. Check deeper (when the risk warrants it)

- One pure transition function: property tests over random event sequences, asserting every invariant after each step.
- Several writers or processes and no single pure core (claims, locks, queues, sync, multi-agent handoffs): model it in Quint or TLA+ and let the model checker search for a sequence that breaks an invariant. Report each counterexample as a design flaw (with the change it calls for) or a modeling mistake. To keep that check in the repo as a project skill the next agent reruns, use **create-formal-verification-skill**, then **maintain-formal-verification-skill** after changes that skipped it.

## 4. Make explicit

Follow [references/refactor.md](references/refactor.md). State becomes one discriminated union. Events become one union, parsed at the boundary. All decisions move into one pure `transition(state, event) -> (state, effects)` with exhaustive matching. A thin shell runs the effects and feeds results back as events. Surfaces (components, routes, handlers, commands) only translate input into events and render state.

- Generate table-driven tests from `check-machine.py SPEC.md --json`, one per row, so the spec and the tests can't drift.
- Route every writer through the transition function, then delete the old flags in the same PR as the last caller.
- Keep the spec next to the code and update it in the same change as any new state or event.

Prove it with **verify-work**: drive the confirmed findings' event sequences against the real app and show each one now lands in the intended state.

## When not to

A single boolean that is local, has two meaningful values, and is unlikely to grow is already explicit. Don't wrap it. Don't adopt a statechart library for a four-state machine. The test is whether the new shape removes reachable illegal states, duplicated guards or lifecycle bugs. If it removes none, leave the code alone.

**Reply:** for Hunt, the inventory table with confirmed and suspected findings. For Formalize, the spec path, the checker output, the matrix and the open assumptions. For Make explicit, what moved into the pure core, which flags were deleted, and the verify-work verdict.
