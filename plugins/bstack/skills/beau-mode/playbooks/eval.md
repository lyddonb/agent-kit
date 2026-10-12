---
id: eval
title: Eval
when: "Testing how a skill, principle or prompt change affects agent behavior before you keep it, including adopting someone else's skill."
source: pstack/skills/poteto-mode/playbooks/eval.md @ ccb5507
---

# Eval

**You own the experiment.** An agent that knows it is being tested behaves differently, so keep candidates blind.

Blinding rules:
- No `eval`, `test`, `judge`, `experiment`, `rubric`, `score`, `benchmark` or `candidate` in any directory, file name or prompt a candidate sees.
- The candidate prompt reads like an organic request: the goal, not the meta. Don't ask candidates to list which skills or principles they used.
- Candidates don't know other candidates exist. The judge sees outputs only under neutral labels, never model or variant names.

Steps:
1. Name the variant under test and what success looks like. Write a 3-6 item rubric for the judge only.
2. Set up one sanitized working directory per candidate, with the variant installed and the context an organic task would have.
3. Write one organic prompt and run it in each candidate directory (different models where the roles file allows).
4. Have one judge score every output in a single pass against the rubric.
5. Grade whether candidates followed the skill from what they actually did (files read, commands run, the shape of the result), not from what they claim.
6. Read every output yourself and compare with the judge. If you disagree, suspect the rubric first.

**Reply:** the variant, the rubric, notes per candidate, the judge's verdict, your synthesis, and whether to keep the change.
