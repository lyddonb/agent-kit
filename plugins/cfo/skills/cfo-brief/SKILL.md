---
name: cfo-brief
description: The CFO's weekly routine. Collects new receipts, invoices, vendor notices and billing data into the private books, checks spend against the budget, finds waste and renewals, writes a brief, and sends it with decisions and questions for the user to approve. Proposes; never acts. Use for "CFO brief", "weekly finance review", "check my spending this week", or from a weekly scheduled task.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# CFO brief

Do the bookkeeping so the user only makes decisions. Be proactive: anything you can't find or confirm becomes a question with your best guess, not a silent gap.

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

## Weekly run

1. **Collect** everything since the last brief:
   - Email: receipts, invoices, payment notices and vendor notices (pricing, terms, billing changes) from every vendor in the books, and any new vendor that looks like a software or cloud charge. Read amounts from the email body. If only an attached PDF has it, record the row as `unknown` and say so.
   - Connected providers: projects, deployments and billing charges from whatever is reachable (Vercel, Google Cloud, AWS, Anthropic, Cursor).
   - The `inbox/` folder.
2. **Record**:
   - Collect the new charges as rows in a scratch CSV outside the books (or in a git-ignored path), with the ledger columns that apply and an `evidence` on every row. Then run `books.py append BOOKS_DIR scratch.csv`. It skips rows whose evidence is already in the ledger and refuses the whole append if any check fails. If it refuses, fix the new rows, or turn the problem into a question. Never edit past rows, and never write the ledger CSV by hand.
   - Add newly discovered resources to `projects.yaml` as `proposed`, and update `renewals.yaml`.
3. **Check**, taking every number from `books.py summary BOOKS_DIR --month <current month> --json` (and the previous month's when comparing):
   - Month-to-date cash against the envelope (`envelope`); flag `over_warning`.
   - Metered lines seen for the first time, and price or terms notices.
   - Renewals in the next 30 days (`renewals`), yearly ones especially.
   - Waste: projects or resources with cost but no deploys, commits or traffic in 60 days; overlapping tools; usage growing faster than the project's activity. Each with a recommendation (keep, shrink, pause, retire), the monthly saving, and what retiring would break. Cost figures come from summary's `by_project` and `monthly_equivalent` lines.
   - Whether the envelope still fits: if summary shows `over_envelope`, or its run-rate (`monthly_equivalent.total`) is above the envelope, say so in the brief and ask whether to change the envelope. Don't propose a new figure from your own arithmetic.
4. **Write** `briefs/YYYY-MM-DD.md` from `briefs/TEMPLATE.md` in the books. If the template is missing, use these sections in this order:
   - **Headline**: one line, month-to-date cash against the envelope with its percentage, as summary prints them.
   - **Decisions**: at most five, each a yes or no with its monthly effect.
   - **Changes since last week**: compare with the figures stated in the previous brief, and list the ledger rows added this run. Don't compute new differences.
   - **Renewals**: the next 30 days.
   - **Waste**.
   - **Questions**: the open ones, each with a best guess.

   Every number in the brief comes from summary output, quoted exactly.
5. **Update `questions.md`.** Ids are stable: `Q7` is always Q7, and a new question takes the next unused number across Open and Answered. A question is `- **Q<n> (YYYY-MM-DD) Title.** question text with a best guess`. When the user has answered (an `Answer:` line under it, or a reply in chat), move it from `## Open` to `## Answered` in this form: `- **Q6 (2026-10-31) Title.** question text **Answered 2026-11-02:** the answer.` Never renumber and never delete a question.
6. **Check and commit.** Run `books.py check BOOKS_DIR --base origin/main` and fix every problem it prints. Then commit the books on a branch or directly, as the books' README says, with the brief's headline as the message.
7. **Send** the user a short message: the headline, up to five decisions (each a yes or no with the saving or cost), and the open questions with best guesses. Take every number from summary. Link the brief.

If the books aren't reachable in this run, still collect and check, and put the rows you would have added at the end of the message so nothing is lost.

## What needs approval

Everything that changes money or services: confirming the envelope or a project budget, retiring or downsizing anything, cancelling or changing a plan, and contacting a vendor. Ask; don't do. Record the user's answers in the books when they reply.
