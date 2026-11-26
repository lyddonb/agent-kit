#!/usr/bin/env python3
"""The Quality Director's primitives: record a test run, fetch the runs of watched repos from GitHub,
book them into the quality books, check the books, and summarize a week. `audit-ci` is separate: it reads a repo's
workflow files, not the books.

Usage:
    uv run --python 3.12 quality.py record TESTS_DIR --out FILE --repo NAME [--sha SHA]
    uv run python quality.py record-junit --junit FILE --out OUT --repo NAME [--sha SHA] -- COMMAND [ARG ...]
    uv run --python 3.12 quality.py fetch BOOKS_DIR OUT_DIR [--since YYYY-MM-DD] [--repo SLUG]
    uv run --python 3.12 quality.py ingest BOOKS_DIR FETCH_DIR [--dry-run] [--json] [--only jobs|visibility]
    uv run --python 3.12 quality.py check BOOKS_DIR [--base REF]
    uv run --python 3.12 quality.py summary BOOKS_DIR [--week YYYY-Www] [--json] [--public-only]
    uv run --python 3.12 quality.py audit-ci REPO_DIR [--json]
    uv run --python 3.12 quality.py leak-check BOOKS_DIR FILE [FILE ...] [--json]
    uv run --python 3.12 quality.py book-skills BOOKS_DIR [--claude-logs DIR] [--cursor-logs DIR] [--lock FILE]
                                                [--since YYYY-MM-DD] [--dry-run] [--json]
    uv run --python 3.12 quality.py migrate-skills BOOKS_DIR [--dry-run]

`record-junit` runs COMMAND (pytest, with `--junitxml=FILE`) and writes the same record from the XML file it left.
`record` runs `python -m unittest discover -s TESTS_DIR` and writes what happened to FILE as
JSON Lines: a run header, then one line per test with its outcome (pass, fail, error, skip) and
milliseconds. Then it prints `recorded N tests in M ms -> FILE`.

The recorder never shares a process with the tests. The parent checks that FILE can be
written (exit 2 if not), reads the start time and git sha, starts a child (the same Python, the
same flags, directory, environment and stdin/stdout/stderr) that runs the suite, and reads the
child's events from a pipe: one line when a test starts, one when each outcome is known. The
parent builds the rows and the header from those events and writes FILE after the child exits,
so nothing a test does (stubbing `json`, closing `sys.stdout`, emptying PATH, `os._exit`, a
KeyboardInterrupt) can change the file or the exit code. A test that started and never finished
is an `error` row. A module that fails to import and a setUpClass that raises each get an
`error` row too. When unittest's run finishes normally the child sends one last event, and the
header says `"complete": true`; a run cut short (SystemExit, KeyboardInterrupt, `os._exit`, a
signal, a test that closed the event pipe) says `false`.

The header's `exit_code` is the child's exit status as a shell reports it (128+N after signal N).
The recorder exits with the child's status when that is not 0. It exits 1 when the run is not
complete, when no test ran, or when a row is fail or error (this includes a test that ended the
process with `os._exit(0)`). These three cases are the only ones where it differs from plain
unittest: a suite cut short at exit 0 and an empty suite never look green. Exit 2 is bad usage, including an output directory
that is missing or not writable.

A test cannot tell the child from `python -m unittest discover -s TESTS_DIR` except through
`__main__` (the child runs a `-c` bootstrap, so `__main__` is not `unittest.__main__`). The
child imports only what plain unittest imports, and `sys.argv`, `sys.path` and `sys.orig_argv`
match. Interpreter flags (`-O`, `-W`, `-X`, `-E`, `-I`, `-P`, `-b`, `-B`, `-s`, `-S`, `-d`,
`-v`, `-q`) are rebuilt from `sys.flags`, `sys.warnoptions` and `sys._xoptions`. `-u` leaves no
trace in those and is not carried (PYTHONUNBUFFERED is, through the environment). POSIX only.

`--sha SHA` (40 lowercase hex, exit 2 otherwise) sets the header's sha and wins over GITHUB_SHA
and git: on pull_request events GITHUB_SHA is a temporary merge commit, so a workflow passes
`--sha "${{ github.event.pull_request.head.sha || github.sha }}"`.

The books are four CSV files under BOOKS_DIR: books/runs.csv (one row per recorded CI run, append
only), books/failures.csv (one row per failing test in a run, append only), books/tests-weekly.csv
(per ISO week, repo and test: runs, failed, total and max milliseconds; rows are updated in place and
kept sorted) and books/watched.csv (the repos to book: `repo,github,workflow`, for example
`agentfiles,lyddonb/agentfiles,ci`; edited by hand). A fifth file is optional: books/kinds.csv
(`repo,prefix,kind`, edited by hand, sorted by repo then prefix) names the tests that are not unit
tests. `prefix` is a module, `module.Class` or a whole test id; a test takes the `kind` (`unit`, `e2e`,
`property` or `differential`) of the row with the longest prefix that matches it on whole dotted segments,
and `unit` when no row matches. A `setUpClass (mod.Class)` or `setUpModule (mod)` row and an import failure
`unittest.loader._FailedTest.mod` are matched as the class or module they name. Books without the file are valid. Only `check` reads its form;
`ingest` never writes it. Two more files, books/jobs.csv and books/steps.csv (one row per CI job and per step, both
append only), are optional until adopted: see "The job books" below.

Trust: CI runs pull-request code, so anyone who can get a workflow to run can write any recorder
file, and runs.csv and failures.csv cannot be edited afterwards. Who a run is therefore comes from
GitHub's API, never from the file. `fetch` writes the API's account of each run as manifest.json;
`ingest` believes the manifest for repo, sha, event, workflow, start time and the run link, and a
recorder file only for what it measured (python, wall_ms, exit_code, complete, its test rows, and the
attempt number inside its evidence when that names this run).

`fetch` asks GitHub through the `gh` CLI (found on PATH, or at $QUALITY_GH) for the completed runs
of each watched repo's workflow created on or after --since (default: the day of the latest
`started` in runs.csv for that repo, else 7 days before today UTC; `--today` sets "today" for tests),
and writes OUT_DIR/<repo>/<run_id>/manifest.json plus OUT_DIR/<repo>/<run_id>/artifacts/<name>/ for each
artifact whose name starts with `test-results-`. It never writes under BOOKS_DIR. A run from a fork
(its head repository is not the watched one) is listed and not downloaded. A push to a branch other than
the default branch is skipped, so every booked `push` run is a push to the default branch and
summary's `failed_on_main` is true to its name. A run whose artifacts are all booked is skipped. An
expired artifact, a failed call or an unsafe archive is reported and the rest carries on. Exit 0 when
everything listed was fetched, 1 when any run could not be, 2 on bad usage, a missing gh, or an OUT_DIR
inside BOOKS_DIR. The calls it makes, in order, for each repo: `gh api --paginate
"repos/O/N/actions/runs?status=completed&per_page=100&created=>=SINCE"`, `gh api repos/O/N`,
and for each run `gh api --paginate "repos/O/N/actions/runs/ID/artifacts?per_page=100"` and, for
each artifact, `gh api repos/O/N/actions/artifacts/ID/zip`. GitHub lists at most 1000 results for a listing filtered by
`created` or `status`, across all of a repo's workflows. When the first listing's `total_count` is over that, the listing is
split at its middle day into `created=A..B` windows (the last stays open-ended) until each is under the cap, and it prints
`listing: N runs since SINCE are over GitHub's 1000; listed in W windows`. A run listed twice is kept once (the larger
`run_attempt`) and printed as `listing: run ID was listed twice; kept once`. A window listed once more when it came back short of its
`total_count`, a window still short, and a single day over the cap are each `FAILED listing`, exit 1, and what was listed is fetched. `--since` filters on a run's creation
date, so a re-run of an old run needs an earlier --since.

Jobs. Once BOOKS_DIR/books/jobs.csv exists (and then books/steps.csv too: see "The job books"), `fetch` also stores what GitHub's Actions jobs API reports for each run it does not
skip: OUT_DIR/<repo>/<run_id>/jobs.json, with `v`, `run_id`, `run_attempt` and per job `id, name, conclusion,
created, started, completed` and its `steps` (`number, name, conclusion, started, completed`), sorted by id
and number. A missing or null timestamp or conclusion is written as "": a skipped job and a cancelled step
are written as reported. It is fetched for a run with no test-results artifact and for a run whose test
record is already booked, and not for a run whose `evidence` is already in jobs.csv. This costs one more
`gh api --paginate "repos/O/N/actions/runs/ID/attempts/ATTEMPT/jobs?per_page=100"` per run. Caps: 64 jobs
per run and 100 steps per job; a run over a cap is refused whole. A failed jobs call, a malformed job or
step, or a run over a cap prints `FAILED RUN_ID: jobs WHY`, writes no jobs.json and makes fetch exit 1, and
the run's artifacts are still fetched. A run whose artifacts fail as a whole keeps the manifest and the
jobs it stored. Without books/jobs.csv none of this happens: the calls, files and
output are the same as before. Names in jobs.json are text a pull request controls; ingest judges them.

Local runs. A watch-list row whose workflow is `local-ci` is read from the repo's refs/local-ci/records, where local-ci
publishes each run's record; see "fetch, local-ci" below.

Volume. Once BOOKS_DIR/books/volume.csv exists, `fetch` also counts the test and source lines of each watched repo for every complete
ISO week not yet booked, at the head of the week's newest push run of the watched workflow on the default branch, and writes
OUT_DIR/<repo>/volume/<week>.json; `ingest` books it and `summary` adds `volume` per repo. See "fetch, volume" below.

Pulls. Once BOOKS_DIR/books/pulls.csv exists, `fetch` also reads every pull request of each watched repo merged on or after
the fetch's since date and not yet booked, with its commits, check runs, commit statuses and timeline, and writes
OUT_DIR/<repo>/pulls/<number>.json; `ingest` books it and `summary` adds `pulls` per repo. SKILL.md, "The pulls book", has the
bucket rule: CI is the union of check and status intervals clipped to the time since ready, wait is the time after the head
commit's last interval that no interval covers, and rework is the rest of the open time (derived by `summary`, never booked).

`check` validates the files (the four books, kinds.csv when it exists, and the two job books when they exist) and prints one `path:line: message` line per problem (path
relative to BOOKS_DIR), then `ok, N rows, 0 problems` or `N problems`. Exit 0 when clean, 1 when
there are problems, 2 on bad usage. With --base REF, runs.csv and failures.csv must be
append-only against REF. It also checks across the files: every failures row belongs to a run,
and a run has exactly as many failures rows as its `failed` says. Every row is held to the row
rules (RUN_RULES, FAILURE_RULES, WEEKLY_RULES, WATCHED_RULES, KINDS_RULES): stamps and weeks in 2020 to 2099,
`python` as 3.0 to 3.99 without leading zeros, cells of at most 1000 characters, and no cell that
starts with = + - @ tab or CR (a spreadsheet would run it) or holds a control character other than
newline and tab (a terminal would obey it).

The job books. books/jobs.csv (`created,repo,sha,event,workflow,job,job_id,conclusion,queue_ms,total_ms,
failed_step_number,evidence`) has one row per job, books/steps.csv (`started,repo,job_id,number,step,conclusion,ms,
evidence`) one row per step; `created` is when the job was queued and a step's `started` is when it ran. A step
reaches its job's sha, event, workflow and name through the join on (`evidence`, `job_id`). Create both files with
their full headers: a file with any other header fails `check`. They are optional until adopted, because books written before they existed have
neither: with neither file, `check`, `ingest`, `fetch` and `summary` print, return and write exactly what they did
before. Exactly one of the two is a `check` problem on the missing file (so every command that refuses books that
fail check refuses it). With both, they are held to `JOB_RULES` and `STEP_RULES` (one set of functions used by
`check` and by `ingest`, like `RUN_RULES`): the header, stamps in 2020 to 2099, `job_id` and `number` as positive
integers without leading zeros, `conclusion` matching [a-z_]{0,30}, `queue_ms`, `total_ms` and `ms` empty or a
non-negative integer, `failed_step_number` empty or a positive integer, the text hygiene and the 1000 characters of every other file, uniqueness on `(evidence,
job_id)` and `(evidence, job_id, number)`, and that every step has a job with the same `(evidence, job_id)` and
`repo`, and that a job's `failed_step_number`, when set, is the `number` of a step of that job whose conclusion
is `failure`. `ok, N rows` counts their rows, and with --base both are append only (a file missing at REF is new and
may have any rows; one that exists at REF and is gone now is `removed since REF`).

`ingest` reads the layout `fetch` writes. For each <repo>/<run_id>/manifest.json: it must agree with
its folder, the repo must be on the watch list with the same github and workflow, `fork` must be false,
`started` must not be after `updated` plus 5 minutes and must be in 2020 to 2099, and a push must be to
the default branch; a manifest that fails is rejected by name with its artifact files unread. Each
*.jsonl under <run>/artifacts is parsed strictly (see `parse_artifact`); a file that is not valid is
named with the reason and skipped, and ingest exits 1 after booking the good ones. The rows a file would
add are built and held to the same row rules `check` uses before anything is planned, so no file can pass
here and fail `check`. Two files in one run folder for the same attempt and python with different
content are both rejected (identical copies count once); a forged file never wins by sorting first. A run
already in runs.csv (same evidence and python) is skipped, so a second ingest changes nothing. The runs.csv
`exit_code` is the recorder's verdict recomputed from the rows (a run cut short at child exit 0 books as
1), and a test with both an `error` and a `fail` line is an `error`: the worst outcome wins. Caps: 8 MB
per file, 20000 test lines per file, 1000 characters per cell, 2000 files and 32 MB of artifacts per
ingest (the rest are counted and named, not read, and ingest exits 1). The three files are built in
memory, checked, and written only if the result passes, all or none. Anything artifact-derived that is
printed has its non-printable characters escaped.

Jobs in ingest, only once the job books are adopted (otherwise jobs.json files are not looked at). A run
folder's `jobs.json` is booked when its evidence is not yet in jobs.csv; its identity needs a valid manifest, and
repo, sha, event, workflow and evidence come from the manifest, never from the file. The file is read strictly (4 MB,
64 jobs, 100 steps, no unknown or missing key), and its `run_id` and `run_attempt` must be the manifest's. Every
job the API reported is booked, `skipped` and `cancelled` ones and ones with no steps included. `created` is the
job's `created` stamp and is required. `queue_ms` is the job's started minus created and `total_ms` completed minus
started, `ms` of a step likewise; each is empty when a stamp it needs is missing or the difference is negative
(empty always means not measured; GitHub reports a skipped job as completing a second before it starts), and 0 is a
real zero at one second resolution. `failed_step_number` is the `number` of the lowest-numbered step whose
conclusion is `failure`, or empty; a name would be ambiguous and does not join. A job or step name is text a
pull request controls: one that is empty, fails text hygiene or is over 1000 characters is booked as
`(unprintable name)` and never blocks the run's timings. A stamp that is not empty and not a valid stamp, or a
conclusion outside its rule, rejects that jobs.json by name and blocks nothing else, not the run's test record
and not other runs. A folder with a manifest, a jobs.json and no artifacts books its jobs and prints no `no
artifacts` line. Per jobs file it prints `booked jobs REPO/RUN: N jobs, M steps`, `skipped jobs REPO/RUN: already
booked`, `skipped jobs REPO/RUN: no jobs` or `rejected: REPO/RUN/jobs.json: why`, and a rejection makes ingest
exit 1. A run with no jobs (a `startup_failure`) can never appear in jobs.csv, so it is reported as `no jobs` on
every ingest and counted in `jobs_empty`, never in `jobs_booked`; fetch still asks the jobs API about it while it is
inside the `--since` window. The totals line and the --json totals gain `jobs_booked`, `jobs_already_booked`,
`jobs_empty`, `jobs_rejected`, `job_rows` and `step_rows`. New job rows are ordered by (created, evidence, job_id)
and step rows by (their job's created, evidence, job_id, number).
`--only jobs` books only jobs and steps: it reads no artifact and leaves runs.csv, failures.csv and
tests-weekly.csv alone; without adopted books it exits 2.

`summary` prints the numbers of one ISO week from books that pass `check`: the one place a
report takes its numbers from. With --json it is one object with sorted keys and integer
numbers only. Per repo, `by_kind` holds all four kinds, each with `tests`, `total_ms`, `caught_on_pr`
and `failed_on_main` (the last two count distinct tests). A median of an even count is the lower of the two middle values.

With adopted job books (both files exist), each listed repo also has `lifecycle`: where the week's CI time went
outside the test suite, from `jobs.csv` and `steps.csv`, or null when no run of the repo belongs to that week.
Without the files the key is absent and the output is what it was before. The repos listed are still those with
`runs.csv` rows in the week, so a repo with job rows and no run rows that week is not listed. A run is one `evidence`
link, so each attempt of a re-run is its own run. A run belongs to one week, whole: the week of its earliest job
`created`, with all its jobs and steps. Times have one second resolution. Skipped jobs and empty (not measured)
times are left out of every median, p95, max and sum. A p95 is the nearest rank, `percentile95`. `run_ms` counts a
run only when every timed job has a `queue_ms`. `with_suite` counts a run only when it has timed jobs, no job that is
neither skipped nor timed, and a `runs.csv` row (any week); `outside_suite_ms` is the sum over those runs of job time
minus suite wall time, each floored at 0, and `runs_floored` says how many runs the floor acted on. See SKILL.md for
each key.

Skill use. books/skill-uses.csv (`week,skill,source,version,tool,how,calls,searches,errors,verdict,use,input_tokens,
output_tokens,cache_write_tokens`) has one row per skill invocation and is append only. A file with the earlier header,
the same without the three token columns, is valid too: its rows read with empty token cells and `book-skills`
appends rows in its shape; `migrate-skills` moves it to the full header, adding an empty cell per token column to
every row, which `check --base` accepts and no other change to an old row. It is optional until created with its header: without the file every
command prints, returns and writes what it did before, and `book-skills` exits 2. With it, `check` holds each row to
`SKILL_RULES` (a real ISO week; `skill` matching [A-Za-z0-9][A-Za-z0-9._-]{0,99}; `tool` claude-code or cursor;
`verdict` unjudged; `use` 16 hex and unique; a claude-code row with `how` one of typed, named, auto, subagent and
`calls` at most 20 with `searches` and `errors` each at most `calls`, and the three token cells all empty or all
non-negative integers; a cursor row with those seven cells empty), and `summary --json` gains `skills` for the week:
`uses`, `window` (20) and `by_skill`, most used first, each with `skill`, `source`, `uses`, `by_how`, `by_tool`, the
sums `calls`, `searches` and `errors`, and `unjudged`, and, when the file has the token columns, the token sums,
`token_uses` and `tokens_per_use` (see `_skill_tokens`).

`book-skills` reads this machine's agent transcripts and appends the uses it has not booked. It runs on the machine
that has the transcripts, never in CI. A Claude Code use is a `Skill` tool call, a slash command followed by the record
that loads a skill, or the first `Read` of a SKILL.md under a folder a tool installs skills into (INSTALLED_ROOTS,
under the home folder) for a skill that chain has not loaded another way; a SKILL.md read anywhere else is a checkout
being edited. Only `user` and `assistant` records are read. `how` is `subagent` in a sidechain; `typed` for a slash
command whose record has `origin.kind` human or no origin at all (those are counted and reported); `named` when the
last text a user record carried names the skill (see `names_skill`), or for a slash command another session sent;
otherwise `auto`. `calls`, `searches` (ToolSearch calls) and `errors` (`is_error` true) count the tool results that
follow the load in the same chain, up to the next turn a human typed or 20 results; the token cells sum the usage
of the model responses in that span (input, output and cache-write tokens, each response once by its message id,
the one that made the load left out). A use that sits in two files (a
resumed or forked session) is booked once, with its longest window. Cursor's only trace is a read of an installed
SKILL.md: one row per transcript and skill, in the week of the file's modification time, with no `how` and no counts.
Only closed ISO weeks (UTC) are booked, since a session still running has a window still growing; `--since` leaves
out earlier days (the weekly job passes the start of the weeks Claude Code's log retention still holds whole).
`source` and `version` come from `--lock`, agentfiles' lock file, as git has it on the day of the use (the file on
disk when git has no commit that early): the lock item that installs the skill, such as `mine:@bstack`, and its
commit. A skill invoked by its bare name takes its plugin from the folder it loaded from, when that folder still
exists. A skill no lock item installs (a project's own, one bundled with the tool, a plugin outside every profile)
is booked with its plugin name as `source` and an empty `version`, and counted as not in the lock. `use` is the first
16 hex of a SHA-256 over the tool-call id (the record id for a slash command; the transcript path and skill for
Cursor): it makes a second run add nothing and says nothing about the session. No transcript text is read into a
row or printed: a row holds names and counts, a name that fails the rules is counted and left out, and the output is
counts and weeks. Exit 0 when it ran, 1 when the books fail `check`, 2 on bad usage or books without the file.

Standard library only; needs Python 3.10 or later (run it through uv).

Shape: `Books` is loaded once (the CSV tables with line numbers; the job books only when the files exist). Each entry in `CHECKS`
takes a `Books` and yields `Problem`s. A new check is a new entry in that registry. Ingest
and summary read the checked tables as typed rows (`RunRow`, `FailureRow`, `WeeklyRow`, `KindRow`, `JobRow`, `StepRow`).
"""
import sys

if sys.version_info < (3, 10):
    sys.stderr.write(
        f"quality.py needs Python 3.10 or later (this is {sys.version_info[0]}.{sys.version_info[1]}). "
        "Run it with: uv run --python 3.12 <path to quality.py> ...\n")
    raise SystemExit(2)

import argparse
import base64
import bisect
import contextlib
import gzip
import csv
import errno
import hashlib
import io
import json
import math
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import tarfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

RECORD_VERSION = 1
OUTCOMES = ("pass", "skip", "fail", "error")  # ordered by severity; a test keeps its worst
RUN_KEYS = ("v", "repo", "sha", "event", "workflow", "python", "os", "started",
            "wall_ms", "exit_code", "complete", "tests", "failed", "skipped", "evidence")
TEST_KEYS = ("id", "outcome", "ms")

RUNS = "books/runs.csv"
FAILURES = "books/failures.csv"
WEEKLY = "books/tests-weekly.csv"
WATCHED = "books/watched.csv"
JOBS = "books/jobs.csv"  # optional until adopted together with STEPS: see check_adoption
STEPS = "books/steps.csv"
KINDS = "books/kinds.csv"  # optional: a book without it is valid and every test is a unit test
REPOS = "books/repos.csv"  # optional until created with its header: what GitHub said about each watched repo's visibility, append only
SKILLS = "books/skill-uses.csv"  # optional until created with its header: one row per skill invocation, append only
VOLUME = "books/volume.csv"  # optional until created with its header: test and source lines per repo per week, append only
PULLS = "books/pulls.csv"
RUNS_SCHEMA = ("started", "repo", "sha", "event", "workflow", "python",
               "tests", "failed", "skipped", "wall_ms", "exit_code", "evidence")
FAILURES_SCHEMA = ("started", "repo", "sha", "python", "test_id", "outcome", "evidence")
WEEKLY_SCHEMA = ("week", "repo", "test_id", "runs", "failed", "total_ms", "max_ms")
WATCHED_SCHEMA = ("repo", "github", "workflow")
KINDS_SCHEMA = ("repo", "prefix", "kind")
JOBS_SCHEMA = ("created", "repo", "sha", "event", "workflow", "job", "job_id", "conclusion",
               "queue_ms", "total_ms", "failed_step_number", "evidence")
STEPS_SCHEMA = ("started", "repo", "job_id", "number", "step", "conclusion", "ms", "evidence")
SCHEMAS = {RUNS: RUNS_SCHEMA, FAILURES: FAILURES_SCHEMA, WEEKLY: WEEKLY_SCHEMA, WATCHED: WATCHED_SCHEMA}  # the files every book has
# The files a book may leave out. ingest never writes kinds.csv. The job books come as a pair: neither file means
# they are not adopted and every command behaves as it did before they existed; exactly one is a check problem.
REPOS_SCHEMA = ("seen", "repo", "github", "visibility")
VISIBILITIES = ("public", "private", "internal", "unknown")
SKILLS_LEGACY_SCHEMA = ("week", "skill", "source", "version", "tool", "how", "calls", "searches", "errors", "verdict", "use")
SKILL_TOKENS = ("input_tokens", "output_tokens", "cache_write_tokens")
SKILLS_SCHEMA = SKILLS_LEGACY_SCHEMA + SKILL_TOKENS
VOLUME_SCHEMA = ("week", "repo", "sha", "rule", "test_files", "test_lines", "source_files", "source_lines", "evidence")
PULLS_SCHEMA = ("merged", "repo", "number", "opened", "ready", "head_ci_done", "ci_ms", "wait_ms", "shas", "checks",
                "force_pushes", "evidence")
OPTIONAL_SCHEMAS = {KINDS: KINDS_SCHEMA, JOBS: JOBS_SCHEMA, STEPS: STEPS_SCHEMA, SKILLS: SKILLS_SCHEMA, REPOS: REPOS_SCHEMA,
                    VOLUME: VOLUME_SCHEMA, PULLS: PULLS_SCHEMA}
LEGACY_SCHEMAS = {SKILLS: SKILLS_LEGACY_SCHEMA}
SKILL_TOOLS = ("claude-code", "cursor")
SKILL_HOWS = ("typed", "named", "auto", "subagent")
SKILL_VERDICTS = ("unjudged",)  # no rule fills a verdict yet
SKILL_WINDOW = 20  # tool results counted after a skill loads
JOB_BOOKS = (JOBS, STEPS)
TABLE_SCHEMAS = {**SCHEMAS, **OPTIONAL_SCHEMAS}
KIND_NAMES = ("unit", "e2e", "property", "differential")
DEFAULT_KIND = "unit"
YEAR_MIN, YEAR_MAX = 2020, 2099  # the years a stamp or a week in the books may have
MAX_CELL = 1000  # characters in one cell, a test id included; the csv module's own field limit (131072) is never reached
FAILING = ("fail", "error")  # the outcomes failures.csv holds
SUITE_MEDIAN_THRESHOLD_MS = 300_000  # a suite whose median wall time is above this is over threshold

# ---------------------------------------------------------------------------
# record: the child
# ---------------------------------------------------------------------------

# The child is `python <flags> -c CHILD FD TESTS_DIR ARGV0 [FLAG...]`. It must look to a test
# like `python -m unittest discover -s TESTS_DIR`, so it imports only what that imports
# (runpy comes with `-m`) and encodes events by hand: no json, no codec lookup. `os.write`,
# the clock and the fd are bound once, so a test that stubs them cannot redirect the stream.
# Events, one per line, fields separated by a tab, the id escaped so it holds no tab or newline:
#   S id            a test started
#   O outcome id    the open test reported an outcome (pass, skip, fail, error)
#   E ms id         the open test finished
#   X outcome id    an outcome for something that never started (setUpClass, import failure)
#   C               unittest's run finished normally (it is the last thing the runner does, so
#                   SystemExit, KeyboardInterrupt, os._exit or a signal never get to send it)
# Only the process that started the run writes: a forked copy of it stays silent.
CHILD = r'''
def _quality_child(fd, tests_dir, argv0, flags):
    import os, sys, time
    import runpy
    import unittest
    write, clock, getpid = os.write, time.perf_counter, os.getpid
    owner = getpid()
    os.set_inheritable(fd, False)

    def escape(text):
        out = []
        for ch in str(text):
            n = ord(ch)
            if ch == "\\":
                out.append("\\\\")
            elif " " <= ch <= "~":
                out.append(ch)
            elif n < 0x10000:
                out.append("\\u%04x" % n)
            else:
                out.append("\\U%08x" % n)
        return "".join(out)

    def ident(test):
        try:
            return escape(test.id())
        except Exception:
            return escape(repr(test))

    def emit(*fields):
        if getpid() != owner:
            return
        try:
            # bytes() and not str.encode: under -X dev the codec lookup would import encodings.ascii
            data = bytes(ord(ch) for ch in "\t".join(fields) + "\n")
            while data:
                data = data[write(fd, data):]
        except Exception:
            pass

    class Result(unittest.TextTestResult):
        # A test may run an inner suite against this same result, so starts nest: a stack.
        _open = ()

        def startTest(self, test):
            emit("S", ident(test))
            self._open = self._open + ((test, clock()),)
            super().startTest(test)

        def stopTest(self, test):
            for i in range(len(self._open) - 1, -1, -1):
                if self._open[i][0] is test:
                    started = self._open[i][1]
                    self._open = self._open[:i] + self._open[i + 1:]
                    emit("E", "%d" % max(0, round((clock() - started) * 1000)), ident(test))
                    break
            super().stopTest(test)

        def _mark(self, test, outcome):
            if isinstance(test, unittest.case._SubTest):
                test = test.test_case
            if any(t is test for t, _ in self._open):
                emit("O", outcome, ident(test))
            elif outcome != "pass":
                emit("X", outcome, ident(test))

        def addSuccess(self, test):
            self._mark(test, "pass")
            super().addSuccess(test)

        def addExpectedFailure(self, test, err):
            self._mark(test, "pass")
            super().addExpectedFailure(test, err)

        def addFailure(self, test, err):
            self._mark(test, "fail")
            super().addFailure(test, err)

        def addError(self, test, err):
            self._mark(test, "error")
            super().addError(test, err)

        def addSkip(self, test, reason):
            self._mark(test, "skip")
            super().addSkip(test, reason)

        def addUnexpectedSuccess(self, test):
            self._mark(test, "fail")
            super().addUnexpectedSuccess(test)

        def addSubTest(self, test, subtest, err):
            if err is not None:
                self._mark(test, "fail" if issubclass(err[0], test.failureException) else "error")
            super().addSubTest(test, subtest, err)

    class Runner(unittest.TextTestRunner):
        resultclass = Result

        def run(self, test):
            result = super().run(test)  # returns only after the last test and the module teardown
            emit("C")
            return result

    if not (sys.flags.isolated or getattr(sys.flags, "safe_path", False)):
        sys.path[0] = os.getcwd()
    sys.argv = [os.path.basename(sys.executable) + " -m unittest", "discover", "-s", tests_dir]
    sys.orig_argv = [argv0] + flags + ["-m", "unittest", "discover", "-s", tests_dir]
    unittest.main(module=None, testRunner=Runner)


import sys
_quality_child(int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:])
'''


# (option, sys.flags attribute, the environment variable that sets the same thing)
_ENV_FLAGS = (("-B", "dont_write_bytecode", "PYTHONDONTWRITEBYTECODE"), ("-s", "no_user_site", "PYTHONNOUSERSITE"),
              ("-P", "safe_path", "PYTHONSAFEPATH"), ("-d", "debug", "PYTHONDEBUG"),
              ("-v", "verbose", "PYTHONVERBOSE"), ("-O", "optimize", "PYTHONOPTIMIZE"))


def interpreter_flags() -> list[str]:
    """The command-line options that changed how this interpreter behaves, for the child.

    Built from sys.flags, sys.warnoptions and sys._xoptions. What the environment already
    supplies (PYTHONWARNINGS, PYTHONOPTIMIZE and the like) reaches the child through the
    inherited environment, so it is not repeated: the child's sys.warnoptions and sys.orig_argv
    must equal plain unittest's.
    """
    f = sys.flags
    from_env = not f.ignore_environment
    args: list[str] = []
    if f.isolated:
        args.append("-I")
    else:
        args += ["-E"] * bool(f.ignore_environment)
    for option, attr, var in _ENV_FLAGS:
        if f.isolated and attr in ("no_user_site", "safe_path"):
            continue  # -I implies them
        want = int(getattr(f, attr, 0))
        have = os.environ.get(var, "") if from_env else ""
        have = (int(have) if have.isdecimal() else 1) if have else 0
        if want > have:
            args.append(option[:1] + option[1] * want)
    args += ["-S"] * bool(f.no_site) + ["-" + "q" * f.quiet] * bool(f.quiet)
    args += ["-" + "b" * f.bytes_warning] * bool(f.bytes_warning)
    warn = list(sys.warnoptions)
    if f.dev_mode and warn[:1] == ["default"]:
        warn = warn[1:]  # -X dev (or PYTHONDEVMODE) puts it there itself
    if from_env:
        in_env = [w for w in os.environ.get("PYTHONWARNINGS", "").split(",") if w]
        if warn[:len(in_env)] == in_env:
            warn = warn[len(in_env):]
    if f.bytes_warning:
        tail = "error::BytesWarning" if f.bytes_warning > 1 else "default::BytesWarning"
        if warn[-1:] == [tail]:
            warn = warn[:-1]  # -b / -bb put it there themselves
    for w in warn:
        args += ["-W", w]
    for key, value in sys._xoptions.items():
        args += ["-X", key if value is True else f"{key}={value}"]
    return args


# ---------------------------------------------------------------------------
# record: the parent
# ---------------------------------------------------------------------------


class Tally:
    """Builds the rows from the child's events. It never runs or imports test code.

    Tests nest: a test may run an inner suite against its own result, so a start arrives while
    the outer test is still open. The open tests are a stack. Each keeps the worst outcome
    reported for it, and `E` closes it with the child's own milliseconds. A test closed without
    any outcome (an interrupt) or never closed (os._exit, a crash, a kill) is an `error`, timed
    by this process's clock.
    """

    def __init__(self, clock=time.perf_counter):
        self.rows: list[dict] = []
        self._clock = clock
        self._open: list[list] = []  # [id, when it started, worst outcome so far], innermost last
        self.complete = False  # the child said its run finished normally
        self._handlers = {"S": self._start, "O": self._outcome_of, "E": self._end, "X": self._alone,
                          "C": self._completed}

    def feed(self, line: str) -> None:
        kind, _, rest = line.partition("\t")
        first, _, test_id = rest.partition("\t")
        handler = self._handlers.get(kind)
        if handler is not None:
            handler(first, test_id)

    def _find(self, test_id: str) -> int | None:
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == test_id:
                return i
        return None

    def _start(self, test_id: str, _: str) -> None:
        self._open.append([_unescape(test_id), self._clock(), None])

    def _outcome_of(self, outcome: str, test_id: str) -> None:
        i = self._find(_unescape(test_id))
        if i is not None and outcome in OUTCOMES:
            entry = self._open[i]
            if entry[2] is None or OUTCOMES.index(outcome) > OUTCOMES.index(entry[2]):
                entry[2] = outcome

    def _end(self, ms: str, test_id: str) -> None:
        i = self._find(_unescape(test_id))
        if i is not None and ms.isdecimal():
            while len(self._open) - 1 > i:
                self._close_innermost(self._clock())  # started inside this one and never finished
            entry = self._open.pop()
            self.rows.append({"id": entry[0], "outcome": entry[2] or "error", "ms": int(ms)})

    def _alone(self, outcome: str, test_id: str) -> None:
        if outcome in OUTCOMES:
            self.rows.append({"id": _unescape(test_id), "outcome": outcome, "ms": 0})

    def _completed(self, _: str, __: str) -> None:
        self.complete = True

    def _close_innermost(self, now: float) -> None:
        test_id, began, outcome = self._open.pop()
        worst = max(outcome or "error", "error", key=OUTCOMES.index)
        self.rows.append({"id": test_id, "outcome": worst, "ms": max(0, round((now - began) * 1000))})

    def finish(self) -> None:
        """The child is gone: every test still open never finished."""
        now = self._clock()
        while self._open:
            self._close_innermost(now)


def _unescape(text: str) -> str:
    try:
        return text.encode("ascii").decode("unicode_escape")
    except UnicodeError:
        return text


def exit_code(child_code: int, records: list[dict], complete: bool) -> int:
    """The recorder's verdict, from the child's exit status, the rows and whether the run completed.

    The child's code stands when it is not 0, so a run exits as plain unittest does. Three guards
    only ever turn a 0 into a 1: a run that did not complete is never green (SystemExit(0) or
    `os._exit(0)` in a setUpClass after a passing test), a run with no rows is never green (plain
    unittest says 0 before 3.12 and 5 after), and a fail or error row is never green (a test that
    ended the process with `os._exit(0)` leaves an `error` row).
    """
    if child_code != 0:
        return child_code
    if not complete or not records:
        return 1
    return 1 if any(r["outcome"] in ("fail", "error") for r in records) else 0


def _git_head(cwd: str) -> str:
    try:
        done = subprocess.run(["git", "-C", cwd, "rev-parse", "HEAD"], capture_output=True, text=True)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _evidence(env) -> str:
    keys = ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
    if not all(env.get(k) for k in keys):
        return ""
    server, repo, run, attempt = (env[k] for k in keys)
    return f"{server}/{repo}/actions/runs/{run}/attempts/{attempt}"


def run_header(repo: str, records: list[dict], started: str, wall_ms: int, child_code: int,
               complete: bool, sha: str, env) -> dict:
    return {
        "v": RECORD_VERSION,
        "repo": repo,
        "sha": sha,
        "event": env.get("GITHUB_EVENT_NAME") or "local",
        "workflow": env.get("GITHUB_WORKFLOW") or "",
        "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
        "os": env.get("RUNNER_OS") or sys.platform,
        "started": started,
        "wall_ms": wall_ms,
        "exit_code": child_code,
        "complete": complete,
        "tests": len(records),
        "failed": sum(r["outcome"] in ("fail", "error") for r in records),
        "skipped": sum(r["outcome"] == "skip" for r in records),
        "evidence": _evidence(env),
    }


def _output_problem(out: str) -> str | None:
    """Why FILE (absolute) cannot be written, found before any test runs."""
    folder = os.path.dirname(out)
    if not os.path.isdir(folder):
        return f"output directory does not exist: {folder}"
    if os.path.isdir(out):
        return f"output path is a directory: {out}"
    if os.path.exists(out):
        return None if os.access(out, os.W_OK) else f"output file is not writable: {out}"
    return None if os.access(folder, os.W_OK | os.X_OK) else f"output directory is not writable: {folder}"


def _sha_arg(text: str) -> str:
    if not _SHA.fullmatch(text):
        raise argparse.ArgumentTypeError(f"must be 40 lowercase hex characters, got {text!r}")
    return text


def _shell_code(returncode: int) -> int:
    """subprocess says -N for death by signal N; a shell says 128+N."""
    return returncode if returncode >= 0 else 128 - returncode


def _read_events(fd: int, proc: subprocess.Popen, tally: Tally) -> None:
    """Feed the child's lines to the tally until the pipe closes.

    The pipe closes when the child exits. A test that leaks the write end to a process that
    outlives the run keeps it open, so once the child is gone only what is already buffered is read.
    """
    pending = b""

    def read_some(timeout: float) -> bool | None:  # True: data, False: nothing now, None: closed
        nonlocal pending
        if not select.select([fd], [], [], timeout)[0]:
            return False
        chunk = os.read(fd, 1 << 16)
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            tally.feed(line.decode("ascii", "replace"))
        return True if chunk else None

    while True:
        got = read_some(0.1)
        if got is None:
            return
        if got is False and proc.poll() is not None:
            while read_some(0):
                pass
            return


def _start_child(tests_dir: str, flags: list[str], write_fd: int) -> subprocess.Popen:
    argv0 = getattr(sys, "orig_argv", [sys.executable])[0]
    return subprocess.Popen(
        [sys.executable, *flags, "-c", CHILD, str(write_fd), tests_dir, argv0, *flags],
        pass_fds=(write_fd,))


def _run_child(tests_dir: str, tally: Tally) -> int:
    """Run the suite in a child and return its exit status as a shell reports it."""
    flags = interpreter_flags()
    read_fd, write_fd = os.pipe()
    box: list[subprocess.Popen] = []

    def relay(signum, frame):
        # Ctrl-C reaches the child through the terminal's process group; SIGTERM and SIGHUP only
        # reach this process, so pass them on and still write the file.
        if signum != signal.SIGINT and box:
            box[0].send_signal(signum)

    saved = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            if signal.getsignal(sig) == signal.SIG_IGN:
                continue  # as for plain unittest: under nohup SIGHUP, after `cmd &` in a script SIGINT
            saved[sig] = signal.signal(sig, relay)
        try:
            box.append(_start_child(tests_dir, flags, write_fd))
        except OSError as e:
            print(f"quality.py: cannot start {sys.executable}: {e}", file=sys.stderr)
            return 127
        finally:
            os.close(write_fd)
        proc = box[0]
        _read_events(read_fd, proc, tally)
        return _shell_code(proc.wait())
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)
        os.close(read_fd)
        tally.finish()


def _write_record(out: str, label: str, header: dict, records: list[dict]) -> bool:
    lines = [json.dumps(row, sort_keys=True, separators=(",", ":")) for row in [header] + records]
    try:
        with open(out, "w") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"quality.py: cannot write {label}: {e}", file=sys.stderr)
        return False
    print(f"recorded {header['tests']} tests in {header['wall_ms']} ms -> {label}")
    return True


def cmd_record(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.tests_dir):
        print(f"quality.py: not a directory: {args.tests_dir}", file=sys.stderr)
        return 2
    out = os.path.abspath(args.out)
    problem = _output_problem(out)
    if problem:
        print(f"quality.py: {problem}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sha = args.sha or env.get("GITHUB_SHA") or _git_head(os.getcwd())
    tally = Tally()
    t0 = time.perf_counter()
    child_code = _run_child(args.tests_dir, tally)
    wall_ms = max(0, round((time.perf_counter() - t0) * 1000))
    header = run_header(args.repo, tally.rows, started, wall_ms, child_code, tally.complete, sha, env)
    code = exit_code(child_code, tally.rows, tally.complete)
    wrote = _write_record(out, args.out, header, tally.rows)
    return code if wrote or code else 1


# ---------------------------------------------------------------------------
# record-junit
# ---------------------------------------------------------------------------

JUNIT_TAG_LEN = 12  # hex characters of the hash that keeps two shortened ids apart
MAX_JUNIT_TEST_MS = 24 * 60 * 60 * 1000  # one test's time is capped at a day, so duplicate ids cannot add up past MAX_NUMBER
_JUNIT_SECONDS = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")  # ASCII digits only: float() also takes "1_000" and other scripts' digits
# A child element's name, without its namespace and in lower case, and the outcome it gives. pytest writes the first
# three; the rerun and flaky ones come from plugins that rerun a failed test, and an attempt that failed is a failure.
_JUNIT_OUTCOMES = (("error", "error"), ("rerunerror", "error"), ("flakyerror", "error"),
                   ("failure", "fail"), ("rerunfailure", "fail"), ("flakyfailure", "fail"), ("skipped", "skip"))


class _NoDoctype(ET.TreeBuilder):
    def doctype(self, name, pubid, system):  # reached only when a DOCTYPE hides from the raw-bytes search (UTF-16)
        raise ET.ParseError("has a DOCTYPE declaration")


def _junit_id(classname: str, name: str) -> str:
    full = f"{classname}.{name}" if classname else name
    if not full:
        return "(unnamed test)"
    if len(full) <= MAX_CELL:
        return full
    tag = "..." + "#" + hashlib.sha256(full.encode("utf-8", "surrogatepass")).hexdigest()[:JUNIT_TAG_LEN]
    return full[:MAX_CELL - len(tag)] + tag


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _junit_outcome(case: ET.Element) -> str:
    children = {_local(child.tag) for child in case}
    for name, outcome in _JUNIT_OUTCOMES:
        if name in children:
            return outcome
    return "pass"


def _junit_ms(text: str | None) -> int:
    """Seconds as pytest writes them, in whole milliseconds from 0 to a day. Anything that is not a plain decimal number is 0."""
    if text is None or not _JUNIT_SECONDS.fullmatch(text):
        return 0
    return round(min(float(text) * 1000, MAX_JUNIT_TEST_MS))  # a huge exponent gives inf, which min() caps


def junit_doubts(rows: list[dict], child_code: int) -> list[str]:
    """Why a converted file cannot be believed as a complete account of the run, though it parsed.
    A test listed more than once with a passing entry is how a rerun plugin writes a failed attempt
    (as an empty testcase), so the failure would be booked as a pass. And pytest's exit 1 says a test
    failed, so a file with no failing row has dropped it in a shape this reader does not know."""
    doubts = []
    seen: dict[str, list[str]] = {}
    for row in rows:
        seen.setdefault(row["id"], []).append(row["outcome"])
    rerun = sorted(test_id for test_id, outcomes in seen.items() if len(outcomes) > 1 and "pass" in outcomes)
    if rerun:
        doubts.append(f"{len(rerun)} test ids appear more than once with a passing entry (first: {printable(rerun[0])[:200]}); "
                      "this is how a rerun plugin writes a failed attempt, and reruns are not supported")
    if child_code == 1 and not any(row["outcome"] in FAILING for row in rows):
        doubts.append("the command exited 1, which pytest uses when a test failed, but the file has no failing test")
    return doubts


def junit_rows(root: ET.Element) -> list[dict]:
    """One row per testcase (in any namespace), in the file's order. Raises ValueError when there are too many."""
    rows = []
    for case in (el for el in root.iter() if _local(el.tag) == "testcase"):
        if len(rows) >= MAX_TEST_ROWS:
            raise ValueError(f"more than {MAX_TEST_ROWS} testcases")
        rows.append({"id": _junit_id(case.get("classname") or "", case.get("name") or ""),
                     "outcome": _junit_outcome(case), "ms": _junit_ms(case.get("time"))})
    return rows


def read_junit(path: str) -> tuple[list[dict], str | None]:
    """The rows of a JUnit XML file, or no rows and why the file was refused. Nothing in it is evaluated."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):  # a FIFO would block the read forever
            return [], "it is not a regular file"
        with open(path, "rb") as f:
            data = f.read(MAX_ARTIFACT_BYTES + 1)
    except FileNotFoundError:
        return [], "the child did not write it"
    except OSError as e:
        return [], f"cannot read it: {printable(e.strerror or type(e).__name__)}"
    if len(data) > MAX_ARTIFACT_BYTES:
        return [], f"it is larger than {_size(MAX_ARTIFACT_BYTES)}"
    if b"<!doctype" in data.lower():
        return [], "it has a DOCTYPE declaration"
    try:
        root = ET.fromstring(data, parser=ET.XMLParser(target=_NoDoctype()))
    except Exception as e:  # ParseError, an unknown encoding (LookupError), anything: the file is untrusted
        return [], f"it is not valid XML: {printable(str(e))[:200]}"
    if root.tag not in ("testsuites", "testsuite"):
        return [], f"its root is {printable(str(root.tag))[:100]}, not testsuites or testsuite"
    try:
        return junit_rows(root), None
    except ValueError as e:
        return [], f"it has {e}"
    except Exception as e:
        return [], f"it could not be converted: {printable(type(e).__name__)}"


def _junit_usage_problem(args: argparse.Namespace, out: str, junit: str) -> str | None:
    if not args.child:
        return "no command after --"
    if shutil.which(args.child[0]) is None:
        return f"command not found: {printable(args.child[0])}"
    problem = _output_problem(out)
    if problem:
        return problem
    if os.path.lexists(junit):
        return f"{printable(args.junit)} already exists; remove it so that a file from an earlier run is never booked"
    if not os.path.isdir(os.path.dirname(junit)):
        return f"junit directory does not exist: {printable(os.path.dirname(junit))}"
    if junit == out:
        return "--junit and --out are the same path"
    return None


def _run_command(command: list[str]) -> int | None:
    """Run command without a shell and return its status as a shell says it; None if it could not start."""
    box: list[subprocess.Popen] = []

    def relay(signum, frame):
        # Ctrl-C reaches the child through the terminal's process group; SIGTERM and SIGHUP only reach
        # this process, so pass them on and still write the record.
        if signum != signal.SIGINT and box:
            box[0].send_signal(signum)

    saved = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            if signal.getsignal(sig) == signal.SIG_IGN:
                continue
            saved[sig] = signal.signal(sig, relay)
        try:
            box.append(subprocess.Popen(command))
        except OSError as e:
            print(f"quality.py: cannot start {printable(command[0])}: {printable(e.strerror or type(e).__name__)}", file=sys.stderr)
            return None
        return _shell_code(box[0].wait())
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)


def cmd_record_junit(args: argparse.Namespace) -> int:
    out = os.path.abspath(args.out)
    junit = os.path.abspath(args.junit)
    problem = _junit_usage_problem(args, out, junit)
    if problem:
        print(f"quality.py: {problem}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sha = args.sha or env.get("GITHUB_SHA") or _git_head(os.getcwd())
    t0 = time.perf_counter()
    child_code = _run_command(args.child)
    wall_ms = max(0, round((time.perf_counter() - t0) * 1000))
    if child_code is None:
        return 2
    rows, why = read_junit(junit)
    doubts = [why] if why else junit_doubts(rows, child_code)
    for doubt in doubts:
        print(f"quality.py: junit file {printable(args.junit)}: {doubt}; recording the run as incomplete", file=sys.stderr)
    complete = not doubts and child_code in (0, 1, 5)  # pytest's 2, 3 and 4 mean it stopped early or never started; 5 ran and found nothing
    header = run_header(args.repo, rows, started, wall_ms, child_code, complete, sha, env)
    code = exit_code(child_code, rows, complete)
    wrote = _write_record(out, args.out, header, rows)
    return code if wrote or code else 1


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass
class Row:
    line: int
    cells: dict[str, str]


@dataclass
class Table:
    rel: str
    header: list[str] | None = None
    rows: list[Row] = field(default_factory=list)
    data: bytes = b""
    present: bool = False  # the file exists (an optional file that is left out has no header and no rows)
    legacy: bool = False
    bad_format: bool = False  # bytes that cannot be compared line by line (already reported)


@dataclass
class Books:
    dir: str
    base: str | None
    tables: dict[str, Table]
    load_problems: list[Problem] = field(default_factory=list)


def _git(books_dir: str, *args: str):
    return subprocess.run(["git", "-C", books_dir] + list(args), capture_output=True)


def _parse_table(rel: str, data: bytes | OSError | None, problems: list[Problem]) -> Table:
    table = Table(rel)
    schema = TABLE_SCHEMAS[rel]
    if data is None:
        if rel in OPTIONAL_SCHEMAS:
            return table  # no header, no rows, no problem
        problems.append(Problem(rel, 1, "missing file"))
        return table
    table.present = True
    if isinstance(data, OSError):
        problems.append(Problem(rel, 1, f"cannot read file ({data.strerror or type(data).__name__})"))
        return table
    table.data = data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(Problem(rel, 1, "not UTF-8 text"))
        table.bad_format = True
        return table
    if text.startswith("\ufeff"):
        problems.append(Problem(rel, 1, "starts with a UTF-8 BOM; the books are plain UTF-8"))
        table.bad_format = True
        return table
    if text.split("\n", 1)[0].endswith("\r"):
        # a CRLF file ends its header line that way; a "\r\n" inside a quoted test id is data
        problems.append(Problem(rel, 1, "CRLF line endings; the books use LF"))
        table.bad_format = True
        return table
    reader = csv.reader(io.StringIO(text, newline=""))
    while True:
        before = reader.line_num
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as e:
            problems.append(Problem(rel, before + 1, f"unreadable CSV: {e}"))
            break
        start = before + 1  # a quoted field may span lines; the row is reported at its first
        if table.header is None:
            table.header = record
            table.legacy = tuple(record) == LEGACY_SCHEMAS.get(rel)
            shape = LEGACY_SCHEMAS[rel] if table.legacy else schema
        elif len(record) != len(shape):
            problems.append(Problem(rel, start, f"row has {len(record)} columns, expected {len(shape)}"))
        else:
            table.rows.append(Row(start, {**dict.fromkeys(schema, ""), **dict(zip(shape, record))}))
    if table.header is None:
        problems.append(Problem(rel, 1, "empty file; expected the header " + ",".join(schema)))
    return table


def books_from_bytes(books_dir: str, files: dict[str, bytes | OSError | None], base: str | None = None) -> Books:
    """Books from file contents (None: no such file; an OSError: it could not be read), off the disk.
    An optional file may be left out of `files`."""
    problems: list[Problem] = []
    return Books(books_dir, base, {rel: _parse_table(rel, files.get(rel) if rel in OPTIONAL_SCHEMAS else files[rel], problems) for rel in TABLE_SCHEMAS}, problems)


def _read(path: str) -> bytes | OSError | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        return e


def load(books_dir: str, base: str | None = None) -> Books:
    return books_from_bytes(books_dir, {rel: _read(os.path.join(books_dir, rel)) for rel in TABLE_SCHEMAS}, base)


def adopted(books: Books) -> bool:
    """The job books are in use: both files exist (an adopted book starts with header-only files)."""
    return all(books.tables[rel].present for rel in JOB_BOOKS)


Check = Callable[[Books], Iterable[Problem]]

_REPO = re.compile(r"[a-z0-9][a-z0-9-]*")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")  # ASCII digits only: \d also matches other scripts' digits
_SHA = re.compile(r"[0-9a-f]{40}")
_PYTHON = re.compile(r"3\.(0|[1-9][0-9]?)")
_WEEK = re.compile(r"([0-9]{4})-W([0-9]{2})")
_RUN_LINK = re.compile(r"https://[^/\s]+/[^/\s]+/[^/\s]+/actions/runs/[0-9]+/attempts/[0-9]+"
                       r"|https://github\.com/[^/\s]+/[^/\s]+/commit/[0-9a-f]{40}#local-ci-[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_COUNT = re.compile(r"0|[1-9][0-9]*")
_GITHUB = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
# C0 controls (ESC among them), DEL and the C1 controls (NEL, 8-bit CSI), but not newline or tab; the line and
# paragraph separators; the bidirectional controls; and the zero-width characters
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\u200b-\u200d\ufeff]")
_FORMULA_FIRST = "=+-@\uff1d\uff0b\uff0d\uff20"  # a spreadsheet runs a cell whose first real character is one of these (ASCII or fullwidth)
_FORMULA_SKIP = " \u00a0\t\n"  # characters a spreadsheet may skip before it sees that first character


def _is_stamp(s: str) -> bool:
    """A real UTC stamp like 2026-11-15T09:30:00Z, in the years the books accept (2020 to 2099)."""
    if not _STAMP.fullmatch(s):
        return False
    try:
        when = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return YEAR_MIN <= when.year <= YEAR_MAX


def _is_iso_week(s: str) -> bool:
    """2026-W53 is a week; 2025-W53 and 2026-W00 are not; the years are the books' 2020 to 2099."""
    m = _WEEK.fullmatch(s)
    if not m or not YEAR_MIN <= int(m[1]) <= YEAR_MAX:
        return False
    try:
        date.fromisocalendar(int(m[1]), int(m[2]), 1)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# row rules: the one definition of a good row, used by `check` on every row in the books and by
# `ingest` on every row a file would add, before the file is planned
# ---------------------------------------------------------------------------
#
# A rule takes a row's cells (a dict of column name to text) and yields a message for each
# problem. `check` reports a message with the row's line; ingest rejects the file that would
# produce the row, so a file that `check` would refuse can never reach the planner.

Rule = Callable[[dict], Iterator[str]]


def text_problem(value: str) -> str | None:
    """Why a text cell cannot go into a CSV the books share with a spreadsheet and a terminal.

    Rejected: a value that starts with a tab or a carriage return, or whose first character after any
    run of space, no-break space, tab and newline is `=`, `+`, `-` or `@` or their fullwidth forms
    (a spreadsheet would run it); any C0 control except newline and tab, DEL, any C1 control
    (U+0080 to U+009F, NEL and 8-bit CSI among them), U+2028, U+2029, the bidirectional controls
    (U+202A to U+202E, U+2066 to U+2069) and the zero-width characters (U+200B to U+200D, U+FEFF)
    (a terminal would obey them or they would hide what the value says); and a value over 1000
    characters. Newline and tab inside a value are allowed."""
    first = value[:1] if value[:1] in ("\t", "\r") else value.lstrip(_FORMULA_SKIP)[:1]
    if first and first in ("\t", "\r") + tuple(_FORMULA_FIRST):
        return f"starts with {_show(first, 8)}; a spreadsheet would run it as a formula"
    if _CONTROL.search(value):
        return "contains a control character (a C0 or C1 control, a line or paragraph separator, a bidirectional control or a zero-width character)"
    if len(value) > MAX_CELL:
        return f"is longer than {MAX_CELL} characters"
    return None


def _text_rule(*columns: str) -> Rule:
    """Hygiene for the cells that hold free text. The other columns are held to a pattern that already
    excludes what text_problem looks for."""
    def rule(cells: dict) -> Iterator[str]:
        for name in columns:
            why = text_problem(cells[name])
            if why:
                yield f"{name} {why}"
    return rule


def _stamp_rule(cells: dict) -> Iterator[str]:
    if not _is_stamp(cells["started"]):
        yield (f"started must look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
               f"got {_show(cells['started'])}")


def _repo_rule(cells: dict) -> Iterator[str]:
    if not _REPO.fullmatch(cells["repo"]):
        yield f"repo must match [a-z0-9][a-z0-9-]*, got {_show(cells['repo'])}"


def _sha_rule(cells: dict) -> Iterator[str]:
    if not _SHA.fullmatch(cells["sha"]):
        yield f"sha must be 40 lowercase hex characters, got {_show(cells['sha'])}"


def _python_rule(cells: dict) -> Iterator[str]:
    if not _PYTHON.fullmatch(cells["python"]):
        yield f"python must look like 3.12, got {_show(cells['python'])}"


def _evidence_rule(cells: dict) -> Iterator[str]:
    if not _RUN_LINK.fullmatch(cells["evidence"]):
        yield ("evidence must look like https://HOST/OWNER/REPO/actions/runs/N/attempts/N or https://github.com/OWNER/REPO/commit/SHA#local-ci-STARTED, "
               f"got {_show(cells['evidence'])}")


def _count_rule(names: tuple[str, ...]) -> Rule:
    def rule(cells: dict) -> Iterator[str]:
        for name in names:
            if not _COUNT.fullmatch(cells[name]):
                yield f"{name} must be a non-negative integer, got {_show(cells[name])}"
    return rule


def _counts_ok(cells: dict, names: tuple[str, ...]) -> list[int] | None:
    return [int(cells[n]) for n in names] if all(_COUNT.fullmatch(cells[n]) for n in names) else None


def _run_totals_rule(cells: dict) -> Iterator[str]:
    values = _counts_ok(cells, ("tests", "failed", "skipped", "wall_ms", "exit_code"))
    if values:
        tests, failed, skipped, _, code = values
        if failed + skipped > tests:
            yield f"failed + skipped ({failed + skipped}) is more than tests ({tests})"
        if code > 255:
            yield f"exit_code must be 0 to 255, got {code}"


def _event_rule(cells: dict) -> Iterator[str]:
    if not cells["event"]:
        yield "event is empty"


def _test_id_rule(cells: dict) -> Iterator[str]:
    if not cells["test_id"]:
        yield "test_id is empty"


def _outcome_rule(cells: dict) -> Iterator[str]:
    if cells["outcome"] not in FAILING:
        yield f"outcome must be fail or error, got {_show(cells['outcome'])}"


def _week_rule(cells: dict) -> Iterator[str]:
    if not _is_iso_week(cells["week"]):
        yield (f"week must be a real ISO week like 2026-W46 (01 to 53) in {YEAR_MIN} to {YEAR_MAX}, "
               f"got {_show(cells['week'])}")


def _weekly_limits_rule(cells: dict) -> Iterator[str]:
    values = _counts_ok(cells, ("runs", "failed", "total_ms", "max_ms"))
    if values:
        runs, failed, total, mx = values
        if runs < 1:
            yield "runs must be at least 1"
        if failed > runs:
            yield f"failed ({failed}) is more than runs ({runs})"
        if mx > total:
            yield f"max_ms ({mx}) is more than total_ms ({total})"


def _github_rule(cells: dict) -> Iterator[str]:
    if not _GITHUB.fullmatch(cells["github"]):
        yield f"github must look like OWNER/NAME, got {_show(cells['github'])}"


_PREFIX = re.compile(r"[^.\s]+(\.[^.\s]+)*")


def _prefix_rule(cells: dict) -> Iterator[str]:
    if not _PREFIX.fullmatch(cells["prefix"]):
        yield f"prefix must be a dotted prefix of a test id (a module, module.Class or module.Class.test), got {_show(cells['prefix'])}"


def _kind_rule(cells: dict) -> Iterator[str]:
    if cells["kind"] not in KIND_NAMES:
        yield f"kind must be one of {', '.join(KIND_NAMES)}, got {_show(cells['kind'])}"


def _workflow_rule(cells: dict) -> Iterator[str]:
    if not cells["workflow"]:
        yield "workflow is empty"


_LOCAL_LINK_SHA = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/commit/([0-9a-f]{40})#local-ci-")


def _run_link_kind_rule(cells: dict) -> Iterator[str]:
    """A local run's link names its own commit, and only a local-ci run has one."""
    local = _LOCAL_LINK_SHA.match(cells["evidence"])
    if (cells["workflow"] == "local-ci") != bool(local):
        yield "evidence must be a local-ci commit link exactly when workflow is local-ci"
    elif local and local[1] != cells["sha"]:
        yield f"evidence names commit {local[1][:12]}, not the row's sha"


RUN_RULES: dict[str, Rule] = {
    "started": _stamp_rule, "repo": _repo_rule, "sha": _sha_rule, "event": _event_rule, "python": _python_rule,
    "counts": _count_rule(("tests", "failed", "skipped", "wall_ms", "exit_code")), "totals": _run_totals_rule,
    "evidence": _evidence_rule, "link_kind": _run_link_kind_rule, "text": _text_rule("event", "workflow", "evidence"),
}
FAILURE_RULES: dict[str, Rule] = {
    "started": _stamp_rule, "repo": _repo_rule, "sha": _sha_rule, "python": _python_rule, "test_id": _test_id_rule,
    "outcome": _outcome_rule, "evidence": _evidence_rule, "text": _text_rule("test_id", "evidence"),
}
WEEKLY_RULES: dict[str, Rule] = {
    "week": _week_rule, "repo": _repo_rule, "test_id": _test_id_rule,
    "counts": _count_rule(("runs", "failed", "total_ms", "max_ms")), "limits": _weekly_limits_rule,
    "text": _text_rule("test_id"),
}
WATCHED_RULES: dict[str, Rule] = {
    "repo": _repo_rule, "github": _github_rule, "workflow": _workflow_rule, "text": _text_rule("workflow"),
}
KINDS_RULES: dict[str, Rule] = {
    "repo": _repo_rule, "prefix": _prefix_rule, "kind": _kind_rule, "text": _text_rule("prefix"),
}


_POSITIVE = re.compile(r"[1-9][0-9]*")
_CONCLUSION = re.compile(r"[a-z_]{0,30}")
_OPTIONAL_COUNT = re.compile(r"(0|[1-9][0-9]*)?")


def _created_rule(cells: dict) -> Iterator[str]:
    if not _is_stamp(cells["created"]):
        yield (f"created must look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
               f"got {_show(cells['created'])}")


def _optional_positive_rule(name: str) -> Rule:
    def rule(cells: dict) -> Iterator[str]:
        if cells[name] and not _POSITIVE.fullmatch(cells[name]):
            yield f"{name} must be empty or a positive integer without leading zeros, got {_show(cells[name])}"
    return rule


def _optional_stamp_rule(cells: dict) -> Iterator[str]:
    if cells["started"] and not _is_stamp(cells["started"]):
        yield (f"started must be empty or look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
               f"got {_show(cells['started'])}")


def _positive_rule(*names: str) -> Rule:
    def rule(cells: dict) -> Iterator[str]:
        for name in names:
            if not _POSITIVE.fullmatch(cells[name]):
                yield f"{name} must be a positive integer without leading zeros, got {_show(cells[name])}"
    return rule


def _nonempty_rule(name: str) -> Rule:
    def rule(cells: dict) -> Iterator[str]:
        if not cells[name]:
            yield f"{name} is empty"
    return rule


def _conclusion_rule(cells: dict) -> Iterator[str]:
    if not _CONCLUSION.fullmatch(cells["conclusion"]):
        yield f"conclusion must match [a-z_]{{0,30}}, got {_show(cells['conclusion'])}"


def _optional_count_rule(*names: str) -> Rule:
    def rule(cells: dict) -> Iterator[str]:
        for name in names:
            if not _OPTIONAL_COUNT.fullmatch(cells[name]):
                yield f"{name} must be empty or a non-negative integer without leading zeros, got {_show(cells[name])}"
    return rule


JOB_RULES: dict[str, Rule] = {
    "created": _created_rule, "repo": _repo_rule, "sha": _sha_rule, "event": _event_rule, "workflow": _workflow_rule,
    "job": _nonempty_rule("job"), "job_id": _positive_rule("job_id"), "conclusion": _conclusion_rule,
    "durations": _optional_count_rule("queue_ms", "total_ms"), "failed_step": _optional_positive_rule("failed_step_number"),
    "evidence": _evidence_rule, "text": _text_rule("event", "workflow", "job", "evidence"),
}
STEP_RULES: dict[str, Rule] = {
    "started": _optional_stamp_rule, "repo": _repo_rule, "job_id": _positive_rule("job_id"),
    "number": _positive_rule("number"), "step": _nonempty_rule("step"), "conclusion": _conclusion_rule,
    "ms": _optional_count_rule("ms"), "evidence": _evidence_rule, "text": _text_rule("step", "evidence"),
}


def _seen_rule(cells: dict) -> Iterator[str]:
    if not _is_stamp(cells["seen"]):
        yield (f"seen must look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
               f"got {_show(cells['seen'])}")


def _visibility_rule(cells: dict) -> Iterator[str]:
    if cells["visibility"] not in VISIBILITIES:
        yield f"visibility must be one of {', '.join(VISIBILITIES)}, got {_show(cells['visibility'])}"


REPOS_RULES: dict[str, Rule] = {"seen": _seen_rule, "repo": _repo_rule, "github": _github_rule, "visibility": _visibility_rule}


def _volume_rule_rule(cells: dict) -> Iterator[str]:
    if cells["rule"] not in VOLUME_RULE_NAMES:
        yield f"rule must be one of {', '.join(VOLUME_RULE_NAMES)}, got {_show(cells['rule'])}"


VOLUME_COUNTS = ("test_files", "test_lines", "source_files", "source_lines")
VOLUME_ROW_RULES: dict[str, Rule] = {"week": _week_rule, "repo": _repo_rule, "sha": _sha_rule, "rule": _volume_rule_rule,
                                     "counts": _count_rule(VOLUME_COUNTS), "evidence": _evidence_rule}


_PULL_LINK = re.compile(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9._-]{0,99})/pull/([1-9][0-9]*)")
PULL_COUNTS = ("ci_ms", "wait_ms", "shas", "checks", "force_pushes")


def _stamp_text(name: str, got: str, empty_ok: bool = False) -> str:
    return (f"{name} must {'be empty or ' if empty_ok else ''}look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
            f"got {_show(got)}")


def _pull_stamps_rule(cells: dict) -> Iterator[str]:
    for name in ("merged", "opened", "ready"):
        if not _is_stamp(cells[name]):
            yield _stamp_text(name, cells[name])
    if cells["head_ci_done"] and not _is_stamp(cells["head_ci_done"]):
        yield _stamp_text("head_ci_done", cells["head_ci_done"], empty_ok=True)


def _pull_evidence_rule(cells: dict) -> Iterator[str]:
    found = _PULL_LINK.fullmatch(cells["evidence"])
    if not found:
        yield f"evidence must look like https://github.com/OWNER/NAME/pull/N, got {_show(cells['evidence'])}"
    elif found[2] != cells["number"]:
        yield f"evidence names pull request {found[2]}, not the row's number {_show(cells['number'])}"


def _pull_time_rule(cells: dict) -> Iterator[str]:
    if not all(_is_stamp(cells[n]) for n in ("merged", "opened", "ready")):
        return
    opened, ready, merged = cells["opened"], cells["ready"], cells["merged"]
    if not opened <= ready <= merged:
        yield f"opened, ready and merged must not run backwards, got {opened}, {ready}, {merged}"
        return
    counts = _counts_ok(cells, ("ci_ms", "wait_ms"))
    if counts and sum(counts) > (epoch_of(merged) - epoch_of(ready)) * 1000:
        yield f"ci_ms + wait_ms ({sum(counts)}) is more than the time from ready to merged"


PULL_ROW_RULES: dict[str, Rule] = {"stamps": _pull_stamps_rule, "repo": _repo_rule, "number": _positive_rule("number"),
                                   "counts": _count_rule(PULL_COUNTS), "time": _pull_time_rule, "evidence": _pull_evidence_rule,
                                   "text": _text_rule("evidence")}


_SKILL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SKILL_SOURCE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._:@/-]{0,199})?")
_SKILL_VERSION = re.compile(r"([0-9a-f]{40})?")
_SKILL_USE = re.compile(r"[0-9a-f]{16}")
_SKILL_COUNTS = ("calls", "searches", "errors")


def _skill_cells_rule(cells: dict) -> Iterator[str]:
    for name, pattern, want in (("skill", _SKILL_NAME, "match [A-Za-z0-9][A-Za-z0-9._-]{0,99}"),
                                ("source", _SKILL_SOURCE, "be empty or match [A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}"),
                                ("version", _SKILL_VERSION, "be empty or 40 lowercase hex characters"),
                                ("use", _SKILL_USE, "be 16 lowercase hex characters")):
        if not pattern.fullmatch(cells[name]):
            yield f"{name} must {want}, got {_show(cells[name])}"
    if cells["tool"] not in SKILL_TOOLS:
        yield f"tool must be one of {', '.join(SKILL_TOOLS)}, got {_show(cells['tool'])}"
    if cells["verdict"] not in SKILL_VERDICTS:
        yield f"verdict must be one of {', '.join(SKILL_VERDICTS)}, got {_show(cells['verdict'])}"


def _skill_window_rule(cells: dict) -> Iterator[str]:
    """Cursor records no tool results and no usage, so its rows carry a use and nothing else. A Claude Code row has
    `how` and the three counts, and all three token cells or none: a row booked before the token columns has none."""
    measured = ("how",) + _SKILL_COUNTS + SKILL_TOKENS
    if cells["tool"] == "cursor":
        if any(cells[name] for name in measured):
            yield "a cursor row has empty how, calls, searches, errors and token cells"
        return
    if cells["tool"] != "claude-code":
        return
    if cells["how"] not in SKILL_HOWS:
        yield f"how must be one of {', '.join(SKILL_HOWS)}, got {_show(cells['how'])}"
    counts = _counts_ok(cells, _SKILL_COUNTS)
    if counts is None:
        yield "calls, searches and errors must be non-negative integers"
    elif counts[0] > SKILL_WINDOW or max(counts[1:]) > counts[0]:
        yield f"calls is at most {SKILL_WINDOW}, and searches and errors are each at most calls"
    if any(cells[name] for name in SKILL_TOKENS) and _counts_ok(cells, SKILL_TOKENS) is None:
        yield "input_tokens, output_tokens and cache_write_tokens must be all empty or all non-negative integers"


SKILL_RULES: dict[str, Rule] = {"week": _week_rule, "cells": _skill_cells_rule, "window": _skill_window_rule}


def rule_messages(rules: dict[str, Rule], cells: dict) -> Iterator[str]:
    for rule in rules.values():
        yield from rule(cells)


def check_load(books: Books) -> Iterator[Problem]:
    yield from books.load_problems


def check_header(books: Books) -> Iterator[Problem]:
    for rel, schema in TABLE_SCHEMAS.items():
        header = books.tables[rel].header
        if header is not None and tuple(header) != schema and not books.tables[rel].legacy:
            yield Problem(rel, 1, "header does not match the schema: expected " + ",".join(schema))


def _check_rows(books: Books, rel: str, rules: dict[str, Rule]) -> Iterator[Problem]:
    for row in books.tables[rel].rows:
        for message in rule_messages(rules, row.cells):
            yield Problem(rel, row.line, message)


def check_runs(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, RUNS, RUN_RULES)
    seen: dict[tuple[str, str], int] = {}
    for row in books.tables[RUNS].rows:
        key = (row.cells["evidence"], row.cells["python"])
        if key in seen:
            yield Problem(RUNS, row.line, f"duplicate of line {seen[key]} (same evidence and python)")
        else:
            seen[key] = row.line


def check_failures(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, FAILURES, FAILURE_RULES)
    seen: dict[tuple[str, str, str], int] = {}
    for row in books.tables[FAILURES].rows:
        c = row.cells
        key = (c["evidence"], c["python"], c["test_id"])
        if key in seen:
            yield Problem(FAILURES, row.line, f"duplicate of line {seen[key]} (same evidence, python and test_id)")
        else:
            seen[key] = row.line


def check_failures_match_runs(books: Books) -> Iterator[Problem]:
    """Every failure belongs to a run, and a run has min(failed, MAX_FAILURE_ROWS) failure rows."""
    if any(p.path in (RUNS, FAILURES) for p in books.load_problems):
        return  # a file that did not load says so once; comparing what is left would only add noise
    runs = {(r.cells["evidence"], r.cells["python"]): r for r in books.tables[RUNS].rows}
    counted: dict[tuple[str, str], int] = {}
    for row in books.tables[FAILURES].rows:
        c = row.cells
        key = (c["evidence"], c["python"])
        run = runs.get(key)
        if run is None:
            yield Problem(FAILURES, row.line, f"no run in {RUNS} with evidence {_show(c['evidence'])} and python {_show(c['python'])}")
            continue
        counted[key] = counted.get(key, 0) + 1
        for name in ("started", "repo", "sha"):
            if c[name] != run.cells[name]:
                yield Problem(FAILURES, row.line, f"{name} {_show(c[name])} differs from {RUNS} line {run.line} ({_show(run.cells[name])})")
    for key, run in runs.items():
        failed = run.cells["failed"]
        if _COUNT.fullmatch(failed) and min(int(failed), MAX_FAILURE_ROWS) != counted.get(key, 0):
            yield Problem(RUNS, run.line, f"failed is {failed} but {FAILURES} has {counted.get(key, 0)} rows for this run "
                          f"(it should have {min(int(failed), MAX_FAILURE_ROWS)})")


def check_weekly(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, WEEKLY, WEEKLY_RULES)
    seen: dict[tuple[str, str, str], int] = {}
    previous: tuple[str, str, str] | None = None
    for row in books.tables[WEEKLY].rows:
        c, n = row.cells, row.line
        key = (c["week"], c["repo"], c["test_id"])
        if key in seen:
            yield Problem(WEEKLY, n, f"duplicate of line {seen[key]} (same week, repo and test_id)")
        else:
            seen[key] = n
        if previous is not None and key < previous:
            yield Problem(WEEKLY, n, "not sorted by week, repo, test_id")
        previous = key


def check_watched(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, WATCHED, WATCHED_RULES)
    repos: dict[str, int] = {}
    pairs: dict[tuple[str, str], int] = {}
    for row in books.tables[WATCHED].rows:
        c, n = row.cells, row.line
        if c["repo"] in repos:
            yield Problem(WATCHED, n, f"duplicate of line {repos[c['repo']]} (same repo)")
        else:
            repos[c["repo"]] = n
        pair = (c["github"].lower(), c["workflow"])  # GitHub names are not case sensitive
        if pair in pairs:
            yield Problem(WATCHED, n, f"duplicate of line {pairs[pair]} (same github and workflow)")
        else:
            pairs[pair] = n


def check_kinds(books: Books) -> Iterator[Problem]:
    """The form of books/kinds.csv, nothing about which tests exist: a prefix that matches no booked test is fine
    (a test may be renamed or not yet run)."""
    yield from _check_rows(books, KINDS, KINDS_RULES)
    watched = {r.cells["repo"] for r in books.tables[WATCHED].rows}
    judge_repo = not any(p.path == WATCHED for p in books.load_problems)  # an unreadable watch list would flag every row
    seen: dict[tuple[str, str], int] = {}
    previous: tuple[str, str] | None = None
    for row in books.tables[KINDS].rows:
        c, n = row.cells, row.line
        if judge_repo and c["repo"] not in watched:
            yield Problem(KINDS, n, f"repo {_show(c['repo'])} is not in {WATCHED}")
        key = (c["repo"], c["prefix"])
        if key in seen:
            yield Problem(KINDS, n, f"duplicate of line {seen[key]} (same repo and prefix)")
        else:
            seen[key] = n
        if previous is not None and key < previous:
            yield Problem(KINDS, n, "not sorted by repo, prefix")
        previous = key


def check_adoption(books: Books) -> Iterator[Problem]:
    """The two job files come together: one without the other is a problem on the missing one."""
    for have, lack in ((JOBS, STEPS), (STEPS, JOBS)):
        if books.tables[have].present and not books.tables[lack].present:
            yield Problem(lack, 1, f"missing file; {have} exists, and the job books are adopted as a pair")


def _unique_rows(books: Books, rel: str, key_of: Callable[[dict], tuple[str, ...]], what: str) -> Iterator[Problem]:
    seen: dict[tuple[str, ...], int] = {}
    for row in books.tables[rel].rows:
        key = key_of(row.cells)
        if key in seen:
            yield Problem(rel, row.line, f"duplicate of line {seen[key]} (same {what})")
        else:
            seen[key] = row.line


def check_jobs(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, JOBS, JOB_RULES)
    yield from _unique_rows(books, JOBS, lambda c: (c["evidence"], c["job_id"]), "evidence and job_id")


def check_steps(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, STEPS, STEP_RULES)
    yield from _unique_rows(books, STEPS, lambda c: (c["evidence"], c["job_id"], c["number"]), "evidence, job_id and number")


def check_steps_match_jobs(books: Books) -> Iterator[Problem]:
    """Every step belongs to a job of the same run (same evidence and job_id) in the same repo, and a job's
    failed_step_number, when set, names a step of it that failed."""
    if not adopted(books) or any(p.path in (JOBS, STEPS) for p in books.load_problems):
        return
    jobs = {(r.cells["evidence"], r.cells["job_id"]): r for r in books.tables[JOBS].rows}
    steps = {(r.cells["evidence"], r.cells["job_id"], r.cells["number"]): r for r in books.tables[STEPS].rows}
    for row in books.tables[JOBS].rows:
        c, number = row.cells, row.cells["failed_step_number"]
        if number:
            step = steps.get((c["evidence"], c["job_id"], number))
            if step is None:
                yield Problem(JOBS, row.line, f"failed_step_number {_show(number)} has no step in {STEPS} with that number")
            elif step.cells["conclusion"] != "failure":
                yield Problem(JOBS, row.line, f"failed_step_number {_show(number)} is {STEPS} line {step.line}, whose conclusion is "
                                              f"{_show(step.cells['conclusion'])}, not failure")
    for row in books.tables[STEPS].rows:
        c = row.cells
        job = jobs.get((c["evidence"], c["job_id"]))
        if job is None:
            yield Problem(STEPS, row.line, f"no job in {JOBS} with evidence {_show(c['evidence'])} and job_id {_show(c['job_id'])}")
        elif c["repo"] != job.cells["repo"]:
            yield Problem(STEPS, row.line, f"repo {_show(c['repo'])} differs from {JOBS} line {job.line} ({_show(job.cells['repo'])})")


def check_skill_uses(books: Books) -> Iterator[Problem]:
    yield from _check_rows(books, SKILLS, SKILL_RULES)
    yield from _unique_rows(books, SKILLS, lambda c: (c["use"],), "use")


def check_volume(books: Books) -> Iterator[Problem]:
    """One row per repo and week; the rows need not be sorted, so a week booked later than a newer one is still appended."""
    yield from _check_rows(books, VOLUME, VOLUME_ROW_RULES)
    yield from _unique_rows(books, VOLUME, lambda c: (c["week"], c["repo"]), "week and repo")


def check_pulls(books: Books) -> Iterator[Problem]:
    """One row per repo and pull request number; the rows need not be sorted, so one booked later than a newer one is still appended."""
    yield from _check_rows(books, PULLS, PULL_ROW_RULES)
    yield from _unique_rows(books, PULLS, lambda c: (c["repo"], c["number"]), "repo and number")


def check_repos(books: Books) -> Iterator[Problem]:
    """The form of books/repos.csv: sorted by (seen, repo), one row per repo and stamp. Whether each row is a change
    from the repo's row before it is ingest's rule, not a check: a hand-added row that repeats a value is harmless."""
    yield from _check_rows(books, REPOS, REPOS_RULES)
    seen: dict[tuple[str, str], int] = {}
    previous: tuple[str, str] | None = None
    for row in books.tables[REPOS].rows:
        c, n = row.cells, row.line
        key = (c["seen"], c["repo"])
        if key in seen:
            yield Problem(REPOS, n, f"duplicate of line {seen[key]} (same seen and repo)")
        else:
            seen[key] = n
        if previous is not None and key < previous:
            yield Problem(REPOS, n, "not sorted by seen, repo")
        previous = key


def _base_problem(books: Books) -> Problem | None:
    ref = books.base
    try:
        if _git(books.dir, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode != 0:
            return Problem(RUNS, 1, f"cannot check against {ref}: not a commit here (is this a git repo, and is the ref fetched?)")
    except OSError as e:
        return Problem(RUNS, 1, f"cannot check against {ref}: git could not run ({e})")
    return None


def _lines(data: bytes) -> list[bytes]:
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts.pop()
    return parts


APPEND_ONLY = (RUNS, FAILURES)


def check_append_only(books: Books) -> Iterator[Problem]:
    ref = books.base
    if ref is None:
        return
    problem = _base_problem(books)
    if problem:
        yield problem
        return
    top = _git(books.dir, "rev-parse", "--show-toplevel")
    top_dir = os.fsdecode(top.stdout).rstrip("\n")
    if top.returncode != 0 or os.path.realpath(top_dir) != os.path.realpath(books.dir):
        # ls-tree is relative to the folder, so inside a bigger repo it would find nothing
        # and call every edited row clean.
        where = f"it is inside the work tree at {top_dir}" if top.returncode == 0 else "it is not in a git work tree"
        yield Problem(RUNS, 1, f"cannot check against {ref}: the books folder must be the top level of its git "
                               f"work tree, but {where}")
        return
    for rel in APPEND_ONLY + JOB_BOOKS + (SKILLS, REPOS, VOLUME, PULLS):
        yield from _append_only(books, rel)


def _append_only(books: Books, rel: str) -> Iterator[Problem]:
    ref = books.base
    listed = _git(books.dir, "ls-tree", "--name-only", ref, "--", rel)
    if listed.returncode != 0:
        yield Problem(rel, 1, f"cannot check against {ref}: git ls-tree failed")
        return
    if not listed.stdout.strip():
        return  # the file did not exist at the base
    if rel in OPTIONAL_SCHEMAS and not books.tables[rel].present:
        yield Problem(rel, 1, f"removed since {ref}")  # an optional book that was adopted at the base, now gone
        return
    shown = _git(books.dir, "show", f"{ref}:./{rel}")
    if shown.returncode != 0:
        yield Problem(rel, 1, f"cannot check against {ref}: git show failed")
        return
    if books.tables[rel].bad_format:
        return  # load already said why; comparing bytes would only repeat it on every line
    old, new = _lines(shown.stdout), _lines(books.tables[rel].data)
    migrated = _migration(rel, old, new)
    if migrated:
        old = migrated
    for i, line in enumerate(old):
        if i >= len(new):
            yield Problem(rel, i + 1, f"removed since {ref}")
        elif new[i] != line:
            yield Problem(rel, i + 1, f"changed since {ref}" + (" (beyond adding empty cells for the new columns)" if migrated else ""))


def _migrated_lines(rel: str, old: list[bytes]) -> list[bytes]:
    """The lines of a file with the legacy header once `migrate-skills` has moved it to the full schema: the new
    header, then each row with one empty cell per added column. No row of these books holds a newline."""
    pad = b"," * (len(TABLE_SCHEMAS[rel]) - len(LEGACY_SCHEMAS[rel]))
    return [",".join(TABLE_SCHEMAS[rel]).encode()] + [line + pad for line in old[1:]]


def _migration(rel: str, old: list[bytes], new: list[bytes]) -> list[bytes] | None:
    """What the base's lines must have become, when the base has the legacy header and the file now has the full one."""
    if rel not in LEGACY_SCHEMAS or not old or not new:
        return None
    if old[0] != ",".join(LEGACY_SCHEMAS[rel]).encode() or new[0] != ",".join(TABLE_SCHEMAS[rel]).encode():
        return None
    return _migrated_lines(rel, old)


CHECKS: tuple[tuple[str, Check], ...] = (
    ("load", check_load),
    ("header", check_header),
    ("runs", check_runs),
    ("failures", check_failures),
    ("failures-match-runs", check_failures_match_runs),
    ("weekly", check_weekly),
    ("watched", check_watched),
    ("kinds", check_kinds),
    ("adoption", check_adoption),
    ("jobs", check_jobs),
    ("steps", check_steps),
    ("steps-match-jobs", check_steps_match_jobs),
    ("skill-uses", check_skill_uses),
    ("repos", check_repos),
    ("volume", check_volume),
    ("pulls", check_pulls),
    ("append-only", check_append_only),
)


def run_checks(books: Books) -> list[Problem]:
    problems = [p for _, check in CHECKS for p in check(books)]
    return sorted(set(problems), key=lambda p: (p.path, p.line, p.message))


def cmd_check(args: argparse.Namespace) -> int:
    books_dir = args.books_dir
    if not os.path.isdir(books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    books = load(books_dir, args.base)
    problems = run_checks(books)
    for p in problems:
        print(p)
    if problems:
        print(f"{len(problems)} problems")
        return 1
    print(f"ok, {sum(len(t.rows) for t in books.tables.values())} rows, 0 problems")
    return 0


# ---------------------------------------------------------------------------
# the books as typed rows
# ---------------------------------------------------------------------------


class RunRow(NamedTuple):
    started: str
    repo: str
    sha: str
    event: str
    workflow: str
    python: str
    tests: int
    failed: int
    skipped: int
    wall_ms: int
    exit_code: int
    evidence: str


class FailureRow(NamedTuple):
    started: str
    repo: str
    sha: str
    python: str
    test_id: str
    outcome: str
    evidence: str


class KindRow(NamedTuple):
    repo: str
    prefix: str
    kind: str


class WeeklyRow(NamedTuple):
    week: str
    repo: str
    test_id: str
    runs: int
    failed: int
    total_ms: int
    max_ms: int


class JobRow(NamedTuple):
    created: str
    repo: str
    sha: str
    event: str
    workflow: str
    job: str
    job_id: int
    conclusion: str
    queue_ms: int | None  # None: not measured (an empty cell), never 0
    total_ms: int | None
    failed_step_number: int | None
    evidence: str


class StepRow(NamedTuple):
    started: str
    repo: str
    job_id: int
    number: int
    step: str
    conclusion: str
    ms: int | None
    evidence: str


class SkillUseRow(NamedTuple):
    week: str
    skill: str
    source: str
    version: str
    tool: str
    how: str
    calls: int | None
    searches: int | None
    errors: int | None
    verdict: str
    use: str
    input_tokens: int | None
    output_tokens: int | None
    cache_write_tokens: int | None


class VolumeRow(NamedTuple):
    week: str
    repo: str
    sha: str
    rule: str
    test_files: int
    test_lines: int
    source_files: int
    source_lines: int
    evidence: str


class PullRow(NamedTuple):
    merged: str
    repo: str
    number: int
    opened: str
    ready: str
    head_ci_done: str
    ci_ms: int
    wait_ms: int
    shas: int
    checks: int
    force_pushes: int
    evidence: str


class RepoRow(NamedTuple):
    seen: str
    repo: str
    github: str
    visibility: str


def visibility_history(books: Books) -> dict[str, list[RepoRow]]:
    """Each repo's rows in repos.csv, oldest first (the file is sorted)."""
    history: dict[str, list[RepoRow]] = {}
    for r in books.tables[REPOS].rows:
        history.setdefault(r.cells["repo"], []).append(RepoRow(*(r.cells[k] for k in REPOS_SCHEMA)))
    return history


def repo_names(books: Books) -> set[str]:
    """Every repo name any row of any book mentions, the watch list or not."""
    return {r.cells["repo"] for rel, table in books.tables.items() if "repo" in TABLE_SCHEMAS[rel] for r in table.rows}


def private_repos(books: Books) -> set[str]:
    """The repos whose books must not reach a public place. A repo is public only when repos.csv has a row for it and
    its latest row says `public` and no row ever said `private` or `internal`: no row and a failed lookup (`unknown`) as
    the latest answer are private, and a repo that was ever private stays private because what was booked then is still
    sensitive. An `unknown` row stops counting once a later lookup answers `public`, so one failed call is not for good."""
    history = visibility_history(books)
    slugs = repo_slugs(books)
    return {repo for repo in repo_names(books) if not history.get(repo) or history[repo][-1].visibility != "public"
            or any(r.visibility in ("private", "internal") for r in history[repo]) or len(slugs.get(repo, ())) > 1}


def repo_slugs(books: Books) -> dict[str, set[str]]:
    """Every OWNER/NAME (lower case) the books tie to each repo name: the watch list, the visibility rows and the run links.
    A name tied to two slugs is private: its `public` row may be about the other repository."""
    slugs: dict[str, set[str]] = {}
    for rel, table in books.tables.items():
        if "repo" not in TABLE_SCHEMAS[rel]:
            continue
        for row in table.rows:
            c = row.cells
            found = _LINK_SLUG.match(c["evidence"]) if "evidence" in c else None
            for slug in (c.get("github"), found[1] if found else None):
                if slug:
                    slugs.setdefault(c["repo"], set()).add(slug.lower())
    return slugs


def visibility_of(info: object) -> str:
    """What the repository API's answer says, as one of VISIBILITIES. Only the exact value `public` counts as public:
    a visibility GitHub did not name, or one this script does not know, is `unknown`. Without a `visibility` key the
    older boolean `private` decides (true: private, false: public), and without that too the answer is `unknown`.
    GitHub answers `private: true` for an internal repo, so `visibility` wins; only `public` against `private: true` is a
    contradiction, and it is private."""
    if not isinstance(info, dict):
        return "unknown"
    value, flag = info.get("visibility"), info.get("private")
    if value is None:
        return "private" if flag is True else "public" if flag is False else "unknown"
    if type(value) is not str or value not in VISIBILITIES[:3]:
        return "unknown"
    return "private" if value == "public" and flag is not False and flag is not None else value


def _typed_rows(books: Books, rel: str, cls) -> list:
    """The rows of a table that passed `check`, as typed tuples. An `int | None` column is None for an empty cell."""
    ints = {name for name, kind in cls.__annotations__.items() if kind is int}
    maybe = {name for name, kind in cls.__annotations__.items() if kind == (int | None)}

    def cell(r: Row, name: str):
        text = r.cells[name]
        if name in ints:
            return int(text)
        if name in maybe:
            return int(text) if text else None
        return text
    return [cls(*(cell(r, name) for name in cls._fields)) for r in books.tables[rel].rows]


def week_of(stamp: str) -> str:
    """The ISO week (UTC) of a `2026-11-15T09:30:00Z` stamp."""
    year, week, _ = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").isocalendar()
    return f"{year:04d}-W{week:02d}"


def epoch_of(stamp: str) -> int:
    """Seconds since 1970 (UTC) of a `2026-11-15T09:30:00Z` stamp."""
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def stamp_of(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def week_back(week: str, count: int) -> str:
    year, number = int(week[:4]), int(week[6:])
    monday = date.fromisocalendar(year, number, 1) - timedelta(weeks=count)
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _cell(text: str) -> str:
    if any(ch in text for ch in ',"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def _csv_line(cells: Iterable[object]) -> str:
    return ",".join(_cell(str(c)) for c in cells) + "\n"


# ---------------------------------------------------------------------------
# ingest: fetched runs in, books out
# ---------------------------------------------------------------------------
#
# Who a run is comes from GitHub's API, written by `fetch` into manifest.json. What a recorder
# file says about itself (repo, sha, event, workflow, started) is ignored: CI runs pull-request
# code, so anyone who can get a workflow to run can write any file. A file is believed only for
# what it measured: python, wall_ms, exit_code, complete, the test rows and, inside `evidence`,
# the attempt number (and only when it names this run).

MAX_ARTIFACT_BYTES = 8 << 20  # one artifact file
MAX_MANIFEST_BYTES = 64 << 10
MAX_TEST_ROWS = 20_000  # test lines in one file
MAX_FILES = 2000  # artifact files read by one ingest
MAX_INGEST_BYTES = 32 << 20  # artifact bytes read by one ingest
MAX_RUN_FILES = 100  # artifact files in one run folder
MAX_RUN_BYTES = 32 << 20  # artifact bytes in one run folder (what fetch lets a run unpack to)
MAX_RECORDS_PER_RUN = 8  # distinct (attempt, python) records in one run folder
MAX_FAILURE_ROWS = 200  # failures.csv rows for one run record, the first by test id
START_SLACK = timedelta(minutes=5)  # a run's `started` may be this much after its `updated`
MAX_NUMBER = 1 << 53  # what any JSON consumer still holds exactly
HEADER_KINDS = {"v": int, "repo": str, "sha": str, "event": str, "workflow": str, "python": str, "os": str,
                "started": str, "wall_ms": int, "exit_code": int, "complete": bool, "tests": int,
                "failed": int, "skipped": int, "evidence": str}
ROW_KINDS = {"id": str, "outcome": str, "ms": int}
MANIFEST_KINDS = {"v": int, "repo": str, "github": str, "run_id": int, "run_attempt": int, "workflow": str,
                  "event": str, "head_sha": str, "head_branch": str, "default_branch": str, "started": str,
                  "updated": str, "conclusion": str, "fork": bool}
MANIFEST = "manifest.json"
ARTIFACTS = "artifacts"


class Rejected(Exception):
    """A file that cannot be booked, and why."""


def _show(value: object, limit: int = 60) -> str:
    """Untrusted text, made safe to print: ASCII only, no control characters, cut short."""
    text = ascii(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def printable(text: str) -> str:
    """Text for the terminal with each character that is not printable written as an escape (\\n, \\x1b)."""
    return "".join(ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii") for ch in text)


class Manifest(NamedTuple):
    """What the API reported about one run, as `fetch` wrote it."""
    v: int
    repo: str
    github: str
    run_id: int
    run_attempt: int
    workflow: str
    event: str
    head_sha: str
    head_branch: str
    default_branch: str
    started: str
    updated: str
    conclusion: str
    fork: bool

    def evidence(self, attempt: int) -> str:
        if self.workflow == LOCAL_CI:
            return f"https://github.com/{self.github}/commit/{self.head_sha}#local-ci-{self.started}"
        return f"https://github.com/{self.github}/actions/runs/{self.run_id}/attempts/{attempt}"


@dataclass(frozen=True)
class RecordedRun:
    """One artifact file, believed for what it measured, under the identity of its manifest."""
    manifest: Manifest
    attempt: int
    python: str
    wall_ms: int
    exit_code: int
    complete: bool
    tests: tuple[tuple[str, str, int], ...]  # (id, outcome, ms) per line
    digest: str  # of what is believed, so two files are the same run's same data or they are not

    @property
    def evidence(self) -> str:
        return self.manifest.evidence(self.attempt)

    @property
    def key(self) -> tuple[str, str]:
        return self.evidence, self.python

    def verdict(self) -> int:
        """The recorder's own verdict for the run, recomputed: a run cut short never books as green."""
        rows = [{"outcome": outcome} for _, outcome, _ in self.tests]
        return exit_code(self.exit_code, rows, self.complete)

    def failing(self) -> dict[str, str]:
        """test id -> fail or error. A test with both an error line and a fail line is an error:
        the worst outcome wins, whatever order the lines come in."""
        found: dict[str, str] = {}
        for test_id, outcome, _ in self.tests:
            if outcome in FAILING:
                found[test_id] = "error" if "error" in (outcome, found.get(test_id)) else "fail"
        return found

    def per_test(self) -> dict[str, tuple[bool, int]]:
        """test id -> (it failed, ms over its lines), for each test with a pass, fail or error line.
        A suite that reuses an id (a nested run) gives one entry, with the lines' time added."""
        seen: dict[str, tuple[bool, int]] = {}
        for test_id, outcome, ms in self.tests:
            if outcome != "skip":
                failed, total = seen.get(test_id, (False, 0))
                seen[test_id] = (failed or outcome in FAILING, total + ms)
        return seen

    def run_cells(self) -> dict[str, str]:
        """The runs.csv row this file would add."""
        m = self.manifest
        skipped = sum(outcome == "skip" for _, outcome, _ in self.tests)
        return _cells(RUNS_SCHEMA, started=m.started, repo=m.repo, sha=m.head_sha, event=m.event, workflow=m.workflow,
                      python=self.python, tests=len(self.tests), failed=len(self.failing()), skipped=skipped,
                      wall_ms=self.wall_ms, exit_code=self.verdict(), evidence=self.evidence)

    def failure_cells(self) -> Iterator[dict[str, str]]:
        """The failures.csv rows, one per failing test, sorted by test id: the first MAX_FAILURE_ROWS of them."""
        m, failing = self.manifest, self.failing()
        for test_id in sorted(failing)[:MAX_FAILURE_ROWS]:
            yield _cells(FAILURES_SCHEMA, started=m.started, repo=m.repo, sha=m.head_sha, python=self.python,
                         test_id=test_id, outcome=failing[test_id], evidence=self.evidence)

    def weekly_cells(self) -> Iterator[dict[str, str]]:
        """What this file adds to tests-weekly.csv, as one row per test (runs 1, its failure, its time)."""
        week = week_of(self.manifest.started)
        for test_id, (failed, ms) in self.per_test().items():
            yield _cells(WEEKLY_SCHEMA, week=week, repo=self.manifest.repo, test_id=test_id, runs=1, failed=int(failed),
                         total_ms=ms, max_ms=ms)


def _cells(schema: tuple[str, ...], **values: object) -> dict[str, str]:
    return {name: str(values[name]) for name in schema}


def _clean_text(value: str, what: str) -> None:
    if "\x00" in value:
        raise Rejected(f"{what} contains a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Rejected(f"{what} is not valid Unicode text") from None


def _check_fields(obj: object, kinds: dict[str, type], what: str, free_text: tuple[str, ...] = ()) -> dict:
    """`free_text` names string keys whose content is judged later (a name a pull request chose), not here."""
    if not isinstance(obj, dict):
        raise Rejected(f"{what} is not a JSON object")
    missing = [k for k in kinds if k not in obj]
    if missing:
        raise Rejected(f"{what} is missing {', '.join(missing)}")
    extra = sorted(set(obj) - set(kinds))
    if extra:
        raise Rejected(f"{what} has an unknown key {_show(extra[0])}")
    for key, kind in kinds.items():
        value = obj[key]
        if type(value) is not kind:  # `is`: True is not a count, 1.0 is not an int
            raise Rejected(f"{what} {key} must be {kind.__name__}, got {_show(value)}")
        if kind is int and not 0 <= value <= MAX_NUMBER:
            raise Rejected(f"{what} {key} must be an integer from 0 to 2**53, got {_show(value)}")
        if kind is str and key not in free_text:
            _clean_text(value, f"{what} {key}")
    return obj


def _load_json(line: bytes, where: str) -> object:
    def twice(pairs):
        found: dict = {}
        for key, value in pairs:
            if key in found:
                raise Rejected(f"{where}: duplicate key {_show(key)}")
            found[key] = value
        return found

    def constant(name):
        raise Rejected(f"{where}: {name} is not valid JSON")

    try:
        return json.loads(line.decode("utf-8"), object_pairs_hook=twice, parse_constant=constant)
    except Rejected:
        raise
    except UnicodeDecodeError:
        raise Rejected(f"{where}: not UTF-8 text") from None
    except (ValueError, RecursionError):
        raise Rejected(f"{where}: not valid JSON") from None


def _read_file(path: str, cap: int) -> bytes:
    """A regular file's bytes, refusing a link, a pipe or anything over `cap` before reading it."""
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise Rejected("is a symbolic link")
        if not stat.S_ISREG(info.st_mode):
            raise Rejected("is not a regular file")
        if info.st_size > cap:
            raise Rejected(f"file is larger than {_size(cap)}")
        with open(path, "rb") as f:
            return f.read(cap + 1)
    except OSError as e:
        raise Rejected(f"cannot read file ({e.strerror or type(e).__name__})") from None


def _size(cap: int) -> str:
    return f"{cap >> 20} MB" if cap >= 1 << 20 else f"{cap >> 10} KB"


def _problems(messages: Iterable[str], limit: int = 3) -> list[str]:
    found: list[str] = []
    for message in messages:
        if message not in found:
            found.append(message)
            if len(found) > limit:
                break
    return found


def _fail_if(messages: Iterable[str], prefix: str = "") -> None:
    found = _problems(messages)
    if found:
        raise Rejected(prefix + "; ".join(found[:3]) + (" ..." if len(found) > 3 else ""))


def read_manifest(path: str, folder_repo: str, folder_run: str, watched: dict[str, tuple[str, str]]) -> Manifest:
    """A run's manifest, checked. It is trusted for who the run is, so it must agree with where it
    was found, with the watch list, and with the rules every booked row is held to."""
    obj = _check_fields(_load_json(_read_file(path, MAX_MANIFEST_BYTES), "manifest"), MANIFEST_KINDS, "manifest")
    if obj["v"] != RECORD_VERSION:
        raise Rejected(f"manifest v must be {RECORD_VERSION}, got {_show(obj['v'])}")
    m = Manifest(**obj)
    for name in ("run_id", "run_attempt"):
        if getattr(m, name) < 1:
            raise Rejected(f"{name} must be at least 1, got {getattr(m, name)}")
    for name in ("head_branch", "default_branch"):
        value = getattr(m, name)
        if not value or len(value) > 255 or _CONTROL.search(value):
            raise Rejected(f"{name} must be 1 to 255 characters without control characters, got {_show(value)}")
    if not _GITHUB.fullmatch(m.github):
        raise Rejected(f"github must look like OWNER/NAME, got {_show(m.github)}")
    placeholder = _cells(RUNS_SCHEMA, started=m.started, repo=m.repo, sha=m.head_sha, event=m.event, workflow=m.workflow,
                         python="3.12", tests=0, failed=0, skipped=0, wall_ms=0, exit_code=0, evidence=m.evidence(m.run_attempt))
    _fail_if(rule_messages(RUN_RULES, placeholder))
    if not _is_stamp(m.updated):
        raise Rejected(f"updated must look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
                       f"got {_show(m.updated)}")
    if m.repo != folder_repo:
        raise Rejected(f"repo {printable(m.repo)} is not in folder {printable(folder_repo)}")
    if str(m.run_id) != folder_run:
        raise Rejected(f"run_id {m.run_id} is not in folder {printable(folder_run)}")
    if m.repo not in watched:
        raise Rejected(f"repo {m.repo} is not on the watch list")
    github, workflow = watched[m.repo]
    if m.github.lower() != github.lower():
        raise Rejected(f"github {printable(m.github)} is not {printable(github)}, the watch list's")
    if m.workflow != workflow:
        raise Rejected(f"workflow {printable(m.workflow)} is not {printable(workflow)}, the watch list's")
    if m.fork:
        raise Rejected("run is from a fork: its code is not the repo's")
    if m.event == "push" and m.head_branch != m.default_branch:
        raise Rejected(f"push to {printable(m.head_branch)}, not the default branch {printable(m.default_branch)}")
    started = datetime.strptime(m.started, "%Y-%m-%dT%H:%M:%SZ")
    if started > datetime.strptime(m.updated, "%Y-%m-%dT%H:%M:%SZ") + START_SLACK:
        raise Rejected(f"started {m.started} is after updated {m.updated}")
    return m


def _attempt_of(evidence: str, m: Manifest) -> int:
    """The attempt a file's evidence names, when it names this run in canonical form and the attempt exists. A local run's
    recorder has no run to name, so its evidence is empty and its one attempt is 1."""
    if m.workflow == LOCAL_CI:
        if evidence == "":
            return 1
        raise Rejected(f"header evidence of a local run must be empty, got {_show(evidence)}")
    found = _EVIDENCE.fullmatch(evidence)
    if found and found[1].lower() == m.github.lower() and found[2] == str(m.run_id) and 1 <= int(found[3]) <= m.run_attempt:
        return int(found[3])
    raise Rejected(f"header evidence must be {m.evidence('N')} with N from 1 to {m.run_attempt}, got {_show(evidence)}")


_EVIDENCE = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/actions/runs/([1-9][0-9]*)/attempts/([1-9][0-9]*)")


def parse_artifact(data: bytes, m: Manifest) -> RecordedRun:
    """A recorder file, strictly, under the identity of its manifest. Nothing in it is executed,
    imported or evaluated, and a test id is only ever a string.

    The header's repo, sha, event, workflow and started are not read for booking. The rows the
    books would get from this file are then built and held to every row rule `check` has, so a
    file that would make `check` fail is rejected here, by name, and never reaches the plan."""
    if len(data) > MAX_ARTIFACT_BYTES:
        raise Rejected(f"file is larger than {_size(MAX_ARTIFACT_BYTES)}")
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if not lines:
        raise Rejected("file is empty")
    if len(lines) - 1 > MAX_TEST_ROWS:
        raise Rejected(f"file has more than {MAX_TEST_ROWS} test rows")
    header = _check_fields(_load_json(lines[0], "line 1"), HEADER_KINDS, "header")
    if header["v"] != RECORD_VERSION:
        raise Rejected(f"header v must be {RECORD_VERSION}, got {_show(header['v'])}")
    tests = []
    for number, line in enumerate(lines[1:], start=2):
        row = _check_fields(_load_json(line, f"line {number}"), ROW_KINDS, f"line {number}")
        if row["outcome"] not in OUTCOMES:
            raise Rejected(f"line {number} outcome must be one of {', '.join(OUTCOMES)}, got {_show(row['outcome'])}")
        if not row["id"]:
            raise Rejected(f"line {number} id is empty")
        tests.append((row["id"], row["outcome"], row["ms"]))
    counted = {"tests": len(tests), "failed": sum(o in FAILING for _, o, _ in tests),
               "skipped": sum(o == "skip" for _, o, _ in tests)}
    for key, actual in counted.items():
        if header[key] != actual:
            raise Rejected(f"header {key} is {header[key]} but the file has {actual}")
    attempt = _attempt_of(header["evidence"], m)
    believed = [attempt, header["python"], header["wall_ms"], header["exit_code"], header["complete"], tests]
    run = RecordedRun(m, attempt, header["python"], header["wall_ms"], header["exit_code"], header["complete"],
                      tuple(tests), hashlib.sha256(json.dumps(believed).encode("utf-8")).hexdigest())
    gate(run)
    return run


def gate(run: RecordedRun) -> None:
    """Hold every row this file would add to every row rule `check` has: the same functions, so there is
    one definition of a good row."""
    messages: list[str] = []

    def add(rules: dict[str, Rule], cells: dict[str, str]) -> None:
        if len(messages) <= 3:
            messages.extend(m for m in rule_messages(rules, cells) if m not in messages)

    add(RUN_RULES, run.run_cells())
    for cells in run.failure_cells():
        add(FAILURE_RULES, cells)
    for cells in run.weekly_cells():
        add(WEEKLY_RULES, cells)
    for test_id in {t for t, outcome, _ in run.tests if outcome == "skip"}:
        add({"test_id": _test_id_rule, "text": _text_rule("test_id")}, {"test_id": test_id})  # skipped: no row, same id rules
    _fail_if(messages, "would fail check: ")


@dataclass
class Scan:
    path: str  # relative to the fetch directory
    status: str  # booked, already, duplicate, no artifacts, rejected
    run: RecordedRun | None = None
    reason: str = ""


def _layout(root: str) -> tuple[dict[tuple[str, str], tuple[str | None, list[str]]], list[str], dict[tuple[str, str], str]]:
    """The run folders under root: (repo, run) -> (manifest path or None, artifact files), the
    *.jsonl files that are not under <repo>/<run_id>/artifacts/, and (repo, run) -> the path of
    <repo>/<run_id>/jobs.json. All paths relative, sorted. Symlinked directories are not entered."""
    runs: dict[tuple[str, str], list] = {}  # (repo, run) -> [manifest path or None, artifact files]
    stray = []
    jobs_files: dict[tuple[str, str], str] = {}
    for folder, _, names in os.walk(root):
        for name in names:
            rel = os.path.relpath(os.path.join(folder, name), root)
            parts = rel.split(os.sep)
            if len(parts) == 3 and name == MANIFEST:
                runs.setdefault((parts[0], parts[1]), [None, []])[0] = rel
            elif len(parts) == 3 and name == JOBS_FILE:
                jobs_files[(parts[0], parts[1])] = rel
            elif name.endswith(".jsonl"):
                if len(parts) >= 4 and parts[2] == ARTIFACTS:
                    runs.setdefault((parts[0], parts[1]), [None, []])[1].append(rel)
                else:
                    stray.append(rel)
    for _, files in runs.values():
        files.sort()
    return {key: (value[0], value[1]) for key, value in sorted(runs.items())}, sorted(stray), jobs_files


@dataclass
class Scanned:
    scans: list[Scan]
    unread: list[tuple[str, str]]  # (run folder, cap) left unread because a per-ingest budget was spent
    jobs: list["JobScan"] = field(default_factory=list)  # one per jobs.json, only when the job books are adopted


def _folder_bytes(root: str, artifacts: list[str]) -> int:
    total = 0
    for rel in artifacts:
        try:
            total += os.lstat(os.path.join(root, rel)).st_size
        except OSError:
            pass
    return total


def _peek_key(path: str, m: Manifest) -> tuple[str, str] | None:
    """The (evidence, python) a file's first line claims for this run, or None when it does not plainly
    claim one. Only the first line is read, and only to tell a file that is booked already from one
    that is not, before the budgets are spent on it."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        with open(path, "rb") as f:
            header = json.loads(f.readline(1 << 16))
        evidence, python = header["evidence"], header["python"]
        if type(evidence) is str and type(python) is str:
            return m.evidence(_attempt_of(evidence, m)), python
    except (OSError, ValueError, KeyError, TypeError, Rejected, RecursionError):
        pass
    return None


def scan_fetched(root: str, watched: dict[str, tuple[str, str]], booked: set[tuple[str, str]] | None = None,
                 booked_jobs: set[str] | None = None, read_artifacts: bool = True) -> Scanned:
    """Read the run folders in order of the manifest's `started`, then run id, each under its own caps
    (MAX_RUN_FILES, MAX_RUN_BYTES, MAX_RECORDS_PER_RUN). A folder is read whole or not at all: one that
    the per-ingest budgets (MAX_FILES, MAX_INGEST_BYTES) cannot hold is named in `unread` and a later
    ingest reads it. A folder whose files all claim a record that is booked already is not read and costs no budget.

    `booked_jobs` is the evidence links already in jobs.csv, or None when the job books are not adopted: then
    jobs.json files are not looked at. `read_artifacts` False (ingest --only jobs) reads no artifact and
    reports nothing about them."""
    runs, stray, jobs_files = _layout(root)
    stray = stray if read_artifacts else []
    found = Scanned([Scan(rel, "rejected", reason="not inside <repo>/<run_id>/artifacts/ of a run folder") for rel in stray], [])
    jobs_files = jobs_files if booked_jobs is not None else {}
    booked = booked or set()
    manifests: list[tuple[tuple, str, str, str | None, list[str], Manifest | None, str]] = []
    for (repo, run_id), (manifest_path, artifacts) in runs.items():
        m, why = None, ""
        if manifest_path is not None:
            try:
                m = read_manifest(os.path.join(root, manifest_path), repo, run_id, watched)
            except Rejected as e:
                why = str(e)
        order = (m.started if m else "", m.run_id if m else (int(run_id) if run_id.isdigit() else 0), repo, run_id)
        manifests.append((order, repo, run_id, manifest_path, artifacts, m, why))
    manifests.sort(key=lambda x: x[0])
    if booked_jobs is not None:
        _scan_jobs(root, manifests, jobs_files, booked_jobs, found)
    files_read = bytes_read = 0
    for _, repo, run_id, manifest_path, artifacts, m, why in manifests:
        folder = f"{repo}/{run_id}"
        if not read_artifacts:
            continue
        if manifest_path is not None and m is None:
            note = f" ({len(artifacts)} artifact file{'s' * (len(artifacts) != 1)} not read)" if artifacts else ""
            found.scans.append(Scan(manifest_path, "rejected", reason=why + note))
            continue
        if m is not None and not artifacts:
            if (repo, run_id) not in jobs_files:  # a run kept for its jobs alone is not news
                found.scans.append(Scan(manifest_path, "no artifacts"))
            continue
        size = _folder_bytes(root, artifacts)
        if m is None:  # no manifest: each file is rejected unread, and the files are counted against the budget
            if files_read + len(artifacts) > MAX_FILES:
                found.unread.append((folder, f"{MAX_FILES}-file cap"))
                continue
            files_read += len(artifacts)
            found.scans.extend(Scan(rel, "rejected", reason=f"no {MANIFEST} in its run folder") for rel in artifacts)
            continue
        if len(artifacts) > MAX_RUN_FILES or size > MAX_RUN_BYTES:
            found.scans.append(Scan(manifest_path, "rejected", reason=(
                f"run {folder} has {len(artifacts)} artifact files and {size} bytes, over the per-run caps of {MAX_RUN_FILES} files "
                f"and {_size(MAX_RUN_BYTES)}; none of it is read or booked")))
            continue
        if all(_peek_key(os.path.join(root, rel), m) in booked for rel in artifacts):
            found.scans.extend(Scan(rel, "already", reason="already booked") for rel in artifacts)
            continue
        if files_read + len(artifacts) > MAX_FILES:
            found.unread.append((folder, f"{MAX_FILES}-file cap"))
            continue
        if bytes_read + size > MAX_INGEST_BYTES:
            found.unread.append((folder, f"{_size(MAX_INGEST_BYTES)} cap"))
            continue
        files_read += len(artifacts)
        bytes_read += size
        mine = []
        for rel in artifacts:
            try:
                mine.append(Scan(rel, "booked", parse_artifact(_read_file(os.path.join(root, rel), MAX_ARTIFACT_BYTES), m)))
            except Rejected as e:
                mine.append(Scan(rel, "rejected", reason=str(e)))
        records = {s.run.key for s in mine if s.status == "booked"}
        if len(records) > MAX_RECORDS_PER_RUN:
            for scan in mine:
                if scan.status == "booked":
                    scan.status, scan.run = "rejected", None
                    scan.reason = (f"run {folder} has {len(records)} records (distinct attempt and python), more than "
                                   f"{MAX_RECORDS_PER_RUN}; none of it is booked")
        found.scans.extend(mine)
    found.scans.sort(key=lambda s: s.path)
    return found


def settle_duplicates(scans: list[Scan]) -> None:
    """Files that claim one (evidence, python) in one batch. Identical content counts once. Content that
    differs is rejected on every file: a forged file next to a genuine one must never decide which is
    believed, so neither is."""
    groups: dict[tuple[str, str], list[Scan]] = {}
    for scan in scans:
        if scan.status == "booked":
            groups.setdefault(scan.run.key, []).append(scan)
    for group in groups.values():
        if len(group) < 2:
            continue
        digests = {s.path: s.run.digest for s in group}
        if len(set(digests.values())) > 1:
            for scan in group:
                other = next(path for path, digest in digests.items() if digest != digests[scan.path])
                scan.status, scan.run = "rejected", None
                scan.reason = (f"conflicts with {printable(other)}: the same attempt and python with different content, "
                               "so neither is booked")
        else:
            for scan in group[1:]:
                scan.status, scan.reason = "duplicate", f"duplicate of {printable(group[0].path)}"


def choose_new_runs(scans: list[Scan], booked: set[tuple[str, str]]) -> list[Scan]:
    """Mark the scans that book a run nobody has booked yet (status stays `booked`), the rest `already`."""
    taken = set(booked)
    candidates = sorted((s for s in scans if s.status == "booked"),
                        key=lambda s: (s.run.manifest.started, s.run.key, s.path))
    for scan in candidates:
        if scan.run.key in taken:
            scan.status, scan.reason = "already", "already booked"
        else:
            taken.add(scan.run.key)
    return [s for s in candidates if s.status == "booked"]


@dataclass
class Plan:
    """What an ingest adds to the books, as the files' new bytes (None: unchanged)."""
    files: dict[str, bytes | None]
    runs: int
    failures: int
    weekly_rows: int


def _appended(data: bytes, text: str) -> bytes:
    return data + (b"" if data.endswith(b"\n") or not data else b"\n") + text.encode("utf-8")


def plan_ingest(books: Books, new: list[Scan]) -> Plan:
    """The books after booking `new`. runs.csv and failures.csv only grow by whole lines at the end."""
    old = {rel: books.tables[rel].data for rel in SCHEMAS}
    if not new:
        return Plan({rel: None for rel in SCHEMAS}, 0, 0, 0)
    weekly = {(w.week, w.repo, w.test_id): [w.runs, w.failed, w.total_ms, w.max_ms]
              for w in _typed_rows(books, WEEKLY, WeeklyRow)}
    touched: set[tuple[str, str, str]] = set()
    runs_text, failures_text, failures = "", "", 0
    for scan in new:
        runs_text += _csv_line(scan.run.run_cells()[k] for k in RUNS_SCHEMA)
        for cells in scan.run.failure_cells():
            failures_text += _csv_line(cells[k] for k in FAILURES_SCHEMA)
            failures += 1
        for cells in scan.run.weekly_cells():
            key = (cells["week"], cells["repo"], cells["test_id"])
            cell = weekly.setdefault(key, [0, 0, 0, 0])
            cell[0] += 1
            cell[1] += int(cells["failed"])
            cell[2] += int(cells["total_ms"])
            cell[3] = max(cell[3], int(cells["max_ms"]))
            touched.add(key)
    weekly_text = _csv_line(WEEKLY_SCHEMA) + "".join(_csv_line(k + tuple(v)) for k, v in sorted(weekly.items()))

    files: dict[str, bytes | None] = {rel: None for rel in SCHEMAS}
    files.update({RUNS: _appended(old[RUNS], runs_text), FAILURES: _appended(old[FAILURES], failures_text),
                  WEEKLY: weekly_text.encode("utf-8")})
    return Plan(files, len(new), failures, len(touched))


def commit_files(books_dir: str, files: dict[str, bytes | None]) -> None:
    """Write the changed files so that either all of them change or none does.

    Every new file is written beside its target first; a failure then leaves the books as they were.
    The renames come last, and one that fails puts the earlier ones back.
    """
    changed = {rel: data for rel, data in files.items() if data is not None}
    paths = {rel: os.path.join(books_dir, rel) for rel in changed}
    temps = {rel: os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{os.getpid()}.tmp")
             for rel, path in paths.items()}
    before = {rel: _read(path) for rel, path in paths.items()}
    swapped: list[str] = []
    try:
        for rel, data in changed.items():
            with open(temps[rel], "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        for rel in changed:
            os.replace(temps[rel], paths[rel])
            swapped.append(rel)
    except BaseException:
        for rel in swapped:
            if isinstance(before[rel], bytes):
                with open(paths[rel], "wb") as f:
                    f.write(before[rel])
        raise
    finally:
        for temp in temps.values():
            with contextlib.suppress(OSError):
                os.remove(temp)


def _print_problems(problems: list[Problem]) -> None:
    for p in problems:
        print(p)


def watch_list(books: Books) -> dict[str, tuple[str, str]]:
    """repo -> (github, workflow) from books that passed check."""
    return {r.cells["repo"]: (r.cells["github"], r.cells["workflow"]) for r in books.tables[WATCHED].rows}


def cmd_ingest(args: argparse.Namespace) -> int:
    for folder in (args.books_dir, args.fetch_dir):
        if not os.path.isdir(folder):
            print(f"quality.py: not a directory: {folder}", file=sys.stderr)
            return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; refusing to ingest into books that fail check")
        return 1
    only_jobs = args.only == "jobs"
    only_visibility = args.only == "visibility"
    if only_jobs and not adopted(books):
        print(f"quality.py: --only jobs needs the job books: create {JOBS} and {STEPS} (each with its header) in the books "
              "folder first", file=sys.stderr)
        return 2
    if only_visibility and not books.tables[REPOS].present:
        print(f"quality.py: --only visibility needs {REPOS}: create it (with its header) in the books folder first", file=sys.stderr)
        return 2
    booked = {(r.evidence, r.python) for r in _typed_rows(books, RUNS, RunRow)}
    found = scan_fetched(args.fetch_dir, watch_list(books), booked, None if only_visibility else jobs_booked_evidence(books),
                         read_artifacts=not (only_jobs or only_visibility))
    scans = found.scans
    settle_duplicates(scans)
    new = choose_new_runs(scans, booked)
    plan = plan_ingest(books, new)
    job_files = plan_jobs(books, found.jobs)
    plan.files.update(job_files)
    visibility = scan_repo_files(args.fetch_dir, watch_list(books), books) if books.tables[REPOS].present and not only_jobs else None
    repo_files = plan_repos(books, visibility) if visibility is not None else {}
    plan.files.update(repo_files)
    volume = scan_volume_files(args.fetch_dir, watch_list(books), books) if books.tables[VOLUME].present and args.only is None else None
    volume_files = plan_volume(books, volume) if volume is not None else {}
    plan.files.update(volume_files)
    pulls = scan_pull_files(args.fetch_dir, watch_list(books), books) if books.tables[PULLS].present and args.only is None else None
    pull_files = plan_pulls(books, pulls) if pulls is not None else {}
    plan.files.update(pull_files)
    if new or job_files or repo_files or volume_files or pull_files:
        unchanged = {rel: books.tables[rel].data if books.tables[rel].present else None for rel in OPTIONAL_SCHEMAS}
        after = run_checks(books_from_bytes(args.books_dir, {**unchanged, **{rel: data if data is not None else books.tables[rel].data
                                                                              for rel, data in plan.files.items()}}))
        if after:
            _print_problems(after)
            print(f"{len(after)} problems; nothing written")
            return 1
    wrote = bool(new or job_files or repo_files or volume_files or pull_files) and not args.dry_run
    if wrote:
        try:
            commit_files(args.books_dir, plan.files)
        except OSError as e:
            print(f"quality.py: cannot write the books, they are unchanged: {e}", file=sys.stderr)
            return 1
    count = lambda status: sum(s.status == status for s in scans)
    unread = len(found.unread)
    totals = {"files": len(scans), "booked": len(new), "already_booked": count("already"), "duplicates": count("duplicate"),
              "no_artifacts": count("no artifacts"), "rejected": count("rejected"), "unread": unread,
              "failures": plan.failures, "weekly_rows": plan.weekly_rows}
    jobs_rejected = 0
    if visibility is not None:
        totals.update(visibility_booked=sum(s.status == "booked" for s in visibility), visibility_unchanged=sum(s.status == "unchanged" for s in visibility),
                      visibility_rejected=sum(s.status == "rejected" for s in visibility))
    if volume is not None:
        totals.update(volume_booked=sum(s.status == "booked" for s in volume), volume_unchanged=sum(s.status == "unchanged" for s in volume),
                      volume_rejected=sum(s.status == "rejected" for s in volume))
    if pulls is not None:
        totals.update(pulls_booked=sum(s.status == "booked" for s in pulls), pulls_unchanged=sum(s.status == "unchanged" for s in pulls),
                      pulls_rejected=sum(s.status == "rejected" for s in pulls))
    if adopted(books) and not only_visibility:
        jobs_rejected = sum(s.status == "rejected" for s in found.jobs)
        booked_jobs = [s for s in found.jobs if s.status == "booked"]
        totals.update(jobs_booked=len(booked_jobs), jobs_already_booked=sum(s.status == "already" for s in found.jobs),
                      jobs_empty=sum(s.status == "empty" for s in found.jobs),
                      jobs_rejected=jobs_rejected, job_rows=sum(len(s.jobs.jobs) for s in booked_jobs),
                      step_rows=sum(s.jobs.step_count for s in booked_jobs))
    if args.json:
        out = {"dry_run": args.dry_run, "files": [_scan_json(s) for s in scans], "totals": totals, "wrote": wrote}
        if adopted(books) and not only_visibility:
            out["jobs"] = [_job_scan_json(s) for s in found.jobs]
        if visibility is not None:
            out["visibility"] = [_repo_scan_json(s) for s in visibility]
        if volume is not None:
            out["volume"] = [_volume_scan_json(s) for s in volume]
        if pulls is not None:
            out["pulls"] = [_pull_scan_json(s) for s in pulls]
        print(json.dumps(out, sort_keys=True, indent=2))
    else:
        _print_ingest(scans, totals, found, args.dry_run, only_jobs, visibility, only_visibility, volume, pulls)
    return 1 if (totals["rejected"] or unread or jobs_rejected or totals.get("visibility_rejected") or totals.get("volume_rejected")
                 or totals.get("pulls_rejected")) else 0


def _job_scan_json(scan: "JobScan") -> dict:
    out = {"path": scan.path, "status": scan.status}
    if scan.reason:
        out["reason"] = scan.reason
    if scan.status == "booked":
        out.update(evidence=scan.jobs.evidence, jobs=len(scan.jobs.jobs), steps=scan.jobs.step_count)
    return out


def _scan_json(scan: Scan) -> dict:
    out = {"path": scan.path, "status": scan.status}
    if scan.reason:
        out["reason"] = scan.reason
    if scan.status == "booked":
        out.update(evidence=scan.run.evidence, python=scan.run.python, tests=len(scan.run.tests),
                   exit_code=scan.run.verdict())
    return out


def _print_ingest(scans: list[Scan], totals: dict, found: Scanned, dry_run: bool, only_jobs: bool = False,
                  visibility: "list[RepoScan] | None" = None, only_visibility: bool = False,
                  volume: "list[VolumeScan] | None" = None, pulls: "list[PullScan] | None" = None) -> None:
    for s in scans:
        name = _show(s.path, 200) if not s.path.isprintable() else s.path
        if s.status == "booked":
            m = s.run.manifest
            print(f"{'would book' if dry_run else 'booked'}: {name}: {m.repo} {s.run.python} {len(s.run.tests)} tests, "
                  f"exit_code {s.run.verdict()}, {s.run.evidence}")
        elif s.status == "already":
            print(f"skipped, already booked: {name}")
        elif s.status == "duplicate":
            print(f"skipped, {s.reason}: {name}")
        elif s.status == "no artifacts":
            print(f"no artifacts: {name}")
        else:
            print(f"rejected: {name}: {s.reason}")
    for s in found.jobs:
        folder = s.path.rsplit("/", 1)[0]
        name = _show(s.path, 200) if not s.path.isprintable() else s.path
        folder = _show(folder, 200) if not folder.isprintable() else folder
        if s.status == "booked":
            print(f"{'would book' if dry_run else 'booked'} jobs {folder}: {len(s.jobs.jobs)} jobs, {s.jobs.step_count} steps")
        elif s.status == "already":
            print(f"skipped jobs {folder}: already booked")
        elif s.status == "empty":
            print(f"skipped jobs {folder}: no jobs")
        else:
            print(f"rejected: {name}: {s.reason}")
    if visibility is not None:
        _print_visibility(visibility, dry_run)
        if only_visibility and not visibility:
            print("no repo.json files")
    if volume is not None:
        _print_volume(volume, dry_run)
    if pulls is not None:
        _print_pulls(pulls, dry_run)
    for folder, cap in found.unread:
        print(f"left unread, the {cap}: {printable(folder)}")
    if found.unread:
        print(f"{len(found.unread)} run folder{'s' * (len(found.unread) != 1)} left unread: ingest again to book "
              f"{'it' if len(found.unread) == 1 else 'them'}")
    verb = "would book" if dry_run else "booked"
    jobs_part = ""
    if "jobs_booked" in totals:
        jobs_part = (f"; {verb} jobs of {totals['jobs_booked']} runs ({totals['job_rows']} job rows, {totals['step_rows']} step rows), "
                     f"skipped {totals['jobs_already_booked']} already booked and {totals['jobs_empty']} with no jobs, "
                     f"rejected {totals['jobs_rejected']}")
    if only_jobs:
        print(jobs_part[2:])
    elif only_visibility:
        pass
    else:
        print(f"{verb} {totals['booked']} runs, {totals['failures']} failures, "
              f"{totals['weekly_rows']} weekly rows touched; skipped {totals['already_booked']} already booked, "
              f"{totals['duplicates']} duplicates; rejected {totals['rejected']} of {totals['files']} files{jobs_part}")
    if "volume_booked" in totals:
        print(f"{verb} volume of {totals['volume_booked']} weeks; {totals['volume_unchanged']} already booked, "
              f"rejected {totals['volume_rejected']}")
    if "pulls_booked" in totals:
        print(f"{verb} {totals['pulls_booked']} merged pull requests; {totals['pulls_unchanged']} already booked, "
              f"rejected {totals['pulls_rejected']}")
    if (totals["rejected"] or totals["unread"] or totals.get("jobs_rejected") or totals.get("visibility_rejected") or totals.get("volume_rejected")
            or totals.get("pulls_rejected")):
        print("some files were rejected or not read: the others were booked and ingest exits 1 so it is not missed"
              if not dry_run else "some files were rejected or not read; ingest exits 1")


# ---------------------------------------------------------------------------
# summary: every number the weekly brief quotes
# ---------------------------------------------------------------------------

SLOWEST = 10  # tests listed per repo and overall
PRIOR_WEEKS = 4  # calendar ISO weeks before the week, whichever of them have runs


def median(values: list[int]) -> int:
    """The lower of the two middle values for an even count, so the result is always an integer
    that one of the runs actually had."""
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def percentile95(values: list[int]) -> int:
    """Nearest rank: the value at 1-based rank ceil(0.95 * n) of the sorted values, so it is always a value one
    run had. Integer arithmetic only. `values` is never empty."""
    ordered = sorted(values)
    return ordered[-(-95 * len(ordered) // 100) - 1]


def _slowest(rows: list[WeeklyRow]) -> list[dict]:
    ranked = sorted(rows, key=lambda w: (-(w.total_ms // w.runs), w.test_id, w.repo))
    return [{"max_ms": w.max_ms, "mean_ms": w.total_ms // w.runs, "repo": w.repo, "runs": w.runs, "test_id": w.test_id}
            for w in ranked[:SLOWEST]]


def _flaky(repo_runs: list[RunRow], repo_failures: list[FailureRow], week: str) -> list[dict]:
    """Tests that failed in one run and not in another of the same commit, Python and event.

    A test is listed when it has a failure row this week. Its failing side is every failure row
    of that repo, sha, Python, event and test (any week); its passing side is every run in the books (any
    week) of the same repo, sha, Python and event that has no failure row for the test. The books keep
    failures only, so a run in which the test was skipped or did not exist looks the same as a
    pass, and a run that is red for some other test counts as passing this one. A commit whose
    every run failed the test is not flaky. Python is part of the key because a test that fails
    only on 3.10 is a compatibility bug, not a flake. The event is part of it because a pull request
    branch can point at a commit that is already on main and report a failure that main never had.
    """
    event_of = {(r.evidence, r.python): r.event for r in repo_runs}
    failed_in: dict[tuple[str, str, str, str], set[str]] = {}
    for f in repo_failures:
        failed_in.setdefault((f.test_id, f.sha, f.python, event_of.get((f.evidence, f.python), "")), set()).add(f.evidence)
    listed = {(f.test_id, f.sha, f.python, event_of.get((f.evidence, f.python), ""))
              for f in repo_failures if week_of(f.started) == week}
    out = []
    for key in sorted(listed):
        test_id, sha, python, event = key
        passed = {r.evidence for r in repo_runs if r.sha == sha and r.python == python and r.event == event} - failed_in[key]
        if passed:
            out.append({"event": event, "failed_evidence": sorted(failed_in[key]), "passed_evidence": sorted(passed),
                        "python": python, "sha": sha, "test_id": test_id})
    return out


_SETUP_ID = re.compile(r"(?:setUpClass|tearDownClass|setUpModule|tearDownModule) \((.+)\)")
_IMPORT_FAILURE = "unittest.loader._FailedTest."


def _kind_subject(test_id: str) -> str:
    """The dotted name a kind row is matched against. The recorder books a class whose setup raises as
    `setUpClass (mod.Class)` and a module that fails to import as `unittest.loader._FailedTest.mod`; both
    belong to the class or module they name, so a break in an e2e module is a catch of the e2e kind."""
    m = _SETUP_ID.fullmatch(test_id)
    if m:
        return m.group(1)
    if test_id.startswith(_IMPORT_FAILURE) and len(test_id) > len(_IMPORT_FAILURE):
        return test_id[len(_IMPORT_FAILURE):]
    return test_id


def kind_of(rules: dict[str, str], test_id: str) -> str:
    """The kind of a test: the row with the longest prefix that is the id or ends where a dotted segment of it ends.
    `rules` maps a prefix to a kind (one repo's rows); a test with no such row is a unit test."""
    parts = _kind_subject(test_id).split(".")
    for n in range(len(parts), 0, -1):
        kind = rules.get(".".join(parts[:n]))
        if kind is not None:
            return kind
    return DEFAULT_KIND


def _by_kind(rules: dict[str, str], here: list[WeeklyRow], on_pr: Iterable[FailureRow], on_main: Iterable[FailureRow]) -> dict:
    """Per kind, this week: tests, their total_ms, and the distinct tests that failed in a pull request run and on a push."""
    out = {kind: {"caught_on_pr": set(), "failed_on_main": set(), "tests": set(), "total_ms": 0} for kind in KIND_NAMES}
    for w in here:
        entry = out[kind_of(rules, w.test_id)]
        entry["tests"].add(w.test_id)
        entry["total_ms"] += w.total_ms
    for key, failed in (("caught_on_pr", on_pr), ("failed_on_main", on_main)):
        for f in failed:
            out[kind_of(rules, f.test_id)][key].add(f.test_id)
    return {kind: {k: len(v) if isinstance(v, set) else v for k, v in entry.items()} for kind, entry in out.items()}


def _spread(values: list[int], *, top: bool = False) -> dict | None:
    """median and p95 (and max when `top`) of measured values; None when nothing was measured."""
    if not values:
        return None
    out = {"median": median(values), "p95": percentile95(values)}
    if top:
        out["max"] = max(values)
    return out


def _epoch_ms(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()) * 1000


def _timed(group: list[JobRow]) -> list[JobRow]:
    """The jobs that were not skipped and have a measured total_ms."""
    return [j for j in group if j.conclusion != "skipped" and j.total_ms is not None]


def _lifecycle(repo: str, week: str, runs: list[RunRow], jobs: list[JobRow], steps: list[StepRow]) -> dict | None:
    """Where a week's CI time went outside the test suite, from the job books. A run (one `evidence` link) belongs
    to the week of its earliest job `created`, with all its jobs and steps. None when no run belongs to the week."""
    by_run: dict[str, list[JobRow]] = {}
    for j in jobs:
        if j.repo == repo:
            by_run.setdefault(j.evidence, []).append(j)
    mine = {e: g for e, g in by_run.items() if week_of(min(j.created for j in g)) == week}
    if not mine:
        return None
    here = [j for g in mine.values() for j in g]
    timed = _timed(here)
    run_ms = []
    for g in mine.values():
        t = _timed(g)
        if t and all(j.queue_ms is not None for j in t):  # one job with no queue time leaves its end unknown
            run_ms.append(max(_epoch_ms(j.created) + j.queue_ms + j.total_ms for j in t)
                          - min(_epoch_ms(j.created) for j in t))
    suite: dict[str, int] = {}
    for r in runs:
        if r.repo == repo:
            suite[r.evidence] = suite.get(r.evidence, 0) + r.wall_ms
    job_ms = suite_ms = outside = floored = 0
    qualifying = 0
    for e, g in mine.items():
        t = _timed(g)
        if not t or e not in suite or any(j.conclusion != "skipped" and j.total_ms is None for j in g):
            continue  # an untimed job that was not skipped makes the run's job time incomplete
        run_job = sum(j.total_ms for j in t)
        qualifying += 1
        job_ms += run_job
        suite_ms += suite[e]
        outside += max(0, run_job - suite[e])
        floored += suite[e] > run_job
    timed_ids = {(j.evidence, j.job_id) for j in timed}
    by_name: dict[str, list[int]] = {}
    for st in steps:
        if st.repo == repo and st.ms is not None and (st.evidence, st.job_id) in timed_ids:
            by_name.setdefault(st.step, []).append(st.ms)
    ranked = sorted(by_name.items(), key=lambda kv: (-median(kv[1]), -percentile95(kv[1]), kv[0]))
    step_name = {(st.evidence, st.job_id, st.number): st.step for st in steps if st.repo == repo}
    failed: dict[str, int] = {}
    for j in here:
        if j.failed_step_number is not None:
            name = step_name[(j.evidence, j.job_id, j.failed_step_number)]
            failed[name] = failed.get(name, 0) + 1
    return {
        "billed_ms": sum(j.total_ms for j in timed),
        "failed_steps": [{"count": n, "step": name} for name, n in sorted(failed.items(), key=lambda kv: (-kv[1], kv[0]))],
        "job_ms": _spread([j.total_ms for j in timed]),
        "jobs": len(here),
        "jobs_skipped": sum(j.conclusion == "skipped" for j in here),
        "jobs_untimed": sum(j.conclusion != "skipped" and j.total_ms is None for j in here),
        "queue_ms": _spread([j.queue_ms for j in timed if j.queue_ms is not None], top=True),
        "resolution_ms": 1000,
        "run_ms": _spread(run_ms),
        "runs": len(mine),
        "slowest_steps": [{"median": median(v), "p95": percentile95(v), "step": name, "steps": len(v)}
                          for name, v in ranked[:5]],
        "with_suite": {"job_ms": job_ms, "outside_suite_ms": outside, "runs": qualifying, "runs_floored": floored,
                       "suite_ms": suite_ms},
    }


def _repo_summary(repo: str, week: str, runs: list[RunRow], failures: list[FailureRow], weekly: list[WeeklyRow],
                  kind_rules: dict[str, str], jobs: list[JobRow] | None = None,
                  steps: list[StepRow] | None = None) -> dict:
    mine = [r for r in runs if r.repo == repo]
    this = [r for r in mine if week_of(r.started) == week]
    walls = [r.wall_ms for r in this]
    by_python = {py: [r.wall_ms for r in this if r.python == py] for py in sorted({r.python for r in this})}
    prior_weeks = {week_back(week, k) for k in range(1, PRIOR_WEEKS + 1)}
    prior = [r for r in mine if week_of(r.started) in prior_weeks]
    prior_median = median([r.wall_ms for r in prior]) if prior else None
    this_median = median(walls)
    event_of = {(r.evidence, r.python): r.event for r in mine}
    repo_failures = [f for f in failures if f.repo == repo]
    fails = [f for f in repo_failures if week_of(f.started) == week]
    rows = [w for w in weekly if w.repo == repo]
    here = [w for w in rows if w.week == week]
    earlier = [w.week for w in rows if w.week < week]
    before = {w.test_id for w in rows if w.week == max(earlier)} if earlier else None
    ids = {w.test_id for w in here}
    on_pr = [f for f in sorted(fails, key=lambda f: (f.test_id, f.evidence, f.python))
             if event_of.get((f.evidence, f.python)) == "pull_request"]
    on_main = [f for f in sorted(fails, key=lambda f: (f.test_id, f.evidence, f.python))
               if event_of.get((f.evidence, f.python)) == "push"]
    out = {
        "by_kind": _by_kind(kind_rules, here, on_pr, on_main),
        "caught_on_pr": {"count": len({f.test_id for f in on_pr}),
                         "failures": [{"evidence": f.evidence, "outcome": f.outcome, "python": f.python, "sha": f.sha,
                                       "test_id": f.test_id} for f in on_pr]},
        "ci_wall_ms": sum(walls),
        "failed_on_main": [{"evidence": f.evidence, "outcome": f.outcome, "python": f.python, "sha": f.sha,
                            "test_id": f.test_id} for f in on_main],
        "flaky": _flaky(mine, repo_failures, week),
        "over_threshold": this_median > SUITE_MEDIAN_THRESHOLD_MS,
        "red_runs": sum(r.exit_code != 0 for r in this),
        "runs": len(this),
        "slowest_tests": [{k: v for k, v in t.items() if k != "repo"} for t in _slowest(here)],
        "suite_ms": {"by_python": {py: {"median": median(v), "runs": len(v)} for py, v in by_python.items()},
                     "max": max(walls), "median": this_median},
        "suite_ms_change": None if prior_median is None else this_median - prior_median,
        "suite_ms_prior4": {"median": prior_median, "weeks": len({week_of(r.started) for r in prior})},
        "tests": max(this, key=lambda r: (r.started, r.evidence, r.python)).tests,
        "tests_added": sorted(ids - before) if before is not None else [],
        "tests_removed": sorted(before - ids) if before is not None else [],
    }
    if jobs is not None:  # adopted job books only: without them the output is what it always was
        out["lifecycle"] = _lifecycle(repo, week, runs, jobs, steps or [])
        out["recorded"] = True
    return out


def _volume(repo: str, week: str, rows: list[VolumeRow]) -> dict | None:
    """The repo's row for the week and the change in lines since its latest earlier row of the same rule, or None
    when the week has no row (no push run that week, or not fetched). Integers only: the brief divides."""
    mine = [r for r in rows if r.repo == repo]
    this = next((r for r in mine if r.week == week), None)
    if this is None:
        return None
    prior = max((r for r in mine if r.week < week and r.rule == this.rule), key=lambda r: r.week, default=None)
    return {"evidence": this.evidence, "rule": this.rule, "sha": this.sha,
            "source_files": this.source_files, "source_lines": this.source_lines,
            "test_files": this.test_files, "test_lines": this.test_lines,
            "prior_week": prior.week if prior else None,
            "source_lines_change": this.source_lines - prior.source_lines if prior else None,
            "test_lines_change": this.test_lines - prior.test_lines if prior else None}


PULL_PARTS = ("open_ms", "ci_ms", "rework_ms", "wait_ms")


def _pulls(repo: str, week: str, rows: list[PullRow]) -> dict | None:
    """The pull requests of the repo merged in the week (the ISO week of `merged`), or None when there are none. Per part,
    the median and the nearest-rank p95 over those pull requests; never a sum, because a few left open overnight would set
    it. `rework_ms` is what is left of the open time once CI and the wait to merge are taken out."""
    mine = [r for r in rows if r.repo == repo and week_of(r.merged) == week]
    if not mine:
        return None
    parts: dict[str, list[int]] = {name: [] for name in PULL_PARTS}
    for r in mine:
        open_ms = (epoch_of(r.merged) - epoch_of(r.opened)) * 1000
        for name, value in zip(PULL_PARTS, (open_ms, r.ci_ms, open_ms - r.ci_ms - r.wait_ms, r.wait_ms)):
            parts[name].append(value)
    return {"count": len(mine), "no_checks": sum(r.checks == 0 for r in mine),
            **{name: {"p50": median(values), "p95": percentile95(values)} for name, values in parts.items()}}


def _unrecorded_summary(lifecycle: dict) -> dict:
    """A repo with CI runs in the week and no test records: only what the job books measured. Its suite time is not
    measured, so no test-side key exists here (an empty value is never a 0)."""
    return {"lifecycle": lifecycle, "recorded": False}


def summarize(runs: list[RunRow], failures: list[FailureRow], weekly: list[WeeklyRow], week: str,
              kinds: Iterable[KindRow] = (), jobs: list[JobRow] | None = None,
              steps: list[StepRow] | None = None, skill_uses: list[SkillUseRow] | None = None,
              private: set[str] | None = None, public_only: bool = False, volume: list[VolumeRow] | None = None,
              pulls: list[PullRow] | None = None, skill_tokens: bool = False) -> dict:
    """The week's numbers as plain data: integers, strings, lists and dicts, nothing else. `jobs` and `steps` are
    given (possibly empty) only for adopted job books; each listed repo then gets a `lifecycle` and `recorded`, and a
    repo with runs in the job books and no `runs.csv` row that week is listed too, as an unrecorded one. `skill_uses` is
    given (possibly empty) only when books/skill-uses.csv exists; the result then has `skills`. `private` is given
    only when books/repos.csv exists; each listed repo then has a `visibility`. `public_only` marks a summary whose rows
    the caller already limited to public repos. `volume` is given (possibly empty) only when books/volume.csv exists;
    each listed repo, recorded or not, then has a `volume` (None when the week has no row). `pulls` likewise for
    books/pulls.csv: each listed repo then has `pulls` (None when no pull request merged that week)."""
    recorded = sorted({r.repo for r in runs if week_of(r.started) == week})
    kinds = list(kinds)
    rules = {repo: {k.prefix: k.kind for k in kinds if k.repo == repo} for repo in recorded}
    repos = {repo: _repo_summary(repo, week, runs, failures, weekly, rules[repo], jobs, steps) for repo in recorded}
    if jobs is not None:
        for repo in sorted({j.repo for j in jobs} - set(recorded)):
            lifecycle = _lifecycle(repo, week, runs, jobs, steps or [])
            if lifecycle is not None:
                repos[repo] = _unrecorded_summary(lifecycle)
    if volume is not None:
        for repo, entry in repos.items():
            entry["volume"] = _volume(repo, week, volume)
    if pulls is not None:
        for repo, entry in repos.items():
            entry["pulls"] = _pulls(repo, week, pulls)
    if private is not None:
        for repo, entry in repos.items():
            entry["visibility"] = "private" if repo in private else "public"
    result = {
        "generated_from": {"failures": len(failures), "runs": len(runs), "weekly_rows": len(weekly)},
        "repos": dict(sorted(repos.items())),
        "slowest_tests": _slowest([w for w in weekly if w.week == week and w.repo in recorded]),
        "thresholds": {"suite_median_ms": SUITE_MEDIAN_THRESHOLD_MS},
        "week": week,
    }
    if skill_uses is not None:
        result["skills"] = _skills_summary([u for u in skill_uses if u.week == week], skill_tokens)
    if public_only:
        result["public_only"] = True
    return result


def _skill_tokens(rows: list[SkillUseRow]) -> dict:
    """Token sums over the rows that measured them, and their mean per such row, rounded to a whole token (None when
    no row did). Cursor rows and rows booked before the token columns are left out of both."""
    measured = [r for r in rows if r.input_tokens is not None]
    sums = {name: sum(getattr(r, name) for r in measured) for name in SKILL_TOKENS}
    total = sum(sums.values())
    return {**sums, "token_uses": len(measured),
            "tokens_per_use": (2 * total + len(measured)) // (2 * len(measured)) if measured else None}


def _skills_summary(uses: list[SkillUseRow], tokens: bool = False) -> dict:
    """Uses per skill in one week, most used first. `calls`, `searches` and `errors` are sums over the Claude Code
    rows (a Cursor row has none), each row counting at most the first SKILL_WINDOW tool results after the load. With
    `tokens` (the book has the token columns), each skill also has `_skill_tokens`."""
    groups: dict[tuple[str, str], list[SkillUseRow]] = {}
    for u in uses:
        groups.setdefault((u.skill, u.source), []).append(u)
    by_skill = [{"skill": skill, "source": source, "uses": len(rows),
                 "by_how": {how: sum(r.how == how for r in rows) for how in SKILL_HOWS},
                 "by_tool": {tool: sum(r.tool == tool for r in rows) for tool in SKILL_TOOLS},
                 "calls": sum(r.calls or 0 for r in rows), "searches": sum(r.searches or 0 for r in rows),
                 "errors": sum(r.errors or 0 for r in rows),
                 "unjudged": sum(r.verdict == "unjudged" for r in rows), **(_skill_tokens(rows) if tokens else {})}
                for (skill, source), rows in groups.items()]
    by_skill.sort(key=lambda s: (-s["uses"], s["skill"], s["source"]))
    return {"by_skill": by_skill, "uses": len(uses), "window": SKILL_WINDOW}


def _render_lifecycle(lc: dict) -> list[str]:
    def spread(d: dict | None, what: str) -> str:
        return f"{what} median {d['median']} ms (p95 {d['p95']})" if d else f"{what} not measured"
    w = lc["with_suite"]
    lines = [f"  lifecycle: {lc['runs']} runs, {lc['jobs']} jobs ({lc['jobs_skipped']} skipped, {lc['jobs_untimed']} untimed); "
             + spread(lc["run_ms"], "run") + "; " + spread(lc["queue_ms"], "queue"),
             f"  outside the suite: {w['outside_suite_ms']} ms of {w['job_ms']} ms job time over {w['runs']} runs "
             f"(suite {w['suite_ms']} ms)"]
    if lc["slowest_steps"]:
        t = lc["slowest_steps"][0]
        name = json.dumps(printable(t["step"]), ensure_ascii=False)  # quoted: a PR controls the name
        lines.append(f"  slowest step: {name} median {t['median']} ms over {t['steps']} steps")
    return lines


def _render_volume(v: dict | None) -> list[str]:
    if v is None:
        return ["  volume: no row this week"]
    change = (f"; since {v['prior_week']}: test {v['test_lines_change']:+d}, source {v['source_lines_change']:+d}"
              if v["prior_week"] else "; no earlier week")
    return [f"  volume: test {v['test_lines']} lines in {v['test_files']} files, source {v['source_lines']} lines in "
            f"{v['source_files']} files{change}"]


def _render_pulls(p: dict | None) -> list[str]:
    if p is None:
        return ["  pulls: none merged this week"]
    def spread(name: str, what: str) -> str:
        return f"{what} p50 {p[name]['p50']} ms (p95 {p[name]['p95']})"
    return [f"  pulls: {p['count']} merged ({p['no_checks']} without checks); " + "; ".join(
        spread(name, what) for name, what in zip(PULL_PARTS, ("open", "ci", "rework", "wait")))]


def render_summary(s: dict) -> str:
    lines = ["public repos only"] if s.get("public_only") else []
    lines.append(f"quality summary for {s['week']} (from {s['generated_from']['runs']} runs, "
                 f"{s['generated_from']['failures']} failures, {s['generated_from']['weekly_rows']} weekly rows)")
    for name, r in s["repos"].items():
        repo = f"{name} (private)" if r.get("visibility") == "private" else name
        if r.get("recorded") is False:
            lines.append(f"{repo}: no test record started this week")
            lines.extend(_render_lifecycle(r["lifecycle"]))
            if "volume" in r:
                lines.extend(_render_volume(r["volume"]))
            if "pulls" in r:
                lines.extend(_render_pulls(r["pulls"]))
            continue
        change = r["suite_ms_change"]
        lines.append(f"{repo}: {r['runs']} runs ({r['red_runs']} red), {r['tests']} tests, suite median "
                     f"{r['suite_ms']['median']} ms (max {r['suite_ms']['max']}), "
                     + ("no prior weeks" if change is None else f"{change:+d} ms vs the prior weeks")
                     + (", OVER THRESHOLD" if r["over_threshold"] else ""))
        lines.append(f"  failed on a push: {len(r['failed_on_main'])}; caught on a pull request: "
                     f"{r['caught_on_pr']['count']} tests; flaky: {len(r['flaky'])}; "
                     f"tests added {len(r['tests_added'])}, removed {len(r['tests_removed'])}; CI time {r['ci_wall_ms']} ms")
        lines.append("  by kind: " + "; ".join(f"{kind} {k['tests']} tests {k['total_ms']} ms, caught {k['caught_on_pr']} on a pull request"
                                                for kind, k in r["by_kind"].items()))
        for t in r["slowest_tests"][:3]:
            lines.append(f"  slow: {printable(t['test_id'])} mean {t['mean_ms']} ms over {t['runs']} runs")
        if r.get("lifecycle"):
            lines.extend(_render_lifecycle(r["lifecycle"]))
        if "volume" in r:
            lines.extend(_render_volume(r["volume"]))
        if "pulls" in r:
            lines.extend(_render_pulls(r["pulls"]))
    if "skills" in s:
        lines.append(f"skills: {s['skills']['uses']} uses of {len(s['skills']['by_skill'])} skills")
    lines.append(f"threshold: suite median above {s['thresholds']['suite_median_ms']} ms")
    return "\n".join(lines)


def cmd_summary(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    if args.week is not None and not _is_iso_week(args.week):
        print(f"quality.py: --week must be a real ISO week like 2026-W46, got {args.week!r}", file=sys.stderr)
        return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        if args.public_only:  # a problem line quotes the cell it faults, and that cell may be a private repo's
            print(f"{len(problems)} problems; no summary from unchecked books (run check to read them: --public-only prints none)")
            return 1
        _print_problems(problems)
        print(f"{len(problems)} problems; no summary from unchecked books")
        return 1
    if args.public_only and not books.tables[REPOS].present:
        print(f"quality.py: summary --public-only needs {REPOS}: visibility is not booked, so no repo can be called public (run fetch and ingest with it)",
              file=sys.stderr)
        return 2
    runs = _typed_rows(books, RUNS, RunRow)
    week = args.week or max((week_of(r.started) for r in runs), default=None)
    if week is None:
        print("no runs in the books; pass --week to summarize an empty week", file=sys.stderr)
        return 1
    job_rows = _typed_rows(books, JOBS, JobRow) if adopted(books) else None
    step_rows = _typed_rows(books, STEPS, StepRow) if adopted(books) else None
    failures, weekly, kinds = _typed_rows(books, FAILURES, FailureRow), _typed_rows(books, WEEKLY, WeeklyRow), _typed_rows(books, KINDS, KindRow)
    skills = _typed_rows(books, SKILLS, SkillUseRow) if books.tables[SKILLS].present else None
    skill_tokens = books.tables[SKILLS].present and not books.tables[SKILLS].legacy
    private = private_repos(books) if books.tables[REPOS].present else None
    volume = _typed_rows(books, VOLUME, VolumeRow) if books.tables[VOLUME].present else None
    pulls = _typed_rows(books, PULLS, PullRow) if books.tables[PULLS].present else None
    if args.public_only:  # drop the private repos' rows before any number is made, so none can leak; skill use is not per repo
        public = lambda rows: [r for r in rows if r.repo not in private]
        runs, failures, weekly, kinds = public(runs), public(failures), public(weekly), public(kinds)
        job_rows, step_rows = (public(job_rows), public(step_rows)) if job_rows is not None else (None, None)
        skills = None
        volume = public(volume) if volume is not None else None
        pulls = public(pulls) if pulls is not None else None
    result = summarize(runs, failures, weekly, week, kinds, job_rows, step_rows, skills, private, args.public_only, volume, pulls,
                       skill_tokens)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else render_summary(result))
    return 0


# ---------------------------------------------------------------------------
# fetch: GitHub's own account of each run, and its test-results artifacts, onto disk
# ---------------------------------------------------------------------------
#
# `fetch` is the only command that talks to GitHub, through the `gh` CLI (`gh api`). It writes
# under OUT_DIR only, never under BOOKS_DIR. What it writes is what `ingest` reads:
#   OUT_DIR/<repo>/<run_id>/manifest.json             the API's account of the run (see Manifest)
#   OUT_DIR/<repo>/<run_id>/artifacts/<name>/*.jsonl  the run's test-results-* artifacts, unzipped
#   OUT_DIR/<repo>/<run_id>/jobs.json                 the API's jobs and steps of the run (see JobsFile), only
#                                                     once BOOKS_DIR/books/jobs.csv exists
#   OUT_DIR/<repo>/repo.json                          the repo's visibility as GitHub said it, only once
#                                                     BOOKS_DIR/books/repos.csv exists
# The artifacts are downloaded as they are and believed only by `ingest`, and only for what they measured.

ARTIFACT_PREFIX = "test-results-"
JOBS_FILE = "jobs.json"
REPO_FILE = "repo.json"  # OUT_DIR/<repo>/repo.json, only once BOOKS_DIR/books/repos.csv exists
MAX_JOBS_PER_RUN = 64
MAX_STEPS_PER_JOB = 100
_ARTIFACT_NAME = re.compile(r"test-results-[A-Za-z0-9._-]{1,100}")
MAX_ARTIFACTS_PER_RUN = 12
MAX_ZIP_BYTES = 32 << 20  # one downloaded archive
MAX_ZIP_MEMBERS = 100
MAX_UNPACKED_BYTES = 16 << 20  # what one archive unpacks to
MAX_RUN_UNPACKED_BYTES = 32 << 20  # what all the archives of one run unpack to
SINCE_OVERLAP_DAYS = 3  # the default --since lists this many days before the latest booked start again
GH_TIMEOUT_SECONDS = 300
LOOKBACK_DAYS = 7  # how far back a repo with nothing booked yet is listed


def _api_text(value: object, what: str) -> str:
    """An API timestamp or conclusion: null or missing is "", any other non-text is malformed."""
    if value is None:
        return ""
    if type(value) is not str:
        raise Rejected(f"has a job or step whose {what} is not text")
    return value


class Step(NamedTuple):
    number: int
    name: str
    conclusion: str
    started: str
    completed: str


class Job(NamedTuple):
    id: int
    name: str
    conclusion: str
    created: str
    started: str
    completed: str
    steps: tuple[Step, ...]


class JobsFile(NamedTuple):
    """What the Actions jobs API reported for one run attempt, as `fetch` writes it to jobs.json."""
    v: int
    run_id: int
    run_attempt: int
    jobs: tuple[Job, ...]

    @staticmethod
    def from_api(manifest: Manifest, pages: list[dict]) -> "JobsFile":
        """Raises Rejected for a malformed job or step, or a run over a cap (the whole run is refused)."""
        if not pages or not all(isinstance(page.get("jobs"), list) for page in pages):
            raise Rejected("answered without a jobs list")
        raw = [j for page in pages for j in page["jobs"]]
        if len(raw) > MAX_JOBS_PER_RUN:
            raise Rejected(f"has more than {MAX_JOBS_PER_RUN} jobs; none stored")
        jobs = []
        for j in raw:
            if not isinstance(j, dict) or type(j.get("id")) is not int or type(j.get("name")) is not str:
                raise Rejected("has a job without an integer id or a text name")
            raw_steps = j.get("steps") if j.get("steps") is not None else []
            if not isinstance(raw_steps, list):
                raise Rejected(f"job {j['id']} has steps that are not a list")
            if len(raw_steps) > MAX_STEPS_PER_JOB:
                raise Rejected(f"job {j['id']} has more than {MAX_STEPS_PER_JOB} steps; none stored")
            steps = []
            for s in raw_steps:
                if not isinstance(s, dict) or type(s.get("number")) is not int or type(s.get("name")) is not str:
                    raise Rejected(f"job {j['id']} has a step without an integer number or a text name")
                steps.append(Step(s["number"], s["name"], _api_text(s.get("conclusion"), "conclusion"),
                                  _api_text(s.get("started_at"), "started_at"), _api_text(s.get("completed_at"), "completed_at")))
            jobs.append(Job(j["id"], j["name"], _api_text(j.get("conclusion"), "conclusion"), _api_text(j.get("created_at"), "created_at"),
                            _api_text(j.get("started_at"), "started_at"), _api_text(j.get("completed_at"), "completed_at"),
                            tuple(sorted(steps, key=lambda s: s.number))))
        return JobsFile(RECORD_VERSION, manifest.run_id, manifest.run_attempt, tuple(sorted(jobs, key=lambda j: j.id)))

    def to_json(self) -> dict:
        return {"v": self.v, "run_id": self.run_id, "run_attempt": self.run_attempt,
                "jobs": [{**j._asdict(), "steps": [s._asdict() for s in j.steps]} for j in self.jobs]}


class GhError(Exception):
    """A `gh api` call that failed, and why."""


class Gh:
    def __init__(self, exe: str):
        self.exe = exe

    def api(self, endpoint: str, paginate: bool = False) -> bytes:
        argv = [self.exe, "api", *(["--paginate"] if paginate else []), endpoint]
        try:
            done = subprocess.run(argv, capture_output=True, timeout=GH_TIMEOUT_SECONDS,
                                  env={**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"})
        except (OSError, subprocess.SubprocessError) as e:
            raise GhError(f"gh could not run: {type(e).__name__}") from None
        if done.returncode != 0:
            raise GhError(f"gh api {endpoint.split('?')[0]} failed: "
                          + (printable(done.stderr.decode('utf-8', 'replace').strip()) or f"exit {done.returncode}"))
        return done.stdout

    def _decoded_pages(self, endpoint: str, kind: type) -> list:
        raw = self.api(endpoint, paginate=True).decode("utf-8", "replace")
        decoder, at, found = json.JSONDecoder(), 0, []
        try:
            while True:
                while at < len(raw) and raw[at].isspace():
                    at += 1
                if at >= len(raw):
                    break
                page, at = decoder.raw_decode(raw, at)
                if not isinstance(page, kind):
                    raise ValueError("a page is not what the listing returns")
                found.append(page)
        except (ValueError, RecursionError):
            raise GhError(f"gh api {endpoint.split('?')[0]} did not answer with JSON") from None
        return found

    def pages(self, endpoint: str) -> list[dict]:
        """A paginated listing: `gh api --paginate` prints one JSON object per page, one after another."""
        return self._decoded_pages(endpoint, dict)

    def items(self, endpoint: str) -> list[dict]:
        """A paginated listing that answers with arrays (`gh api --paginate` prints one array per page): every item, in order."""
        found = [item for page in self._decoded_pages(endpoint, list) for item in page]
        if not all(isinstance(item, dict) for item in found):
            raise GhError(f"gh api {endpoint.split('?')[0]} listed something that is not an object")
        return found


def find_gh() -> str | None:
    """QUALITY_GH when set (tests point it at a fake), else `gh` on PATH."""
    return shutil.which(os.environ.get("QUALITY_GH") or "gh")


def _day(text: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _inside(folder: str, parent: str) -> bool:
    folder, parent = os.path.realpath(folder), os.path.realpath(parent)
    return folder == parent or folder.startswith(parent.rstrip(os.sep) + os.sep)


def _safe_member(name: str) -> bool:
    parts = name.split("/")
    return (0 < len(name) <= 200 and "\\" not in name and not _CONTROL.search(name)
            and all(p not in ("", ".", "..") for p in parts))


class OverCap(Rejected):
    """An archive or a run that unpacks to more than its cap: the whole run is failed."""


def extract_archive(raw: bytes, dest: str, run_left: list[int] | None = None) -> int:
    """Unzip the *.jsonl members of an artifact into `dest`, replacing it. An archive with a member whose
    name climbs out, is absolute, or is a link, or one that is too big, is refused whole. Bytes are counted
    as they are written, never taken from the header, and writing stops the moment a cap is passed: one
    member (8 MB), the archive (16 MB), and `run_left[0]`, the bytes the run may still unpack (spent here).
    Returns the files written."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise Rejected("is not a zip archive") from None
    if run_left is None:
        run_left = [MAX_RUN_UNPACKED_BYTES]
    with archive:
        members = [i for i in archive.infolist() if not i.filename.endswith("/")]
        if len(members) > MAX_ZIP_MEMBERS:
            raise Rejected(f"has more than {MAX_ZIP_MEMBERS} files")
        for info in members:
            if not _safe_member(info.filename) or stat.S_ISLNK(info.external_attr >> 16):
                raise Rejected(f"has an unsafe member name {_show(info.filename, 80)}")
            if info.file_size > MAX_ARTIFACT_BYTES:
                raise Rejected(f"has a file larger than {_size(MAX_ARTIFACT_BYTES)}")
        partial = dest + ".partial"
        shutil.rmtree(partial, ignore_errors=True)
        written = total = 0
        try:
            for info in members:
                if not info.filename.endswith(".jsonl"):
                    continue
                path = os.path.join(partial, *info.filename.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                size = 0
                with archive.open(info) as member, open(path, "xb") as f:
                    while chunk := member.read(1 << 16):
                        size += len(chunk)
                        total += len(chunk)
                        run_left[0] -= len(chunk)
                        if size > MAX_ARTIFACT_BYTES:
                            raise Rejected(f"has a file larger than {_size(MAX_ARTIFACT_BYTES)}")
                        if total > MAX_UNPACKED_BYTES:
                            raise OverCap(f"unpacks to more than {_size(MAX_UNPACKED_BYTES)}")
                        if run_left[0] < 0:
                            raise OverCap(f"unpacks, with the run's other artifacts, to more than {_size(MAX_RUN_UNPACKED_BYTES)}")
                        f.write(chunk)
                written += 1
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if written:
                os.replace(partial, dest)
            else:
                os.makedirs(dest)
        finally:
            shutil.rmtree(partial, ignore_errors=True)
    return written


@dataclass
class FetchTally:
    runs: int = 0  # fetched
    artifacts: int = 0
    listed: int = 0
    forks: int = 0
    pushes: int = 0
    booked: int = 0
    empty: int = 0
    failed: int = 0
    jobs_adopted: bool = False  # books/jobs.csv exists: the totals line says what was stored
    jobs_runs: int = 0  # runs with a jobs.json written
    jobs: int = 0
    volume_adopted: bool = False  # books/volume.csv exists: the totals line says what was counted
    volume_weeks: int = 0  # volume.json files written
    volume_none: int = 0  # weeks without a push run, so without a row
    pulls_adopted: bool = False
    pulls: int = 0

    def fail(self, where: str, why: str) -> None:
        self.failed += 1
        print(f"  FAILED {where}: {why}")


def _latest_started(books: Books, repo: str) -> str | None:
    """The day SINCE_OVERLAP_DAYS before the repo's latest booked start: a run still going or whose download
    failed when a newer run was booked is listed again, and a run already booked is skipped."""
    stamps = [r.cells["started"] for r in books.tables[RUNS].rows if r.cells["repo"] == repo]
    return (date.fromisoformat(max(stamps)[:10]) - timedelta(days=SINCE_OVERLAP_DAYS)).isoformat() if stamps else None


def _booked_per_run(books: Books) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in books.tables[RUNS].rows:
        counts[r.cells["evidence"]] = counts.get(r.cells["evidence"], 0) + 1
    return counts


def _write_json(path: str, value: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{os.getpid()}.tmp"
    with open(temp, "w") as f:
        f.write(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temp, path)


def _manifest_of(run: dict, repo: str, github: str, workflow: str, default_branch: str) -> Manifest:
    """The manifest for one API run object. Raises Rejected when the API left out what the manifest holds."""
    def field(key: str, kind: type) -> object:
        value = run.get(key)
        if type(value) is not kind:
            raise Rejected(f"run has no usable {key}")
        return value

    head = run.get("head_repository")
    fork = not isinstance(head, dict) or str(head.get("full_name") or "").lower() != github.lower()
    return Manifest(RECORD_VERSION, repo, github, field("id", int), field("run_attempt", int), workflow, field("event", str),
                    field("head_sha", str), str(run.get("head_branch") or ""), default_branch,
                    field("run_started_at", str), field("updated_at", str), str(run.get("conclusion") or ""), fork)


def _repo_info(gh: Gh, github: str) -> tuple[object, str]:
    """The repository API's answer and "", or None and why there is none."""
    try:
        return json.loads(gh.api(f"repos/{github}")), ""
    except GhError as e:
        return None, str(e)
    except ValueError:
        return None, f"gh api repos/{github} did not answer with JSON"


def utc_stamp() -> str:
    """Now, as the books write a time. One function so a test can set the clock."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_visibility(out_dir: str, repo: str, github: str, info: object) -> None:
    """Write OUT_DIR/<repo>/repo.json from the repository API's answer (None: the call failed, so `unknown`) and say what it holds."""
    visibility = visibility_of(info)
    seen = utc_stamp()
    _write_json(os.path.join(out_dir, repo, REPO_FILE), {"v": RECORD_VERSION, "repo": repo, "github": github, "visibility": visibility, "seen": seen})
    print(f"  visibility: {visibility}")


GH_LIST_CAP = 1000  # GitHub's runs listing returns at most this many results when it is filtered by `created` or `status`
MAX_LIST_CALLS = 200  # listing calls per repo: enough to split years of runs to single days, a bound if GitHub's counts are wrong


class Window(NamedTuple):
    """A range of created dates, both days inclusive. `last` None is open-ended: runs created on or after `first`, by any clock."""
    first: date
    last: date | None

    def query(self) -> str:
        return f"%3E%3D{self.first.isoformat()}" if self.last is None else f"{self.first.isoformat()}..{self.last.isoformat()}"

    def label(self) -> str:
        return f"since {self.first.isoformat()}" if self.last is None else f"{self.first.isoformat()} to {self.last.isoformat()}"


@dataclass
class RunListing:
    """What listing a repo's completed runs found: each run once, and what to say about how it was listed."""
    runs: dict[int, dict] = field(default_factory=dict)
    windows: int = 0
    over: int | None = None  # the first listing's total_count when it was over the cap
    twice: set[int] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)
    calls: int = 0
    stopped: bool = False  # MAX_LIST_CALLS was reached; windows not yet listed were left out

    def add(self, runs: dict[int, dict]) -> None:
        self.twice |= {run_id for run_id, run in runs.items() if _keep(self.runs, run)}


def _keep(runs: dict[int, dict], run: dict) -> bool:
    """Add a listed run by its id. A run already there is listed twice: the larger run_attempt, then the later updated_at, stays.
    True when it was already there."""
    def rank(r: dict) -> tuple[int, str]:
        attempt, updated = r.get("run_attempt"), r.get("updated_at")
        return (attempt if type(attempt) is int else 0, updated if isinstance(updated, str) else "")
    old = runs.get(run["id"])
    if old is None or rank(run) > rank(old):
        runs[run["id"]] = run
    return old is not None


def _read_window(gh: Gh, github: str, window: Window) -> tuple[dict[int, dict], int, int | None, set[int]]:
    """List one window: its runs by id, how many entries had no usable id, the total_count its first page reports (None when
    it is missing or not an integer), and the ids it listed more than once."""
    pages = gh.pages(f"repos/{github}/actions/runs?status=completed&per_page=100&created={window.query()}")
    total = pages[0].get("total_count") if pages else None
    runs, twice, unusable = {}, set(), 0
    for page in pages:
        for run in page.get("workflow_runs", []):
            if not isinstance(run, dict) or type(run.get("id")) is not int:
                unusable += 1
                continue
            if _keep(runs, run):
                twice.add(run["id"])
    return runs, unusable, total if type(total) is int else None, twice


def _read_counted(gh: Gh, github: str, window: Window, found: RunListing):
    """_read_window, counted against MAX_LIST_CALLS. None once the bound is reached (said once in the problems)."""
    if found.calls >= MAX_LIST_CALLS:
        if not found.stopped:
            found.stopped = True
            found.problems.append(f"{github}: stopped after {MAX_LIST_CALLS} listing calls; runs created {window.label()} and later windows were not listed")
        return None
    found.calls += 1
    return _read_window(gh, github, window)


def _list_window(gh: Gh, github: str, window: Window, today: date, found: RunListing, read=None) -> None:
    try:
        read = read or _read_counted(gh, github, window, found)
    except GhError as e:
        found.problems.append(f"{github}: listing {window.label()}: {e}")
        return
    if read is None:
        return
    runs, unusable, total, twice = read
    if total is not None and total <= GH_LIST_CAP and len(runs) + unusable < total:
        try:  # a run listed meanwhile moved the pages
            again = _read_counted(gh, github, window, found)
        except GhError as e:
            again = None
            found.problems.append(f"{github}: listing {window.label()} again: {e}")
        if again is not None:  # what the first read found is kept whatever the second one does
            again_runs, again_unusable, _, again_twice = again
            for run in again_runs.values():
                _keep(runs, run)
            unusable, twice = max(unusable, again_unusable), twice | again_twice
        if len(runs) + unusable < total:
            found.problems.append(f"{github}: {len(runs)} of {total} runs listed {window.label()}")
    over = total is not None and total > GH_LIST_CAP
    end = max(today, window.first) if window.last is None else window.last
    if over and end > window.first:  # what this window listed is a part of what its halves list
        middle = window.first + (end - window.first) // 2
        _list_window(gh, github, Window(window.first, middle), today, found)
        _list_window(gh, github, Window(middle + timedelta(days=1), window.last), today, found)
        return
    found.windows += 1
    found.twice |= twice
    found.add(runs)
    if over:
        found.problems.append(f"{github}: {total} runs on {window.first.isoformat()}; GitHub lists at most {GH_LIST_CAP}")


def list_runs(gh: Gh, github: str, since: str, today: date) -> RunListing:
    """Every completed run created on or after `since`, each once. Over GitHub's cap the listing is split by created date.
    Raises GhError when the first call fails."""
    window = Window(date.fromisoformat(since), None)
    first = _read_window(gh, github, window)
    found = RunListing(over=first[2] if first[2] is not None and first[2] > GH_LIST_CAP else None, calls=1)
    _list_window(gh, github, window, today, found, read=first)
    return found


def fetch_repo(gh: Gh, out_dir: str, repo: str, github: str, workflow: str, since: str,
               tally: FetchTally, booked: dict[str, int], booked_jobs: set[str] | None, visibility: bool = False,
               today: date | None = None) -> None:
    """`visibility` (the books have repos.csv): the repo's own call is made even when the listing fails or has no runs, and repo.json is written."""
    print(f"{repo} ({github}, {workflow}): runs created since {since}")
    try:
        listing = list_runs(gh, github, since, today or datetime.now(timezone.utc).date())
    except GhError as e:
        tally.fail("listing", str(e))
        if visibility:
            store_visibility(out_dir, repo, github, _repo_info(gh, github)[0])
        return
    runs = sorted((r for r in listing.runs.values() if r.get("name") == workflow), key=lambda r: r["id"])
    if listing.over is not None:
        print(f"  listing: {listing.over} runs since {since} are over GitHub's {GH_LIST_CAP}; listed in {listing.windows} windows")
    for run in runs:
        if run["id"] in listing.twice:
            print(f"  listing: run {run['id']} was listed twice; kept once")
    for problem in listing.problems:
        tally.fail("listing", problem)
    tally.listed += len(runs)
    if not runs and not visibility:
        return
    info, why = _repo_info(gh, github)
    if visibility:
        store_visibility(out_dir, repo, github, info)
    if not runs:
        if why:
            tally.fail("visibility", why)
        return
    default_branch = info.get("default_branch") if isinstance(info, dict) else None
    if why:
        tally.fail("default branch", why)
        return
    if not isinstance(default_branch, str) or not default_branch:
        tally.fail("default branch", f"gh api repos/{github} did not name one")
        return
    for run in runs:
        fetch_run(gh, out_dir, repo, github, workflow, default_branch, run, tally, booked, booked_jobs)


def fetch_jobs(gh: Gh, out_dir: str, manifest: Manifest, tally: FetchTally) -> JobsFile | None:
    """Store the jobs of one run attempt as jobs.json (and the manifest beside it). On any failure, say so,
    write nothing and return None: the run's artifacts are fetched all the same."""
    try:
        pages = gh.pages(f"repos/{manifest.github}/actions/runs/{manifest.run_id}/attempts/{manifest.run_attempt}/jobs?per_page=100")
        found = JobsFile.from_api(manifest, pages)
    except (GhError, Rejected) as e:
        tally.fail(str(manifest.run_id), f"jobs {e}")
        return None
    folder = os.path.join(out_dir, manifest.repo, str(manifest.run_id))
    _write_json(os.path.join(folder, MANIFEST), manifest._asdict())
    _write_json(os.path.join(folder, JOBS_FILE), found.to_json())
    tally.jobs_runs += 1
    tally.jobs += len(found.jobs)
    return found


def fetch_run(gh: Gh, out_dir: str, repo: str, github: str, workflow: str, default_branch: str, run: dict,
              tally: FetchTally, booked: dict[str, int], booked_jobs: set[str] | None) -> None:
    run_id = run["id"]
    if run.get("status") != "completed":
        print(f"  skipped {run_id}: not completed ({printable(str(run.get('status')))}); it is listed again next time")
        return
    head = run.get("head_repository")
    if not isinstance(head, dict) or str(head.get("full_name") or "").lower() != github.lower():
        tally.forks += 1
        print(f"  skipped {run_id}: fork ({printable(str((head or {}).get('full_name')))}), its code is not the repo's; not downloaded")
        return
    branch = str(run.get("head_branch") or "")
    if run.get("event") == "push" and branch != default_branch:
        tally.pushes += 1
        print(f"  skipped {run_id}: push to {printable(branch)}, not the default branch {printable(default_branch)}")
        return
    try:
        manifest = _manifest_of(run, repo, github, workflow, default_branch)
    except Rejected as e:
        tally.fail(str(run_id), str(e))
        return
    jobs = None
    if booked_jobs is not None and manifest.evidence(manifest.run_attempt) not in booked_jobs:
        jobs = fetch_jobs(gh, out_dir, manifest, tally)
    got = fetch_artifacts(gh, out_dir, manifest, run_id, tally, booked, jobs is not None)
    suffix = f", {len(jobs.jobs)} job{'s' * (len(jobs.jobs) != 1)}" if jobs is not None else ""
    if got:
        tally.runs += 1
        tally.artifacts += got
        print(f"  fetched {run_id}: {printable(str(run.get('event')))} {printable(branch)} attempt {manifest.run_attempt}, "
              f"{got} artifact{'s' * (got != 1)}{suffix}")
    elif jobs is not None:
        print(f"  fetched {run_id}: jobs only ({len(jobs.jobs)} job{'s' * (len(jobs.jobs) != 1)})")


def fetch_artifacts(gh: Gh, out_dir: str, manifest: Manifest, run_id: int, tally: FetchTally, booked: dict[str, int],
                    has_jobs: bool) -> int:
    """Download the run's test-results artifacts. Returns how many were fetched; failures are tallied."""
    github, repo = manifest.github, manifest.repo
    try:
        artifacts = [a for page in gh.pages(f"repos/{github}/actions/runs/{run_id}/artifacts?per_page=100")
                     for a in page.get("artifacts", []) if isinstance(a, dict)]
    except GhError as e:
        tally.fail(str(run_id), str(e))
        return 0
    wanted = [a for a in artifacts if str(a.get("name", "")).startswith(ARTIFACT_PREFIX)]
    if not wanted:
        tally.empty += 1  # counted in the totals line; most runs (a docs-only change) have none
        return 0
    if len(wanted) > MAX_ARTIFACTS_PER_RUN:
        tally.fail(str(run_id), f"has {len(wanted)} test-results artifacts, more than the {MAX_ARTIFACTS_PER_RUN} a run may have; nothing fetched")
        return 0
    fresh = []
    for a in wanted:
        name = str(a.get("name"))
        if a.get("expired") is True:
            tally.fail(str(run_id), f"artifact {printable(name)} expired")
        elif not _ARTIFACT_NAME.fullmatch(name) or type(a.get("id")) is not int:
            tally.fail(str(run_id), f"artifact {_show(name, 80)} is not a plain name or has no id")
        else:
            fresh.append(a)
    if not fresh:
        return 0
    if booked.get(manifest.evidence(manifest.run_attempt), 0) >= len(fresh):
        tally.booked += 1
        print(f"  skipped {run_id}: already booked")
        return 0
    folder = os.path.join(out_dir, repo, str(run_id))
    if not has_jobs:  # fetch_jobs wrote the manifest already
        _write_json(os.path.join(folder, MANIFEST), manifest._asdict())
    got, run_left = 0, [MAX_RUN_UNPACKED_BYTES]
    for a in fresh:
        name = a["name"]
        try:
            if type(a.get("size_in_bytes")) is int and a["size_in_bytes"] > MAX_ZIP_BYTES:
                raise Rejected(f"is larger than {_size(MAX_ZIP_BYTES)}")
            raw = gh.api(f"repos/{github}/actions/artifacts/{a['id']}/zip")
            if len(raw) > MAX_ZIP_BYTES:
                raise Rejected(f"is larger than {_size(MAX_ZIP_BYTES)}")
            extract_archive(raw, os.path.join(folder, ARTIFACTS, name), run_left)
            got += 1
        except OverCap as e:
            shutil.rmtree(os.path.join(folder, ARTIFACTS) if has_jobs else folder, ignore_errors=True)
            tally.fail(str(run_id), f"artifact {name} ({a['id']}) {e}; the run is not fetched")
            return 0
        except (Rejected, GhError, OSError) as e:
            tally.fail(str(run_id), f"artifact {name} ({a['id']}) not fetched: {e if not isinstance(e, OSError) else e.strerror}")
    return got


def cmd_fetch(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    today = _day(args.today) if args.today else datetime.now(timezone.utc).date()
    if today is None or (args.since is not None and _day(args.since) is None):
        print("quality.py: --since and --today must be a date like 2026-11-15", file=sys.stderr)
        return 2
    if _inside(args.out_dir, args.books_dir):
        print(f"quality.py: {args.out_dir} is inside the books folder; fetch never writes there", file=sys.stderr)
        return 2
    exe = find_gh()
    if exe is None:
        print("quality.py: cannot find the gh CLI (put it on PATH, or set QUALITY_GH to its path)", file=sys.stderr)
        return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; refusing to fetch with books that fail check")
        return 1
    booked_jobs = jobs_booked_evidence(books)
    watched = [(r.cells["repo"], r.cells["github"], r.cells["workflow"]) for r in books.tables[WATCHED].rows]
    if args.repo is not None:
        watched = [w for w in watched if w[0] == args.repo]
        if not watched:
            print(f"quality.py: {args.repo!r} is not in books/watched.csv", file=sys.stderr)
            return 2
    if not watched:
        print("nothing to fetch: books/watched.csv lists no repos")
        return 0
    os.makedirs(args.out_dir, exist_ok=True)
    volume, pulls = books.tables[VOLUME].present, books.tables[PULLS].present
    gh, booked = Gh(exe), _booked_per_run(books)
    tally = FetchTally(jobs_adopted=booked_jobs is not None, volume_adopted=volume, pulls_adopted=pulls)
    volume_booked: dict[str, set[str]] = {}
    for r in books.tables[VOLUME].rows:
        volume_booked.setdefault(r.cells["repo"], set()).add(r.cells["week"])
    pulls_booked: dict[str, set[int]] = {}
    for r in books.tables[PULLS].rows:
        pulls_booked.setdefault(r.cells["repo"], set()).add(int(r.cells["number"]))
    for repo, github, workflow in watched:
        since = args.since or _latest_started(books, repo) or (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
        local = None
        if workflow == LOCAL_CI:
            local = fetch_local(gh, args.out_dir, repo, github, since, tally, booked, books.tables[REPOS].present)
            if local is None and volume:
                print("  volume: not counted this time, a local run could not be read; the next fetch asks again")
        else:
            fetch_repo(gh, args.out_dir, repo, github, workflow, since, tally, booked, booked_jobs, books.tables[REPOS].present, today)
        if volume and not (workflow == LOCAL_CI and local is None):
            fetch_volume(gh, args.out_dir, repo, github, workflow, volume_weeks(today, args.since, volume_booked.get(repo, set())), tally,
                         local)
        if pulls:
            fetch_pulls(gh, args.out_dir, repo, github, args.since or _latest_merged(books, repo) or (today - timedelta(days=LOOKBACK_DAYS)).isoformat(),
                        pulls_booked.get(repo, set()), tally)
    t = tally
    print(f"fetched {t.runs} runs ({t.artifacts} artifacts); listed {t.listed}; skipped {t.forks} forks, "
          f"{t.pushes} pushes to a non-default branch, {t.booked} already booked, {t.empty} without test-results artifacts"
          + (f"; {t.jobs_runs} runs with jobs ({t.jobs} jobs)" if t.jobs_adopted else "")
          + (f"; volume counted for {t.volume_weeks} weeks ({t.volume_none} without a push run)" if t.volume_adopted else "")
          + (f"; {t.pulls} merged pull requests read" if t.pulls_adopted else "")
          + f"; {t.failed} failed")
    return 1 if t.failed else 0


# ---------------------------------------------------------------------------
# fetch, local-ci: runs recorded on a machine, read from the repo's refs/local-ci/records
# ---------------------------------------------------------------------------
#
# A watch-list row whose workflow is `local-ci` has no Actions runs: local-ci (agent-kit bstack) runs the repo's
# scripts/ci on a machine and publishes each run's record to the ref refs/local-ci/records of the repo, as
# runs/<sha>/<started>/manifest.json (written by local-ci) and test-results.jsonl (written by the repo's code). `fetch`
# reads that ref through the git API and writes the same layout an Actions run gets: OUT_DIR/<repo>/<run_id>/manifest.json
# and artifacts/test-results-local/test-results.jsonl, where run_id is the run's start in epoch seconds and the evidence is
# https://github.com/OWNER/NAME/commit/SHA#local-ci-STARTED. No jobs are booked: a local run has no queue time.
# The identity is local-ci's word, not GitHub's: anyone who can push to the repo can write that ref.

LOCAL_CI = "local-ci"
LOCAL_RECORDS_REF = "refs/local-ci/records"
LOCAL_ARTIFACT = "test-results-local"
MAX_LOCAL_RUNS = 2000  # runs listed on the ref; more is refused
LOCAL_MANIFEST_KINDS = {"v": int, "github": str, "sha": str, "event": str, "head_branch": str, "base": str, "started": str,
                        "completed": str, "host": str}
_LOCAL_PATH = re.compile(r"runs/([0-9a-f]{40})/([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)/(manifest\.json|test-results\.jsonl)")


class LocalRun(NamedTuple):
    sha: str
    started: str
    manifest_blob: str
    record_blob: str
    record_size: int


def list_local_runs(gh: Gh, github: str) -> list[LocalRun]:
    """Every run on the repo's records ref, oldest first; [] when the ref does not exist. Raises GhError."""
    refs = json.loads(gh.api(f"repos/{github}/git/matching-refs/{LOCAL_RECORDS_REF[len('refs/'):]}"))
    tip = next((r.get("object", {}).get("sha") for r in refs if isinstance(r, dict) and r.get("ref") == LOCAL_RECORDS_REF), None) \
        if isinstance(refs, list) else None
    if not isinstance(tip, str) or not _SHA.fullmatch(tip):
        return []
    commit = json.loads(gh.api(f"repos/{github}/git/commits/{tip}"))
    tree_sha = commit.get("tree", {}).get("sha") if isinstance(commit, dict) else None
    if not isinstance(tree_sha, str) or not _SHA.fullmatch(tree_sha):
        raise GhError(f"gh api repos/{github}/git/commits/{tip[:12]} named no tree")
    tree = json.loads(gh.api(f"repos/{github}/git/trees/{tree_sha}?recursive=1"))
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list) or tree.get("truncated") is not False:
        raise GhError(f"{LOCAL_RECORDS_REF} of {github} came back truncated or without a tree")
    files: dict[tuple[str, str], dict[str, tuple[str, int]]] = {}
    for entry in tree["tree"]:
        found = _LOCAL_PATH.fullmatch(str(entry.get("path"))) if isinstance(entry, dict) and entry.get("type") == "blob" else None
        if found and isinstance(entry.get("sha"), str) and type(entry.get("size")) is int:
            files.setdefault((found[1], found[2]), {})[found[3]] = (entry["sha"], entry["size"])
    runs = [LocalRun(sha, started, f["manifest.json"][0], f["test-results.jsonl"][0], f["test-results.jsonl"][1])
            for (sha, started), f in files.items() if len(f) == 2]
    if len(runs) > MAX_LOCAL_RUNS:
        raise GhError(f"{LOCAL_RECORDS_REF} of {github} holds {len(runs)} runs, more than {MAX_LOCAL_RUNS}")
    return sorted(runs, key=lambda r: (r.started, r.sha))


def _blob(gh: Gh, github: str, sha: str, cap: int) -> bytes:
    obj = json.loads(gh.api(f"repos/{github}/git/blobs/{sha}"))
    if not isinstance(obj, dict) or obj.get("encoding") != "base64" or not isinstance(obj.get("content"), str):
        raise Rejected("blob came back without base64 content")
    data = base64.b64decode(obj["content"])
    if len(data) > cap:
        raise Rejected(f"is larger than {_size(cap)}")
    return data


def local_manifest(raw: bytes, run: LocalRun, repo: str, github: str, default_branch: str) -> Manifest:
    """The Manifest of one local run from local-ci's manifest.json, which must agree with where it was found."""
    obj = _load_json(raw, "local manifest")
    if not isinstance(obj, dict):
        raise Rejected("local manifest is not a JSON object")
    _check_fields({k: obj.get(k) for k in LOCAL_MANIFEST_KINDS}, LOCAL_MANIFEST_KINDS, "local manifest")
    if obj["v"] != RECORD_VERSION:
        raise Rejected(f"local manifest v must be {RECORD_VERSION}, got {_show(obj['v'])}")
    if obj["github"].lower() != github.lower() or obj["sha"] != run.sha or obj["started"] != run.started:
        raise Rejected("local manifest does not match its folder or the watch list")
    pr, code = obj.get("pr"), obj.get("exit_code")
    if obj["event"] not in ("push", "pull_request") or (pr is not None and type(pr) is not int) \
            or (code is not None and type(code) is not int) or not _is_stamp(obj["completed"]):
        raise Rejected("local manifest has a bad event, pr, exit_code or completed")
    head_branch = obj["head_branch"] or (f"pull/{pr}" if pr else "")
    if not head_branch or obj["completed"] < run.started:
        raise Rejected("local manifest has no head branch, or completed before it started")
    conclusion = "timed_out" if code is None else "success" if code == 0 else "failure"
    epoch = int(datetime.strptime(run.started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    return Manifest(RECORD_VERSION, repo, github, epoch, 1, LOCAL_CI, obj["event"], run.sha, head_branch, default_branch,
                    run.started, obj["completed"], conclusion, False)


def fetch_local(gh: Gh, out_dir: str, repo: str, github: str, since: str, tally: "FetchTally", booked: dict[str, int],
                visibility: bool = False) -> list[Manifest] | None:
    """Fetch the local runs started on or after `since` that are not booked. Returns every push to the default branch on
    the ref (booked or not), for the volume book, or None when the ref could not be read whole: a week's newest push is
    then unknown, and the volume book must not guess it."""
    print(f"{repo} ({github}, {LOCAL_CI}): local runs started since {since}")
    info, why = _repo_info(gh, github)
    if visibility:
        store_visibility(out_dir, repo, github, info)
    branch = info.get("default_branch") if isinstance(info, dict) else None
    if why or not isinstance(branch, str) or not branch:
        tally.fail("default branch", why or f"gh api repos/{github} did not name one")
        return None
    try:
        runs = list_local_runs(gh, github)
    except (GhError, ValueError) as e:
        tally.fail("listing", f"{LOCAL_RECORDS_REF}: {e}")
        return None
    pushes: list[Manifest] | None = []
    taken: set[int] = set()
    for run in runs:
        where = f"{run.sha[:12]} {run.started}"
        try:
            m = local_manifest(_blob(gh, github, run.manifest_blob, MAX_MANIFEST_BYTES), run, repo, github, branch)
        except (GhError, Rejected, ValueError) as e:
            tally.fail(where, f"manifest {e}")
            pushes = None
            continue
        if m.event == "push" and m.head_branch == branch and pushes is not None:
            pushes.append(m)
        if run.started < since:
            continue
        tally.listed += 1
        if m.event == "push" and m.head_branch != branch:
            tally.pushes += 1
            print(f"  skipped {where}: push to {printable(m.head_branch)}, not the default branch {printable(branch)}")
            continue
        if booked.get(m.evidence(1), 0):
            tally.booked += 1
            continue
        if m.run_id in taken:  # two runs started in the same second share a run_id; the next fetch takes this one
            print(f"  deferred {where}: another run started the same second; fetched next time")
            continue
        taken.add(m.run_id)
        if run.record_size > MAX_ARTIFACT_BYTES:
            tally.fail(where, f"record is larger than {_size(MAX_ARTIFACT_BYTES)}")
            continue
        try:
            record = _blob(gh, github, run.record_blob, MAX_ARTIFACT_BYTES)
        except (GhError, Rejected, ValueError) as e:
            tally.fail(where, f"record {e}")
            continue
        folder = os.path.join(out_dir, repo, str(m.run_id))
        _write_json(os.path.join(folder, MANIFEST), m._asdict())
        target = os.path.join(folder, ARTIFACTS, LOCAL_ARTIFACT, "test-results.jsonl")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(record)
        tally.runs += 1
        tally.artifacts += 1
        print(f"  fetched {where}: {m.event} {printable(m.head_branch)}, {m.conclusion}")
    return pushes


# ---------------------------------------------------------------------------
# fetch, volume: test and source lines of each watched repo, one commit per week
# ---------------------------------------------------------------------------
#
# Only when books/volume.csv exists. For each complete ISO week (UTC) not yet booked for the repo, the commit counted is
# the head of the newest push run of the watched workflow on the default branch created in that week: one call lists
# them (`repos/O/N/actions/runs?branch=B&event=push&per_page=100&created=MON..SUN`), and the same week always answers
# the same commit. A week with no such run has no row. The commit's tarball (`repos/O/N/tarball/SHA`) is read in
# memory and never extracted: only regular files are opened, and each file is classified by its path alone
# (classify_path, rule VOLUME_RULE). The source of a private repo is downloaded too, and only counts are kept.
#   OUT_DIR/<repo>/volume/<week>.json   {v, repo, github, week, sha, evidence, rule, test_files, test_lines,
#                                        source_files, source_lines}

VOLUME_DIR = "volume"
VOLUME_RULE = "v1"
VOLUME_RULE_NAMES = (VOLUME_RULE,)  # a row's rule names how its paths were classified; rows of two rules are not compared
MAX_VOLUME_WEEKS = 60  # weeks one fetch counts per repo, oldest first; the rest are counted by a later fetch
VOLUME_RETRY_WEEKS = 12  # a week without a row this recent is asked about again on every fetch
MAX_TARBALL_BYTES = 64 << 20  # one downloaded tarball
MAX_TARBALL_UNPACKED = 256 << 20  # the whole decompressed stream (headers and skipped members too), counted as it is read
MAX_TARBALL_MEMBERS = 100_000
# v1: code by suffix; a test file is one under a test directory or named as a test; vendored and built folders are not counted
CODE_SUFFIXES = (".py", ".pyi", ".sh", ".bash", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".go", ".rs",
                 ".rb", ".java", ".kt", ".kts", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".php", ".scala")
TEST_DIRS = frozenset(("test", "tests", "__tests__", "spec", "e2e"))
SKIPPED_DIRS = frozenset(("node_modules", "vendor", "third_party", "dist", "build", ".git"))
_TEST_NAME = re.compile(r"test_[^/]*\.py|[^/]*_test\.(py|go)|conftest\.py|[^/]*\.(test|spec)\.[A-Za-z0-9]+|[^/]*_spec\.rb")


def classify_path(path: str) -> str | None:
    """`test`, `source` or None (not counted) for a path inside the repo, by rule VOLUME_RULE."""
    *folders, name = path.split("/")
    if not name.endswith(CODE_SUFFIXES) or SKIPPED_DIRS & set(folders):
        return None
    return "test" if TEST_DIRS & set(folders) or _TEST_NAME.fullmatch(name) else "source"


class Volume(NamedTuple):
    test_files: int
    test_lines: int
    source_files: int
    source_lines: int


class _CappedReader:
    """A read-only stream that raises Rejected once more than `cap` bytes were asked of it: never more than cap + 1 bytes
    are read in one call, so a header that claims a huge payload cannot make the decompressor allocate it."""

    def __init__(self, inner, cap: int):
        self.inner, self.left = inner, cap

    def read(self, size: int = -1) -> bytes:
        want = self.left + 1 if size is None or size < 0 or size > self.left + 1 else size
        data = self.inner.read(want)
        self.left -= len(data)
        if self.left < 0:
            raise Rejected(f"unpacks to more than {_size(MAX_TARBALL_UNPACKED)}")
        return data


def count_tarball(raw: bytes) -> Volume:
    """Count the lines (newlines, plus a last line without one) of the code files in a gzip tarball as GitHub serves it:
    every member under one top folder named for the commit. Raises Rejected for an archive that is not one, or over a cap."""
    if len(raw) > MAX_TARBALL_BYTES:
        raise Rejected(f"is larger than {_size(MAX_TARBALL_BYTES)}")
    counts = {"test": [0, 0], "source": [0, 0]}
    members = 0
    stream = _CappedReader(gzip.GzipFile(fileobj=io.BytesIO(raw)), MAX_TARBALL_UNPACKED)
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                members += 1
                if members > MAX_TARBALL_MEMBERS:
                    raise Rejected(f"has more than {MAX_TARBALL_MEMBERS} members")
                if not member.isreg() or "/" not in member.name:
                    continue
                kind = classify_path(member.name.split("/", 1)[1])
                if kind is None:
                    continue
                f = archive.extractfile(member)
                lines, last = 0, b"\n"
                while chunk := f.read(1 << 16):
                    lines += chunk.count(b"\n")
                    last = chunk[-1:]
                counts[kind][0] += 1
                counts[kind][1] += lines + (last != b"\n")
    except (tarfile.TarError, EOFError, OSError, zlib.error) as e:
        raise Rejected(f"is not a readable gzip tarball ({type(e).__name__})") from None
    return Volume(counts["test"][0], counts["test"][1], counts["source"][0], counts["source"][1])


def volume_weeks(today: date, since: str | None, booked: set[str]) -> list[str]:
    """The complete weeks to count, oldest first, less the weeks already booked: from the week of `since`; else from the
    week after the latest booked one, or VOLUME_RETRY_WEEKS back from last week when that is earlier (so a week that
    failed or had no push run is asked again), but never before the earliest booked week; else last week alone."""
    iso = today.isocalendar()
    last = week_back(f"{iso[0]:04d}-W{iso[1]:02d}", 1)
    if since is not None:
        week = week_of(since + "T00:00:00Z")
    elif booked:
        week = max(min(week_back(max(booked), -1), week_back(last, VOLUME_RETRY_WEEKS - 1)), min(booked))
    else:
        week = last
    weeks = []
    while week <= last:
        if week not in booked:
            weeks.append(week)
        week = week_back(week, -1)
    return weeks


def _week_days(week: str) -> tuple[date, date]:
    monday = date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    return monday, monday + timedelta(days=6)


def week_push_run(gh: Gh, github: str, workflow: str, branch: str, week: str) -> dict | None:
    """The newest push run of `workflow` on `branch` from the repo itself created in `week`, or None. Raises GhError."""
    monday, sunday = _week_days(week)
    pages = gh.pages(f"repos/{github}/actions/runs?branch={urllib.parse.quote(branch, safe='')}&event=push&per_page=100"
                     f"&created={monday.isoformat()}..{sunday.isoformat()}")
    if not pages or not all(isinstance(page.get("workflow_runs"), list) for page in pages):
        raise GhError(f"gh api repos/{github}/actions/runs answered without a runs list")
    runs = [r for page in pages for r in page["workflow_runs"]]
    mine = [r for r in runs if isinstance(r, dict) and r.get("name") == workflow and r.get("event") == "push"
            and r.get("head_branch") == branch and type(r.get("id")) is int and type(r.get("run_attempt")) is int
            and isinstance(r.get("head_sha"), str) and _SHA.fullmatch(r["head_sha"]) and isinstance(r.get("created_at"), str)
            and isinstance(r.get("head_repository"), dict)
            and str(r["head_repository"].get("full_name") or "").lower() == github.lower()]
    return max(mine, key=lambda r: (r["created_at"], r["id"]), default=None)


def fetch_volume(gh: Gh, out_dir: str, repo: str, github: str, workflow: str, weeks: list[str], tally: "FetchTally",
                 local: list[Manifest] | None = None) -> None:
    """Write OUT_DIR/<repo>/volume/<week>.json for each of `weeks` that had a push run, oldest first, up to MAX_VOLUME_WEEKS.
    `local` (a local-ci repo): the week's push is the newest local run of a push to the default branch, not an Actions run."""
    if not weeks:
        return
    if len(weeks) > MAX_VOLUME_WEEKS:
        print(f"  volume: {len(weeks)} weeks to count; counting the oldest {MAX_VOLUME_WEEKS}, the rest on a later fetch")
        weeks = weeks[:MAX_VOLUME_WEEKS]
    info, why = _repo_info(gh, github)
    branch = info.get("default_branch") if isinstance(info, dict) else None
    if why or not isinstance(branch, str) or not branch:
        tally.fail("volume", why or f"gh api repos/{github} did not name a default branch")
        return
    counted: dict[str, Volume] = {}
    for week in weeks:
        if local is not None:
            newest = max((m for m in local if week_of(m.started) == week), key=lambda m: m.started, default=None)
            run = None if newest is None else {"head_sha": newest.head_sha, "evidence": newest.evidence(1)}
        else:
            try:
                run = week_push_run(gh, github, workflow, branch, week)
            except GhError as e:
                tally.fail(f"volume {week}", str(e))
                continue
        if run is None:
            tally.volume_none += 1
            print(f"  volume {week}: no push run of {printable(workflow)} on {printable(branch)}; no row")
            continue
        sha = run["head_sha"]
        if sha not in counted:
            try:
                counted[sha] = count_tarball(gh.api(f"repos/{github}/tarball/{sha}"))
            except GhError as e:
                tally.fail(f"volume {week}", str(e))
                continue
            except Rejected as e:
                tally.fail(f"volume {week}", f"tarball of {sha[:12]} {e}")
                continue
        v = counted[sha]
        _write_json(os.path.join(out_dir, repo, VOLUME_DIR, f"{week}.json"),
                    {"v": RECORD_VERSION, "repo": repo, "github": github, "week": week, "sha": sha, "rule": VOLUME_RULE,
                     "evidence": run.get("evidence") or f"https://github.com/{github}/actions/runs/{run['id']}/attempts/{run['run_attempt']}",
                     **v._asdict()})
        tally.volume_weeks += 1
        print(f"  volume {week}: {sha[:12]} test {v.test_lines} lines in {v.test_files} files, "
              f"source {v.source_lines} lines in {v.source_files} files")


PULLS_DIR = "pulls"
MAX_PULLS_PER_FETCH = 300
MAX_PULL_PAGES = 50


def _latest_merged(books: Books, repo: str) -> str | None:
    """The day SINCE_OVERLAP_DAYS before the repo's latest booked merge: what was merged since is read, and what is booked is skipped."""
    stamps = [r.cells["merged"] for r in books.tables[PULLS].rows if r.cells["repo"] == repo]
    return (date.fromisoformat(max(stamps)[:10]) - timedelta(days=SINCE_OVERLAP_DAYS)).isoformat() if stamps else None


def _api_stamp(value: object, what: str) -> int:
    if type(value) is not str or not _is_stamp(value):
        raise Rejected(f"{what} is not a usable time ({_show(value)})")
    return epoch_of(value)


def list_merged_pulls(gh: Gh, github: str, since: str) -> list[dict]:
    """The pull requests of `github` merged on or after `since` (a day), as the API listed them. Raises GhError."""
    found: dict[int, dict] = {}
    for page in range(1, MAX_PULL_PAGES + 1):
        endpoint = f"repos/{github}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}"
        try:
            listed = json.loads(gh.api(endpoint))
        except ValueError:
            raise GhError(f"gh api repos/{github}/pulls did not answer with JSON") from None
        if not isinstance(listed, list) or not all(isinstance(p, dict) and type(p.get("number")) is int for p in listed):
            raise GhError(f"gh api repos/{github}/pulls answered without a list of pull requests")
        for p in listed:
            merged = p.get("merged_at")
            if isinstance(merged, str) and merged[:10] >= since:
                found[p["number"]] = p
        last = listed[-1].get("updated_at") if listed else None
        if len(listed) < 100 or (isinstance(last, str) and last[:10] < since):
            return list(found.values())
    raise GhError(f"gh api repos/{github}/pulls: more than {MAX_PULL_PAGES} pages of pull requests since {since}; pass a later --since")


def check_intervals(runs: list[dict], merged: int) -> list[tuple[int, int]]:
    """One interval per check run that started by the merge: to its completion, or to the merge when it has none."""
    found = []
    for run in runs:
        if run.get("started_at") is None:
            continue
        start = _api_stamp(run["started_at"], "a check run's started_at")
        if start > merged:
            continue
        end = merged if run.get("completed_at") is None else _api_stamp(run["completed_at"], "a check run's completed_at")
        found.append((start, max(start, end)))
    return found


def status_intervals(statuses: list[dict], merged: int) -> list[tuple[int, int]]:
    """One interval per pending by the merge of a commit status context to the context's next state; a pending still open runs to the
    merge."""
    by_context: dict[str, list[tuple[int, int, str]]] = {}
    for status in statuses:
        context, state = status.get("context"), status.get("state")
        if type(context) is not str or type(state) is not str:
            raise Rejected("a commit status has no usable context or state")
        by_context.setdefault(context, []).append((_api_stamp(status.get("created_at"), "a commit status's created_at"),
                                                   status["id"] if type(status.get("id")) is int else 0, state))
    found = []
    for events in by_context.values():
        open_since = None
        for at, _, state in sorted(events):
            if state == "pending":
                open_since = at if open_since is None else open_since
            elif open_since is not None:
                found.append((open_since, max(open_since, at)))
                open_since = None
        if open_since is not None:
            found.append((open_since, max(open_since, merged)))
    return [(start, end) for start, end in found if start <= merged]


def _union(intervals: list[tuple[int, int]], low: int, high: int) -> list[tuple[int, int]]:
    """The intervals clipped to [low, high] and joined where they touch or overlap; empty ones dropped."""
    joined: list[list[int]] = []
    for start, end in sorted((max(s, low), min(e, high)) for s, e in intervals):
        if start >= end:
            continue
        if joined and start <= joined[-1][1]:
            joined[-1][1] = max(joined[-1][1], end)
        else:
            joined.append([start, end])
    return [(a, b) for a, b in joined]


def _covered(union: list[tuple[int, int]], low: int, high: int) -> int:
    return sum(max(0, min(b, high) - max(a, low)) for a, b in union)


def pull_cycle(opened: int, merged: int, ready_events: list[int], intervals: list[tuple[int, int]],
               head_intervals: list[tuple[int, int]]) -> dict[str, int]:
    """Seconds: `ready`, `ci` and `wait` of a pull request (see "The pulls book" in SKILL.md), and `head_done`, the end of the last interval on the
    head commit, unclipped, or 0 when it had none. Raises Rejected when the pull request was merged before it was opened."""
    if merged < opened:
        raise Rejected("was merged before it was opened")
    ready = max([opened] + [t for t in ready_events if t <= merged])
    union = _union(intervals, ready, merged)
    head_done = max((end for _, end in head_intervals), default=0)
    done = min(max(head_done, ready), merged) if head_intervals else ready
    return {"ready": ready, "ci": _covered(union, ready, merged), "head_done": head_done,
            "wait": merged - done - _covered(union, done, merged)}


def read_pull(gh: Gh, repo: str, github: str, pull: dict) -> PullRow:
    """The row for one merged pull request as the list API gave it. Raises GhError or Rejected for this pull request only."""
    number = pull["number"]
    head = pull.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if type(head_sha) is not str or not _SHA.fullmatch(head_sha):
        raise Rejected("has no usable head sha")
    opened, merged = _api_stamp(pull.get("created_at"), "created_at"), _api_stamp(pull.get("merged_at"), "merged_at")
    commits = gh.items(f"repos/{github}/pulls/{number}/commits?per_page=100")
    shas = [c.get("sha") for c in commits]
    if not all(type(sha) is str and _SHA.fullmatch(sha) for sha in shas):
        raise Rejected("lists a commit without a usable sha")
    intervals: dict[str, list[tuple[int, int]]] = {}
    for sha in dict.fromkeys(shas + [head_sha]):
        runs = []
        for page in gh.pages(f"repos/{github}/commits/{sha}/check-runs?filter=all&per_page=100"):
            if not isinstance(page.get("check_runs"), list) or not all(isinstance(r, dict) for r in page["check_runs"]):
                raise GhError(f"gh api repos/{github}/commits/{sha}/check-runs answered without a check_runs list")
            runs.extend(page["check_runs"])
        statuses = gh.items(f"repos/{github}/commits/{sha}/statuses?per_page=100")
        intervals[sha] = check_intervals(runs, merged) + status_intervals(statuses, merged)
    timeline = gh.items(f"repos/{github}/issues/{number}/timeline?per_page=100")
    ready_events = [_api_stamp(e.get("created_at"), "a ready_for_review event's created_at") for e in timeline if e.get("event") == "ready_for_review"]
    cycle = pull_cycle(opened, merged, ready_events, [i for found in intervals.values() for i in found], intervals[head_sha])
    return PullRow(stamp_of(merged), repo, number, stamp_of(opened), stamp_of(cycle["ready"]),
                   stamp_of(cycle["head_done"]) if intervals[head_sha] else "", cycle["ci"] * 1000, cycle["wait"] * 1000, len(shas),
                   sum(len(found) for found in intervals.values()), sum(e.get("event") == "head_ref_force_pushed" for e in timeline),
                   f"https://github.com/{github}/pull/{number}")


def fetch_pulls(gh: Gh, out_dir: str, repo: str, github: str, since: str, booked: set[int], tally: "FetchTally") -> None:
    """Write OUT_DIR/<repo>/pulls/<number>.json for each pull request merged on or after `since` and not in `booked`, oldest merged
    first, up to MAX_PULLS_PER_FETCH. A pull request that cannot be read prints FAILED and costs only itself."""
    try:
        listed = list_merged_pulls(gh, github, since)
    except GhError as e:
        tally.fail("pulls", str(e))
        return
    fresh = sorted((p for p in listed if p["number"] not in booked), key=lambda p: (str(p["merged_at"]), p["number"]))
    if len(fresh) > MAX_PULLS_PER_FETCH:
        print(f"  pulls: {len(fresh)} to read; reading the oldest {MAX_PULLS_PER_FETCH}, the rest on a later fetch")
        fresh = fresh[:MAX_PULLS_PER_FETCH]
    for pull in fresh:
        number = pull["number"]
        try:
            row = read_pull(gh, repo, github, pull)
        except (GhError, Rejected) as e:
            tally.fail(f"pull {number}", str(e))
            continue
        _write_json(os.path.join(out_dir, repo, PULLS_DIR, f"{number}.json"), {"v": RECORD_VERSION, "github": github, **row._asdict()})
        tally.pulls += 1
        print(f"  pull {number}: merged {row.merged}, ci {row.ci_ms} ms, wait {row.wait_ms} ms, {row.shas} commits, "
              f"{row.checks} checks, {row.force_pushes} force pushes")


# ---------------------------------------------------------------------------
# ingest, jobs: jobs.json into books/jobs.csv and books/steps.csv
# ---------------------------------------------------------------------------
#
# Only when the job books are adopted (both files exist). Identity (repo, sha, event, workflow, evidence) is the
# manifest's, as for test records. jobs.json is believed for what the API measured: job and step names,
# conclusions and timestamps. Names are text a pull request controls, so a name that is empty or would fail
# text hygiene is booked as UNPRINTABLE and never blocks the run's timings; a bad timestamp or a conclusion
# that does not fit its rule rejects the file, by name, and blocks nothing else.

UNPRINTABLE = "(unprintable name)"
MAX_JOBS_BYTES = 4 << 20
JOBS_FILE_KINDS = {"v": int, "run_id": int, "run_attempt": int, "jobs": list}
JOB_KINDS = {"id": int, "name": str, "conclusion": str, "created": str, "started": str, "completed": str, "steps": list}
STEP_KINDS = {"number": int, "name": str, "conclusion": str, "started": str, "completed": str}


def _name(text: str) -> str:
    """A job or step name as it is booked: itself, or UNPRINTABLE when it is empty or a cell could not hold it."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate
        return UNPRINTABLE
    return text if text and text_problem(text) is None else UNPRINTABLE


def _span_ms(start: str, end: str) -> str:
    """Milliseconds from one stamp to another. "" means not measured: a missing stamp, or an end before the start
    (GitHub reports a skipped job as completing a second before it starts). 0 is a real zero at one second resolution."""
    if not start or not end:
        return ""
    stamp = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    ms = round((stamp(end) - stamp(start)).total_seconds() * 1000)
    return str(ms) if ms >= 0 else ""


def _stamp_field(value: str, what: str, required: bool = False) -> None:
    if value == "" and not required:
        return
    if not _is_stamp(value):
        raise Rejected(f"{what} must look like 2026-11-15T09:30:00Z (UTC) with a year from {YEAR_MIN} to {YEAR_MAX}, "
                       f"got {_show(value)}")


@dataclass(frozen=True)
class BookedJobs:
    """One run attempt's jobs and steps, under the identity of its manifest."""
    manifest: Manifest
    jobs: tuple[Job, ...]

    @property
    def evidence(self) -> str:
        return self.manifest.evidence(self.manifest.run_attempt)

    @property
    def step_count(self) -> int:
        return sum(len(j.steps) for j in self.jobs)

    def entries(self) -> list[tuple[dict[str, str], list[dict[str, str]]]]:
        """Each job's jobs.csv cells with its steps' steps.csv cells, jobs by id and steps by number."""
        m, out = self.manifest, []
        for job in sorted(self.jobs, key=lambda j: j.id):
            steps = sorted(job.steps, key=lambda s: s.number)
            failed = next((s for s in steps if s.conclusion == "failure"), None)
            cells = _cells(JOBS_SCHEMA, created=job.created, repo=m.repo, sha=m.head_sha, event=m.event, workflow=m.workflow,
                           job=_name(job.name), job_id=job.id, conclusion=job.conclusion,
                           queue_ms=_span_ms(job.created, job.started), total_ms=_span_ms(job.started, job.completed),
                           failed_step_number=failed.number if failed else "", evidence=self.evidence)
            out.append((cells, [_cells(STEPS_SCHEMA, started=s.started, repo=m.repo, job_id=job.id, number=s.number,
                                       step=_name(s.name), conclusion=s.conclusion, ms=_span_ms(s.started, s.completed),
                                       evidence=self.evidence) for s in steps]))
        return out

    def gate(self) -> None:
        """Hold every row this file would add to every row rule `check` has, and to uniqueness."""
        messages: list[str] = []
        ids = [j.id for j in self.jobs]
        if len(set(ids)) != len(ids):
            messages.append("a job id appears twice")
        for job in self.jobs:
            numbers = [s.number for s in job.steps]
            if len(set(numbers)) != len(numbers):
                messages.append(f"job {job.id} has a step number twice")
        for job_cells, step_cells in self.entries():
            for rules, cells in [(JOB_RULES, job_cells)] + [(STEP_RULES, c) for c in step_cells]:
                if len(messages) <= 3:
                    messages.extend(m for m in rule_messages(rules, cells) if m not in messages)
        _fail_if(messages, "would fail check: ")


def read_jobs_file(path: str, m: Manifest) -> BookedJobs:
    """A run's jobs.json, strictly, under the identity of its manifest. Raises Rejected, naming what is wrong."""
    obj = _check_fields(_load_json(_read_file(path, MAX_JOBS_BYTES), "jobs.json"), JOBS_FILE_KINDS, "jobs.json")
    if obj["v"] != RECORD_VERSION:
        raise Rejected(f"jobs.json v must be {RECORD_VERSION}, got {_show(obj['v'])}")
    if (obj["run_id"], obj["run_attempt"]) != (m.run_id, m.run_attempt):
        raise Rejected(f"run_id {obj['run_id']} and run_attempt {obj['run_attempt']} are not the manifest's "
                       f"{m.run_id} and {m.run_attempt}")
    if len(obj["jobs"]) > MAX_JOBS_PER_RUN:
        raise Rejected(f"has more than {MAX_JOBS_PER_RUN} jobs")
    jobs = []
    for n, raw in enumerate(obj["jobs"], start=1):
        j = _check_fields(raw, JOB_KINDS, f"job {n}", free_text=("name",))
        where = f"job {j['id']}"
        if j["id"] < 1:
            raise Rejected(f"job {n} id must be at least 1, got {j['id']}")
        if len(j["steps"]) > MAX_STEPS_PER_JOB:
            raise Rejected(f"{where} has more than {MAX_STEPS_PER_JOB} steps")
        _stamp_field(j["created"], f"{where} created", required=True)
        _stamp_field(j["started"], f"{where} started")
        _stamp_field(j["completed"], f"{where} completed")
        steps = []
        for k, raw_step in enumerate(j["steps"], start=1):
            s = _check_fields(raw_step, STEP_KINDS, f"{where} step {k}", free_text=("name",))
            _stamp_field(s["started"], f"{where} step {s['number']} started")
            _stamp_field(s["completed"], f"{where} step {s['number']} completed")
            steps.append(Step(s["number"], s["name"], s["conclusion"], s["started"], s["completed"]))
        jobs.append(Job(j["id"], j["name"], j["conclusion"], j["created"], j["started"], j["completed"], tuple(steps)))
    booked = BookedJobs(m, tuple(jobs))
    booked.gate()
    return booked


@dataclass
class JobScan:
    path: str  # <repo>/<run_id>/jobs.json
    status: str  # booked, already, empty (the run has no jobs), rejected
    jobs: BookedJobs | None = None
    reason: str = ""


def _scan_jobs(root: str, manifests: list, jobs_files: dict[tuple[str, str], str], booked_jobs: set[str],
               found: Scanned) -> None:
    """One JobScan per jobs.json, in the order of the runs' `started`. A run whose evidence is in jobs.csv is not read."""
    files_read = bytes_read = 0
    seen = set()
    for _, repo, run_id, manifest_path, _artifacts, m, _why in manifests:
        path = jobs_files.get((repo, run_id))
        if path is None:
            continue
        seen.add((repo, run_id))
        if m is None:
            found.jobs.append(JobScan(path, "rejected", reason="its manifest.json is rejected, so its jobs are not read"
                                      if manifest_path else f"no {MANIFEST} in its run folder"))
        elif m.evidence(m.run_attempt) in booked_jobs:
            found.jobs.append(JobScan(path, "already", reason="already booked"))
        else:
            try:
                size = os.lstat(os.path.join(root, path)).st_size
            except OSError:
                size = 0
            if files_read >= MAX_FILES or bytes_read + size > MAX_INGEST_BYTES:
                found.unread.append((f"{repo}/{run_id}", f"{MAX_FILES}-file or {_size(MAX_INGEST_BYTES)} cap on jobs"))
                continue
            files_read += 1
            bytes_read += size
            try:
                booked = read_jobs_file(os.path.join(root, path), m)
                found.jobs.append(JobScan(path, "booked", booked) if booked.jobs else JobScan(path, "empty", reason="no jobs"))
            except Rejected as e:
                found.jobs.append(JobScan(path, "rejected", reason=str(e)))
    found.jobs.extend(JobScan(path, "rejected", reason=f"no {MANIFEST} in its run folder")
                      for key, path in jobs_files.items() if key not in seen)
    found.jobs.sort(key=lambda s: s.path)


def plan_jobs(books: Books, scans: list[JobScan]) -> dict[str, bytes | None]:
    """jobs.csv and steps.csv after booking the new runs' jobs: rows only at the end, jobs by (created, evidence,
    job_id) and steps by (their job's created, evidence, job_id, number). Empty when there is nothing to book."""
    entries = sorted(((cells["created"], cells["evidence"], int(cells["job_id"]), cells, steps)
                      for s in scans if s.status == "booked" for cells, steps in s.jobs.entries()), key=lambda e: e[:3])
    if not entries:
        return {}
    jobs_text = "".join(_csv_line(cells[k] for k in JOBS_SCHEMA) for *_, cells, _ in entries)
    steps_text = "".join(_csv_line(c[k] for k in STEPS_SCHEMA) for *_, steps in entries for c in steps)
    return {JOBS: _appended(books.tables[JOBS].data, jobs_text), STEPS: _appended(books.tables[STEPS].data, steps_text)}


def jobs_booked_evidence(books: Books) -> set[str] | None:
    """The evidence links in jobs.csv, or None when the job books are not adopted."""
    return {r.cells["evidence"] for r in books.tables[JOBS].rows} if adopted(books) else None


# ---------------------------------------------------------------------------
# ingest, visibility: repo.json into books/repos.csv
# ---------------------------------------------------------------------------
#
# Only when books/repos.csv exists. repo.json is what `fetch` wrote after asking GitHub about the repo; it is read as strictly
# as a manifest. A row is added only when the visibility differs from the repo's latest row (or it has none), so every
# row is a change, and only after the file's last row in (seen, repo) order, so the file stays sorted and append only.

REPO_FILE_KINDS = {"v": int, "repo": str, "github": str, "visibility": str, "seen": str}


@dataclass
class RepoScan:
    path: str  # <repo>/repo.json
    status: str  # booked, unchanged, rejected
    row: RepoRow | None = None
    previous: str | None = None  # the repo's latest booked visibility, None when it has no row yet
    reason: str = ""


def read_repo_file(path: str, folder_repo: str, watched: dict[str, tuple[str, str]]) -> RepoRow:
    obj = _check_fields(_load_json(_read_file(path, MAX_MANIFEST_BYTES), "repo.json"), REPO_FILE_KINDS, "repo.json")
    if obj["v"] != RECORD_VERSION:
        raise Rejected(f"repo.json v must be {RECORD_VERSION}, got {_show(obj['v'])}")
    if obj["repo"] != folder_repo:
        raise Rejected(f"repo {printable(obj['repo'])} is not in folder {printable(folder_repo)}")
    if folder_repo not in watched:
        raise Rejected(f"repo {printable(folder_repo)} is not on the watch list")
    github = watched[folder_repo][0]
    if obj["github"].lower() != github.lower():
        raise Rejected(f"github {printable(obj['github'])} is not {printable(github)}, the watch list's")
    cells = _cells(REPOS_SCHEMA, seen=obj["seen"], repo=folder_repo, github=github, visibility=obj["visibility"])
    _fail_if(rule_messages(REPOS_RULES, cells))
    return RepoRow(*(cells[k] for k in REPOS_SCHEMA))


def scan_repo_files(root: str, watched: dict[str, tuple[str, str]], books: Books) -> list[RepoScan]:
    """One RepoScan per <repo>/repo.json directly under root, by folder name. A linked folder is not entered."""
    history = visibility_history(books)
    last = max(((r.seen, r.repo) for rows in history.values() for r in rows), default=None)
    try:
        names = sorted(os.listdir(root))
    except OSError as e:
        return [RepoScan(".", "rejected", reason=f"cannot list the fetch folder ({e.strerror})")]
    scans = []
    for name in names:
        folder = os.path.join(root, name)
        path = os.path.join(folder, REPO_FILE)
        if os.path.islink(folder) or not os.path.isdir(folder) or not os.path.lexists(path):
            continue
        rel = f"{name}/{REPO_FILE}"
        try:
            row = read_repo_file(path, name, watched)
        except Rejected as e:
            scans.append(RepoScan(rel, "rejected", reason=str(e)))
            continue
        rows = history.get(row.repo, [])
        previous = rows[-1].visibility if rows else None
        if previous == row.visibility:
            scans.append(RepoScan(rel, "unchanged", row, previous))
        elif rows and row.seen <= rows[-1].seen and row.visibility in ("private", "internal"):
            # it cannot be appended in order, and dropping it would lose that the repo was private
            scans.append(RepoScan(rel, "rejected", reason=f"GitHub answered {row.visibility} at {row.seen}, before the latest row ({previous}, {rows[-1].seen}); fetch again"))
        elif rows and row.seen <= rows[-1].seen:  # an older answer than one already booked: nothing new
            scans.append(RepoScan(rel, "unchanged", rows[-1], previous))
        elif last is not None and (row.seen, row.repo) <= last:
            scans.append(RepoScan(rel, "rejected", reason=f"seen {row.seen} is not after the latest row of {REPOS} ({last[0]}); fetch again"))
        else:
            scans.append(RepoScan(rel, "booked", row, previous))
    return scans


def plan_repos(books: Books, scans: list[RepoScan]) -> dict[str, bytes | None]:
    rows = sorted((s.row for s in scans if s.status == "booked"), key=lambda r: (r.seen, r.repo))
    if not rows:
        return {}
    return {REPOS: _appended(books.tables[REPOS].data, "".join(_csv_line(r) for r in rows))}


def _print_visibility(scans: list[RepoScan], dry_run: bool) -> None:
    for s in scans:
        name = _show(s.path, 200) if not s.path.isprintable() else s.path
        if s.status == "rejected":
            print(f"rejected: {name}: {s.reason}")
        elif s.status == "unchanged":
            print(f"visibility {s.row.repo}: unchanged ({s.row.visibility})")
        else:
            print(f"{'would book' if dry_run else 'booked'} visibility {s.row.repo}: {s.row.visibility}")
            if s.previous is not None:
                print(f"visibility {s.row.repo} changed: {s.previous} -> {s.row.visibility}")


def _repo_scan_json(scan: RepoScan) -> dict:
    out = {"path": scan.path, "status": scan.status}
    if scan.reason:
        out["reason"] = scan.reason
    if scan.row is not None:
        out["visibility"] = scan.row.visibility
        if scan.status == "booked" and scan.previous is not None:
            out["previous"] = scan.previous
    return out


# ---------------------------------------------------------------------------
# ingest, volume: volume/<week>.json into books/volume.csv
# ---------------------------------------------------------------------------
#
# Only when books/volume.csv exists, and not with --only. Each <repo>/volume/<week>.json is read as strictly as a
# manifest; its repo must be on the watch list with the same github, and the run link must be that repo's. A week already
# booked with the same commit and counts is `unchanged`; with anything else it is rejected, because a row is never edited.

VOLUME_FILE_KINDS = {"v": int, "repo": str, "github": str, "week": str, "sha": str, "rule": str, "evidence": str,
                     "test_files": int, "test_lines": int, "source_files": int, "source_lines": int}


@dataclass
class VolumeScan:
    path: str  # <repo>/volume/<week>.json
    status: str  # booked, unchanged, rejected
    row: VolumeRow | None = None
    reason: str = ""


def read_volume_file(path: str, folder_repo: str, file_week: str, watched: dict[str, tuple[str, str]]) -> VolumeRow:
    obj = _check_fields(_load_json(_read_file(path, MAX_MANIFEST_BYTES), "volume.json"), VOLUME_FILE_KINDS, "volume.json")
    if obj["v"] != RECORD_VERSION:
        raise Rejected(f"volume.json v must be {RECORD_VERSION}, got {_show(obj['v'])}")
    if obj["repo"] != folder_repo:
        raise Rejected(f"repo {printable(obj['repo'])} is not in folder {printable(folder_repo)}")
    if obj["week"] != file_week:
        raise Rejected(f"week {printable(obj['week'])} is not the file's name")
    if _is_iso_week(obj["week"]) and obj["week"] >= week_of(utc_stamp()):
        raise Rejected(f"week {obj['week']} is not over yet")
    if folder_repo not in watched:
        raise Rejected(f"repo {printable(folder_repo)} is not on the watch list")
    github = watched[folder_repo][0]
    if obj["github"].lower() != github.lower():
        raise Rejected(f"github {printable(obj['github'])} is not {printable(github)}, the watch list's")
    found = _LINK_SLUG.match(obj["evidence"])
    if not found or found[1].lower() != github.lower():
        raise Rejected(f"evidence {_show(obj['evidence'])} is not a run of {printable(github)}")
    cells = _cells(VOLUME_SCHEMA, **{k: obj[k] for k in VOLUME_SCHEMA if k != "repo"}, repo=folder_repo)
    _fail_if(rule_messages(VOLUME_ROW_RULES, cells))
    return VolumeRow(*(int(cells[k]) if k in VOLUME_COUNTS else cells[k] for k in VOLUME_SCHEMA))


def scan_volume_files(root: str, watched: dict[str, tuple[str, str]], books: Books) -> list[VolumeScan]:
    """One VolumeScan per <repo>/volume/*.json under root, in (repo, week) order. A linked folder is not entered."""
    booked = {(r.week, r.repo): r for r in _typed_rows(books, VOLUME, VolumeRow)}
    try:
        names = sorted(os.listdir(root))
    except OSError as e:
        return [VolumeScan(".", "rejected", reason=f"cannot list the fetch folder ({e.strerror})")]
    scans = []
    for name in names:
        folder = os.path.join(root, name, VOLUME_DIR)
        if os.path.islink(os.path.join(root, name)) or os.path.islink(folder) or not os.path.isdir(folder):
            continue
        try:
            files = sorted(os.listdir(folder))
        except OSError as e:
            scans.append(VolumeScan(f"{name}/{VOLUME_DIR}", "rejected", reason=f"cannot list the folder ({e.strerror})"))
            continue
        for file in files:
            if not file.endswith(".json"):
                continue
            rel = f"{name}/{VOLUME_DIR}/{file}"
            try:
                row = read_volume_file(os.path.join(folder, file), name, file[:-len(".json")], watched)
            except Rejected as e:
                scans.append(VolumeScan(rel, "rejected", reason=str(e)))
                continue
            old = booked.get((row.week, row.repo))
            if old is None:
                scans.append(VolumeScan(rel, "booked", row))
                booked[(row.week, row.repo)] = row
            elif old == row:
                scans.append(VolumeScan(rel, "unchanged", row))
            else:
                scans.append(VolumeScan(rel, "rejected", reason=f"{row.repo} {row.week} is booked already with "
                                                                f"{old.sha[:12]} ({old.rule}); a row is never changed"))
    return scans


def plan_volume(books: Books, scans: list[VolumeScan]) -> dict[str, bytes | None]:
    rows = [s.row for s in scans if s.status == "booked"]
    if not rows:
        return {}
    return {VOLUME: _appended(books.tables[VOLUME].data, "".join(_csv_line(r) for r in rows))}


def _print_volume(scans: list[VolumeScan], dry_run: bool) -> None:
    for s in scans:
        name = _show(s.path, 200) if not s.path.isprintable() else s.path
        if s.status == "rejected":
            print(f"rejected: {name}: {s.reason}")
        elif s.status == "unchanged":
            print(f"volume {s.row.repo} {s.row.week}: already booked")
        else:
            print(f"{'would book' if dry_run else 'booked'} volume {s.row.repo} {s.row.week}: test {s.row.test_lines} lines, "
                  f"source {s.row.source_lines} lines")


def _volume_scan_json(scan: VolumeScan) -> dict:
    out = {"path": scan.path, "status": scan.status}
    if scan.reason:
        out["reason"] = scan.reason
    if scan.row is not None:
        out.update(week=scan.row.week, sha=scan.row.sha)
    return out


PULL_FILE_KINDS = {"v": int, "repo": str, "github": str, "merged": str, "number": int, "opened": str, "ready": str,
                   "head_ci_done": str, "ci_ms": int, "wait_ms": int, "shas": int, "checks": int, "force_pushes": int, "evidence": str}


@dataclass
class PullScan:
    path: str
    status: str
    row: PullRow | None = None
    reason: str = ""


def read_pull_file(path: str, folder_repo: str, file_number: str, watched: dict[str, tuple[str, str]]) -> PullRow:
    obj = _check_fields(_load_json(_read_file(path, MAX_MANIFEST_BYTES), "pulls.json"), PULL_FILE_KINDS, "pulls.json")
    if obj["v"] != RECORD_VERSION:
        raise Rejected(f"pulls.json v must be {RECORD_VERSION}, got {_show(obj['v'])}")
    if obj["repo"] != folder_repo:
        raise Rejected(f"repo {printable(obj['repo'])} is not in folder {printable(folder_repo)}")
    if str(obj["number"]) != file_number:
        raise Rejected(f"number {obj['number']} is not the file's name")
    if folder_repo not in watched:
        raise Rejected(f"repo {printable(folder_repo)} is not on the watch list")
    github = watched[folder_repo][0]
    if obj["github"].lower() != github.lower():
        raise Rejected(f"github {printable(obj['github'])} is not {printable(github)}, the watch list's")
    found = _PULL_LINK.fullmatch(obj["evidence"])
    if not found or found[1].lower() != github.lower() or found[2] != file_number:
        raise Rejected(f"evidence {_show(obj['evidence'])} is not pull request {file_number} of {printable(github)}")
    cells = _cells(PULLS_SCHEMA, **{k: obj[k] for k in PULLS_SCHEMA if k != "repo"}, repo=folder_repo)
    _fail_if(rule_messages(PULL_ROW_RULES, cells))
    return PullRow(*(int(cells[k]) if k in PULL_COUNTS or k == "number" else cells[k] for k in PULLS_SCHEMA))


def scan_pull_files(root: str, watched: dict[str, tuple[str, str]], books: Books) -> list[PullScan]:
    """One PullScan per <repo>/pulls/*.json under root, in (repo, file name) order. A linked folder is not entered."""
    booked = {(r.repo, r.number): r for r in _typed_rows(books, PULLS, PullRow)}
    try:
        names = sorted(os.listdir(root))
    except OSError as e:
        return [PullScan(".", "rejected", reason=f"cannot list the fetch folder ({e.strerror})")]
    scans = []
    for name in names:
        folder = os.path.join(root, name, PULLS_DIR)
        if os.path.islink(os.path.join(root, name)) or os.path.islink(folder) or not os.path.isdir(folder):
            continue
        try:
            files = sorted(os.listdir(folder))
        except OSError as e:
            scans.append(PullScan(f"{name}/{PULLS_DIR}", "rejected", reason=f"cannot list the folder ({e.strerror})"))
            continue
        for file in files:
            if not file.endswith(".json"):
                continue
            rel = f"{name}/{PULLS_DIR}/{file}"
            try:
                row = read_pull_file(os.path.join(folder, file), name, file[:-len(".json")], watched)
            except Rejected as e:
                scans.append(PullScan(rel, "rejected", reason=str(e)))
                continue
            old = booked.get((row.repo, row.number))
            if old is None:
                scans.append(PullScan(rel, "booked", row))
                booked[(row.repo, row.number)] = row
            elif old == row:
                scans.append(PullScan(rel, "unchanged", row))
            else:
                scans.append(PullScan(rel, "rejected", reason=f"{row.repo} pull request {row.number} is booked already with a different "
                                                              f"row; a row is never changed"))
    return scans


def plan_pulls(books: Books, scans: list[PullScan]) -> dict[str, bytes | None]:
    rows = sorted((s.row for s in scans if s.status == "booked"), key=lambda r: (r.merged, r.repo, r.number))
    if not rows:
        return {}
    return {PULLS: _appended(books.tables[PULLS].data, "".join(_csv_line(r) for r in rows))}


def _print_pulls(scans: list[PullScan], dry_run: bool) -> None:
    for s in scans:
        name = _show(s.path, 200) if not s.path.isprintable() else s.path
        if s.status == "rejected":
            print(f"rejected: {name}: {s.reason}")
        elif s.status == "unchanged":
            print(f"pull {s.row.repo} {s.row.number}: already booked")
        else:
            print(f"{'would book' if dry_run else 'booked'} pull {s.row.repo} {s.row.number}: merged {s.row.merged}, "
                  f"ci {s.row.ci_ms} ms, wait {s.row.wait_ms} ms")


def _pull_scan_json(scan: PullScan) -> dict:
    out = {"path": scan.path, "status": scan.status}
    if scan.reason:
        out["reason"] = scan.reason
    if scan.row is not None:
        out.update(number=scan.row.number, merged=scan.row.merged)
    return out


# ---------------------------------------------------------------------------
# audit-ci: what a repo's workflow files say about CI speed, read from the files and nothing else
# ---------------------------------------------------------------------------
#
# `audit-ci REPO_DIR` is read-only: it opens `.github/workflows/*.yml|*.yaml` for reading and prints. It never follows a symlink,
# reads at most MAX_WORKFLOW_BYTES per file and MAX_WORKFLOWS files, and prints text that a pull request controls only after
# `_audit_text` (no control characters, MAX_CELL characters at most). Python has no YAML reader, so `read_workflow_yaml` reads
# the block-style subset workflows use and refuses (WorkflowUnreadable) whatever it cannot read exactly: it returns what PyYAML's
# BaseLoader returns (dict, list and str only) or it raises.

AUDIT_VERSION = 1
MAX_WORKFLOW_BYTES = 1 << 20
MAX_WORKFLOWS = 200
MAX_YAML_DEPTH = 40
MAX_YAML_KEY = 1000  # PyYAML refuses a simple key longer than 1024
MAX_MATRIX_COMBINATIONS = 10 ** 9  # a product above this is reported as "unknown"
SELECTION_PROOF = "not checked"  # no convention exists yet for where a path filter's proof lives
WORKFLOWS_DIR = ".github/workflows"


class WorkflowUnreadable(Exception):
    """A workflow this command will not read, and why (`line N: why` when the reader refused a line)."""


class _Line(NamedTuple):
    indent: int
    text: str  # the line after its indentation, comment included
    no: int


# Every character PyYAML accepts, minus the ones this reader refuses: tab, carriage return, NEL, line and paragraph separators, BOM.
_BAD_YAML_CHAR = re.compile("[^\n\x20-\x7e\xa0-‧‪-퟿-﻾＀-�\U00010000-\U0010ffff]")
_PLAIN_KEY = re.compile(r"[A-Za-z0-9_$./][A-Za-z0-9_ $./=+()@{}<>~^;-]*")
_BLOCK_HEADER = re.compile(r"([|>])([+-]?)(?: *| +#.*)")
_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ",
            '"': '"', "/": "/", "\\": "\\"}


def _refuse(no: int, why: str) -> WorkflowUnreadable:
    return WorkflowUnreadable(f"line {no}: {why}")


def _is_dash(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _skip_spaces(text: str, i: int) -> int:
    while i < len(text) and text[i] == " ":
        i += 1
    return i


def _block_scalar(raw: list[str], start: int, parent: int, folded: bool, chomp: str, no: int) -> tuple[str, int]:
    """A `|` or `>` body that starts at raw[start], where `parent` is the indent of the collection it sits in. This is PyYAML's
    scan_block_scalar line by line: `raw` is the text split on "\\n", so only raw[-1] has no break after it (an empty raw[-1] is
    the end of the file). Returns the text and the index of the first line that is not part of it."""
    last = len(raw) - 1
    min_indent = max(parent + 1, 1)
    k, widest, breaks = start, 0, []
    while k <= last and raw[k].strip(" ") == "":
        widest = max(widest, len(raw[k]))
        if k < last:
            breaks.append("\n")
        k += 1
    chunks: list[str] = []
    line_break = ""
    if k <= last and _spaces(raw[k]) >= min_indent:
        indent = _spaces(raw[k])
        if widest > indent:
            raise _refuse(no, "a blank line before the block scalar's text is indented deeper than the text")
        while True:
            chunks.extend(breaks)
            text = raw[k][indent:]
            chunks.append(text)
            line_break = "\n" if k < last else ""
            k += 1
            breaks = []
            while k <= last and raw[k].strip(" ") == "" and len(raw[k]) <= indent:
                if k < last:
                    breaks.append("\n")
                k += 1
            if k > last or _spaces(raw[k]) < indent:
                break
            if folded and line_break == "\n" and text[0] not in " \t" and raw[k][indent] not in " \t":
                if not breaks:
                    chunks.append(" ")
            else:
                chunks.append(line_break)
    if chomp != "-":
        chunks.append(line_break)
    if chomp == "+":
        chunks.extend(breaks)
    return "".join(chunks), k


class _YamlReader:
    """Block-style YAML, one document, read line by line. Anything outside the subset raises WorkflowUnreadable."""

    def __init__(self, text: str) -> None:
        self.raw = text.split("\n")
        self.pos = 0
        self.held: _Line | None = None
        self.depth = 0

    def _scan(self) -> _Line | None:
        while self.pos < len(self.raw):
            line = self.raw[self.pos]
            self.pos += 1
            text = line.lstrip(" ")
            if text == "" or text[0] == "#":
                continue
            if line.startswith(("---", "...")):
                raise _refuse(self.pos, "a document marker (this reader reads one document)")
            if line.startswith("%"):
                raise _refuse(self.pos, "a directive")
            return _Line(len(line) - len(text), text, self.pos)
        return None

    def peek(self) -> _Line | None:
        if self.held is None:
            self.held = self._scan()
        return self.held

    def take(self) -> _Line | None:
        line = self.peek()
        self.held = None
        return line

    def enter(self, no: int) -> None:
        self.depth += 1
        if self.depth > MAX_YAML_DEPTH:
            raise _refuse(no, f"nesting deeper than {MAX_YAML_DEPTH} levels")

    def node(self) -> dict | list:
        line = self.peek()
        assert line is not None
        return self.seq(line.indent) if _is_dash(line.text) else self.map(line.indent)

    def child(self, parent: int, same_indent_list: bool) -> dict | list | str:
        line = self.peek()
        if line is None:
            return ""
        if line.indent > parent:
            return self.node()
        if same_indent_list and line.indent == parent and _is_dash(line.text):
            return self.seq(parent)
        return ""

    def map(self, indent: int) -> dict:
        out: dict = {}
        first = self.peek()
        assert first is not None
        self.enter(first.no)
        while (line := self.peek()) is not None and line.indent == indent and not _is_dash(line.text):
            self.take()
            split = self.key_of(line.text, line.no)
            if split is None:
                raise _refuse(line.no, "not a `key: value` line this reader reads")
            key, rest = split
            if key in out:
                raise _refuse(line.no, f"the key {_show(key)} appears twice")
            out[key] = self.value(rest, indent, line.no)
        self.depth -= 1
        self.no_deeper(indent)
        return out

    def seq(self, indent: int) -> list:
        out: list = []
        first = self.peek()
        assert first is not None
        self.enter(first.no)
        while (line := self.peek()) is not None and line.indent == indent and _is_dash(line.text):
            self.take()
            body = line.text[1:]
            rest = body.lstrip(" ")
            inner = indent + 1 + len(body) - len(rest)
            if rest == "" or rest[0] == "#":
                out.append(self.child(indent, same_indent_list=False))
            elif _is_dash(rest):
                raise _refuse(line.no, "a list inside a list on one line")
            elif self.key_of(rest, line.no) is not None:
                self.held = _Line(inner, rest, line.no)
                out.append(self.map(inner))
            else:
                out.append(self.value(rest, indent, line.no))
        self.depth -= 1
        self.no_deeper(indent)
        return out

    def no_deeper(self, indent: int) -> None:
        line = self.peek()
        if line is not None and line.indent > indent:
            raise _refuse(line.no, "indentation that continues nothing (a value on more than one line is not read)")

    def key_of(self, text: str, no: int) -> tuple[str, str] | None:
        """`key: rest` at the start of text as (key, rest), or None when text is not a mapping entry."""
        if text[0] in "\"'":
            key, end = self.quoted(text, 0, no)
            after = text[end:].lstrip(" ")
            if after[:1] != ":" or after[1:2] not in ("", " "):
                return None
            if len(text) - len(after) > MAX_YAML_KEY:  # PyYAML measures from the key's start to its colon, spaces included
                raise _refuse(no, "a key longer than PyYAML reads")
            return key, after[1:].lstrip(" ")
        colon = text.find(":")
        if colon < 0 or text[colon + 1:colon + 2] not in ("", " "):
            return None
        key = text[:colon].rstrip(" ")
        if _PLAIN_KEY.fullmatch(key) is None:
            return None
        if colon > MAX_YAML_KEY:
            raise _refuse(no, "a key longer than PyYAML reads")
        return key, text[colon + 1:].lstrip(" ")

    def value(self, rest: str, parent: int, no: int) -> dict | list | str:
        if rest == "" or rest[0] == "#":
            return self.child(parent, same_indent_list=True)
        first = rest[0]
        if first in "|>":
            header = _BLOCK_HEADER.fullmatch(rest)
            if header is None:
                raise _refuse(no, "a block scalar header with an indentation indicator or other text")
            scalar, self.pos = _block_scalar(self.raw, self.pos, parent, first == ">", header.group(2), no)
            return scalar
        if first in "\"'":
            scalar, end = self.quoted(rest, 0, no)
            self.tail(rest[end:], no)
        elif first == "[":
            scalar = self.flow_list(rest, no)
        else:
            scalar = self.plain(rest, no)
        self.no_deeper(parent)
        return scalar

    def tail(self, tail: str, no: int) -> None:
        after = tail.lstrip(" ")
        if after != "" and not (after[0] == "#" and tail[0] == " "):
            raise _refuse(no, "text after a quoted value or a list")

    def plain(self, rest: str, no: int) -> str:
        cut = rest.find(" #")
        text = (rest if cut < 0 else rest[:cut]).rstrip(" ")
        first = text[0]
        if first in "&*!|>%@`,]}{[#" or (first in "-?:" and (len(text) == 1 or text[1] == " ")):
            raise _refuse(no, f"{first!r} starts a form this reader does not read (anchor, alias, tag, flow map or reserved)")
        if ": " in text or text.endswith(":"):
            raise _refuse(no, "a colon followed by a space inside a plain value (PyYAML refuses it too)")
        return text

    def quoted(self, text: str, start: int, no: int) -> tuple[str, int]:
        quote, i, out = text[start], start + 1, []
        while i < len(text):
            c = text[i]
            if c == quote:
                if quote == "'" and text[i + 1:i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), i + 1
            if c == "\\" and quote == '"':
                escape = _ESCAPES.get(text[i + 1:i + 2])
                if escape is None:
                    raise _refuse(no, "an escape this reader does not read")
                out.append(escape)
                i += 2
                continue
            out.append(c)
            i += 1
        raise _refuse(no, "a quoted value that does not end on its line")

    def flow_list(self, text: str, no: int) -> list[str]:
        items: list[str] = []
        i = 1
        while True:
            i = _skip_spaces(text, i)
            if i >= len(text):
                raise _refuse(no, "a list that does not end on its line")
            if text[i] == "]":
                break
            if text[i] in "\"'":
                item, i = self.quoted(text, i, no)
            else:
                end = i
                while end < len(text) and text[end] not in ",]":
                    end += 1
                if end >= len(text):
                    raise _refuse(no, "a list that does not end on its line")
                item = text[i:end].rstrip(" ")
                i = end
                if item == "" or item[0] in "&*!|>%@`#?:" or (item[0] == "-" and item[1:2] in ("", " ")) \
                        or any(c in item for c in "[]{}#?") or re.search(r":(\s|$)", item):
                    raise _refuse(no, "a list item this reader does not read (empty, nested, tagged or with a colon)")
            items.append(item)
            i = _skip_spaces(text, i)
            if i >= len(text):
                raise _refuse(no, "a list that does not end on its line")
            if text[i] == ",":
                i += 1
            elif text[i] != "]":
                raise _refuse(no, "text after a list item")
        self.tail(text[i + 1:], no)
        return items


def read_workflow_yaml(text: str) -> dict | list:
    """What PyYAML's BaseLoader returns for text (dict, list and str only), or WorkflowUnreadable. Never an approximation."""
    text = text.replace("\r\n", "\n")
    bad = _BAD_YAML_CHAR.search(text)
    if bad is not None:
        raise _refuse(text.count("\n", 0, bad.start()) + 1, f"{_show(bad.group())} (a tab, control character or unusual line break is not read)")
    reader = _YamlReader(text)
    first = reader.peek()
    if first is None:
        raise _refuse(1, "the file has no content")
    if first.indent != 0:
        raise _refuse(first.no, "the first line is indented")
    try:
        doc = reader.node()
    except RecursionError:
        raise _refuse(first.no, "nesting too deep") from None
    left = reader.peek()
    if left is not None:
        raise _refuse(left.no, "indentation or a list entry that belongs to nothing")
    return doc


class Concurrency(NamedTuple):
    set: bool
    cancel_in_progress: str  # "yes" | "no" | "pull_requests_only" | "unknown"
    raw: str | None  # the text of the expression when "unknown" or "pull_requests_only"


class Matrix(NamedTuple):
    axes: dict[str, int | str]  # the length of each list axis, "unknown" for an axis that is an expression
    include: int
    exclude: int
    combinations: int | str  # "unknown" unless every axis is a literal list and there is no include or exclude
    full_on_pull_request: str  # "yes" | "no" | "unknown"


class PathFilter(NamedTuple):
    trigger: str
    paths: list[str]
    paths_ignore: list[str]
    selection_proof: str


class JobFacts(NamedTuple):
    id: str
    reusable_workflow: bool
    timeout_minutes: int | str | None  # None when absent, "unknown", "not applicable" for a reusable workflow
    concurrency: Concurrency
    matrix: Matrix | None
    caching: list[str]
    steps: int


class WorkflowFacts(NamedTuple):
    path: str
    sha256: str | None
    unreadable: str | None  # why, or None when the file was read
    name: str | None
    triggers: list[str]
    on_pull_request: bool
    concurrency: Concurrency
    path_filters: list[PathFilter]
    jobs: list[JobFacts]


_NO_CONCURRENCY = Concurrency(False, "no", None)
_MATRIX_UNKNOWN = Matrix({}, 0, 0, "unknown", "unknown")
_EVENT_IS = r"github\.event_name\s*==\s*'(pull_request|pull_request_target)'"
_PR_ONLY = re.compile(rf"\s*{_EVENT_IS}\s*(?:\|\|\s*{_EVENT_IS}\s*)?")


def _audit_text(value: object) -> str:
    """Text from a workflow, safe to print: no control characters, at most MAX_CELL characters."""
    shown = printable(str(value))
    return shown if len(shown) <= MAX_CELL else shown[:MAX_CELL - 3] + "..."


def _is_pr_only(expression: str) -> bool:
    """True for a test of the event name against pull_request, alone or joined to pull_request_target. Spaces count only around
    `==` and `||`, and only single-quoted strings, which is all GitHub reads."""
    inner = re.fullmatch(r"\$\{\{(.*)\}\}", expression.strip(), re.S)
    match = _PR_ONLY.fullmatch(inner.group(1)) if inner else None
    return match is not None and "pull_request" in match.groups() and match.group(1) != match.group(2)


def _kind(value: object) -> str:
    return "(map)" if isinstance(value, dict) else "(list)"


def _concurrency(node: object) -> Concurrency:
    if node is None or node == "":
        return _NO_CONCURRENCY
    if not isinstance(node, dict):
        return Concurrency(True, "no", None) if isinstance(node, str) else Concurrency(True, "unknown", _kind(node))
    if "cancel-in-progress" not in node:
        return Concurrency(True, "no", None)
    value = node["cancel-in-progress"]
    if not isinstance(value, str):
        return Concurrency(True, "unknown", _kind(value))
    if value in ("true", "false"):
        return Concurrency(True, "yes" if value == "true" else "no", None)
    return Concurrency(True, "pull_requests_only" if _is_pr_only(value) else "unknown", _audit_text(value))


def _mentions_event(value: object) -> bool:
    if isinstance(value, str):
        return "github.event_name" in value
    if isinstance(value, list):
        return any(_mentions_event(v) for v in value)
    return isinstance(value, dict) and any(_mentions_event(v) for v in value.values())


def _matrix(job: dict, on_pull_request: bool, called: bool) -> Matrix | None:
    strategy = job.get("strategy")
    if isinstance(strategy, str) and strategy != "":
        return _MATRIX_UNKNOWN
    if not isinstance(strategy, dict) or "matrix" not in strategy:
        return None
    matrix = strategy["matrix"]
    if not isinstance(matrix, dict):
        return _MATRIX_UNKNOWN
    axes: dict[str, int | str] = {}
    conditional = job.get("if") not in (None, "")  # any condition may skip the job on a pull request; none is evaluated here
    mentions = False
    for key, value in matrix.items():
        if key in ("include", "exclude"):
            continue
        if isinstance(value, list):
            axes[_audit_text(key)] = len(value)
        else:
            axes[_audit_text(key)] = "unknown"
        mentions = mentions or _mentions_event(value)
    combinations: int | str = "unknown"
    if axes and "include" not in matrix and "exclude" not in matrix and all(type(n) is int for n in axes.values()):
        combinations = 1
        for n in axes.values():
            combinations *= n
            if combinations > MAX_MATRIX_COMBINATIONS:
                combinations = "unknown"
                break
    include, exclude = matrix.get("include"), matrix.get("exclude")
    # A called workflow runs in its caller's event, so it may run on pull requests.
    full = "unknown" if combinations == "unknown" or mentions or conditional or (called and not on_pull_request) else ("yes" if on_pull_request else "no")
    return Matrix(axes, len(include) if isinstance(include, list) else 0, len(exclude) if isinstance(exclude, list) else 0, combinations, full)


def _caching(steps: list) -> list[str]:
    found: set[str] = set()
    for step in steps:
        uses = step.get("uses") if isinstance(step, dict) else None
        if not isinstance(uses, str):
            continue
        action = uses.split("@", 1)[0].strip().lower()
        options = step.get("with")
        options = options if isinstance(options, dict) else {}
        cache = options.get("cache")
        if action in ("actions/cache", "actions/cache/restore"):
            found.add("actions/cache")
        elif action.startswith("actions/setup-") and isinstance(cache, str) and cache.strip() not in ("", "false"):
            found.add(f"{action} cache: {'expression' if '${{' in cache else cache.strip()}")
        elif action == "astral-sh/setup-uv" and options.get("enable-cache") == "true":
            found.add("astral-sh/setup-uv cache")
    return sorted(_audit_text(name) for name in found)


def _timeout_minutes(job: dict, reusable: bool) -> int | str | None:
    value = job.get("timeout-minutes")
    if reusable:
        return "not applicable"
    if value is None:
        return None
    return int(value) if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value) else "unknown"


def _job_facts(job_id: str, job: dict, on_pull_request: bool, called: bool) -> JobFacts:
    reusable = isinstance(job.get("uses"), str)
    steps = job.get("steps")
    steps = steps if isinstance(steps, list) else []
    return JobFacts(_audit_text(job_id), reusable, _timeout_minutes(job, reusable), _concurrency(job.get("concurrency")),
                    _matrix(job, on_pull_request, called), _caching(steps), len(steps))


def _strings(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return [_audit_text(v) for v in values if isinstance(v, str)]


def _workflow_facts(path: str, sha256: str, doc: object) -> WorkflowFacts:
    if not isinstance(doc, dict):
        raise WorkflowUnreadable("the top level is not a map")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise WorkflowUnreadable("there is no jobs map")
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            raise WorkflowUnreadable(f"the job {_show(job_id)} is not a map")
    on = doc.get("on")
    if isinstance(on, list) and not all(isinstance(t, str) for t in on):
        raise WorkflowUnreadable("the on list has an entry that is not an event name")
    triggers = sorted({_audit_text(t) for t in (on if isinstance(on, (list, dict)) else [on] if isinstance(on, str) and on != "" else [])})
    on_pull_request = "pull_request" in triggers or "pull_request_target" in triggers
    filters = [PathFilter(_audit_text(t), _strings(v.get("paths")), _strings(v.get("paths-ignore")), SELECTION_PROOF)
               for t, v in sorted(on.items()) if isinstance(v, dict) and ("paths" in v or "paths-ignore" in v)] if isinstance(on, dict) else []
    name = doc.get("name")
    return WorkflowFacts(path, sha256, None, _audit_text(name) if isinstance(name, str) and name != "" else None, triggers,
                         on_pull_request, _concurrency(doc.get("concurrency")), filters,
                         [_job_facts(job_id, job, on_pull_request, "workflow_call" in triggers) for job_id, job in jobs.items()])


def _unreadable(path: str, sha256: str | None, why: str) -> WorkflowFacts:
    return WorkflowFacts(_audit_text(path), sha256, _audit_text(why), None, [], False, _NO_CONCURRENCY, [], [])


def _read_regular_file(path: str) -> tuple[bytes | None, str]:
    """The bytes of a regular file that is not a symlink and at most MAX_WORKFLOW_BYTES (else None and why not)."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None, "is a symbolic link, which this command does not follow" if os.path.islink(path) else "is not a regular file"
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        return None, "is a symbolic link, which this command does not follow" if e.errno == errno.ELOOP else f"could not be read: {e.strerror}"
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            return None, "is not a regular file"
        data = handle.read(MAX_WORKFLOW_BYTES + 1) if info.st_size <= MAX_WORKFLOW_BYTES else b""
    return (data, "") if info.st_size <= MAX_WORKFLOW_BYTES and len(data) <= MAX_WORKFLOW_BYTES else (None, f"is larger than {MAX_WORKFLOW_BYTES} bytes")


def _audit_file(path: str, rel: str) -> WorkflowFacts:
    data, why = _read_regular_file(path)
    if data is None:
        return _unreadable(rel, None, why)
    sha256 = hashlib.sha256(data).hexdigest()
    try:
        return _workflow_facts(_audit_text(rel), sha256, read_workflow_yaml(data.decode("utf-8")))
    except UnicodeDecodeError:
        return _unreadable(rel, sha256, "is not UTF-8 text")
    except WorkflowUnreadable as e:
        return _unreadable(rel, sha256, str(e))


class AuditLimit(Exception):
    """The repo has more workflow files than audit-ci reads."""


def audit_workflows(repo_dir: str) -> list[WorkflowFacts]:
    """The facts of every workflow file under REPO_DIR/.github/workflows, sorted by path. Reads nothing else, writes nothing."""
    folder = repo_dir
    for part, rel in ((".github", ".github"), ("workflows", WORKFLOWS_DIR)):
        folder = os.path.join(folder, part)
        try:
            info = os.lstat(folder)
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError as e:
            return [_unreadable(rel, None, f"could not be inspected: {e.strerror}")]
        if stat.S_ISLNK(info.st_mode):
            return [_unreadable(rel, None, "is a symbolic link, which this command does not follow")]
        if not stat.S_ISDIR(info.st_mode):
            return [] if part == ".github" else [_unreadable(rel, None, "is not a directory")]
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith((".yml", ".yaml")))
    except OSError as e:
        return [_unreadable(WORKFLOWS_DIR, None, f"could not be listed: {e.strerror}")]
    if len(names) > MAX_WORKFLOWS:
        raise AuditLimit(f"{len(names)} workflow files (audit-ci reads at most {MAX_WORKFLOWS})")
    return [_audit_file(os.path.join(folder, n), f"{WORKFLOWS_DIR}/{n}") for n in names]


def _facts_json(value: object) -> object:
    if isinstance(value, tuple):
        return {k: _facts_json(v) for k, v in zip(value._fields, value)}  # type: ignore[attr-defined]
    if isinstance(value, list):
        return [_facts_json(v) for v in value]
    return value


def audit_report(workflows: list[WorkflowFacts]) -> dict:
    readable = [w for w in workflows if w.unreadable is None]
    jobs = [j for w in readable for j in w.jobs]
    without_cancel = [w for w in readable if w.on_pull_request and w.concurrency.cancel_in_progress == "no"
                      and any(j.concurrency.cancel_in_progress == "no" for j in w.jobs)]
    entries = []
    for w in workflows:
        entry = {"path": w.path, "sha256": w.sha256, "readable": w.unreadable is None}
        if w.unreadable is not None:
            entry["unreadable"] = w.unreadable
        else:
            entry.update({k: v for k, v in _facts_json(w).items() if k not in entry and k != "unreadable"})  # type: ignore[attr-defined]
        entries.append(entry)
    return {"v": AUDIT_VERSION, "workflows": entries, "summary": {
        "workflows": len(workflows), "unreadable": len(workflows) - len(readable), "jobs": len(jobs),
        "jobs_without_timeout": sum(j.timeout_minutes is None for j in jobs),
        "pull_request_workflows_without_cancel": len(without_cancel),
        "jobs_with_matrix": sum(j.matrix is not None for j in jobs), "jobs_with_caching": sum(bool(j.caching) for j in jobs),
        "path_filters": sum(len(w.path_filters) for w in readable)}}


def _concurrency_text(c: Concurrency) -> str:
    return "none" if not c.set else f"cancel-in-progress {c.cancel_in_progress}" + (f" ({c.raw})" if c.raw is not None else "")


def _matrix_text(m: Matrix | None) -> str:
    if m is None:
        return "none"
    axes = " x ".join(f"{k} {n}" for k, n in sorted(m.axes.items())) or "no axes"
    return f"{axes}, include {m.include}, exclude {m.exclude}, combinations {m.combinations}, full on pull requests {m.full_on_pull_request}"


def render_audit(workflows: list[WorkflowFacts], summary: dict) -> str:
    lines = [f"audit-ci: {summary['workflows']} workflows, {summary['unreadable']} unreadable"]
    for w in workflows:
        lines.append(printable(w.path) + (f" ({printable(w.name)})" if w.name else ""))
        if w.unreadable is not None:
            lines.append(f"  unreadable: {printable(w.unreadable)}")
            continue
        lines.append(f"  triggers: {', '.join(w.triggers) or 'none'}; pull requests: {'yes' if w.on_pull_request else 'no'}")
        lines.append(f"  concurrency: {_concurrency_text(w.concurrency)}")
        for f in w.path_filters:
            lines.append(f"  path filter on {f.trigger}: paths {f.paths}, paths-ignore {f.paths_ignore}, selection proof {f.selection_proof}")
        for j in w.jobs:
            timeout = "none" if j.timeout_minutes is None else j.timeout_minutes
            lines.append(f"  job {j.id}: timeout {timeout}{', reusable workflow' if j.reusable_workflow else ''}; "
                         f"concurrency {_concurrency_text(j.concurrency)}; matrix {_matrix_text(j.matrix)}; "
                         f"caching {', '.join(j.caching) or 'none'}; steps {j.steps}")
    lines.append("summary: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in summary.items()))
    return "\n".join(lines)


def cmd_audit_ci(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.repo_dir):
        print(f"quality.py: not a directory: {args.repo_dir}", file=sys.stderr)
        return 2
    try:
        workflows = audit_workflows(args.repo_dir)
    except AuditLimit as e:
        print(f"quality.py: {_audit_text(e)}", file=sys.stderr)
        return 1
    report = audit_report(workflows)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_audit(workflows, report["summary"]))
    return 1 if report["summary"]["unreadable"] else 0


# ---------------------------------------------------------------------------
# leak-check: text that is about to go public, held against what the books know about private repos
# ---------------------------------------------------------------------------
#
# `leak-check BOOKS_DIR FILE...` is read-only. A repo is private unless repos.csv says `public` in every row it has (private_repos).
# The strings the books hold about private repos are looked for in the files: run links and the repo's slug, commit shas,
# test ids, and job and step names that no public repo also has. Bare repo names and numbers are never looked for, and nothing
# that the books do not hold (workflow text, audit-ci output) can be found. A pass is not proof. Files are opened as audit-ci
# opens a workflow: no symlink is followed, nothing over MAX_WORKFLOW_BYTES (1 MB) is read.

LEAK_MAX_FILES = 2000
LEAK_VERSION = 1
MIN_LEAK_COMMIT = 8  # a shorter prefix names too many commits
MIN_LEAK_TEST_ID = 12
MIN_LEAK_NAME = 16  # a job or step name: `lint` and `Run tests` are in every repo
MIN_LEAK_REPO_NAME = 4  # a private repo's own name, matched as a whole word
MAX_GRAM = 20
_LINK_SLUG = re.compile(r"https://[^/\s]+/([^/\s]+/[^/\s]+)/(?:actions/runs/|commit/[0-9a-f]{40}#local-ci-|pull/[0-9])")
_OWNER, _NAME = r"([A-Za-z0-9][A-Za-z0-9-]{0,38})", r"([A-Za-z0-9_][A-Za-z0-9._-]{0,99})"
_BARE_SLUG = re.compile(rf"(?<![A-Za-z0-9_./-]){_OWNER}/{_NAME}")
_URL_SLUG = re.compile(rf"(?:api\.github\.com/repos/|raw\.githubusercontent\.com/|github\.com[/:]){_OWNER}/{_NAME}", re.I)
_PAGES_SLUG = re.compile(rf"(?<![A-Za-z0-9-]){_OWNER}\.github\.io/{_NAME}", re.I)
_COMMIT_TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{8,40}(?![0-9A-Za-z])")


class Needles:
    """Exact substrings (each with the kind it makes) to find in a text without trying every needle at every position.
    Needles are keyed by their first `k` characters (k: the shortest needle's length, at most MAX_GRAM); the text's own
    k-grams are intersected with the keys, and only where a key occurs are the lengths of the needles under it tried.
    Cost: one pass over the text plus the occurrences of keys, however many needles there are."""

    def __init__(self, needles: Iterable[tuple[str, str]]):
        kinds: dict[str, set[str]] = {}
        for needle, kind in needles:
            if needle:
                kinds.setdefault(needle, set()).add(kind)
        self.k = min(min(map(len, kinds), default=0), MAX_GRAM)
        self.table: dict[str, dict[int, dict[str, set[str]]]] = {}
        for needle, found in kinds.items():
            self.table.setdefault(needle[:self.k], {}).setdefault(len(needle), {})[needle] = found

    def find(self, text: str) -> Iterator[tuple[int, int, str]]:
        """(start, end, kind) of every needle in the text."""
        k = self.k
        if not self.table or len(text) < k:
            return
        for gram in {text[i:i + k] for i in range(len(text) - k + 1)} & self.table.keys():
            lengths = self.table[gram]
            at = text.find(gram)
            while at != -1:
                for n, group in lengths.items():
                    for kind in group.get(text[at:at + n], ()):
                        yield at, at + n, kind
                at = text.find(gram, at + 1)


@dataclass
class LeakStrings:
    """What the books hold about private repos, by the kind of match it makes."""
    private: int
    needles: Needles  # run links (kind link), test ids (test), job names (job) and step names (step)
    slugs: frozenset[str]  # OWNER/NAME, lower case
    commits: list[str]  # sorted full shas
    names: re.Pattern | None  # the private repos' own names as whole words, any case
    counts: dict[str, int]  # the strings checked, by links, commits, tests, jobs, steps, names


def leak_strings(books: Books) -> LeakStrings:
    private = private_repos(books)
    evidence: set[str] = set()
    slugs: set[str] = set()
    shas: set[str] = set()
    tests: set[str] = set()
    names: set[str] = set()
    jobs: dict[str, set[str]] = {"private": set(), "public": set()}
    steps: dict[str, set[str]] = {"private": set(), "public": set()}
    for rel, table in books.tables.items():
        if "repo" not in TABLE_SCHEMAS[rel]:
            continue
        for row in table.rows:
            c = row.cells
            side = "private" if c["repo"] in private else "public"
            if "job" in c:
                jobs[side].add(c["job"])
            if "step" in c:
                steps[side].add(c["step"])
            if side == "public":
                continue
            names.add(c["repo"].lower())
            if "evidence" in c:
                evidence.add(c["evidence"])
                found = _LINK_SLUG.match(c["evidence"])
                if found and _GITHUB.fullmatch(found[1]):
                    slugs.add(found[1].lower())
            if "github" in c:
                slugs.add(c["github"].lower())
            if "sha" in c:
                shas.add(c["sha"])
            if "test_id" in c and len(c["test_id"]) >= MIN_LEAK_TEST_ID:
                tests.add(c["test_id"])
    # a name a public repo also has says nothing about a private one; the public side counts jobs and steps together
    shared = jobs["public"] | steps["public"]
    own = lambda names: {n for n in names if len(n) >= MIN_LEAK_NAME and n != UNPRINTABLE and n not in shared}
    job_names, step_names = own(jobs["private"]), own(steps["private"])
    needles = Needles([(n, "link") for n in evidence] + [(n, "test") for n in tests] + [(n, "job") for n in job_names] + [(n, "step") for n in step_names])
    names = {n for n in names | {s.split("/", 1)[1] for s in slugs} if len(n) >= MIN_LEAK_REPO_NAME}
    # a whole word: `verify-NAME`, `NAME-extra`, `NAME.py` and a path part are other things; a sentence's full stop is fine
    word = re.compile(r"(?<![A-Za-z0-9_./-])(?:" + "|".join(map(re.escape, sorted(names, key=len, reverse=True))) + r")(?![A-Za-z0-9_/-])(?!\.[A-Za-z0-9])", re.I) if names else None
    counts = {"links": len(evidence) + len(slugs), "commits": len(shas), "tests": len(tests), "jobs": len(job_names), "steps": len(step_names),
              "names": len(names)}
    return LeakStrings(len(private), needles, frozenset(slugs), sorted(shas), word, counts)


def _slug_hits(text: str, pattern: re.Pattern, slugs: frozenset[str], cut_at_dots: bool) -> Iterator[tuple[int, int]]:
    for m in pattern.finditer(text):
        owner, name = m[1], m[2]
        ends = {len(name.rstrip("."))}  # a sentence's full stop is not part of the name
        if name.lower().endswith(".git"):
            ends.add(len(name) - 4)
        if cut_at_dots:
            ends |= {len(name)} | {i for i, ch in enumerate(name) if ch == "." and i > 0}  # .git
        for end in sorted(ends, reverse=True):
            if end and f"{owner}/{name[:end]}".lower() in slugs:
                yield (m.start() if cut_at_dots else m.start(1)), m.start(2) + end
                break


def leak_matches(text: str, leaks: LeakStrings) -> list[tuple[int, str, str]]:
    """(offset, kind, matched text) for every sensitive string in the text. A link inside a longer link is not reported again."""
    found: list[tuple[int, str, str]] = []
    spans = set(_slug_hits(text, _URL_SLUG, leaks.slugs, True)) | set(_slug_hits(text, _BARE_SLUG, leaks.slugs, False)) | set(_slug_hits(text, _PAGES_SLUG, leaks.slugs, True))
    for start, end, kind in leaks.needles.find(text):
        if kind == "link":
            spans.add((start, end))
        else:
            found.append((start, kind, text[start:end]))
    links = sorted(spans, key=lambda span: (span[0], -span[1]))
    reached = -1
    for start, end in links:
        if end > reached:
            found.append((start, "link", text[start:end]))
            reached = end
    if leaks.names is not None:
        found.extend((m.start(), "name", m[0]) for m in leaks.names.finditer(text))
    if leaks.commits:
        for m in _COMMIT_TOKEN.finditer(text):
            token = m[0].lower()
            at = bisect.bisect_left(leaks.commits, token)
            if at < len(leaks.commits) and leaks.commits[at].startswith(token):
                found.append((m.start(), "commit", m[0]))
    return found


def _read_leak_input(path: str) -> tuple[bytes | None, str]:
    if path != "-":
        return _read_regular_file(path)
    stdin = getattr(sys.stdin, "buffer", None)
    data = stdin.read(MAX_WORKFLOW_BYTES + 1) if stdin is not None else sys.stdin.read(MAX_WORKFLOW_BYTES + 1).encode("utf-8", "replace")
    return (data, "") if len(data) <= MAX_WORKFLOW_BYTES else (None, f"is larger than {MAX_WORKFLOW_BYTES} bytes")


def cmd_leak_check(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    if len(args.files) > LEAK_MAX_FILES:
        print(f"quality.py: {len(args.files)} files; leak-check reads at most {LEAK_MAX_FILES}", file=sys.stderr)
        return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; no leak-check against unchecked books")
        return 2
    if not books.tables[REPOS].present:
        print(f"quality.py: leak-check needs {REPOS}: visibility is not booked, so no repo can be called public (run fetch and ingest with it)",
              file=sys.stderr)
        return 2
    leaks = leak_strings(books)
    paths = list(dict.fromkeys(args.files))
    matches: set[tuple[str, int, str, str]] = set()
    unreadable: list[tuple[str, str]] = []
    for path in paths:
        data, why = _read_leak_input(path)
        if data is None:
            unreadable.append((_audit_text(path), _audit_text(why)))
            continue
        text = data.decode("utf-8", "replace")
        found = leak_matches(text, leaks)
        if not found:
            continue
        newlines = [m.start() for m in re.finditer("\n", text)]
        shown = _audit_text(path)
        matches.update((shown, bisect.bisect_left(newlines, start) + 1, kind, _audit_text(hit)) for start, kind, hit in found)
    ordered = sorted(matches)
    unreadable.sort()
    counts = leaks.counts
    if args.json:
        print(json.dumps({"v": LEAK_VERSION, "matches": [{"path": p, "line": n, "kind": k, "text": t} for p, n, k, t in ordered],
                          "files": len(paths), "private_repos": leaks.private, "strings": counts}, indent=2, sort_keys=True))
        for p, w in unreadable:  # the JSON shape has no place for them; the exit code is 1
            print(f"{p}: unreadable: {w}", file=sys.stderr)
    else:
        for p, n, k, t in ordered:
            print(f"{p}:{n}: {k}: {t}")
        for p, w in unreadable:
            print(f"{p}: unreadable: {w}")
        print(f"leak-check: {len(ordered)} matches in {len(paths)} files; checked against {leaks.private} private repos "
              f"({counts['links']} links, {counts['commits']} commits, {counts['tests']} tests, {counts['jobs']} job names, "
              f"{counts['steps']} step names, {counts['names']} repo names)")
    return 1 if ordered or unreadable else 0


# ---------------------------------------------------------------------------
# book-skills: skill use from this machine's agent transcripts into books/skill-uses.csv
# ---------------------------------------------------------------------------
#
# The transcripts are private conversations. This section reads them for structure only (which tool was
# called, with which skill name, how many results followed) and nothing it reads is printed or booked except a
# skill name held to _SKILL_NAME, a plugin name held to the same pattern, and counts.

# Where a tool keeps the skills it loads, relative to the home folder. A SKILL.md read from anywhere else is a
# checkout: someone editing the skill, not using it.
INSTALLED_ROOTS = (".claude/skills/", ".claude/plugins/", ".agents/skills/", ".cursor/skills/", ".cursor/skills-cursor/",
                   ".cursor/plugins/", ".local/share/agentfiles/", "Library/Application Support/Claude/")
_COMMAND = re.compile(r"<command-name>/([^<\s]+)</command-name>")
_SKILL_BASE = "Base directory for this skill:"
_VERSION_DIR = re.compile(r"[0-9]+\.[0-9].*|[0-9a-f]{12,}")
_CURSOR_READS = ("Read", "ReadFile")


class SkillUse(NamedTuple):
    """One invocation as a transcript shows it. `key` names it across copies of the same session and never
    reaches the books: the `use` cell is a hash of it."""
    day: date  # UTC
    skill: str
    plugin: str  # the namespace it was invoked or loaded under, "" when there is none
    tool: str
    how: str
    calls: int | None
    searches: int | None
    errors: int | None
    key: str
    no_origin: bool = False  # a slash command in a record with no `origin`: booked as typed, and counted
    tokens: tuple[int, int, int] | None = None


def _parts(record: dict, kind: str) -> list[dict]:
    content = record["message"].get("content")
    return [p for p in content if isinstance(p, dict) and p.get("type") == kind] if isinstance(content, list) else []


def _text_of(record: dict) -> str:
    content = record["message"].get("content")
    if isinstance(content, str):
        return content
    return "\n".join(p["text"] for p in _parts(record, "text") if isinstance(p.get("text"), str))


def _origin(record: dict) -> str | None:
    origin = record.get("origin")
    return origin.get("kind") if isinstance(origin, dict) and isinstance(origin.get("kind"), str) else None


def _split_name(name: str) -> tuple[str, str]:
    """('bstack', 'how') from 'bstack:how' or '/bstack:how'; ('', 'how') from 'how'."""
    plugin, _, skill = name.lstrip("/").rpartition(":")
    return plugin, skill


def skill_of_path(path: str) -> tuple[str, str]:
    """(plugin, skill) from a skill folder or its SKILL.md: .../<plugin>[/<version>]/skills/<skill>. The plugin is ""
    when the folder above `skills` is a dot folder or an opaque id, which name no plugin."""
    segments = [s for s in path.split("/") if s]
    if segments and segments[-1] == "SKILL.md":
        segments.pop()
    if not segments:
        return "", ""
    owners = segments[:-2][::-1] if len(segments) >= 2 and segments[-2] == "skills" else []
    if owners and _VERSION_DIR.fullmatch(owners[0]):
        owners = owners[1:]
    plugin = owners[0] if owners else ""
    return ("" if plugin.startswith((".", "plugin_")) else plugin), segments[-1]


def plugin_of_folder(folder: str) -> str:
    """The plugin a skill folder belongs to: from its path, else from where the path really leads (agentfiles links
    ~/.agents/skills/<skill> into the plugin's tree), else from the plugin manifest two folders up. "" when the
    folder is gone or belongs to no plugin."""
    for path in (folder, os.path.realpath(folder)):
        plugin = skill_of_path(path)[0]
        if plugin:
            return plugin
    try:
        with open(os.path.join(folder, "..", "..", ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            name = json.load(f).get("name")
    except (OSError, ValueError, AttributeError):
        return ""
    return name if isinstance(name, str) else ""


def _installed(path: str, home: str) -> bool:
    return path.startswith(home + "/") and path[len(home) + 1:].startswith(INSTALLED_ROOTS)


def names_skill(text: str, skill: str) -> bool:
    """The text names the skill: its name as a whole word, with a space allowed for a hyphen. A one-word name
    (`how`, `why`) is also an ordinary word, so it counts only as `/how`, `plugin:how`, `how skill` or `skill how`."""
    low = text.lower()
    pattern = r"(?<![a-z0-9_-])" + re.escape(skill.lower()).replace(r"\-", "[- ]") + r"(?![a-z0-9_-])"
    for m in re.finditer(pattern, low):
        if "-" in skill or low[max(m.start() - 1, 0):m.start()] in ("/", ":"):
            return True
        if re.search(r"\bskill\s*$", low[:m.start()]) or re.match(r"\s*skill\b", low[m.end():]):
            return True
    return False


def _records(path: str) -> list[dict]:
    """The user and assistant records of a Claude Code transcript. The other record types repeat their content."""
    records = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"user"' not in line and '"assistant"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("type") in ("user", "assistant") and isinstance(record.get("message"), dict):
                records.append(record)
    return records


def _record_day(record: dict) -> date | None:
    try:
        return datetime.fromisoformat(str(record.get("timestamp")).replace("Z", "+00:00")).astimezone(timezone.utc).date()
    except ValueError:
        return None


def _base_dir(record: dict, tool_id: str | None) -> str | None:
    """The folder a skill was loaded from, when this record is the load that follows a slash command (tool_id
    None) or the given Skill call."""
    if record["type"] != "user" or not record.get("isMeta") or record.get("sourceToolUseID") != tool_id:
        return None
    text = _text_of(record)
    return text.split("\n", 1)[0][len(_SKILL_BASE):].strip() if text.startswith(_SKILL_BASE) else None


_USAGE = ("input_tokens", "output_tokens", "cache_creation_input_tokens")


def _message_key(record: dict) -> str | None:
    """One model response is split over several assistant records that repeat its id and its usage."""
    key = record["message"].get("id")
    return key if isinstance(key, str) else record.get("uuid") if isinstance(record.get("uuid"), str) else None


def _usage(record: dict) -> tuple[int, int, int]:
    usage = record["message"].get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return tuple(v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0 for v in (usage.get(k) for k in _USAGE))


def _window(records: list[dict], start: int, chain: str, own_id: str | None,
            tool_names: dict[str, str]) -> tuple[int, int, int, tuple[int, int, int]]:
    """(calls, searches, errors, tokens) over what follows a load in the same chain, up to the next turn a human
    typed or SKILL_WINDOW tool results, whichever comes first. The counts are over the tool results; the load's own
    result is not counted. The tokens are the usage of the model responses in the same span, each response once and
    the one that made the load left out: the cost of the use, the way a session's cost after a call minus before it
    measures it."""
    calls = searches = errors = 0
    tokens = [0, 0, 0]
    seen = {_message_key(records[start])} if records[start]["type"] == "assistant" else set()
    for record in records[start + 1:]:
        if (record.get("agentId") or "") != chain:
            continue
        if record["type"] == "assistant":
            key = _message_key(record)
            if key not in seen:
                seen.add(key)
                tokens = [a + b for a, b in zip(tokens, _usage(record))]
            continue
        results = _parts(record, "tool_result")
        if not results and not record.get("isMeta") and _origin(record) == "human":
            break
        for part in results:
            if part.get("tool_use_id") == own_id:
                continue
            calls += 1
            searches += tool_names.get(part.get("tool_use_id")) == "ToolSearch"
            errors += part.get("is_error") is True
            if calls == SKILL_WINDOW:
                return calls, searches, errors, tuple(tokens)
    return calls, searches, errors, tuple(tokens)


def claude_code_uses(path: str, home: str) -> Iterator[SkillUse]:
    """The skill uses in one Claude Code transcript: a Skill tool call, a slash command that loads a skill, or the
    first Read of an installed SKILL.md for a skill the chain has not loaded another way."""
    records = _records(path)
    tool_names = {p["id"]: p.get("name") for r in records if r["type"] == "assistant"
                  for p in _parts(r, "tool_use") if isinstance(p.get("id"), str)}
    prompt: dict[str, str] = {}  # per chain, the last text a user record carried
    loaded: set[tuple[str, str]] = set()
    for i, record in enumerate(records):
        chain = record.get("agentId") or ""
        day = _record_day(record)
        found: list[tuple[str, str, str | None, str, bool]] = []  # plugin, skill, own tool id, key, is a slash command
        if record["type"] == "user":
            text = _text_of(record)
            if record.get("isMeta") or _parts(record, "tool_result") or not text:
                continue
            prompt[chain] = text
            command = _COMMAND.search(text)
            base = _base_dir(records[i + 1], None) if command and i + 1 < len(records) else None
            if base is not None and isinstance(record.get("uuid"), str):
                plugin, skill = _split_name(command[1])
                found.append((plugin or plugin_of_folder(base), skill, None, record["uuid"], True))
        else:
            for part in _parts(record, "tool_use"):
                tool_id, given = part.get("id"), part.get("input")
                if not isinstance(tool_id, str) or not isinstance(given, dict):
                    continue
                if part.get("name") == "Skill" and isinstance(given.get("skill"), str):
                    plugin, skill = _split_name(given["skill"])
                    if not plugin:
                        bases = (_base_dir(r, tool_id) for r in records[i + 1:i + 8])
                        plugin = next((plugin_of_folder(b) for b in bases if b is not None), "")
                    found.append((plugin, skill, tool_id, tool_id, False))
                elif part.get("name") == "Read" and isinstance(given.get("file_path"), str):
                    target = given["file_path"]
                    if target.endswith("/SKILL.md") and _installed(target, home) and (chain, skill_of_path(target)[1]) not in loaded:
                        found.append((plugin_of_folder(os.path.dirname(target)), skill_of_path(target)[1], tool_id, tool_id, False))
        for plugin, skill, own_id, key, typed in found:
            loaded.add((chain, skill))
            if day is None:
                continue
            kind = _origin(record)
            if record.get("isSidechain"):
                how = "subagent"
            elif typed:
                how = "typed" if kind in (None, "human") else "named"
            else:
                how = "named" if names_skill(prompt.get(chain, ""), skill) else "auto"
            calls, searches, errors, tokens = _window(records, i, chain, own_id, tool_names)
            yield SkillUse(day, skill, plugin, "claude-code", how, calls, searches, errors,
                           "claude-code:" + key, typed and how == "typed" and kind is None, tokens)


def cursor_uses(path: str, root: str, home: str) -> Iterator[SkillUse]:
    """Cursor's only trace of a skill is a read of an installed SKILL.md: one use per transcript and skill, dated by
    the file because its records carry no time, with no counts because it records no tool results."""
    day = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).date()
    session = os.path.relpath(path, root)
    seen: set[str] = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "SKILL.md" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or not isinstance(record.get("message"), dict):
                continue
            for part in _parts(record, "tool_use"):
                given = part.get("input")
                target = given.get("path") if isinstance(given, dict) else None
                if part.get("name") not in _CURSOR_READS or not isinstance(target, str):
                    continue
                if not target.endswith("/SKILL.md") or not _installed(target, home):
                    continue
                skill = skill_of_path(target)[1]
                if skill not in seen:
                    seen.add(skill)
                    yield SkillUse(day, skill, plugin_of_folder(os.path.dirname(target)), "cursor", "", None, None, None, f"cursor:{session}:{skill}")


class SkillLock:
    """agentfiles.lock as it stood on a day: the last commit of the file on or before that day (UTC), or the file
    on disk when git has no such commit. The transcript almost never says which version of a skill loaded."""

    def __init__(self, path: str | None):
        self.path = path
        self._days: dict[date, dict] = {}

    def _items(self, day: date) -> dict:
        if self.path is None:
            return {}
        if day not in self._days:
            folder, name = os.path.split(os.path.abspath(self.path))
            data = None
            with contextlib.suppress(OSError):  # no git on PATH: the file on disk
                found = _git(folder, "log", "-1", "--format=%H", f"--before={day + timedelta(days=1)}T00:00:00Z", "--", name)
                commit = found.stdout.decode("ascii", "replace").strip() if found.returncode == 0 else ""
                shown = _git(folder, "show", f"{commit}:./{name}") if commit else None
                data = shown.stdout if shown is not None and shown.returncode == 0 else None
            if data is None:
                data = _read(self.path)
            try:
                items = json.loads(data).get("items") if isinstance(data, bytes) else None
            except (ValueError, AttributeError):
                items = None
            self._days[day] = items if isinstance(items, dict) else {}
        return self._days[day]

    def entry(self, day: date, plugin: str, skill: str) -> tuple[str, str]:
        """(source, version) for a skill: the lock item that installs it (`mine:@bstack`) and its commit. A `plugin:`
        item is matched on the plugin's name, then a `skill:` item on the skill's (agentfiles may prefix it with the
        source). A skill no item installs keeps its plugin name as the source, with an empty version."""
        hits: dict[str, tuple[str, str]] = {}
        for key, item in sorted(self._items(day).items()):
            kind, _, rest = key.partition(":")
            source, _, where = rest.partition(":")
            tail = where.rsplit("/", 1)[-1].lstrip("@")
            commit = item.get("commit") if isinstance(item, dict) else None
            hit = tail == plugin if kind == "plugin" else kind == "skill" and skill in (tail, f"{source}-{tail}")
            if hit and _SKILL_SOURCE.fullmatch(rest) and isinstance(commit, str) and _SHA.fullmatch(commit):
                hits.setdefault(kind, (rest, commit))
        return hits.get("plugin") or hits.get("skill") or (plugin, "")


def _transcripts(root: str, since: date | None) -> list[str]:
    """Every .jsonl under root that was written to on or after `since`."""
    paths = []
    for folder, _, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            if name.endswith(".jsonl") and (since is None or datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).date() >= since):
                paths.append(path)
    return sorted(paths)


def _iso_week(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def scan_skill_uses(claude_logs: str, cursor_logs: str, home: str, since: date | None) -> tuple[list[SkillUse], int]:
    """Every use the transcripts hold, one per key, and how many files could not be read. A resumed or forked
    session repeats its records in another file; the copy with the longest window is kept, so the choice does not
    depend on which file is read first."""
    uses: dict[str, SkillUse] = {}
    unreadable = 0
    sources = [(claude_logs, lambda path: claude_code_uses(path, home)),
               (cursor_logs, lambda path: cursor_uses(path, cursor_logs, home))]
    for root, read in sources:
        for path in _transcripts(root, since) if os.path.isdir(root) else []:
            try:
                for use in read(path):
                    uses[use.key] = max(uses.get(use.key, use), use, key=lambda u: (u.calls or 0, u.searches or 0, u.errors or 0, u.how, u.day,
                                                                                        u.tokens or (0, 0, 0)))
            except OSError:
                unreadable += 1
    return [uses[key] for key in sorted(uses)], unreadable


def cmd_book_skills(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    days = {}
    for flag in ("since", "today"):
        text = getattr(args, flag)
        days[flag] = _day(text) if text is not None else None
        if text is not None and days[flag] is None:
            print(f"quality.py: --{flag} must be a date like 2026-11-15, got {text!r}", file=sys.stderr)
            return 2
    if args.lock is not None and not os.path.isfile(args.lock):
        print(f"quality.py: --lock is not a file: {args.lock}", file=sys.stderr)
        return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; refusing to book into books that fail check")
        return 1
    if not books.tables[SKILLS].present:
        print(f"quality.py: book-skills needs {SKILLS}: create it with its header in the books folder first",
              file=sys.stderr)
        return 2
    home = os.path.expanduser("~")
    legacy = books.tables[SKILLS].legacy
    shape = LEGACY_SCHEMAS[SKILLS] if legacy else SKILLS_SCHEMA
    this_week = _iso_week(days["today"] or datetime.now(timezone.utc).date())
    found, unreadable = scan_skill_uses(args.claude_logs or os.path.join(home, ".claude", "projects"),
                                        args.cursor_logs or os.path.join(home, ".cursor", "projects"), home, days["since"])
    lock = SkillLock(args.lock)
    booked = {row.cells["use"] for row in books.tables[SKILLS].rows}
    totals = {"found": len(found), "booked": 0, "already_booked": 0, "open_week": 0, "before_since": 0, "bad_names": 0,
              "not_in_lock": 0, "no_origin": 0, "unreadable_files": unreadable}
    rows: list[dict[str, str]] = []
    for use in found:
        cells = _cells(SKILLS_SCHEMA, week=_iso_week(use.day), skill=use.skill, tool=use.tool, how=use.how,
                       calls="" if use.calls is None else use.calls, searches="" if use.searches is None else use.searches,
                       errors="" if use.errors is None else use.errors, verdict=SKILL_VERDICTS[0],
                       use=hashlib.sha256(use.key.encode("utf-8")).hexdigest()[:16], source="", version="",
                       **dict(zip(SKILL_TOKENS, use.tokens if use.tokens is not None and not legacy else ("", "", ""))))
        if days["since"] is not None and use.day < days["since"]:
            totals["before_since"] += 1
        elif cells["week"] >= this_week:
            totals["open_week"] += 1  # its window may still be growing; next week's run books it
        elif cells["use"] in booked:
            totals["already_booked"] += 1
        elif not _SKILL_NAME.fullmatch(use.skill) or not _SKILL_SOURCE.fullmatch(use.plugin):
            totals["bad_names"] += 1
        else:
            cells["source"], cells["version"] = lock.entry(use.day, use.plugin, use.skill)
            if any(rule_messages(SKILL_RULES, cells)):
                totals["bad_names"] += 1
                continue
            rows.append(cells)
            totals["not_in_lock"] += not cells["version"]
            totals["no_origin"] += use.no_origin
    rows.sort(key=lambda c: (c["week"], c["tool"], c["skill"], c["source"], c["use"]))
    totals["booked"] = len(rows)
    by_week: dict[str, int] = {}
    for cells in rows:
        by_week[cells["week"]] = by_week.get(cells["week"], 0) + 1
    data = _appended(books.tables[SKILLS].data, "".join(_csv_line(cells[k] for k in shape) for cells in rows))
    if rows:
        files = {rel: books.tables[rel].data if books.tables[rel].present else None for rel in TABLE_SCHEMAS}
        after = run_checks(books_from_bytes(args.books_dir, {**files, SKILLS: data}))
        if after:
            _print_problems(after)
            print(f"{len(after)} problems; nothing written")
            return 1
    wrote = bool(rows) and not args.dry_run
    if wrote:
        try:
            commit_files(args.books_dir, {SKILLS: data})
        except OSError as e:
            print(f"quality.py: cannot write the books, they are unchanged: {e}", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps({"dry_run": args.dry_run, "totals": totals, "weeks": by_week, "wrote": wrote, "tokens": not legacy},
                         sort_keys=True, indent=2))
    else:
        print(("would book " if args.dry_run else "booked ") + f"{len(rows)} skill uses"
              + (" for " + ", ".join(f"{week} ({n})" for week, n in sorted(by_week.items())) if rows else "")
              + f"; {totals['already_booked']} already booked, {totals['open_week']} in the open week, "
              f"{totals['before_since']} before --since, {totals['bad_names']} with a name the books refuse, "
              f"{unreadable} unreadable files")
        print(f"of the {len(rows)}: {totals['not_in_lock']} not in the lock, {totals['no_origin']} slash commands with no origin")
        if legacy:
            print(f"{SKILLS} has the header without token columns, so no tokens were booked; run migrate-skills to add them")
    return 0


def cmd_migrate_skills(args: argparse.Namespace) -> int:
    """Move books/skill-uses.csv from the legacy header to the full schema: the new header, and one empty cell per
    added column on every row. The rows booked before keep empty token cells, since nothing measured them. Running
    it again finds nothing to do."""
    if not os.path.isdir(args.books_dir):
        print(f"quality.py: not a directory: {args.books_dir}", file=sys.stderr)
        return 2
    books = load(args.books_dir)
    problems = run_checks(books)
    if problems:
        _print_problems(problems)
        print(f"{len(problems)} problems; refusing to migrate books that fail check")
        return 1
    table = books.tables[SKILLS]
    if not table.present:
        print(f"quality.py: migrate-skills needs {SKILLS}", file=sys.stderr)
        return 2
    if not table.legacy:
        print(f"{SKILLS} already has the token columns; nothing to do")
        return 0
    data = b"".join(line + b"\n" for line in _migrated_lines(SKILLS, _lines(table.data)))
    files = {rel: books.tables[rel].data if books.tables[rel].present else None for rel in TABLE_SCHEMAS}
    after = run_checks(books_from_bytes(args.books_dir, {**files, SKILLS: data}))
    if after:
        _print_problems(after)
        print(f"{len(after)} problems; nothing written")
        return 1
    if not args.dry_run:
        try:
            commit_files(args.books_dir, {SKILLS: data})
        except OSError as e:
            print(f"quality.py: cannot write the books, they are unchanged: {e}", file=sys.stderr)
            return 1
    print(("would add " if args.dry_run else "added ") + f"{', '.join(SKILL_TOKENS)} to {SKILLS}: "
          f"{len(table.rows)} rows keep them empty")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality.py", description="The Quality Director's recorder and books checker.")
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="run a unittest suite and write per-test time and outcome")
    record.add_argument("tests_dir", metavar="TESTS_DIR")
    record.add_argument("--out", required=True, metavar="FILE")
    record.add_argument("--repo", required=True, metavar="NAME")
    record.add_argument("--sha", type=_sha_arg, metavar="SHA",
                        help="the commit the run tests, 40 lowercase hex (wins over GITHUB_SHA and git)")
    record.set_defaults(func=cmd_record)
    junit = sub.add_parser("record-junit", help="run a command (pytest) and write per-test time and outcome from its JUnit XML file",
                           usage="quality.py record-junit --junit FILE --out OUT --repo NAME [--sha SHA] -- COMMAND [ARG ...]")
    junit.add_argument("--junit", required=True, metavar="FILE", help="the JUnit XML file COMMAND writes; it must not exist yet")
    junit.add_argument("--out", required=True, metavar="OUT")
    junit.add_argument("--repo", required=True, metavar="NAME")
    junit.add_argument("--sha", type=_sha_arg, metavar="SHA",
                       help="the commit the run tests, 40 lowercase hex (wins over GITHUB_SHA and git)")
    junit.set_defaults(func=cmd_record_junit)
    check = sub.add_parser("check", help="validate the quality books")
    check.add_argument("books_dir", metavar="BOOKS_DIR")
    check.add_argument("--base", metavar="REF", help="fail if a runs.csv line at REF changed or was removed")
    check.set_defaults(func=cmd_check)
    fetch = sub.add_parser("fetch", help="download the test-results artifacts and GitHub's account of each watched run")
    fetch.add_argument("books_dir", metavar="BOOKS_DIR")
    fetch.add_argument("out_dir", metavar="OUT_DIR")
    fetch.add_argument("--since", metavar="YYYY-MM-DD", help="runs created on or after this day (default: 3 days before "
                       "the repo's latest started in runs.csv, else 7 days before today UTC)")
    fetch.add_argument("--repo", metavar="SLUG", help="only this watched repo")
    fetch.add_argument("--today", metavar="YYYY-MM-DD", help="the date to count the 7 days back from (for tests)")
    fetch.set_defaults(func=cmd_fetch)
    ingest = sub.add_parser("ingest", help="book the runs `fetch` downloaded into the quality books")
    ingest.add_argument("books_dir", metavar="BOOKS_DIR")
    ingest.add_argument("fetch_dir", metavar="FETCH_DIR")
    ingest.add_argument("--dry-run", action="store_true", help="say what would be booked; write nothing")
    ingest.add_argument("--json", action="store_true")
    ingest.add_argument("--only", choices=["jobs", "visibility"], help="jobs: book only jobs.json files into books/jobs.csv and "
                        "books/steps.csv; visibility: book only repo.json files into books/repos.csv. Either way no artifact is "
                        "read and the three test books are left alone")
    ingest.set_defaults(func=cmd_ingest)
    summary = sub.add_parser("summary", help="the numbers for one week, from books that pass check")
    summary.add_argument("books_dir", metavar="BOOKS_DIR")
    summary.add_argument("--week", metavar="YYYY-Www", help="an ISO week; the latest week in runs.csv by default")
    summary.add_argument("--json", action="store_true")
    summary.add_argument("--public-only", action="store_true", help="leave private repos out; needs books/repos.csv")
    summary.set_defaults(func=cmd_summary)
    skills = sub.add_parser("book-skills", help="book skill use from this machine's agent transcripts into books/skill-uses.csv")
    skills.add_argument("books_dir", metavar="BOOKS_DIR")
    skills.add_argument("--claude-logs", metavar="DIR", help="Claude Code's transcripts (default ~/.claude/projects)")
    skills.add_argument("--cursor-logs", metavar="DIR", help="Cursor's transcripts (default ~/.cursor/projects)")
    skills.add_argument("--lock", metavar="FILE", help="agentfiles.lock, for each skill's source and version")
    skills.add_argument("--since", metavar="YYYY-MM-DD", help="leave out uses before this day")
    skills.add_argument("--today", metavar="YYYY-MM-DD", help="the date whose ISO week is still open (for tests)")
    skills.add_argument("--dry-run", action="store_true", help="say what would be booked; write nothing")
    skills.add_argument("--json", action="store_true")
    skills.set_defaults(func=cmd_book_skills)
    migrate = sub.add_parser("migrate-skills", help="add the token columns to books/skill-uses.csv, empty on the rows already booked")
    migrate.add_argument("books_dir", metavar="BOOKS_DIR")
    migrate.add_argument("--dry-run", action="store_true", help="say what would change; write nothing")
    migrate.set_defaults(func=cmd_migrate_skills)
    audit = sub.add_parser("audit-ci", help="what a repo's workflow files say about CI speed (read-only, no books)")
    audit.add_argument("repo_dir", metavar="REPO_DIR")
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=cmd_audit_ci)
    leak = sub.add_parser("leak-check", help="look for what the books know about private repos in files that may go public (read-only)")
    leak.add_argument("books_dir", metavar="BOOKS_DIR")
    leak.add_argument("files", nargs="+", metavar="FILE", help="a text file, or - for stdin")
    leak.add_argument("--json", action="store_true")
    leak.set_defaults(func=cmd_leak_check)
    argv = list(sys.argv[1:] if argv is None else argv)
    child: list[str] = []
    if argv[:1] == ["record-junit"] and "--" in argv:
        cut = argv.index("--")
        argv, child = argv[:cut], argv[cut + 1:]
    args = parser.parse_args(argv)
    if args.command == "record-junit":
        args.child = child
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
