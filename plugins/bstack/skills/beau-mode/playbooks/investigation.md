---
id: investigation
title: Investigation
when: "A read-only question: how does X work, why was Y built this way, are we sure about Z, should we do X or Y."
source: pstack/skills/poteto-mode/playbooks/investigation.md @ 11713c6
---

# Investigation

**You own the answer.** Investigations are read-only. They produce a cited explanation or a recommendation, not a code change.

1. Restate the question in your own words, in plain English, and say what a good answer would let the user do. If the question came from a thread or ticket, read all of it first.
2. If it's about the user's own recent work on this area, run **recall** first so you start where they left off.
3. Run the **how** skill on the subsystem in question. For "why was it built this way", where a number came from, or a regression's history, run the **why** skill. It searches git, PRs, tickets, docs, chat and observability in parallel and keeps what's known apart from what's inferred.
4. Answer from evidence. Cite files with line numbers, commits, PRs or docs for each claim, and label anything you inferred.
5. For a decision between alternatives, give a recommendation with a trade-offs table. Settle factual forks by running something, not by guessing.
6. If the user wants to understand it deeply, not just get an answer, hand the findings to the **teach** skill.
7. If the investigation turns into a code change, stop and re-route to Bug fix, Feature or Refactoring.

**Reply:** the explanation (Overview, Key concepts, How it works, Where things live, Gotchas) or the recommendation with its trade-offs. For "are we sure?", give your real judgment and push back if the premise is wrong.
