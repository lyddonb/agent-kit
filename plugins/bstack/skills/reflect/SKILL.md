---
name: reflect
description: Mine the current session for durable lessons and turn each one into a concrete, approved edit to a skill, playbook or principle, or a backlog item. Three independent reviewers read the transcript, a synthesizer sorts their findings, and nothing changes without the user's approval. Use when the user says reflect, "capture what we learned", or "so the next run doesn't repeat this".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack reflect @ ccb5507 (MIT, Lauren Tan)"
---

# Reflect

Turn what this session taught into edits that change future agents' decisions. One odd session is an anecdote, not a rule.

Skip it when the session was trivial, or when an existing skill already covered it and the agent followed it.

## 1. Find the transcript

Run `python3 <this skill's folder>/scripts/find-transcripts.py --project <project root>` to list the project's recent sessions across tools, and pick the one whose first message matches this conversation. Always pass `--project`; without it the script uses the current directory.

<!-- BEGIN GENERATED: snippet:transcripts (tools/kitgen.py; edit plugins/bstack/snippets/transcripts.md) -->
**Finding transcripts.** Read only the current project's sessions. Never search other projects' transcripts: they hold private conversations that have nothing to do with this work.

| Tool | Session files |
|---|---|
| Claude Code | `~/.claude/projects/<project path, non-alphanumerics as ->/<session-id>.jsonl` |
| Codex | `~/.codex/sessions/<yyyy>/<mm>/<dd>/*.jsonl` (match the project by the `cwd` in the first line) |
| Cursor | `~/.cursor/projects/<workspace>/agent-transcripts/` |
| pi | `~/.pi/agent/sessions/--<project path>--/<timestamp>_<id>.jsonl` |
| OpenCode | no portable file; use its export command if it has one |

The reflect skill ships `scripts/find-transcripts.py`, which lists the current project's newest sessions across these tools. If no transcript resolves, write a tight digest of the session from your own context and use that instead. Say which one you used.
<!-- END GENERATED: snippet:transcripts -->

## 2. Three reviewers, in parallel

Start three subagents that don't edit files (keep their MCP access; some tools drop it in read-only mode), each with one prompt filled with the transcript path or digest:

| Lens | Role | Prompt |
|---|---|---|
| Judgment: decisions that went wrong or took too long | `judgment` | [references/judgment-reviewer.md](references/judgment-reviewer.md) |
| Tooling: context the human supplied that a tool or skill could have fetched | `explorer` | [references/tooling-reviewer.md](references/tooling-reviewer.md) |
| Divergent: what a different approach would have done | a `reviewers` entry that differs from the judgment model | [references/divergent-reviewer.md](references/divergent-reviewer.md) |

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## 3. Synthesize

Have a `judgment` subagent merge the three outputs with [references/synthesizer.md](references/synthesizer.md) into **Accepted**, **Rejected** and **Backlog**. Then move any Accepted item that a script, check or lint would enforce better into Backlog, routed to the **correct** skill (`encode-lessons-in-structure`).

## 4. Ask before changing anything

Show the user the full Accepted, Rejected and Backlog lists and wait for approval. Skill edits change every future session, so never auto-apply. The user picks which items to apply and may redirect them.

## 5. Apply the approved items

Route each edit to where it belongs:
- **Generic and public-safe** (a principle, a bstack skill or playbook): edit the repo the skill is published from (for bstack and principles, your checkout of agent-kit or your fork of it) on a branch, following the Authoring a skill playbook in **beau-mode**. In agent-kit, run `make gen validate claude-validate`.
- **Project- or employer-specific**: the project's own `.agents/skills/` or its private skills repo.
- **A fact or convention, not a behavior**: the knowledge base if one is available, otherwise the project's agent instructions.
- **The skill existed but didn't trigger**: rewrite its `description` with the words the user actually used.

Open a PR for skill edits rather than editing installed copies: agentfiles installs pinned copies, and edits there are lost on the next sync.

## 6. Summarize

- Edits applied: path and one line each.
- New skills: path and one line each (rare).
- Backlog: one line each, with where it was filed.
- Dropped: one line each, with the synthesizer's reason.
