---
name: design-review
description: Review a technical design doc, RFC, or ADR the way a senior engineering leader would - find risks, gaps, and unclear decisions, and give prioritized, actionable feedback. Use when asked to review, critique, or poke holes in a design, RFC, proposal, architecture doc, or ADR.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Design review

Give feedback that improves the decision, not just the document.

## Steps

1. **Get the doc and the context.** Read the whole document first. If key context is missing (who the users are, scale, deadline, team size, what already exists), ask at most three questions, or state your assumptions explicitly and continue.
2. **Restate the proposal** in 3-5 sentences: the problem, the chosen approach, and the main trade-off. If you cannot, that is the first finding - the doc is unclear.
3. **Walk the checklist** in [references/checklist.md](references/checklist.md). Skip sections that clearly do not apply; do not pad the review.
4. **Write the review** in the format below.

## Output format

```
## Summary
<restated proposal + overall verdict: Approve / Approve with changes / Needs another pass / Reconsider approach>

## Must address before building
1. <finding> — <why it matters> — <concrete suggestion or question>

## Should address
...

## Consider / nits
...

## What's strong
<2-3 specific things worth keeping; skip generic praise>

## Questions for the author
...
```

## Principles

- **Prioritize ruthlessly.** Three must-fix items that matter beat twenty comments. Label severity honestly.
- **Attack the decision, not the prose.** Wording fixes go under nits, if at all.
- **Be concrete.** Name the failure scenario ("if the queue backs up during a deploy, ...") and propose an alternative or a test that would settle it.
- **Separate facts from opinions.** Mark preferences as preferences.
- **Check reversibility.** Spend scrutiny on one-way doors (data models, public APIs, vendor lock-in, migrations); be light on two-way doors.
- **Ask whether it should be built at all.** Simpler alternatives and "do nothing" are valid findings.
