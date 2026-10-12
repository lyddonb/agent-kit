---
id: session-pickup
title: Session pickup
when: "Resuming or taking over another agent's in-flight work from a transcript, a handoff note, or a pushed branch."
source: pstack/skills/poteto-mode/playbooks/session-pickup.md @ ccb5507
---

# Session pickup

**You own the resume point. Read the prior trail; don't redo it.**

1. Find the trail: a `HANDOFF.md` or resume note, a decision log, the prior transcript, or the branch. Read the last messages and decision points first. Parse a long transcript in a subagent and keep only the timeline in the main thread (`guard-the-context-window`). The section below says where each tool keeps transcripts.
2. Rebuild the state: branch, what already landed (`git log` and `git diff` against the base), open todos, and decisions. Treat the trail as authoritative. Don't re-derive it.
3. Compare done against planned and name the resume point. Don't re-run finished work.
4. Route the remaining work to the matching playbook.
5. Verify inherited claims against the original goal on the real artifact (`prove-it-works`). A prior self-report is not proof.

## Finding the prior transcript

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

**Reply:** where the prior agent stopped, what you inherited and what (ideally nothing) you redid, the resume point, and the outcome.
