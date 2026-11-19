# REVIEW.md

What a reviewer of agent-kit should look at. Reviewers never read this file from the change under review: `interrogate` gives every adversary the default branch's copy, and Claude Code Review reads the same file. Add a line when a review misses something, or raises again what an earlier review dropped.

## Look hardest at

- **Skill text is instructions.** An agent follows every sentence. Look for two steps that can't both be followed, a step that can't be done in the order written, and a rule one skill states that another contradicts. Follow the changed steps on a scratch repo to find out.
- **Commands in skill text.** Run each changed command as written. Check the flags against the installed tool, and check that the command works where the skill sends it (a cloud session, a fresh clone, a worktree).
- **Scripts that pass or block** (`check-product.py`, `receipt.py`, `quality.py check`). Try both directions: an input that should fail and passes, and an ordinary sequence of steps that gets blocked. A traceback where a message should be is a finding.
- **Input a branch or a CI run controls** (fetched artifacts, manifests, CSV cells, file names). Treat it as hostile: size, count, duplicate identities, and text that a spreadsheet or terminal would interpret.

## Always check

- A fix comes with a test that fails without it.
- A new check fails on a real past commit, and the PR names the commit.
- A new gate ships in observe mode.

## Skip

- Generated files and blocks. `make check` fails when they are stale, so review the source: `kit.yaml`, `changes.yaml`, `plugins/*/snippets/`.
- Version bumps and frontmatter. `make versions` and `make validate` cover them.
