---
name: interrogate
description: Adversarial multi-model review of a diff, branch or PR. Several independent reviewers try to break it, then a lead reviewer sorts findings into act on, consider, noted and dismissed. Use for "interrogate", "adversarial review", "tear this apart", "stress test this change", "find blind spots", or before shipping a contested or risky change.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack interrogate @ ccb5507 (MIT, Lauren Tan)"
---

# Interrogate

Several reviewers attack the same change independently. The signal comes from model diversity, not from assigned personas. The deliverable is a verdict. Don't apply changes unless asked.

## 1. Scope

Use what the user pointed at. Otherwise review the branch against its base: `git diff <base>...HEAD`. Gather the surrounding files reviewers need: callers, types, tests.

## 2. State the intent

Write one paragraph on what the change is meant to do, from the user's words, commit messages, the PR description and the code. If you are unsure of the intent, ask before reviewing.

## 3. Run the reviewers

Start one read-only subagent per entry in the `reviewers` role, all at once, each with the same prompt: [references/reviewer-prompt.md](references/reviewer-prompt.md) filled with the intent, the diff, the [rubric](references/rubric.md) and the [code-quality lens](references/code-quality-review.md).

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

With no `reviewers` entry for your tool, run two reviewers on the current model and say the panel was not diverse.

## 4. Judge

Merge the findings: deduplicate, mark which reviewers raised each one, and note disagreements. Findings raised independently by two or more models are the strongest signal. Then act as the lead reviewer per [references/lead-judgment.md](references/lead-judgment.md): a pragmatic senior engineer, not an aggregator. Trace each finding to a real execution path before you accept it.

## Output

- **Intent**: the paragraph from step 2.
- **Reviewers**: one line each, model and finding count.
- **Act on**: issues that would block a real PR (correctness, security, maintainability), with who raised them and why they matter. Usually five or fewer.
- **Consider**: real points whose cost-benefit is unclear.
- **Noted**: valid, low priority.
- **Dismissed**: rejected findings, each with a one-line reason.
- **Agreement map**: where reviewers agreed and diverged, and what that says.
