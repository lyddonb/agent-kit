# Pre-registered before the first judge call

Arms: full1 and full2 get beau-mode's SKILL.md as it is at agent-kit 1a6aa9c (two identical
runs), slim gets the router built from it (restate, match a playbook, read only the principles
that playbook names, playbook index). Candidates: Claude Sonnet via `claude -p`, no user
settings, no MCP, skills off, sandboxed, $2 cap per run.

Rubric (judge only), each scored 1 to 5 per answer:
1. cause: finds the real cause of the problem (for the read-only question: gets the facts right).
2. fix: the change solves the stated problem without breaking existing behavior (read-only
   question: the answer is complete for what was asked).
3. proof: evidence from running something; best is a test that fails without the fix and
   passes with it (read-only question: each claim is tied to a file or command it was read from).
4. scope: the smallest change that meets the goal, nothing unrequested.
5. reply: the final reply's claims match what the diff and the run show, and it says what is
   not proven.

Comparisons per task and item, from the judge's scores: higher score wins, equal is a tie
(0.5). Win share of X over Y = (wins + 0.5 * ties) / n over tasks where both have a verdict.

- Noise band for item i: band_i = |share(full1 over full2) - 0.5|.
- Slim effect: share(slim over full) pooled over both full runs (2 comparisons per task).
- Slim holds on item i iff share(slim over full) >= 0.5 - band_i. A deficit inside the band
  counts as none.
- Recommendation: slim if slim holds on every item; keep otherwise.

Missing data: a judge status other than ok, or an answer that does not parse as the asked
JSON, is a missing verdict for that task (no rerun on the current model). A candidate run that
hit its budget cap or errored is scored as what it produced, and flagged in the report; a run
with no final reply and no diff is missing.

Labels: per task, the three runs are shown as Answer A, B and C in an order drawn from
random.Random(4343 + task number); the judge sees no arm names. The judge also gets the merged
PR's diff as one accepted fix, not the only correct one.

Resolution: 8 tasks, so one task moves a full-vs-full share by 12.5 points, and the band is one
sample of the identical-pair gap.
