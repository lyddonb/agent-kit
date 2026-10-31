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
<!-- END GENERATED: snippet:books -->

## Weekly run

1. **Collect** everything since the last brief:
   - Email: receipts, invoices, payment notices and vendor notices (pricing, terms, billing changes) from every vendor in the books, and any new vendor that looks like a software or cloud charge. Read amounts from the email body. If only an attached PDF has it, record the row as `unknown` and say so.
   - Connected providers: projects, deployments and billing charges from whatever is reachable (Vercel, Google Cloud, AWS, Anthropic, Cursor).
   - The `inbox/` folder.
2. **Record**: append new charges to the ledger (dedupe by evidence), add newly discovered resources to `projects.yaml` as `proposed`, update `renewals.yaml`.
3. **Check**:
   - Month-to-date spend against the envelope; flag past the warning share.
   - Metered lines seen for the first time, and price or terms notices.
   - Renewals in the next 30 days, yearly ones especially.
   - Waste: projects or resources with cost but no deploys, commits or traffic in 60 days; overlapping tools; usage growing faster than the project's activity. Each with a recommendation (keep, shrink, pause, retire), the monthly saving, and what retiring would break.
   - Whether the envelope still fits: if three months of actuals plus planned work differ from it by more than 20%, propose a new figure.
4. **Write** `briefs/YYYY-MM-DD.md` and update `questions.md` (move answered questions down with the date).
5. **Commit** the books on a branch or directly, as the books' README says, with the brief's headline as the message.
6. **Send** the user a short message: the headline, up to five decisions (each a yes or no with the saving or cost), and the open questions with best guesses. Link the brief.

If the books aren't reachable in this run, still collect and check, and put the rows you would have added at the end of the message so nothing is lost.

## What needs approval

Everything that changes money or services: confirming the envelope or a project budget, retiring or downsizing anything, cancelling or changing a plan, and contacting a vendor. Ask; don't do. Record the user's answers in the books when they reply.
