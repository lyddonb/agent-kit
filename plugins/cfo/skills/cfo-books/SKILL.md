---
name: cfo-books
description: Check the CFO's private books (ledger, projects, budgets, renewals, questions) for schema errors, forbidden content such as card numbers, account IDs and API keys, and rewritten ledger history. Use before committing or opening a PR against the books, when a books CI check fails, or when asked to "check the books" or "validate the ledger".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# CFO books check

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
| `missing top-level key` or `unsupported YAML` | The YAML files use a small subset (block maps, lists, flow maps, quoted strings, `>-`). Rewrite the named line in that style. |
| `forbidden content` | A card number (Luhn-valid, 13 to 19 digits), a 12-digit account ID, or a secret-shaped token. The message gives the kind, never the value. Remove it from the file. If it is already committed, tell the user, because history needs cleaning. A 12-digit receipt number is fine in the `evidence` column. |
| `changed since REF` or `removed since REF` | A ledger line that exists at REF was edited or deleted. Restore it and add an `adjustment` row instead. |
