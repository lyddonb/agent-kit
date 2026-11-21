# The speed ladder

The order in which the Quality Director may propose making a watched repo's CI faster. Read it before writing a speed proposal in a brief. It proposes; it changes no workflow and no test. The hard rule in `SKILL.md` and the books repo's `AGENTS.md` still hold, and `AGENTS.md` wins.

Work down the rungs in order, one repo at a time. Propose from the first rung that is open for that repo. A lower rung stays shut while a rung above it is open and its question is unanswered. A rung Beau answered "no" counts as shut until its numbers change.

Each rung has three parts. **Opens when** is a test on values the tools print: `repos.<repo>.lifecycle` and the other keys of `summary --json`, and `audit-ci REPO_DIR --json` run on a current checkout of the repo. **Proof** is what the proposal must show. **Ask** is the question for `questions.md`.

## Rules for every rung

- Copy numbers exactly as printed, with their key names. Compare two printed numbers; never add, divide or take a share by hand. Times have one second resolution, so a difference of 1000 ms is not a finding.
- A value that is `unknown`, `null` or absent does not open a rung. Say it is not measured.
- No speed from hiding failures: never propose a retry, a skip, a quarantine or a wider timeout to make a run pass.
- Anything that runs fewer checks narrows pull-request feedback only. The full suite, in every version, still runs on every push to the default branch.
- Say what gets slower or dearer. Splitting a job cuts `run_ms` and raises `billed_ms`; quote both.
- One change per proposal. Its question says which keys will be compared, before and after, over which weeks. Do not credit a change with a drop in a week when the number of tests or runs also changed.
- At most three proposals in a brief, as always.

## 1. Delete: stop work nobody waits for

- **Opens when:** `audit-ci` gives `summary.pull_request_workflows_without_cancel` above 0. Name each workflow whose `on_pull_request` is true and whose `concurrency.cancel_in_progress` is `no`.
- **Proof:** none about coverage is needed, because the newest commit of a pull request still gets every check. Quote the repo's `lifecycle.runs` and `lifecycle.billed_ms` for scale. How many runs were superseded is not in the books; say so.
- **Ask:** "Cancel superseded pull-request runs in WORKFLOW of REPO (`concurrency` with `cancel-in-progress` for pull requests only)?" Runs on the default branch are never cancelled.

## 2. Budget: bound every job

- **Opens when:** `audit-ci` gives `summary.jobs_without_timeout` above 0, and the repo has `lifecycle.job_ms.p95` for the last two briefs.
- **Proof:** `job_ms.p95` from both briefs. Propose `timeout-minutes` of about twice the larger one, rounded up to a whole minute, and show the two numbers so Beau can check the doubling. This is the one place a number is worked out; it goes in the question, not the brief's tables.
- **Ask:** "Set `timeout-minutes: N` on JOB of REPO?" A timeout is a bound on a hung job. Never propose raising one to get a slow run through.

## 3. Stage: run each check where it pays

- **Opens when:** `audit-ci` shows a job whose `matrix.combinations` is above 1 and whose `matrix.full_on_pull_request` is `yes`.
- **Proof:** `lifecycle.billed_ms` beside `lifecycle.run_ms.median`, and every entry of `failed_on_main`, `caught_on_pr` and `flaky` from the briefs so far that names one version only. The cost is plain: a bug that shows in one version is found after merge, not before. If the books hold fewer than four briefs, say the history is too short to judge that cost.
- **Ask:** "Run JOB of REPO on one version for pull requests and on all of them for pushes to the default branch and weekly?"

## 4. Cache: stop rebuilding the same environment

- **Opens when:** the repo's `lifecycle.with_suite.outside_suite_ms` is above its `with_suite.suite_ms`, `with_suite.runs_floored` is 0, and `audit-ci` shows `caching` empty for the job.
- **Proof:** the step to cache, from `lifecycle.slowest_steps`, with its `median`, `p95` and `steps`. It must be a set-up or install step. The step that runs the tests is never a cache target.
- **Ask:** "Cache STEP in JOB of REPO (median N ms)?" Say what the cache is keyed on, and that a stale cache must fail loudly, not pass quietly.

## 5. Parallelize: split a serial job

- **Opens when:** rung 4 is shut for the repo, and `lifecycle.slowest_steps` still holds a step other than the test step whose `median` is above the repo's `queue_ms.max`. Below that, the wait for a second runner costs more than the split saves.
- **Proof:** that step's `median`, the repo's `run_ms.median` and `billed_ms`. State that a second job repeats checkout and set-up, so `billed_ms` rises.
- **Ask:** "Move STEP of REPO into its own job that runs beside the tests?"

## 6. Select: run only the tests a change can reach

- **Opens when:** `repos.<repo>.over_threshold` is true, which means `suite_ms.median` is above `thresholds.suite_median_ms` (300000). Not before.
- **Proof:** a selection proof. Hide a real change from the selector or path filter and show CI goes red; keep that as a test. An unknown dependency widens the run and never justifies a skip. With zero misses in N planted changes, the 95% bound on the miss rate is about 3/N: give the N. `audit-ci` reports every path filter's `selection_proof` as `not checked`, so the proof is cited by hand until a convention exists.
- **Ask:** "Open test selection for REPO?" This is phase 6 of the books' roadmap and gets its own plan.

## 7. Shard: split the suite across runners

- **Opens when:** rung 6 is in place for the repo and `over_threshold` is still true.
- **Proof:** `tests-weekly.csv` times that fill the shards evenly, and the fixed cost each shard repeats, from `slowest_steps`. Too many shards repeat checkout and start-up for little work.
- **Ask:** "Split REPO's suite into N shards?"

## What the ladder does not cover

Cycle time from opening a pull request to merging it, and how many runs are superseded, are not in the books. A proposal that needs one asks for the measurement first.
