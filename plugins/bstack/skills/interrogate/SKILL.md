---
name: interrogate
description: Adversarial multi-model review of a diff, branch, PR or design. Several adversaries try to break it, and a finding survives only when a run proves it. Use for "interrogate", "adversarial review", "tear this apart", "stress test this change", "find blind spots", or before shipping a contested or risky change.
license: MIT
metadata:
  author: lyddonb
  version: "0.2.0"
  upstream: "pstack interrogate @ 246bc50 (MIT, Lauren Tan)"
---

# Interrogate

Adversaries try to break a change or a design. A finding survives only when a run proves it, so the user never gets a risk they have to check by hand. Report the findings. Don't apply fixes unless asked.

## 1. Frame

The scope is what the user names. Otherwise it is the branch diff from its merge base with the base branch, through the working tree. State the intent in one paragraph from the user's words, the commits and the PR description: the goal and the problem it solves. If the intent is unclear, ask before reviewing.

## 2. Fan out

Start one adversary per entry in the `reviewers` role, all at once, in the background if your tool can. Give each its own git worktree at the scope's head with the scope's uncommitted changes copied in (`separate-before-serializing-shared-state`), so repros don't collide.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

With no `reviewers` entry for your tool, run two adversaries on the current model and say the panel was not diverse.

Give each adversary the scope, the intent, its worktree path, and this brief:

> Break this change. Prove each finding with a run against the real code, such as a failing test, a repro script, or command output that shows the wrong behavior. For a design or plan, run a prototype or probe the current tree. Keep repros in your own worktree. Report each finding with a title, the exact command, the output it printed, and the output the intent requires. Leave out anything you did not run. That covers style, naming, structure, and risks that need a future change to matter. No findings is a valid result.

If an adversary returns nothing, continue without it and note the dropout.

## 3. Verify

Rerun each finding's command yourself. Keep a finding when the output shows the failure and the failure breaks the intent. Drop the rest, including findings whose command you can't reproduce. Merge findings that share a root cause.

Adversaries find different failures, so the verdict keeps every verified finding, not one adversary's list. Clean up the worktrees after you have the outputs you need.

## Output

- **Intent**: the paragraph from step 1.
- **Adversaries**: one line each, model and finding count.
- **Findings**: for each verified finding, the command, its output, how it breaks the intent, and the adversaries that found it. Say "no verified findings" when none survive.
- **Dropped**: for each adversary, the count of dropped findings and why.
