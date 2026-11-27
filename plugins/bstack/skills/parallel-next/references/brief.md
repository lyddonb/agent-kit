# Brief for a session started by parallel-next

Fill in every field. The session starts with nothing but this text, so don't write "as discussed" or point at this conversation.

```text
/beau-mode ID: TITLE

Goal: GOAL, in your own words: what the item is for, who it is for, and what done looks like.

Item: ID in FILE (LINK). Why now: TRIGGER OR WHAT IT UNBLOCKS.

Where: work in REPO. Read its AGENTS.md first. Use your own worktree and a branch whose name
contains ID, so other sessions can see this work is taken.

Fence: other sessions are working in this repo at the same time. Expect to touch only:
PATHS (inferred, not checked). Before you edit any other file, run
`python3 PARALLEL_NEXT_DIR/scripts/inflight.py REPO`. If another claim already lists that
file, stop and report back instead of editing it. Hot files (changelogs, manifests, version
files) are fine. Rebase onto the default branch before you open the pull request.

Done: the item's own done criteria, proven per beau-mode, ending with a pull request through
the Opening a PR playbook. Never merge it.
```

`PARALLEL_NEXT_DIR` is this skill's folder as an absolute path.
