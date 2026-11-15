---
name: qualitydirector
description: The Quality Director measures what a repo's tests cost and what they catch, from per-test time and outcome, and proposes changes for you to approve. It records a unittest run to JSON Lines and checks the quality books (runs.csv, tests-weekly.csv). Use for "record the tests", "how long do our tests take", "check the quality books", "which tests are slow or flaky", or when a quality books CI check fails.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Quality Director

The Quality Director measures test economics across Beau's repos: how long each test takes, how often it fails, and what the suite costs per run. It writes numbers into the quality books (a private git repo with `books/runs.csv` and `books/tests-weekly.csv`) and proposes changes. Phase 1 is measurement only.

## The hard rule

It measures and proposes. It never acts on tests itself:

- It never skips, deletes or weakens a test.
- It never changes another repo's CI on its own.
- It never adds a dependency.

Each of those is a question for the human, written with the evidence (the numbers and the run links) and a best guess.

## Record a run

```sh
uv run --python 3.12 <skill dir>/scripts/quality.py record tests --out run.jsonl --repo agentfiles
```

Runs `python -m unittest discover -s tests` in a child process and records it from outside, so nothing a test does can change the file: a test that stubs `json`, closes `sys.stdout`, empties `PATH`, raises `KeyboardInterrupt` or calls `os._exit` still leaves a true file. The child is the same Python with the same flags, directory and environment, and a test sees the same `sys.argv`, `sys.path` and loaded modules as under plain unittest (the one difference is `__main__`, which is not `unittest.__main__`). unittest's normal report goes to stderr. The file `run.jsonl` is a header line (repo, sha, event, python, wall time, the child's `exit_code`, `complete`, counts, link to the CI run) and one line per test with `id`, `outcome` (`pass`, `fail`, `error`, `skip`) and `ms`. A module that fails to import and a setUpClass that raises each get an `error` line, and so does a test that started and never finished (an interrupt, `os._exit`, a crash or a kill). Prints `recorded N tests in M ms -> run.jsonl`. The recorder is POSIX only.

`exit_code` in the header is how the child ended, as a shell says it (128+N after signal N). The recorder exits with that status when it is not 0, so it matches plain unittest (1, 5 on 3.12 and later when no test started, 130 after an interrupt, a `SystemExit` code from setUpClass). `complete` in the header is `true` when unittest's run finished normally (after the last test and module teardown) and `false` when it was cut short by `SystemExit`, `KeyboardInterrupt`, `os._exit`, a signal, or a test that closed the pipe the recorder reads. A run that is not complete is never green.

The recorder is stricter than plain unittest in three cases, where it exits 1 instead of 0:

- The run is not complete (`SystemExit(0)` or `os._exit(0)` in a later class's setUpClass after a passing test).
- No test ran.
- A test ended the process while it ran (`os._exit(0)`), which leaves an `error` row.

A recorder started with SIGHUP ignored (under `nohup`) ignores it, as plain unittest would; SIGTERM and SIGHUP otherwise go on to the suite. Bad usage exits 2, including an output directory that is missing or not writable, which is found before any test runs. The file goes to the path as given from the starting directory, even if a test changes directory.

## Check the books

```sh
uv run --python 3.12 <skill dir>/scripts/quality.py check BOOKS_DIR [--base origin/main]
```

`BOOKS_DIR` is the books repo root. Prints one `path:line: message` per problem, then `ok, N rows, 0 problems` or `N problems`. With `--base REF`, `runs.csv` may only grow: no earlier line may change or go away; `BOOKS_DIR` must then be the top level of its git work tree. A file with CRLF line endings or a UTF-8 BOM is rejected by name. `runs.csv` has the columns `started,repo,sha,event,workflow,python,tests,failed,skipped,wall_ms,exit_code,evidence`; `exit_code` is the `exit_code` from the recorder's header and must be an integer from 0 to 255 (0 with `failed` above 0 is valid: the run ended 0 but a row failed). It has no `complete` column. Run it before committing to the books.

Known limits:

- A test that closes or reuses every open file descriptor (`os.closerange(3, 256)`) cuts the recorder off from the suite. Rows after that point are lost, the header says `complete: false`, and the run never exits 0.
- SIGINT sent to the recorder process alone (not the process group) is ignored. Ctrl-C in a terminal reaches the whole group, so it stops the suite as usual.

Without uv, use any Python 3.10 or later. The script uses only the standard library.
