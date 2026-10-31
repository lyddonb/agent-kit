---
name: cfo-books
description: Check, append to and summarize the CFO's private books (ledger, projects, budgets, renewals, questions). Checks find schema errors, forbidden content such as card numbers, account IDs and API keys, and rewritten ledger history. Use before committing or opening a PR against the books, to add ledger rows, to get a month's spend numbers, when a books CI check fails, or when asked to "check the books", "validate the ledger" or "summarize the month".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# CFO books: check, append, summary

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
- Numbers come only from `books.py summary BOOKS_DIR --month YYYY-MM --json`, and ledger writes only from `books.py append BOOKS_DIR ROWS_CSV`. Never add, average, total or round amounts by hand or in prose, and never write the ledger CSV by hand. Quote each number exactly as summary prints it. Run the script as `python3 <cfo-books skill dir>/scripts/books.py`; `cfo-books` is a sibling skill in this plugin, so look for its directory next to this skill's directory.
<!-- END GENERATED: snippet:books -->

## Run it

```sh
python3 <skill dir>/scripts/books.py check BOOKS_DIR [--base REF]
```

It needs only Python 3.9 or later. Each problem prints as `path:line: message`, with the path relative to `BOOKS_DIR`. The last line is `ok, N rows, 0 problems` (exit 0) or `N problems` (exit 1). A missing directory or bad arguments exit 2.

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
python3 <skill dir>/scripts/books.py append BOOKS_DIR ROWS_CSV
```

`ROWS_CSV` has a header with any of the 13 ledger columns in any order, and at least `evidence`. A column you leave out stays empty; nothing is filled in for you. An unknown column is an error (exit 2).

A row whose `evidence` is already in the ledger, or repeats an earlier row in `ROWS_CSV`, is skipped. Before writing, the whole check runs on the ledger as it would be after the append. If the books already had a problem, or the new rows add one, it prints the problems and `refused, ledger unchanged` (exit 1) and the file is byte-identical. Otherwise it writes atomically and prints `added N, skipped M (evidence already in the ledger)`. With nothing to add it does not touch the file.

## Summarize a month

```sh
python3 <skill dir>/scripts/books.py summary BOOKS_DIR --month YYYY-MM [--as-of YYYY-MM-DD] [--json]
```

It runs the checks first and prints the problems (exit 1) instead of numbers if the books are not clean. `--as-of` defaults to today and sets the renewals window, so briefs and tests are repeatable. Text output has sections in this order: Cash, Envelope, Monthly equivalent, Renewals, Unknown amounts, API-equivalent.

Rules behind the numbers:
- **Cash** is the `verified` rows with a `charge_date` in the month, adjustments included. `usage-equivalent` rows never count. A yearly charge is cash in its month only.
- **Monthly equivalent** is the run-rate: each subscription whose period covers the month, at `billed_cost` divided by `round(days / 30.4375)` months. The latest row per provider and service counts, so a plan renewed mid-month is not doubled. `lines` lists only the multi-month ones (a $100 yearly plan shows as $8.33).
- **Envelope** compares cash with `budgets.yaml`. `over_warning` means past `envelope_warning_pct`; exactly at it is not over. `null` when no envelope is set.
- **Renewals** are `renewals.yaml` entries due 0 to 30 days after `--as-of`. Entries without a date go to `renewals_undated`.
- **Unknown** lists every `unknown` row in the whole ledger, with its line number, until it is resolved.
- **API-equivalent** sums `api_equivalent_cost` for the month and is never added to cash.

`--json` money values are strings with two decimals (exact, no floats). Other skills read these keys:

```
month, as_of, currency
cash: total, by_provider{}, by_project{}, rows
envelope: usd, status, spent, pct, warning_pct, over_warning, over_envelope   (or null)
monthly_equivalent: total, lines[{provider, service, billed_cost, period_start, period_end, months, monthly}]
renewals[{vendor, plan, amount_usd, cadence, next, days}]
renewals_undated[{vendor, plan}]
unknown[{line, charge_date, provider, service, evidence}]
api_equivalent: total, by_project{}
```
