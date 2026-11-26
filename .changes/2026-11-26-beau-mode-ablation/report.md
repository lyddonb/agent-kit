# R43: does beau-mode's always-on text help or distract?

**Goal.** Find out whether the roughly 3,000 words of beau-mode's `SKILL.md`, which beau-agent
loads before any work, make agents do better work than a slim router that only restates the
task, picks a playbook and reads that playbook and the principles it names. If the slim router
did as well, the always-on text could shrink.

**Recommendation: keep.** The slim arm held on cause, fix and proof. It fell outside the noise
band on scope and reply. Nothing under `plugins/bstack/skills/beau-mode/**` changes. With 8
tasks this is weak evidence either way, but it gives no grounds to cut.

## The variant

| Arm | What the candidate got in its system prompt | Tokens it adds (measured) |
|---|---|---|
| full (run twice: full1, full2) | `SKILL.md` exactly as at agent-kit `1a6aa9c` (3,178 words) | 7,505 |
| slim | Its frontmatter, intro and steps 1-2, a step 3 "read only the principles the playbook names", and the playbook index (`arm-slim.md`) | 2,169 |

Each arm also got a 60-word preamble saying where the skill files live, included in the counts
above. A count is the input tokens of a one-word `claude -p` reply on Sonnet with that prompt,
minus the same call with no prompt (3,407). The principles index in the brief is the generated
block inside `SKILL.md`, so the full arm is that file alone.
Main has since changed one line of `SKILL.md` (R45's flag rule, PR 123, 8 more words). The
eval tested the text before that change.

Cost per run, from each run's `total_cost_usd` (measured): full $0.36 (16 runs), slim $0.38
(8 runs). The slim prompt is 5,336 tokens shorter, but it is cached after the first turn, so it
saved nothing measurable per run. All 24 runs cost $8.88.

## Setup

- **Tasks.** 8 merged PRs, each started from the commit just before its merge, with a prompt
  written from the PR's symptom, not its fix (`tasks.json`): agent-kit #98, #108, #106, #103,
  #71 and #79 (read-only, scoped to this repo), and agent-ledger #15 and #42.
- **Snapshots.** `git init` plus a shallow fetch of that one commit, so a candidate saw no later
  commits, no remote and no `FETCH_HEAD`. `git grep R43` found no mention at any base.
- **Candidates.** `claude -p` on Sonnet 5.5 (the `code` role) with `--setting-sources ""`,
  `--strict-mcp-config` and `--disable-slash-commands`. Each run's init event shows no user
  rules, no MCP servers and no skills. The kit's skills sat at a neutral path outside the repo.
  Runs were sandboxed: writes only to the folder and the system temp folder, and no network.
  `gh`, `git push` and web tools were disallowed. Each run had a $2 cap (no run reached it), and
  its stream-json transcript was kept outside its view. Directory names and prompts held none of
  the Eval playbook's banned words.
- **Judge.** `cli:cursor-agent:gpt-5.6-sol-high` through `second_opinion.py`, one call per task
  scoring all three runs together. Labels A/B/C came from a per-task seed. The judge also got
  the merged diff as "one accepted fix; other correct fixes exist". All 8 calls returned
  `status: ok` with parseable JSON (30 to 74 seconds each), so no verdict is missing.
- **Rubric and rules** are in `prereg.md`, written before the first judge call. Each item is
  scored 1 to 5. Win share = (wins + 0.5 x ties) / tasks. Noise band = |share(full1 over
  full2) - 0.5|. Slim holds on an item if share(slim over full), pooled over both full runs,
  is at least 0.5 - band.

## Results

| Item | full1 over full2 | Noise band | slim over full1 | slim over full2 | slim over full | Holds |
|---|---|---|---|---|---|---|
| cause | 0.375 | 0.125 | 0.500 | 0.375 | 0.438 | yes |
| fix | 0.438 | 0.063 | 0.500 | 0.500 | 0.500 | yes |
| proof | 0.313 | 0.188 | 0.438 | 0.313 | 0.375 | yes |
| scope | 0.500 | 0.000 | 0.375 | 0.313 | 0.344 | **no** |
| reply | 0.375 | 0.125 | 0.375 | 0.188 | 0.281 | **no** |

Mean scores (full1 / full2 / slim): cause 4.63 / 4.88 / 4.38, fix 3.75 / 4.38 / 4.00, proof
4.13 / 4.38 / 3.88, scope 4.38 / 4.38 / 4.00, reply 4.00 / 4.38 / 3.38. Per-task verdicts and
notes are in `verdicts.json`, and the computed shares are in `scores.json`.

Resolution: one task moves a share by 12.5 points, and each band is one sample of the gap
between identical runs. The scope band is 0 because full1 and full2 tied on scope overall, so
any slim deficit on scope counts. That makes the scope result weak. The reply result is
firmer: slim scored below both full runs on 4 of 8 tasks (t4, t5, t6, t8) and above both on
none.

## What the candidates did (from transcripts, not replies)

| | full (16 runs) | slim (8 runs) |
|---|---|---|
| Opened a playbook file | 10 | 8 |
| Opened a principle file | 0 | 0 |
| Read the repo's own copy of beau-mode `SKILL.md` | 0 | 0 |

- **Playbooks.** The slim arm opened its playbook every time. The full arm skipped it in 6 of
  16 runs (t2-full2, both t3 runs, t4-full1, both t6 runs). Both arms have the same step 2, so
  the full arm's extra 2,400 words seem to crowd out the step they share. That is inferred from
  24 runs.
- **Principles.** No run in either arm opened a principle file, though both arms' step 3 points
  at them. The full arm's principles index caused no reads in these tasks.
- **Gates.** t7-full1 found the cause, changed nothing and stopped. Both fixes it saw changed a
  stored entry's shape, so it asked for that call. In the real PR (agent-ledger #15), Beau made
  that same call ("Beau chose to change the shape"). The rubric has no item for stopping at a
  human decision, so the judge gave it fix 1 and scope 2. In my reading, this run did what
  beau-mode's Policy section asks, and the rubric under-scores it. Scoring it fairly would only
  widen the gap in the full arm's favor.

## My read against the judge's (Eval step 6)

I read the outputs behind the largest gaps:

- **t8-slim** (cause 2, fix 1): it assumed `github.base_ref` names the parent PR's branch and
  built the fix on that. The merged PR shows `base_ref` is `main` in a stack, so its fix leaves
  the reported failure in place. I agree with the judge.
- **t4-slim** (reply 2): it said the full-suite failures "aren't from my change", then admitted
  it never ran the suite on unmodified main. I agree.
- **t7-full1**: see Gates above. I disagree with its low fix score, for a reason the rubric
  doesn't cover.

**Cross-check without the judge.** For t3, t7 and t8 I ran each merged PR's new tests against
every candidate's code (`runs.tsv`). They fail on the unmodified base and on nearly every
candidate, because they test the merged design (its error text, its data shape) rather than the
behavior. The only partial pass is t8-full2 (2 of 3), which the judge also scored best on t8.
These tests are too strict to separate the arms.

## Threats to validity

- **The judge has beau-mode loaded.** `cursor-agent` loads Beau's user rules and skills,
  beau-mode among them, and no flag turns that off (measured 2026-11-26, recorded in
  `references/second-opinion.md`). It is an independent model but not an independent reader of
  these conventions. It may reward replies written the way beau-mode's "Writing the reply" asks,
  and only the full arm has that section. That bias points at the reply item, one of the two
  where slim lost.
- **Small n.** 8 tasks, and one pair of identical runs for the band. A rerun could move any
  share by a task or two.
- **Label position was not balanced.** Slim was A in 3 tasks, B in 1 and C in 4.
- **One model, one tool.** Candidates were Sonnet in `claude -p` only. R25 wants runs in more
  than one tool before any cut.
- **The sandbox limited proof.** `uv` could not write its cache, so `make` targets that need
  Python 3.12 failed in every arm. The equal handicap may hide a difference on proof.
- **One judge, and no human-annotated check** of its scores (Uber's ablation has one).
- **The rubric scores outcomes**, not beau-mode habits, and has no item for rightly stopping at
  a human decision (t7-full1).

## What next

- **R13's beau-mode comparison** can reuse `tasks.json`, the harness and these full runs as its
  beau-mode arm (source: ROADMAP R13, "can reuse its tasks"). R42 already reuses them as its
  no-KB arm and noise band.
- **Why the full arm skips its playbook in 6 of 16 runs** (inferred from the table above). This
  is where the always-on text plausibly distracts. A follow-up eval could move or repeat step 2
  at the end of `SKILL.md` and count playbook opens. Under R25 it needs that eval before any
  edit.
- **No cut is proposed.** R43 requires the slim arm to hold on every item first, and it did not.
