---
id: pause-safely
title: Pause safely
when: "An explicit request to pause, going offline, a restart, or imminent context compaction. Never on \"keep going\"."
source: pstack/skills/poteto-mode/playbooks/pause-safely.md @ ccb5507
---

# Pause safely

**You own a clean stop.** Leave a checkpoint that a cold-start agent, in any tool, can resume from.

1. Stop at a safe boundary. Finish or back out of the current step. Start nothing new and stop running subagents.
2. Take no irreversible action to pause: no new PR and no push you weren't already doing.
3. Commit uncommitted edits as one `wip:` commit on the current branch. If the tree is broken, say so in one line of the commit body.
4. Write a resume note with the **handoff-notes** skill if it is installed, otherwise a `HANDOFF.md` with intent, progress, what is verified, next steps, key files and gotchas. Point at an existing decision log instead of copying it.

**Reply:** where you are, what's on disk versus only in your head, the commits and whether the tree is clean, and the first action on resume.
