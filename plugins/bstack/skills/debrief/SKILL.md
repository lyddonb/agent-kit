---
name: debrief
description: Close out a piece of work for the human. Says what was done, what is proven and what is not, what comes next with why and impact, and the release note, and keeps it as a checked change record in the repo. Use for /debrief, "debrief", "what did we just do", "what's next and why", "write the release note", "release notes since X", or at the end of any work that ships a change.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Debrief

The human was not watching. Tell them what happened and what to do next, with enough context that they need not open the transcript. **handoff-notes** is for unfinished work and the next agent. This is for finished work and the person who owns it.

## The four parts

1. **Goal and what changed.** The goal in the user's words, then what is different now. When what shipped falls short of the goal, say so here in plain words.
2. **Claims.** One per thing you say works, and one per thing the goal needs that failed its check (`NOT VERIFIED`) or that nobody checked. Each names the check that ran and its conditions, the commit it ran on, where the output is kept, and what it leaves unchecked. Use **verify-work**'s verdicts, plus `UNCHECKED` for a claim nothing tested. A check on a mock, a fixture or one platform proves that much: put the rest in `remaining`.
3. **Next items.** Each has a source, why now, and impact: who notices and what changes for them if it is done or left. Look for the source in this order: the phase spec's failing criteria, `ROADMAP.md`, `HUMAN_TASKS.md`, open issues, a follow-up this work created. When none names the item, the source is `inferred`, and say so. Never invent a roadmap id. List what matters, most valuable first, and an empty list is a fine answer.
4. **Release note.** One line a user reads: what they can now do or what behaves differently, not which file changed. No user-visible change is `none` with the reason.

## When a change ships

Write the record once the commits are final (a rebase changes the hashes it names). Run the script from the repo root:

```bash
python3 <this skill's folder>/scripts/debrief.py new <slug>
```

Fill in `.changes/<date>-<slug>.json`, one record per PR. Then:

```bash
python3 <this skill's folder>/scripts/debrief.py check
python3 <this skill's folder>/scripts/debrief.py show
```

- A claim's `commit` is the commit its check ran on, not the record's own commit.
- `git add .changes` before `check`, which must pass before the record is committed. Fix the record, never the claim's verdict, to get there: a claim with nothing kept is `UNCHECKED`.
- Output worth keeping goes in a file git tracks, in a folder named as the record is without `.json` (`.changes/<date>-<slug>/`), or is a link to the CI run, the PR or the ledger run in `.audit/runs/`. A path git ignores (`.evidence/` in some repos) is refused.
- A repo that already keeps release notes somewhere it enforces (agent-kit's `changes.yaml`) uses `{"see": "<that entry>"}` and writes the line there.
- Commit the record with the PR: `docs(changes): record <slug>`, with `--trailer 'Verified: none record only'`.
- Paste what `show` prints as the brief in your reply.

## When nothing shipped

An investigation, a prototype or a plan has no record. Give the same four parts in the reply, and write no file. Claims are then what you found and how you know it.

## Release notes for a range

```bash
python3 <this skill's folder>/scripts/debrief.py notes --since 2026-11-01
```

Prints every record's release note, newest first. Run **unslop** over it before it goes to people.
