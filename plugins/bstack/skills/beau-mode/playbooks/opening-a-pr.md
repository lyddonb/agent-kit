---
id: opening-a-pr
title: Opening a PR
when: "The last step of every playbook that changes code."
source: pstack/skills/poteto-mode/playbooks/opening-a-pr.md @ ccb5507, goal in Why from 246bc50
---

# Opening a PR

1. **Branch.** Work on a branch or worktree off the default branch, never on it. Give parallel subagents their own worktrees.
2. **Commits.** Commit as you go, then rebase into small ordered commits that each tell one step of the story and each pass checks. Use Conventional Commits: `type(scope): subject`, imperative, no trailing period, with types `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`.
3. **Stamp each commit.** Once the commits are final, each one carries exactly one `Verified:` git trailer. It names the strongest check that passed on what that commit changes:
   - `Verified: receipt <run-id>`: a receipt's probe ran on this commit, and that ledger run holds its VERIFIED receipt.
   - `Verified: verify-work`: **verify-work** returned VERIFIED for the behavior the commit changes.
   - `Verified: tests`: the project's tests passed with the commit, and nothing stronger ran.
   - `Verified: none <reason>`: nothing checked it. Give the reason in a few words (`none docs only`, `none verify-work inconclusive`). An honest `none` is fine. A stamp that claims more than ran is not.

   Add it with `git commit --trailer 'Verified: tests'`. On an existing commit use `git -c trailer.ifexists=replace commit --amend --no-edit --trailer 'Verified: tests'`. Don't type the line into the message: git reads trailers only from the last paragraph, so a `Verified:` line set apart from `Co-Authored-By:` is not one. A receipt names its commit, so stamp that commit `receipt <run-id>` before you run its probe and don't rewrite it afterward. If the probe fails, fix the stamp along with the code, then run the probe again. Before you push, `git log --format='%h %(trailers:key=Verified,valueonly,separator=%x7C)' <base>..HEAD` must print one value beside every hash, with no `|`.
4. **Clean up before review.** Remove narrating comments and debug leftovers. Run **unslop** over the PR title, body and commit messages.
5. **Description.** A briefing, not a lab notebook. A reviewer with the diff should learn in under a minute why it exists, what it leaves out, what it could break and how you proved it. Use these `##` sections in order and drop any with nothing to say:
   - `## Why`: open with the user's goal, then the problem and approach, in one to three sentences.
   - `## What changed`: one to three bullets.
   - `## Scope`: what it covers and what it deliberately leaves out.
   - `## Trade-offs`: only rejected alternatives a reviewer would ask about.
   - `## Blast radius`: who or what it touches and why that is safe or risky.
   - `## Verification`: one to three bullets naming the real run and its outcome. One primary number for performance work. When the PR moves spec criteria, paste the output of `ledger receipts <run-id>` here as it is. Don't retype or trim the table: it is the record of which probes ran, and a criterion missing from it has no receipt.
   Link bulky evidence (logs, decision trails, screenshots) instead of pasting it.
6. **Size.** Prefer several narrow PRs to one wide one. Stack dependent PRs on each other's branches.
7. **Open it ready for review**, not as a draft, with `gh pr create` or the tool's built-in PR feature. The exception is a unit PR in a Large work item run, which stays a draft until its reviews are in. Post the URL and keep going; don't wait on CI unless asked.

**Reply:** the PR URL and a one-line summary.
