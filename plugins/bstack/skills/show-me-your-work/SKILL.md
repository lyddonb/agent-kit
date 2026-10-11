---
name: show-me-your-work
description: Keep a reviewable decision trail for long, unattended or multi-phase work (one TSV row per decision with what, why, evidence and result), then audit it against the transcript and have a different model flag what deserves attention. Use for /show-me-your-work, "keep a decision log", autonomous or overnight runs, or "catch me up on what you did".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack show-me-your-work @ ccb5507 (MIT, Lauren Tan)"
---

# Show me your work

Keep one canonical log so a human can audit decisions instead of re-reading a whole run.

## The log

A TSV file, one row per decision, cells on one line, evidence as a pointer. Columns (header in [references/decision-log-template.tsv](references/decision-log-template.tsv)):

- **ts**: ISO 8601 timestamp.
- **phase**: the phase or workstream.
- **decision**: what was chosen or done, one line.
- **why**: the reason in plain words.
- **evidence**: a commit SHA, PR, `file:line`, or artifact path. Never a paragraph.
- **result**: the outcome, such as `tests green`, `reverted`, `pixel-diff 0`, `INCONCLUSIVE`, `open`.

Append rows with `bash <this skill's folder>/scripts/log.sh <logfile> <phase> <decision> <why> <evidence> <result>`, run from the project root with a log path inside the project. Never write the log inside the skill's folder: installed skills are replaced on every sync. It stamps the time, writes the header on first use, flattens tabs and newlines, and neutralizes cells that a spreadsheet would run as formulas.

Log decision points, not every action: a fork chosen, a unit finished with its verification result, a pivot or revert and its trigger, a blocker. In a loop, one row per iteration. Write rows the way you'd tell a teammate (the **unslop** rules apply).

When a later run adds to an existing log, its first row has phase `start` and names the rows before it that it did not write. Use `start` for nothing else.

## Where it lives

`decisions.tsv` in the working directory, or `.audit/<task-slug>.tsv` when several efforts share a directory. Keep it out of git by default. Commit it when the work is big enough that a reviewer needs the trail to trust the result.

Rules: append-only. A wrong call gets a new row that supersedes it. Never edit or delete history.

## Before handing back

1. **Audit the log against what happened.** Walk this run's rows against its transcript. Every row maps to a real action, every evidence pointer resolves, and every fork or abandoned approach that shaped the work has a row. Fix gaps by adding rows, never by editing old ones.

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

2. **Get an outside read.** Start a subagent that doesn't edit files, on a model different from the one that did the work (the first `reviewers` entry that differs from yours). It reads the log and the transcript and flags: decisions with weak evidence, verification claimed without proof, choices that look risky in hindsight, and gaps a casual skim would miss.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

3. **End the reply with an Attention section**: `reviewed by <model>` on its own line, then each flag with the rows or moments it points at. "No flags" is a valid result.

To review a trail: `column -s$'\t' -t decisions.tsv`, or open it on GitHub, which renders TSV as a table.
