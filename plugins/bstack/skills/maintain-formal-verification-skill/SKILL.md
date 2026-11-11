---
name: maintain-formal-verification-skill
description: Bring a project's formal verification back in line with the code after the code changes. Finds the commits that touched verified code, updates the model, harness or properties to describe the code as it is now, reruns, and says whether each failure is drift in the verification or a bug in the code. Use for /maintain-formal-verification-skill, "is the model still true to the code", or after merges and refactors that touched verified code without rechecking it.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack maintain-formal-verification-skill @ 246bc50 (MIT, Lauren Tan)"
---

# Maintain a formal verification skill

A formal check proves a property of what it describes. When the code changes and the verification doesn't, the check can keep passing while it describes code that no longer exists. That pass is the dangerous case, because it looks like a proof.

This is the upkeep loop for a verify skill made by **create-formal-verification-skill**, or any project-local skill that runs a model checker, prover or code-level verifier against named code. The project-local skill handles a change an agent makes while using it. This skill handles the changes that skipped it: merges, edits made without the skill, and drift that builds up across many commits.

## Outcomes

Give each check one outcome, and say which:

- **in sync**: no change since the last sync alters what the check describes, and the check passes.
- **updated**: the code changed, the verification now describes the new code, and the check passes.
- **bug**: the verification describes the current code, and the code breaks the property. This is a finding about the code, not drift.
- **blocked**: the check couldn't be brought back in line or couldn't run. Say exactly why.

A check can be both **updated** and **bug**: the update makes the verification describe the code again, and then the property fails on it.

## Edit scope

Edit only the verification: models, harnesses, property files, and the verify skill itself. Never edit product code during a run unless the user asks. When a property fails on the current code, don't weaken the property or the model to make it pass. Report the failure.

## Pass

1. **Find the checks.** A verify skill has no fixed name, so find it by what it does: a project skill, usually under `.agents/skills/verify-*/` or `.claude/skills/verify-*/`, that runs a model checker, prover or other verifier against named code. Paths that resolve to the same folder are one target. Read each one you find, or the one the user named. For each check, collect the property, the code it covers, the bounds and assumptions, the command that runs it, and the commit where it was last confirmed to describe the code. If no verify skill exists, stop and point at **create-formal-verification-skill**. If the skill records no sync commit, use the last commit that changed the verification files, and say so.

2. **Run it as it is.** Run each check once before you change anything, and record the result. A pass here doesn't mean the code is correct. It means the old description still holds. A failure here can be drift or a bug. Don't decide which until step 5.

3. **Read every change to covered code.** Diff the covered files from the sync commit to the current commit, and read each commit message. Also look for code that moved: a covered function that is renamed, split or moved to another file is still covered code. Also look for new code that touches the state a check guards, such as a new function that writes the same fields. When many files or checks are covered, start one read-only `explorer` subagent per check to do this reading and return the classified changes with file and line citations. Classify each change as one of:
   - **No effect.** It doesn't alter anything the verification describes (formatting, comments, paths the verification doesn't cover). Check this against the model or harness, not against the commit message.
   - **The verification no longer describes the code.** A step that was one indivisible action is now two, a branch was added or removed, a check moved, a new path reaches the guarded state, or a value now has a different range. The model or harness must change.
   - **The promise changed on purpose.** The change alters what the code promises, and evidence in the change says it is intended: the doc comment, the tests, the changelog or the commit message. The property must change, and you must cite that evidence.
   - **The promise may be broken.** The code changed, and no evidence says the promise changed. Treat a failure that follows as a bug candidate.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

4. **Update from the code, not from the result.** Change the model or harness so each changed part again points to code a reviewer can open, and keep one indivisible step in the code as one step in the verification. Write the update from the code before you rerun, and don't shape it by what makes the check pass. Change a property only for a promise that changed on purpose: write down the old wording, the new wording and the evidence. Keep the bounds unless the change makes them wrong. If you must reduce a bound, say so in the report.

5. **Rerun and judge each result.**
   - **Pass:** the check may now pass on a description that has lost the ability to fail. Break the new code the way the property guards against, such as removing a new check or reordering a new step, and confirm the check catches it. Then drop the break.
   - **Fail:** replay the counterexample against the real code, step by step. If a step can't happen in the code, the verification is wrong: fix it and say what was wrong. If every step can happen, it is a bug. Name the commit that introduced it, tell the counterexample as steps in the code's own words, and state the harm in one sentence. If a cheap test or reproduction against the real code shows the bug, add it to the report as evidence. Don't commit it to the product code.

6. **Update the verify skill.** Update the code each check covers, the commands, the bounds, the assumptions and the sync commit. Set the sync commit to the commit you checked. Don't move the sync commit for a blocked check, and say so in the report. Then follow the verify skill once as the next agent would, so you know its steps still run.

7. **Ship.** Put the verification updates in a PR of their own, separate from any product fix, with **Opening a PR** from **beau-mode**. If every check is **in sync**, open no PR.

**Reply:** for each check:

- the outcome, and the commits you read;
- what changed in the verification and why, with a short reason per change: the code changed shape, or the promise changed on purpose (with the evidence);
- the rerun result, and the break you used to show the updated check can still fail;
- each bug in plain words: the counterexample as steps in the code's words, the harm, and the commit that introduced it;
- what the verification still doesn't cover, including new code it should cover and doesn't.

Say outright which failures were drift in the verification and which were bugs in the code. For a check that passed before you updated it and fails after, say the old pass was on a stale description.
