---
name: beau-help
description: List what agent-kit and bstack can do (skills, playbooks, subagents) and how to call each one, or show what changed since you last looked. Use for /beau-help, "what can you do", "which skill should I use for X", "what's new", or "what changed in bstack".
---

# beau-help

Two jobs: show what the kit can do, and show what changed. Both read generated files in `references/`, so they match the installed version. Never list a skill that is not in `references/catalog.md`, and never describe one from memory.

## Pick the mode from the request

| Request | Do |
|---|---|
| No topic ("beau-help", "what can you do") | **Overview** |
| A task or topic ("beau-help verify", "which skill for a flaky test") | **Find** |
| "new", "what's new", "what changed", "since last time" | **What's new** |
| "everything that changed", "changelog" | Run `whats_new.py --all` and summarize |

## Overview

1. Read `references/catalog.md`.
2. Show one short section per plugin: one line per skill with how to call it and when to use it, in your own words, at most 15 words. List playbooks under beau-mode in one line.
3. Write each call the way the current tool takes it. In Claude Code a plugin skill is `/<plugin>:<skill>` (`/bstack:how`); in Codex it is `$<skill>`; elsewhere name the skill in plain words ("use the how skill"). If you can't tell the tool, give the skill name only.
4. End with the two or three newest entries from `python3 scripts/whats_new.py --days 14`, or say nothing changed in the last two weeks.

## Find

Read `references/catalog.md` and pick the one to three skills or playbooks that fit the task. For each one, say why it fits and give the exact call. If beau-mode would route the task, say which playbook it would pick. If nothing fits, say so; don't stretch a skill to cover it.

## What's new

Run `python3 scripts/whats_new.py` from this skill's folder. It prints entries you have not seen and marks them seen; when nothing is unseen it prints the last 14 days instead. Use `--peek` to look without marking, and `--days N` for a window. Summarize each entry in plain words, in this order: what you can do now, then how to try it (the `Try:` line). Skip the "First release" entries unless the user asks for history.

If the script can't run (no Python), read `references/changes.json` and show the entries from the last 14 days.

In Claude Code a session-start hook runs the same script once after an update and shows the user a one-line notice.
