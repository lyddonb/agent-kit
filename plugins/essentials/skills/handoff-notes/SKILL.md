---
name: handoff-notes
description: Write a concise handoff note so another agent session, another tool (Claude Code, Codex, Cursor, pi, OpenCode), or a teammate can resume the current work without re-reading the conversation. Use when the user says hand off, wrap up, save progress, pause, switch tools, or before a context reset.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Handoff notes

Capture the state of the work in a file that any agent or person can pick up cold.

## Steps

1. Gather repo context by running the bundled script from the project root:

   ```bash
   bash <path-to-this-skill>/scripts/collect-context.sh
   ```

   It prints the branch, upstream status, uncommitted changes, recent commits, and stashes. If the script is unavailable (no bash, not a git repo), collect the same facts by hand or skip that section.

2. Review this session yourself: the goal, decisions made and why, what was tried and failed, what is done, and what is left.

3. Write the note to `HANDOFF.md` in the project root, unless the user names another path. If a `HANDOFF.md` already exists, replace its contents - it describes the latest state only, not a history. Use the template in [references/template.md](references/template.md).

4. Tell the user the file path and suggest a one-line prompt to resume, such as:
   `Read HANDOFF.md and continue from "Next steps".`

## What makes a good handoff

- **Specific next action.** "Run `pnpm test api/` and fix the 2 failing auth tests" beats "finish tests".
- **Decisions with reasons.** The next session will otherwise reopen settled questions.
- **Dead ends.** Record approaches that failed and why, so they are not retried.
- **Exact pointers.** File paths, function names, commands, URLs, ticket ids.
- **Short.** Aim for one screen. Link to files instead of pasting them.
- **No secrets.** Never copy tokens, passwords, or customer data into the note.

Ask the user before adding `HANDOFF.md` to git; many people keep it untracked (add it to `.git/info/exclude` for a local-only ignore).
