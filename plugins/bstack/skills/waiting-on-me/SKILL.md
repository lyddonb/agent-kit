---
name: waiting-on-me
description: List everything across your repos that waits on you, in one read-only pass. Covers open HUMAN_TASKS.md items with blockers first and what each blocks, open ledger gates in unsealed runs, pull requests waiting for your review or merge, and open questions in questions.md, each with a link to its source. Use for "what's waiting on me", "what needs me", "what am I blocking", "any open gates", "which PRs need my review", or as the first step of choosing what to work on next.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Waiting on me

One list instead of five files and a pull request page. The script only reads: it sends nothing, edits nothing and fetches nothing. A notifier can read its `--json` output later.

## Run it

```bash
python3 <skill dir>/scripts/waiting.py PATH [PATH ...]
```

Python 3.10+, standard library only, and `gh` for pull requests. Each `PATH` is a git repo, or a folder whose direct subfolders are git repos (hidden folders such as `.worktrees` are skipped). Pass the repo list every time; the script holds none. Add `--github OWNER/NAME` for a repo you have no clone of, which lists only its pull requests. `--json` prints the same items as JSON.

## What it lists, in order

| Section | Source | Open when |
|---|---|---|
| Blockers | `HUMAN_TASKS.md` | An open task whose status says `BLOCKER`. It shows what the task blocks |
| Open ledger gates | `.audit/runs/*/ledger.jsonl` in the repo and each of its git worktrees | A `gate` entry with no later `gate-answer`, in a run with no `seal` |
| Pull requests | `gh pr list` | Open and not a draft. It shows the check state and any review decision |
| Human tasks | `HUMAN_TASKS.md` | A table row whose status does not start with Done or Skipped, a `[ ]` in a Done column, or a bullet under `## Open` |
| Open questions | `questions.md` | A bullet under `## Open` with no `Answer:` line |

Each item ends with its link: the GitHub URL at the line when the local file matches the remote default branch as last fetched, else `PATH:LINE`. A file the script cannot parse, a ledger line that is not JSON, and a `gh` failure each go under "Could not read", and the exit code is 1. Never report a section as empty when it is listed there.

## Using the list

- Read the list before you rank work. A blocker or an open gate comes first: ask about it, don't work around it.
- A pull request with failing checks waits on whoever owns the fix, not only on review. Say which.
- Copy items as the script prints them. Don't merge two items or restate a task from memory.
- The list is a snapshot of the clones as they are. Run `git fetch` in a repo first if its links must match GitHub.
