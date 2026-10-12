---
name: recall
description: Rebuild the user's recent context on a topic from their own agent transcripts, the PRs, tickets and reports around it, and live git state, then return a short brief and the next move. Use for "recall my work on X", "catch me up on X", "where did I leave off", before starting or resuming work.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack recall @ 11713c6 (MIT, Lauren Tan)"
---

# Recall

Before starting or resuming work, rebuild the user's recent context and hand back a short brief of where things stand and what to do next. Read only what the in-scope threads need, then stop.

Context lives in two records. The user's own agent sessions hold what they did and decided. The shared record holds everything else that happened around the same code: the symptoms users keep reporting, fixes that shipped and got reverted, errors still firing. The **why** skill searches that second record. A feature with a long bug tail keeps most of its story there, so don't rebuild it from transcripts alone.

## Steps

1. **Route first.** Resuming one specific prior session is the **Session pickup** playbook in **beau-mode**, not this. A summary of an unattended run's trail is **show-me-your-work**. If the user already gave you a full state capsule (paths, branch, the change), use it and skip the mining.
2. **Lock the scope.** Pin the window (default: the last 7 days), the topic if named, and the project (default: the current one). State the scope back in one line. Never read another project's transcripts, and never quietly turn "all" into "recent".
3. **Mine the user's sessions.** List the matching transcripts with the **reflect** skill's script (in the `reflect` folder next to this skill when bstack is installed):

   ```bash
   python3 <reflect skill folder>/scripts/find-transcripts.py --project <project root> --days 7 --grep "<topic>" --limit 50
   ```

   An empty list with `--days` or `--grep` means no session in the window touched the topic. Say so; don't fall back to a digest of the current session. Skip the current session and obvious noise (subagent, eval and test sessions). For one or two sessions, read them directly. For more, split them across parallel `explorer` subagents. Tell each to grep the topic first, read only the matching regions, and return one block per session: topic, the user's goal, decisions, open threads, struggles and corrections, and artifacts (PRs, tickets, branches), each citing the transcript file. The raw transcripts stay in the subagents.

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

4. **Sweep the shared record** whenever the topic names a feature, file, subsystem or bug. This is the default; "my work on X" doesn't exempt it. Use the **why** skill's investigators and source playbooks, but change their question from "why was it built this way" to "what's the current state, what's been tried and didn't hold, and what are users still reporting". Run them in parallel with step 3. Skip this only for pure activity recall with no named target ("what did I do this week").
5. **Check live state.** Verify the PRs, branches and tickets you found with `git` and `gh`. When the answer depends on what an agent actually did (tools it ran, errors it hit), read the full transcript, not a summary.
6. **Write the brief** to the contract below, grouped by thread and on the named topic.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

## Output contract

- **Capsule.** At most 5 bullets: what this work is and where it stands.
- **Threads.** One line each, with exactly one status tag: `[merged #N]`, `[open PR #N]`, `[in flight <branch>]`, `[verified, uncommitted]`, `[reverted #N]` or `[planned, not started]`. An untagged thread is unfinished; tag it.
- **Problems.** At most 5 recurring ones, including what users keep reporting and any fix that shipped and was reverted, so the next attempt starts where the last one failed.
- **Next move.** The single most useful next action, concrete.

Adjacent features stay out unless they block this one. When the brief outgrows a screen, cut detail before cutting threads. Write it through the **unslop** skill. Cite session findings by transcript file and shared-record findings by source (PR number, ticket ID, chat permalink, error issue). Strip private context before anything goes somewhere public.

**Reply:** the brief.
