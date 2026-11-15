# The weekly quality brief

The run that turns a week of CI test records into a brief Beau signs off. The books repo's `AGENTS.md` is the rulebook and wins over this file. `Q` below is `uv run --no-project --python 3.12 <this skill>/scripts/quality.py`; `BOOKS` is the books repo root (`lyddonb/quality`); `FETCHED` is a new scratch folder outside every repo.

Measure and propose. Never skip, delete, loosen or retry a test, never change a watched repo, never edit the books by hand, and never take a number from anywhere but `summary --json`.

## 1. Fetch

```sh
Q fetch BOOKS FETCHED
```

Lists each watched repo's completed runs on GitHub and downloads their test records. It needs `gh`, signed in. With no `--since` it starts three days before the latest run already booked for each repo, or seven days back for a repo with none. Read the last line: it counts runs fetched, listed, and skipped as forks, as pushes off the default branch, as already booked, and as having no test record.

Exit 1 means at least one run could not be fetched (`FAILED RUN_ID: why`). Carry on, and report each one in the brief. Exit 2 is a setup problem (no `gh`, bad arguments): stop and report it.

## 2. Book

```sh
Q ingest BOOKS FETCHED
```

Books each new run once: a row in `books/runs.csv`, a row per failing test in `books/failures.csv` (at most 200 per run record), and the per-test rows in `books/tests-weekly.csv`. One line per file says `booked`, `skipped, already booked`, or `rejected: <file>: <reason>`.

Exit 1 means something was rejected or left unread. What was good is still booked. Report each rejection and unread run by name in the brief. Never edit a fetched file, a manifest or a books file to get past a rejection: a rejection is a finding.

## 3. Summarize

```sh
Q summary BOOKS --json > FETCHED/summary.json
```

This is the only source of numbers. The default week is the latest week with runs; pass `--week YYYY-Www` to write up another. Every value is an integer: times are milliseconds. Copy values exactly, with their unit. Do not convert, round, add or compare them yourself; `suite_ms_change` already holds the change from the prior four weeks, and it is `null` when there are no earlier weeks.

## 4. Write the brief

Write `BOOKS/briefs/YYYY-MM-DD.md` from `BOOKS/briefs/TEMPLATE.md`, keeping all six sections in order.

- **Headline:** one sentence. If anything could not be fetched or booked, the same sentence says so.
- **Time:** one table row per repo from `repos.<repo>`, then the top-level `slowest_tests`.
- **Reliability:** `flaky` and `failed_on_main` per repo, then every fetch failure, rejection and unread run. A flaky entry is a lead, not proof: say that a run without the failure may have skipped the test.
- **Changes since last brief:** `tests_added` and `tests_removed`.
- **Proposals:** at most three, most valuable first. Each names the measured number it rests on, says what would change, and points to the question id that asks Beau to decide. Good proposals are specific and reversible, for example "move test X (8484 ms mean) to a nightly job". Never propose skipping, deleting, loosening or retrying a test, and never propose a dependency without a `deps.yaml` entry in the same question.
- **Questions:** the open questions from `questions.md` by id.

Paste the whole `summary.json` in the details block at the foot, so every number can be checked against it.

Update `BOOKS/questions.md` by the rules at its top: a new question takes the next unused id; an answered one moves to Answered with the date.

## 5. Check

```sh
Q check BOOKS --base origin/main
```

It must print `ok, N rows, 0 problems`. CI runs the same check. If it names a problem in a books file, do not edit the file: say what `ingest` wrote and why the check refused it.

Then audit the brief once: every number in it must appear in `summary.json` exactly.

## 6. Open one pull request

Never write to `main`. If a brief PR is already open, add this week's commit to its branch; unmerged weeks share one PR. Otherwise branch `quality/brief-YYYY-MM-DD` from `origin/main`. Commit the brief, `questions.md` and the three books files together, push by explicit branch name, and open or update the PR through the REST API. Title it `Quality brief YYYY-MM-DD: <headline>`. Never merge, approve or force-push. Merging is Beau's sign-off.

Tell Beau the headline, the proposals with their numbers, the open questions, the PR link, and whether the `books` and `ledger-verify` checks passed.
