---
name: create-formal-verification-skill
description: Generate a project-local verify-AREA skill that formally verifies the code where a bug costs the most and tests reach the least, in any language, with whichever verification tool fits (model checker, prover, SMT-backed verifier). Use for /create-formal-verification-skill, "model-check this race", "prove this invariant", or when concurrency, retries, state machines, parsers or unsafe code need more than tests.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack create-formal-verification-skill @ 246bc50 (MIT, Lauren Tan)"
---

# Create a formal verification skill

A test checks the cases someone thought to write. Formal verification checks every case in a stated scope: every order of steps in a model, every input up to a bound, or every input. This skill finds the part of the repo where that matters most, verifies one property of it, and leaves a project-local `verify-<area>` skill that lets the next agent check a change against that property. Write that skill for an agent who reads it cold, mid-change, and has never seen your work. The user must be able to trust the result and act on it without learning the verification language.

## 1. Choose the target from the code

Answer from the codebase. Ask the user only what you can't observe. If the user named an area or a bug, start there.

A good target is a promise the code makes, where a break harms users and tests rarely reach the case that breaks it. Choose the strongest such target in the repo, not the one that is easiest to verify. When **state-machines** has already written a spec for a machine with several writers, that machine is a strong candidate.

## 2. Let the question choose the tool

Pick the tool that answers the question at the lowest cost: a model checker, a proof assistant, an SMT-backed verifier, or another tool.

- **Can events happen in a bad order?** Usually a model checker over a small model of the design. TLA+ (or Quint) is the default for that in any language.
- **Does the code itself behave for every input** (memory safety, overflow, a data-structure invariant)? Usually a verifier that runs on the code. If no verifier runs on this language, say so, and test the real code with generated inputs, not a hand model of the function.
- **Must it hold at every size**, where a bound is not enough? That can need a proof.

Prefer a tool the repo's developers can install and run, and tell the user why you chose it.

## What makes it good

- **True to the code.** Every part of the model or proof points to code a reviewer can open. What the verification treats as one indivisible step is one indivisible step in the code. Names come from this repo.
- **Able to fail.** A check you have never seen fail proves nothing. Show each property failing on a broken variant of the code it guards, such as a removed check or a reordered step.
- **Findings stay findings.** When the current code breaks the property, report it with the counterexample in the code's terms. Don't weaken the property or the model until it passes, and don't change product code unless the user asks.
- **Honest about scope.** Say what is verified, under which bounds and assumptions, and what is left out. A pass covers the model or the bound, not the whole system.
- **Readable without the tool.** State the property and the harm in one plain sentence each. Tell a counterexample as a short sequence of steps in the code's words.
- **Cheap to rerun.** One command, a pinned tool version, and a run short enough that the next agent will use it on every relevant change.
- **Kept in step with the code.** Record which files and functions each check covers, and the commit at which you last confirmed the verification describes them. When covered code changes after that commit, the next agent can see the verification needs another look.

## 3. Generate the verify skill

Put it where every tool you use will load it:

- `.agents/skills/verify-<area>/` (Codex, Cursor, pi and OpenCode read `.agents/skills`).
- If anyone uses Claude Code on the repo, also link `.claude/skills/verify-<area>` to it (`ln -s ../../.agents/skills/verify-<area> .claude/skills/`). Claude Code reads only `.claude/skills`.
- If the repo already keeps skills somewhere else, follow that instead.

Write `SKILL.md` with frontmatter (`name: verify-<area>` and a `description` naming the area and when to use it; without frontmatter the skill never loads). Keep the model, harness and property files next to it or where the repo already keeps them. From the skill alone, the next agent must be able to:

- tell whether a change touches the verified code;
- run the check with one command;
- tell a real bug from a modeling error, by replaying the counterexample against the code;
- update the verification when a change is intended.

Put the coverage record and the sync commit in the skill, and tell the next agent to move the sync commit forward only after confirming the verification describes the code at the new commit. Use this repo's real commands, paths and nouns. Leave no placeholders.

## 4. Prove it before you hand off

Have a fresh `code` subagent follow the generated skill cold, as the next agent would, on a scratch change that breaks the property in the real code. Give it only the skill path and the scratch change, not your notes. It must catch the break. Then drop the scratch change and confirm the check is back where it started: passing, or failing only on the findings you will report. A verify skill that was never run is a draft. If it misses the break or a step doesn't run, fix the skill or the verification, not the scratch change.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## 5. Hand it over

Commit the skill and its verification files on a branch and run **Opening a PR** from **beau-mode**.

**Reply:** what you verified, which tool and why, the bounds, what the check found in plain words, how to run it, and what it doesn't cover. Suggest a second target only if you found a close one. Point the user at **maintain-formal-verification-skill** for bringing the verification back in line after changes that didn't recheck it.
