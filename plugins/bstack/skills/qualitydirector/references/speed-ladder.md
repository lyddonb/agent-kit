# The speed ladder

The order in which the Quality Director may propose making a watched repo's CI faster. Read it before writing a speed proposal in a brief. It proposes; it changes no workflow and no test. The hard rule in `SKILL.md` and the books repo's `AGENTS.md` still hold, and `AGENTS.md` wins.

Work down the rungs in order, one repo at a time. Propose from the first rung that is open for that repo. A lower rung stays shut while a rung above it is open and its question is unanswered. A rung Beau answered "no" counts as shut until its numbers change.

Each rung has three parts. **Opens when** is a test on values the tools print. **Proof** is what the proposal must show. **Ask** is the question for `questions.md`.

## Where the values come from

- **The books:** `repos.<repo>.lifecycle` and the other keys of `summary --json`.
- **The workflow:** `audit-ci REPO_DIR --json` on a fresh clone of the repo's default branch, made in this run into a scratch folder outside the books (`gh repo clone GITHUB DIR -- --depth 1`, with `GITHUB` from `books/watched.csv`). Never audit a checkout that was already on disk; it may be stale.
- **Only the watched workflow counts.** In the audit's `workflows`, take the entry whose `name` is the `workflow` in `books/watched.csv`, and its `jobs`. The audit's `summary` counts every workflow in the repo, so do not use it here.
- **The test step** is the step that writes the test record the workflow uploads as a `test-results-` artifact. It runs `quality.py record`, directly or through a make target. Find it by reading the watched workflow's file in the clone. Never decide what a step does from its name.

## Rules for every rung

- Copy numbers exactly as printed, with their key names. Compare two printed numbers; never add, multiply, divide or take a share by hand. Times have one second resolution, so a difference of 1000 ms is not a finding, and a step whose `median` is 1000 is not a target.
- Only `summary --json` numbers go in a brief. State what the audit found in words and names (the workflow, the job, `yes`, `no`, "no timeout"), never as a count.
- A step is a target only when its `steps` is at least the repo's `lifecycle.runs`. A lower count means it did not run in every run, as a scheduled job's step does not.
- A rung that is open but has nothing that qualifies as its target counts as shut. Say so in one sentence and go to the next rung.
- A value that is `unknown`, `null` or absent does not open a rung. Say it is not measured.
- No speed from hiding failures: never propose a retry, a skip, a quarantine or a wider timeout to make a run pass.
- Anything that runs fewer checks narrows pull-request feedback only. The full suite, in every version, still runs on every push to the default branch.
- Say what gets slower or dearer. Splitting a job cuts `run_ms` and raises `billed_ms`; quote both.
- One change per proposal. Its question says which keys will be compared, before and after, over which weeks. Do not credit a change with a drop in a week when the number of tests or runs also changed.
- At most three proposals in a brief, as always.

## 1. Delete: stop work nobody waits for

- **Opens when:** the watched workflow's `on_pull_request` is true, its `concurrency.cancel_in_progress` is `no`, and at least one of its jobs has `concurrency.cancel_in_progress` `no`.
- **Proof:** none about coverage is needed, because the newest commit of a pull request still gets every check. Quote the repo's `lifecycle.runs` and `lifecycle.billed_ms` for scale. How many runs were superseded is not in the books; say so.
- **Ask:** "Cancel superseded pull-request runs in WORKFLOW of REPO (`concurrency` with `cancel-in-progress` for pull requests only)?" Runs on the default branch are never cancelled.

## 2. Budget: bound every job

- **Opens when:** a job of the watched workflow has `timeout_minutes` `null`, and the repo has a `lifecycle.job_ms.p95` in this brief and in the one before it.
- **Proof:** both `job_ms.p95` values, copied. `job_ms` pools every job of the workflow, so for a workflow with more than one job say that the number is pooled.
- **Ask:** "Set `timeout-minutes` on JOB of REPO? `job_ms.p95` was A ms and B ms; the usual bound is about twice the larger." Beau picks the number; do not work it out. A timeout bounds a hung job. Never propose raising one to get a slow run through.

## 3. Stage: run each check where it pays

- **Opens when:** `audit-ci` shows a job whose `matrix.combinations` is above 1 and whose `matrix.full_on_pull_request` is `yes`.
- **Proof:** `lifecycle.billed_ms` beside `lifecycle.run_ms.median`, and, from the briefs so far, every `failed_on_main`, `caught_on_pr.failures` and `flaky` entry for a test that failed in one `python` only. The cost is plain: a bug that shows in one version is found after merge, not before. If the books hold fewer than four briefs, say the history is too short to judge that cost.
- **Ask:** "Run JOB of REPO on one version for pull requests and on all of them for pushes to the default branch and weekly?"

## 4. Cache: stop rebuilding the same environment

- **Opens when:** the repo's `lifecycle.with_suite.outside_suite_ms` is above its `with_suite.suite_ms`, `with_suite.runs_floored` is 0, and the job's `caching` is empty.
- **Proof:** the target step, from `lifecycle.slowest_steps`, with its `median`, `p95` and `steps`. The test step is never a target. Write the step's name in backticks exactly as printed.
- **Ask:** "Is `STEP` in JOB of REPO (median N ms) something a cache would shorten, and should it be cached?" Beau decides what the step does. Say that a stale cache must fail loudly, not pass quietly.

## 5. Parallelize: split a serial job

- **Opens when:** rung 4 is shut for the repo, `with_suite.outside_suite_ms` is still above `with_suite.suite_ms`, and `lifecycle.slowest_steps` holds a step other than the test step whose `median` is above the repo's `queue_ms.max`. Below that, the wait for a second runner costs more than the split saves.
- **Proof:** that step's `median`, the repo's `run_ms.median` and `billed_ms`. State that a second job repeats checkout and set-up, so `billed_ms` rises.
- **Ask:** "Move STEP of REPO into its own job that runs beside the tests?"

## 6. Select: run only the tests a change can reach

- **Opens when:** `repos.<repo>.over_threshold` is true, which means `suite_ms.median` is above `thresholds.suite_median_ms` (300000). Not before.
- **Proof:** a selection proof. Hide a real change from the selector or path filter and show CI goes red; keep that as a test. An unknown dependency widens the run and never justifies a skip. With zero misses in N planted changes, the 95% bound on the miss rate is about 3/N: give the N. The audit reports every path filter's `selection_proof` as `not checked`, so the proof is cited by hand until a convention exists.
- **Ask:** "Open test selection for REPO?" This is phase 6 of the books' roadmap and gets its own plan.

## 7. Shard: split the suite across runners

- **Opens when:** rung 6 is in place for the repo and `over_threshold` is still true.
- **Proof:** `tests-weekly.csv` times that fill the shards evenly, and the fixed cost each shard repeats, from `slowest_steps`. Too many shards repeat checkout and start-up for little work.
- **Ask:** "Split REPO's suite into N shards?"

## What the ladder does not cover

Cycle time from opening a pull request to merging it, and how many runs are superseded, are not in the books. A proposal that needs one asks for the measurement first.
