---
name: qualitydirector
description: The Quality Director measures what a repo's tests cost and what they catch, from per-test time and outcome, and proposes changes for you to approve. It records a unittest run to JSON Lines, books recorded runs into the quality books (runs.csv, failures.csv, tests-weekly.csv), checks them, and summarizes a week as JSON. Use for "record the tests", "how long do our tests take", "book the test runs", "quality summary for the week", "check the quality books", "which tests are slow or flaky", or when a quality books CI check fails.
license: MIT
metadata:
  author: lyddonb
  version: "0.2.0"
---

# Quality Director

The Quality Director measures test economics across Beau's repos: how long each test takes, how often it fails, and what the suite costs per run. It writes numbers into the quality books (a private git repo with `books/runs.csv`, `books/failures.csv` and `books/tests-weekly.csv`) and proposes changes. Phase 1 is measurement only.

## The hard rule

It measures and proposes. It never acts on tests itself:

- It never skips, deletes or weakens a test.
- It never changes another repo's CI on its own.
- It never adds a dependency.

Each of those is a question for the human, written with the evidence (the numbers and the run links) and a best guess.

## Record a run

```sh
uv run --python 3.12 <skill dir>/scripts/quality.py record tests --out run.jsonl --repo agentfiles \
  --sha "${{ github.event.pull_request.head.sha || github.sha }}"
```

`--sha SHA` (40 lowercase hex, exit 2 otherwise) sets the header's `sha` and wins over `GITHUB_SHA` and git. Use it in a GitHub workflow: on `pull_request` events `GITHUB_SHA` is a temporary merge commit, not the commit the PR tests, and the line above records the PR head (`github.sha` is right on `push`).

Runs `python -m unittest discover -s tests` in a child process and records it from outside, so nothing a test does can change the file: a test that stubs `json`, closes `sys.stdout`, empties `PATH`, raises `KeyboardInterrupt` or calls `os._exit` still leaves a true file. The child is the same Python with the same flags, directory and environment, and a test sees the same `sys.argv`, `sys.path` and loaded modules as under plain unittest (the one difference is `__main__`, which is not `unittest.__main__`). unittest's normal report goes to stderr. The file `run.jsonl` is a header line (repo, sha, event, python, wall time, the child's `exit_code`, `complete`, counts, link to the CI run) and one line per test with `id`, `outcome` (`pass`, `fail`, `error`, `skip`) and `ms`. A module that fails to import and a setUpClass that raises each get an `error` line, and so does a test that started and never finished (an interrupt, `os._exit`, a crash or a kill). Prints `recorded N tests in M ms -> run.jsonl`. The recorder is POSIX only.

`exit_code` in the header is how the child ended, as a shell says it (128+N after signal N). The recorder exits with that status when it is not 0, so it matches plain unittest (1, 5 on 3.12 and later when no test started, 130 after an interrupt, a `SystemExit` code from setUpClass). `complete` in the header is `true` when unittest's run finished normally (after the last test and module teardown) and `false` when it was cut short by `SystemExit`, `KeyboardInterrupt`, `os._exit`, a signal, or a test that closed the pipe the recorder reads. A run that is not complete is never green.

The recorder is stricter than plain unittest in three cases, where it exits 1 instead of 0:

- The run is not complete (`SystemExit(0)` or `os._exit(0)` in a later class's setUpClass after a passing test).
- No test ran.
- A test ended the process while it ran (`os._exit(0)`), which leaves an `error` row.

A recorder started with SIGHUP or SIGINT ignored (under `nohup`, or `cmd &` in a non-interactive shell) leaves it ignored for the suite, as plain unittest would; SIGTERM and SIGHUP otherwise go on to the suite. Bad usage exits 2, including an output directory that is missing or not writable, which is found before any test runs. The file goes to the path as given from the starting directory, even if a test changes directory.

## The books

Three CSV files in the books repo, all UTF-8 with LF line endings:

| File | One row per | Rule |
|---|---|---|
| `books/runs.csv` | recorded CI run | append-only. Columns `started,repo,sha,event,workflow,python,tests,failed,skipped,wall_ms,exit_code,evidence`. `exit_code` is the recorder's verdict for the run (a run cut short at child exit 0 is booked as 1); `failed` is the number of distinct failing tests |
| `books/failures.csv` | failing test in a run | append-only. Columns `started,repo,sha,python,test_id,outcome,evidence`; `outcome` is `fail` or `error`; unique on `(evidence, python, test_id)` |
| `books/tests-weekly.csv` | ISO week, repo and test | rows are updated in place and kept sorted by `(week, repo, test_id)`. Columns `week,repo,test_id,runs,failed,total_ms,max_ms`; `runs` counts runs with a pass, fail or error row (not skip) |

`evidence` is the link to the CI run. A run is keyed by `(evidence, python)`.

## Book the runs

```sh
uv run --python 3.12 <skill dir>/scripts/quality.py ingest BOOKS_DIR ARTIFACT_DIR [--dry-run] [--json]
```

`ARTIFACT_DIR` is a folder of downloaded artifacts (`gh run download` gives `<run dir>/<artifact name>/test-results.jsonl`); every `*.jsonl` under it, at any depth, is one recorded run. Ingest prints one line per file (`booked`, `skipped, already booked`, `skipped, not a CI run`, or `rejected: <file>: <reason>`), then a totals line.

- Artifacts are untrusted, because CI runs pull-request code. A file is parsed strictly and rejected, with its name and the reason, if the header is not `v` 1, a key is missing, unknown or of the wrong type, `sha` is not 40 hex, `evidence` is not a run link, an outcome is not `pass`, `skip`, `fail` or `error`, an id is empty, a number is negative or not an integer, or the header counts disagree with the rows. Nothing in a file is executed, imported or evaluated; a test id is data and may hold commas, quotes and newlines.
- A rejected file never stops the good ones: they are booked, and ingest then exits 1 so the rejection is seen.
- A run with an empty `evidence` or `event` `local` is skipped with a note. A run already in `runs.csv` is skipped, so ingesting the same folder twice changes nothing.
- The three files are built in memory and checked, and written (to temp files, then renamed) only if the result passes. Books that fail `check` before the ingest are refused (exit 1).
- A test id that appears twice in one run (a suite that runs another suite inside a test) counts as one test: its time is added.
- `--dry-run` writes nothing. `--json` gives the same report as one object.

New rows go in the order `started`, `evidence`, `python`, `test_id`. That order holds within one ingest; a later ingest appends after the earlier rows, so `runs.csv` and `failures.csv` only match byte for byte when the batches are cut from that order. `tests-weekly.csv` does not depend on batches or order.

## Summarize a week

```sh
uv run --python 3.12 <skill dir>/scripts/quality.py summary BOOKS_DIR --week 2026-W46 --json
```

`--week` defaults to the latest week in `runs.csv`. Books that fail `check` are refused. Without `--json` it prints a short readable version. With `--json` it is one object, keys sorted, every number an integer (milliseconds and counts, no floats), the same bytes on every run:

- `week`, `generated_from` (`runs`, `failures`, `weekly_rows`: rows in each file), `thresholds` (`suite_median_ms`: 300000).
- `repos.<repo>`: `runs`, `red_runs` (`exit_code` not 0), `tests` (the latest run's count), `suite_ms` (`median`, `max`, `by_python`), `suite_ms_prior4` (`median` and `weeks`) and `suite_ms_change`, `ci_wall_ms`, `slowest_tests` (top 10 by `mean_ms`, which is `total_ms // runs`), `failed_on_main`, `flaky`, `tests_added`, `tests_removed`, `over_threshold`.
- `slowest_tests` across all repos, each with `repo`.

A suite's time is a run's `wall_ms`. A median of an even count is the lower of the two middle values, so it is always a time one run had. `suite_ms_prior4` pools the runs of the four calendar ISO weeks before the week (only those that have runs; `weeks` says how many) and is `null` with none. `over_threshold` is true when the suite median is above 300000 ms (300 seconds): exactly 300000 is not over. `tests_added` and `tests_removed` compare this week's tests with the previous week that has rows for the repo, and are empty with no such week. `failed_on_main` lists this week's failures in runs whose `event` is `push`; the books do not record the branch, so a push to any branch counts.

**Flaky** means a test with a failure row this week, for a `(repo, sha, python)` that has another run in the books (any week) with no failure row for that test. The entry lists the failing and the passing evidence links. A sha whose every run failed the test is not flaky. The Python version is part of the key, because a test that fails only on 3.10 is a compatibility bug. The books keep failures only, so a run in which the test was skipped or did not exist, or that is red for another test, counts as passing it: treat `flaky` as a lead to check in the run logs, never as proof.

**A brief's numbers come only from `summary --json`.** Copy them; never add, average or estimate them in prose. When a number is not in the output, say it is not measured.

## Check the books

```sh
uv run --python 3.12 <skill dir>/scripts/quality.py check BOOKS_DIR [--base origin/main]
```

`BOOKS_DIR` is the books repo root. Prints one `path:line: message` per problem, then `ok, N rows, 0 problems` or `N problems`. It checks each file's header, types, ranges, uniqueness and sort order (`tests-weekly.csv`), that `failed <= runs` and `max_ms <= total_ms`, that `week` is a real ISO week and `evidence` a run link, and across files: every `failures.csv` row belongs to a run in `runs.csv` (same `evidence` and `python`, and the same `started`, `repo` and `sha`), and each run has exactly as many `failures.csv` rows as its `failed`. A missing `failures.csv` is a problem: the books repo adds it in the same PR that moves its pin to this version. With `--base REF`, `runs.csv` and `failures.csv` may only grow: no earlier line may change or go away; `BOOKS_DIR` must then be the top level of its git work tree. A file with CRLF line endings or a UTF-8 BOM is rejected by name. `exit_code` is an integer from 0 to 255; `runs.csv` has no `complete` column. Run it before committing to the books.

Known limits:

- A test that closes or reuses every open file descriptor (`os.closerange(3, 256)`) cuts the recorder off from the suite. Rows after that point are lost, the header says `complete: false`, and the run never exits 0.
- SIGINT sent to the recorder process alone (not the process group) is ignored. Ctrl-C in a terminal reaches the whole group, so it stops the suite as usual.

Without uv, use any Python 3.10 or later. The script uses only the standard library.
