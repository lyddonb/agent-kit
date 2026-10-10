---
name: commit-message
description: Write a clear git commit message (Conventional Commits style) from the staged diff. Use when the user asks to commit, write or improve a commit message, or summarize staged changes for a commit.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Commit message

Write one commit message that tells a future reader *what changed and why*, based on what is actually staged.

## Steps

1. Look at what is staged, not the whole working tree:
   - `git diff --cached --stat` for the shape of the change
   - `git diff --cached` for the details (skim large generated files, lockfiles, and snapshots)
   - If nothing is staged, say so and ask whether to stage everything (`git add -A`) or specific paths. Do not stage on your own.
2. Check the repo's existing style with `git log --oneline -15`. If the history clearly uses a different convention (ticket prefixes, gitmoji, sentence case), follow the repo, not this skill.
3. Decide whether this is one logical change. If the staged diff mixes unrelated changes (a refactor plus a bug fix plus a dependency bump), suggest splitting it and show which paths go in which commit.
4. Write the message using the format below, then show it to the user before committing. Only run `git commit` if they asked you to commit.

## Format

```
<type>(<optional scope>): <summary in imperative mood, <= 72 chars, no period>

<body: why this change was needed and what it does, wrapped at 72 chars.
Mention behavior changes, migrations, or follow-ups a reviewer must know.>

<footers: BREAKING CHANGE: ..., Refs: #123, Co-authored-by: ...>
```

Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`, `ci`, `chore`, `revert`.

## Rules

- Summary says what the commit does ("add retry to webhook sender"), not what you did ("added", "updated stuff").
- The body explains *why*. The diff already shows *what*; repeat it only when the change is non-obvious.
- Skip the body for truly trivial commits (typo fixes, formatting).
- Use `BREAKING CHANGE:` whenever a public API, CLI flag, config key, schema, or default changes incompatibly.
- Never invent ticket numbers, co-authors, or test results. If the user mentioned a ticket, include it.
- Keep any attribution trailers the repo or user requires.

## Examples

```
fix(billing): stop double-charging on webhook retries

Stripe retries webhooks on timeouts, and the handler was not
idempotent, so a slow response could create a second charge. Store the
event id and skip events we have already processed.

Refs: PAY-412
```

```
docs: fix broken install link in README
```
