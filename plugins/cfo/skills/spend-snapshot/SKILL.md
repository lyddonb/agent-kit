---
name: spend-snapshot
description: Answer "what am I spending" on AI, cloud and developer tools, by provider and by project, with month-to-date spend against the budget, renewals coming up, and anything unknown. Reads the private books plus receipts and billing data from connected tools. Use for "what am I spending", "how much do my AI tools cost", "am I over budget", "spend snapshot", or before deciding on a new tool or plan.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Spend snapshot

Give the user an accurate picture of their spending in under a minute of reading, with every number traced to its evidence.

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

## Steps

1. **Read the books.** Load the ledger, budgets, renewals and open questions.
2. **Top up from live sources** for anything newer than the last ledger row, using what this session can reach:
   - Email receipts and invoices (search by vendor billing senders; read the amount from the body).
   - Provider tools that are connected or installed: the Vercel connector or CLI (projects, billing charges), `gcloud` and `bq` (billing export), the AWS CLI (Cost Explorer), and an Anthropic Admin API key if the user has a Console organization.
   - Files in `inbox/`.
   Put new rows, each with its evidence, in a scratch CSV and add them with `books.py append BOOKS_DIR scratch.csv`. If you can't write to the books in this session, list the rows you would add and say the numbers below exclude them.
3. **Get the numbers** from `books.py summary BOOKS_DIR --month <current month> --json`: this month's cash to date, the run-rate (`monthly_equivalent`), spend per project (`cash.by_project`), the share of the envelope used, and renewals in the next 30 days. Do no arithmetic of your own. If summary prints problems instead of numbers, fix them or report them.
4. **Flag**: unknown amounts, unassigned charges, metered lines seen for the first time, and vendor notices about price or terms changes.

## Reply

- One headline sentence: month-to-date against the envelope, and the run-rate.
- A table by provider (plan, cadence, monthly equivalent, evidence), then a short table by project.
- Renewals in the next 30 days.
- Unknowns and flags, each with a best guess and the question that would settle it.

Every number in the reply is quoted exactly from summary output. Label every number `verified` (from a receipt or API), `estimated` (with how), or `unknown`. Never present a guess as a total.
