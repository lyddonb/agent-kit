---
id: opening-a-pr
title: Opening a PR
when: "The last step of every playbook that changes code."
source: pstack/skills/poteto-mode/playbooks/opening-a-pr.md @ ccb5507
---

# Opening a PR

1. **Branch.** Work on a branch or worktree off the default branch, never on it. Give parallel subagents their own worktrees.
2. **Commits.** Commit as you go, then rebase into small ordered commits that each tell one step of the story and each pass checks. Use Conventional Commits: `type(scope): subject`, imperative, no trailing period, with types `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`.
3. **Clean up before review.** Remove narrating comments and debug leftovers. Run **unslop** over the PR title, body and commit messages.
4. **Description.** A briefing, not a lab notebook. A reviewer with the diff should learn in under a minute why it exists, what it leaves out, what it could break and how you proved it. Use these `##` sections in order and drop any with nothing to say:
   - `## Why`: the problem and approach in one to three sentences.
   - `## What changed`: one to three bullets.
   - `## Scope`: what it covers and what it deliberately leaves out.
   - `## Trade-offs`: only rejected alternatives a reviewer would ask about.
   - `## Blast radius`: who or what it touches and why that is safe or risky.
   - `## Verification`: one to three bullets naming the real run and its outcome. One primary number for performance work.
   Link bulky evidence (logs, decision trails, screenshots) instead of pasting it.
5. **Size.** Prefer several narrow PRs to one wide one. Stack dependent PRs on each other's branches.
6. **Open it ready for review**, not as a draft, with `gh pr create` or the tool's built-in PR feature. Post the URL and keep going; don't wait on CI unless asked.

**Reply:** the PR URL and a one-line summary.
