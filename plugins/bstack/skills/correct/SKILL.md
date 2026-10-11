---
name: correct
description: Find the mistakes agents keep repeating in this repo and make each one impossible. Tries architecture first, then types, then a lint or CI check whose error names the fix, then a test, and docs last, and proves each new check fails on a real past mistake. Use for /correct, "agents keep doing X", or after correcting the same mistake twice.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack correct @ ccb5507 (MIT, Lauren Tan)"
---

# Correct

The human keeps correcting agents in this repo for the same mistakes. Change the repo so the next agent can't make them.

Assume every contributor is an agent that sees only the files it opened, copies the nearest example, and takes the shortest path that compiles. Design the repo so a change that looks right from one file is right for the whole repo.

## 1. Find the mistake classes

Read recent commits, reverts, review comments, agent instruction files (`AGENTS.md`, `CLAUDE.md`, rules folders), and comments that explain workarounds. Group the mistakes into classes. A class counts once it has happened twice. If the user named a mistake, start there.

## 2. Fix each class at the highest level that works

1. **Architecture** removes it: one owner per piece of state, one supported way per task, internals hidden so the wrong import fails, one source of truth instead of hand-synced lists, and old ways deleted so nobody copies them.
2. **Types** make the bad state unwritable. If bad code still compiles, add a **lint or CI check** whose error message names the file, type or function to use instead. If the bad pattern is already common, fail only when a change adds more.
3. **A test** of the behavior. Fix or delete any test that would still pass if every function it calls returned nothing.
4. **Docs or agent rules**, last, and only for judgment calls. Nothing fails when an agent skips a rule.

## 3. Fix and prove

Fix the most frequent classes now, one commit each. Prove each new check fails on a real past mistake (check out the old commit or reapply the bad diff). Run the same command locally and in CI. Exceptions go on the offending line with a reason and an expiry date.

## 4. Keep the rule table

Keep a table in the repo's agent instruction file that pairs each rule with what enforces it. When the human corrects you, fix the mistake and add the rule. If the rule was already there and nothing enforced it, that's a repeat: enforce it at the highest level in the same change. Drop a rule once its mistake can't happen anymore.

**Reply:** each class with its evidence, the level you chose, and why a higher level didn't work.
