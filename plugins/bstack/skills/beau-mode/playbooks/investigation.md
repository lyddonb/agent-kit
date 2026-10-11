---
id: investigation
title: Investigation
when: "A read-only question: how does X work, why was Y built this way, are we sure about Z, should we do X or Y."
source: pstack/skills/poteto-mode/playbooks/investigation.md @ ccb5507
---

# Investigation

**You own the answer.** Investigations are read-only. They produce a cited explanation or a recommendation, not a code change.

1. Run the **how** skill on the subsystem in question. For "why was it built this way", also read the history: `git log -S`, `git blame`, the PRs and tickets those commits link to, and any decision records or knowledge-base entries about the area.
2. Answer from evidence. Cite files with line numbers, commits, PRs, or docs for each claim, and label anything you inferred.
3. For a decision between alternatives, give a recommendation with a trade-offs table. Settle factual forks by running something, not by guessing.
4. If the investigation turns into a code change, stop and re-route to Bug fix, Feature or Refactoring.

**Reply:** the explanation (Overview, Key concepts, How it works, Where things live, Gotchas) or the recommendation with its trade-offs. For "are we sure?", give your real judgment and push back if the premise is wrong.
