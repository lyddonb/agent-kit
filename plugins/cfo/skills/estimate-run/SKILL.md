---
name: estimate-run
description: Estimate what an agent run, a charter or a whole project will cost before it starts, in both cash and API-equivalent terms, with a typical and a high figure based on past runs where the books have them. Fills a run charter's estimate and budget. Use for "what will this cost", "estimate this run", "price this charter", "is this worth running", or when writing a run charter.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Estimate a run

Price the work before it starts, so the budget in its charter is a number with a basis, not a guess.

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

## Steps

1. **Describe the run's shape**: its rigor tier, the staffing (roles, models, how many agents), the planned calls (implementation units, review panels, arenas, swarm lanes), expected wall-clock time, and any cloud resources it will create (deployments, databases, storage).
2. **Find comparable history.** Look in the books and in the project's run ledgers (`.audit/runs/*/ledger.jsonl` `spend` entries, if the project uses agent-ledger) for past runs of the same tier. Use their actual cost per unit of work. With fewer than five comparable runs, say so and fall back to step 3.
3. **Price from first principles** when history is thin: tokens per call times the provider's current price per token for each model (look prices up; don't rely on memory), plus cloud resources at their list prices. State every assumption.
4. **Split the two numbers.**
   - **API-equivalent cost**: the token cost at metered prices, whatever plan the user is on.
   - **Cash cost**: what actually leaves the account. On a flat subscription it's usually zero extra, unless the run would push past the plan's limits or uses metered services (API keys, cloud usage).
5. **Give a range**: a typical figure and a high figure (the high one covers retries, a scrapped design, or a longer run). With history, use the spread of past runs; without it, use typical plus 50%.
6. **Propose limits**: dollars, tokens and wall-clock time for the charter's budget, set at the high figure, never above the project's ceiling in the books.

## Reply

A short table (item, assumption, API-equivalent, cash), the typical and high totals, the proposed budget in the charter's front-matter format:

```yaml
estimate: {usd: <typical cash>, tokens: <typical>, wall_clock: <typical>, calls: {...}}
budget: {usd: <high cash>, tokens: <high>, wall_clock: <high>, max_parallel_agents: <n>}
```

and one sentence on what would change the estimate most.
