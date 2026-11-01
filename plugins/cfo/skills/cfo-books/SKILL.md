---
name: cfo-books
description: Check, append to and summarize the CFO's private books (ledger, projects, budgets, renewals, questions). Checks find schema errors, forbidden content such as card numbers, account IDs and API keys, and rewritten ledger history. Use before committing or opening a PR against the books, to add ledger rows, to get a month's spend numbers, when a books CI check fails, or when asked to "check the books", "validate the ledger" or "summarize the month".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# CFO books: check, append, summary, claude-code

Run the checker before you commit anything to the books. The other cfo skills do this before they commit.

<!-- BEGIN GENERATED: snippet:books (tools/kitgen.py; edit plugins/cfo/snippets/books.md) -->
**The books.** The CFO keeps its data in a private git repo, "the books", never in this skill or any public repo. Find it in this order: the `CFO_BOOKS` environment variable, then `~/code/finances`, then ask the user where it is. If there are no books yet, offer to create them with this layout:

| File | Holds |
|---|---|
| `ledger/charges.csv` | One row per charge: `charge_date, period_start, period_end, provider, service, charge_type, billed_cost, currency, api_equivalent_cost, project, status, source, evidence` (FOCUS-style) |
| `projects.yaml` | Which project each provider resource belongs to; new ones are `state: proposed` until confirmed |
| `budgets.yaml` | The monthly envelope and alert rules; `status: proposed` until the user confirms |
| `renewals.yaml` | Upcoming renewals and vendor changes to watch |
| `questions.md` | What the CFO needs from the user, each with a best guess |
| `briefs/` | One brief per weekly run |
| `inbox/` | Files the user drops in (invoice PDFs, statement CSVs); git-ignored |

Rules that always apply:
- Never write card numbers, bank account numbers, cloud account IDs or credentials into the books. Vendors, amounts, dates and receipt or invoice numbers are fine.
- Never pay, cancel, downgrade, delete or contact a vendor. Propose it; the user approves, and the approval goes on record.
- Never guess an amount. Leave `billed_cost` empty with `status: unknown` and add a question with your best guess.
- Append to the ledger; never rewrite a past row. A correction is a new row with `charge_type: adjustment`.
- Keep two numbers apart: **cash cost** (money that left the account) and **API-equivalent cost** (what the tokens would cost at metered API prices). On flat subscriptions they differ a lot; a product built on metered APIs turns the second into the first.
- Numbers come only from `books.py summary BOOKS_DIR --month YYYY-MM --json`, and ledger writes only from `books.py append BOOKS_DIR ROWS_CSV`. Never add, average, total or round amounts by hand or in prose, and never write the ledger CSV by hand. Quote each number exactly as summary prints it. Run the script with `uv run --python 3.12 <cfo-books skill dir>/scripts/books.py` (or with any Python 3.10 or later if uv is not installed); `cfo-books` is a sibling skill in this plugin, so look for its directory next to this skill's directory.
<!-- END GENERATED: snippet:books -->

## Run it

```sh
uv run --python 3.12 <skill dir>/scripts/books.py check BOOKS_DIR [--base REF]
```

It needs Python 3.10 or later and the standard library only. Run it through uv; any Python 3.10+ works if uv is not installed. Each problem prints as `path:line: message`, with the path relative to `BOOKS_DIR`. The last line is `ok, N rows, 0 problems` (exit 0) or `N problems` (exit 1). A missing directory or bad arguments exit 2.

Stale pricing prints `path:line: warning: ...` lines and a trailing `, 1 warning`; warnings never change the exit code.

Use `--base origin/main` (or any ref) on a branch or PR. Leave it off for a quick local check.

## What the problems mean

| Problem | Meaning and fix |
|---|---|
| `header does not match the schema` | The first ledger line must be the 13 columns above, in order. |
| a row field message | `charge_date` and `period_start` need `YYYY-MM-DD`; `period_end` is empty or a date on or after `period_start`; `charge_type`, `status` and `currency` take known values; `billed_cost` is empty exactly when `status` is `unknown`; `evidence` is never empty; `project` is a key in `projects.yaml` or `unassigned`. |
| `questions.md` problem | Each question is `- **Q<n> (YYYY-MM-DD) <title>.** text`, under `## Open` or `## Answered`. Ids are unique across both sections. An answered one carries `**Answered YYYY-MM-DD:**`. An `Answer:` line under an Open question is fine; it means answered, not yet moved. |
| `missing top-level key` or `unsupported YAML` | The YAML files use a small subset (block maps, lists, flow maps, quoted strings, `>-`). Rewrite the named line in that style. |
| `forbidden content` | A card number (Luhn-valid, 13 to 19 digits), a 12-digit account ID, or a secret-shaped token. The message gives the kind, never the value. Remove it from the file. If it is already committed, tell the user, because history needs cleaning. A 12-digit receipt number is fine in the `evidence` column. |
| `changed since REF` or `removed since REF` | A ledger line that exists at REF was edited or deleted. Restore it and add an `adjustment` row instead. |

## Append rows

```sh
uv run --python 3.12 <skill dir>/scripts/books.py append BOOKS_DIR ROWS_CSV
```

`ROWS_CSV` has a header with any of the 13 ledger columns in any order, and at least `evidence`. A column you leave out stays empty; nothing is filled in for you. An unknown column is an error (exit 2).

A row whose `evidence` is already in the ledger, or repeats an earlier row in `ROWS_CSV`, is skipped. Before writing, the whole check runs on the ledger as it would be after the append. If the books already had a problem, or the new rows add one, it prints the problems and `refused, ledger unchanged` (exit 1) and the file is byte-identical. Otherwise it writes atomically and prints `added N, skipped M (evidence already in the ledger)`. With nothing to add it does not touch the file.

## Summarize a month

```sh
uv run --python 3.12 <skill dir>/scripts/books.py summary BOOKS_DIR --month YYYY-MM [--as-of YYYY-MM-DD] [--json]
```

It runs the checks first and prints the problems (exit 1) instead of numbers if the books are not clean. `--as-of` defaults to today and sets the renewals window, so briefs and tests are repeatable. Text output has sections in this order: Cash, Envelope, Monthly equivalent, Renewals, Unknown amounts, API-equivalent.

Rules behind the numbers:
- **Cash** is the `verified` rows with a `charge_date` in the month, adjustments included. `usage-equivalent` rows never count. A yearly charge is cash in its month only.
- **Monthly equivalent** is the run-rate: each subscription whose period covers the month, at `billed_cost` divided by `round(days / 30.4375)` months. The latest row per provider and service counts, so a plan renewed mid-month is not doubled. `lines` lists only the multi-month ones (a $100 yearly plan shows as $8.33).
- **Envelope** compares cash with `budgets.yaml`. `over_warning` means past `envelope_warning_pct`; exactly at it is not over. `null` when no envelope is set.
- **Renewals** are `renewals.yaml` entries due 0 to 30 days after `--as-of`. Entries without a date go to `renewals_undated`.
- **Unknown** lists every `unknown` row in the whole ledger, with its line number, until it is resolved.
- **API-equivalent** sums `api_equivalent_cost` for the month and is never added to cash. `claude_code_latest_week` is the newest week of `claude-code` rows anywhere in the ledger, so a brief can say how old the Claude Code numbers are.

`--json` money values are strings with two decimals (exact, no floats). Other skills read these keys:

```
month, as_of, currency
cash: total, by_provider{}, by_project{}, rows
envelope: usd, status, spent, pct, warning_pct, over_warning, over_envelope   (or null)
monthly_equivalent: total, lines[{provider, service, billed_cost, period_start, period_end, months, monthly}]
renewals[{vendor, plan, amount_usd, cadence, next, days}]
renewals_undated[{vendor, plan}]
unknown[{line, charge_date, provider, service, evidence}]
api_equivalent: total, by_project{}, claude_code_latest_week   (e.g. "2026-W43", or null)
```

## Price Claude Code usage

```sh
uv run --python 3.12 <skill dir>/scripts/books.py claude-code BOOKS_DIR --since YYYY-MM-DD [--until YYYY-MM-DD] [--logs DIR] [--dry-run] [--json]
```

Runs only on the machine that holds the Claude Code session logs (`~/.claude/projects`, read recursively), so never in the scheduled cloud run. Python 3.10 or later, standard library only, run through uv. Run `--dry-run` first.

- It reads token counts, model, timestamp and working directory from assistant lines and nothing else. No prompt, message or tool text is read, printed or stored.
- Whole ISO weeks only (Monday to Sunday, UTC). `--since` rounds down to its Monday. A week is written only once its Sunday is before `--until` (today in UTC by default), so a week is never partial. Run on a Sunday, the newest week is the one that ended a week earlier.
- A week that already has any `claude-code` row is skipped, so a later `paths:` change never counts a week twice under new project names. To re-split a recorded week, add `adjustment` rows.
- One `usage-equivalent` row per project per week: `billed_cost` 0, `api_equivalent_cost` priced from `scripts/pricing.json`, evidence `claude-code:2026-W43:project`. Rows go through the same path as `append`, so a rerun adds nothing and the full check runs first.
- A session's working directory maps to the project whose `paths:` entry (in `projects.yaml`, `~` allowed) is its longest directory prefix; no match is `unassigned`. Add `paths: [~/code/x]` to a project to claim its sessions.
- A model missing from `pricing.json` is never guessed. The output lists its tokens as unpriced and leaves its cost out of every total. Add it to the table with the price from the source URL.
- The output states the weeks, messages counted after dedupe, duplicates dropped, unpriced models, message speeds and the pricing date. Fast-mode messages get a model's `fast_multiplier` when the table has one; otherwise they are priced at standard rates and counted.
- `pricing.json` carries its `source` and `as_of`. `check` warns when `as_of` is more than 90 days old. Refresh the table from the source, then update `as_of`.

## Weekly Mac job for Claude Code usage

The scheduled cloud brief can't read the Mac's logs, so `scripts/weekly-claude-code.sh` runs `claude-code` on the Mac and hands the rows to the weekly brief PR:

```sh
<skill dir>/scripts/weekly-claude-code.sh --repo OWNER/BOOKS [--dry-run]
```

1. It clones the books into a temp directory, so your working copy is never touched.
2. If a PR from a `cfo/brief-` or `claude/cfo-brief-` branch is open, it adds a commit to the oldest one's branch. Otherwise it uses `cfo/brief-<next Sunday>` (the Sunday after, if today's brief is already on `main`): it builds on that branch if it exists unmerged, else creates it from `main`, and opens the PR. The cloud run adds its commit to an open brief PR, so the week still ends in one PR. Dates are America/Denver (`CFO_TZ`).
3. It prices whole weeks from the first Monday at least two days inside Claude Code's log retention (`cleanupPeriodDays` in `~/.claude/settings.json`, default 30; it refuses a value under 9). Older logs may be partly deleted, and a partial week would be written as a verified total. A value set only in managed or local settings is not read.
4. It commits only `ledger/charges.csv`, runs `check --base origin/main` first, and never pushes to `main`, merges or force-pushes. Nothing new means no commit and no PR. If the push is rejected because the cloud run pushed first, it refetches and retries once. Pushes authenticate through `gh`.
5. A failure exits non-zero and shows one macOS notification.

Install it once; it then runs every Sunday at 06:00 local time:

```sh
<skill dir>/scripts/weekly-claude-code.sh --install     # also: --status, --run-now, --uninstall
```

`--install` checks that `git`, `gh` (logged in) and `uv` are reachable, writes the launch agent, loads it, and raises Claude Code's `cleanupPeriodDays` to 120 if it is lower (the old settings file is kept as `settings.json.bak`). Rerun it after moving agent-kit. The books repo comes from the books' GitHub remote (`CFO_BOOKS`, else `~/code/finances`); pass `--repo OWNER/NAME` to override. A books repo can wrap these in a Makefile (`make install`, `make status`, `make run`, `make uninstall`).

A Mac that is asleep at 06:00 runs the job on wake; a Mac that is off skips it, and the next run picks up the missed week while its logs are still kept. The log is `~/Library/Logs/cfo-claude-code.log` (a few lines a week, never rotated).
