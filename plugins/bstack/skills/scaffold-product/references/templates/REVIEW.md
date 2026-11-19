# REVIEW.md

What a reviewer of {{product}} should look at. Reviewers never read this file from the change under review: `interrogate` gives every adversary the default branch's copy, and Claude Code Review reads the same file. Add a line when a review misses something, or raises again what an earlier review dropped.

## Look hardest at

- {{Where a bug costs the most and tests reach the least: money, data loss, auth, anything that runs unattended. Say what to try there.}}

## Always check

- A fix comes with a test that fails without it.
- {{A rule from AGENTS.md that a diff can break without failing a test.}}

## Skip

- {{What CI already enforces: formatting, lint, generated files.}}
