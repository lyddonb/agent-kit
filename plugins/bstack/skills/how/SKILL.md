---
name: how
description: Explain how a subsystem, feature or code path works, at the level a senior engineer needs before changing it, covering runtime flow, key concepts, where things live and gotchas. Use for "how does X work", walkthroughs before a change, onboarding to unfamiliar code, and "where should this live" or "which layer owns this" questions.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack how @ ccb5507 (MIT, Lauren Tan)"
---

# How

Explore the code and explain how it works: enough to build a working mental model, not an annotated source listing.

## 1. Size the question

State your reading of the scope. The user can redirect.

- **Simple** (one module, one function, a narrow question): explore and explain in one pass. Go to step 3.
- **Complex** (a subsystem across files or services, a cross-cutting feature, an architectural overview): split it into 2-4 exploration angles, each a distinct slice. Go to step 2.

When in doubt, take the simple path.

## 2. Explore in parallel (complex only)

Start one `explorer` subagent per angle, read-only, each with [references/explorer-prompt.md](references/explorer-prompt.md) and its angle filled in. Keep their raw findings out of the main thread; you need their structured results, not their transcripts.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## 3. Explain

Write the explanation (or have a `judgment` subagent write it from the explorers' findings) using [references/explainer-prompt.md](references/explainer-prompt.md). Every claim points at a file and line, a commit, or a doc.

## Output

Use these sections and drop any that don't apply: **Overview**, **Key concepts**, **How it works**, **Where things live**, **Gotchas**. Diagrams (Mermaid or ASCII) are welcome when the flow has more than three hops.
