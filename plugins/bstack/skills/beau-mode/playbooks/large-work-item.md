---
id: large-work-item
title: Large work item
when: "Work that spans several PRs, runs while the human is away, or touches a default gate (migration, public API, deploy, auth, a new dependency, secrets, deleting data). The human approves a charter before work starts, and every decision lands in a ledger."
---

# Large work item

**A human approves the run before it starts; afterward, anyone can check what happened without trusting you.** The charter fixes scope, gates, budget and staffing (spec S1). The ledger records every decision, gate answer, verification and cost, and CI checks it (spec S3). Commands are the `ledger` CLI; see **show-me-your-work** for installing it and for `--actor`.

1. **Pick the tier.** 1 routine (reversible, small blast radius), 2 significant (several PRs, shared code, user-facing changes), 3 critical (one-way doors, money, permissions, customer data, migrations). Tier 1 run attended needs no charter: use the matching playbook and **show-me-your-work**. Bias high when unsure.
2. **Ground cheaply.** **how**, **why** and **recall** on the affected code. No fan-outs and no edits before approval: the charter is what decides how much to spend.
3. **Write the charter.** `ledger charter new <slug> --title '<what the run does>' --tier <n>`, then fill every field and section of `.audit/runs/<run-id>/charter.md`. Use [references/charter-template.md](../references/charter-template.md) for what good answers look like. The predicate is checkable; the plan is units in order, each landing on its own; the budget comes from the policy's tier ceiling; the estimate lists planned calls (reviews, rollouts) so close can compare.
4. **Check it.** `ledger charter check <run-id>` until it reports no problems. It prints every value the tools will enforce and the charter's sha256.
5. **Start the run.** `ledger init <slug> --actor '<you>' --why '<the goal>'`, with the same slug and date, so the run lives beside its charter.
6. **Get approval.** Show the human the `check` output (the enforced values and the sha256) and a two-line summary, then stop. They approve by replying with the first 12 characters of the hash, for example "Approved c37ae9b1a466". Record it: `ledger charter approve <run-id> --actor '<their human actor>' --sha256 <prefix> --quote '<their exact words>' --relayed-by '<your agent id>' --channel '<where>'`. If they ask for edits, make them, check again, and ask again: an edited charter needs a new approval. Never approve on their behalf, and never start work on a draft.
7. **Run.** Work without asking about reversible, in-budget work. Follow the charter's plan with the playbook each unit needs (Feature, Bug fix, Multi-phase plan), one unit per PR, verified before the next starts. Record each decision, verification and review with **show-me-your-work** into this run.
8. **At a gate, stop only that thread.** Record a `gate` entry naming the gate and what you were about to do, ask the human, and keep working on independent units. Their reply is a `gate-answer` entry (human actor, `data.quote`, `data.relayed_by`). Then continue as they said.
9. **Watch the budget.** Record `spend` entries as units finish (`usd_micros`, `tokens` without cache reads, `estimate: true` when estimated). Reaching any limit is the `spend` gate. Stop-loss: if the predicate hasn't moved in two units and half the budget is spent, stop and write up why instead of pushing on.
10. **Close.** Verify the whole against the predicate on the real artifact (**verify-work**). Run the reviews the tier calls for (tier 2: **interrogate** with two model families; tier 3: also a security lens and a decision review). Record a final `spend` entry comparing the estimate's planned calls with what ran, and any `lever` or `lesson` entries.
11. **Archive the sessions.** `ledger session add <transcript> --run <run-id> --actor '<you>'` for each session that worked on the run (find them with the transcripts table in **show-me-your-work**). A transcript whose redaction can't be confirmed stays out of git: say so in the reply.
12. **Seal.** Commit everything under `.audit/runs/<run-id>/`, then `ledger seal <run-id> --actor '<you>'`, then commit the seal entry and `.audit/INDEX.jsonl`. `ledger verify --base origin/main` and `ledger scan --base origin/main` must pass. Merge with a merge commit: a squash or rebase merge drops the commit the seal names.

<!-- BEGIN GENERATED: snippet:policy (tools/kitgen.py; edit plugins/bstack/snippets/policy.md) -->
**Policy.** Read `.agents/policy.yaml` in the project, then `~/.agents/policy.yaml` (agentfiles writes it). Stricter wins: the gates are both lists together, and each budget is the lower figure. If neither file exists, the gates are the ten defaults below and the budgets are tier 2 $50, 8M tokens, 8h, 4 agents; tier 3 $150, 20M tokens, 24h, 6 agents.

| Gate | Fires when |
|---|---|
| `migration` | A schema or data migration touches shared data |
| `delete-data` | Data, branches or files outside the run's scope would be deleted |
| `public-api` | A public API, protocol or CLI contract changes |
| `deploy` | Anything deploys, or infrastructure changes |
| `auth-permissions` | Auth, permissions or access control code changes |
| `new-dependency` | A package or service dependency is added |
| `secrets` | A secret, credential or key would be read, created or rotated |
| `outbound-message` | A message goes to a person outside the session |
| `license` | A license changes, or code under a new license comes in |
| `spend` | Any budget limit, or the stop-loss, is reached |

At a gate, stop only that thread and ask the human, saying which gate fired and what you were about to do. Independent work continues. In a run with a ledger, record the stop as a `gate` entry and the human's reply as a `gate-answer` entry (human actor, their words in `data.quote`), then carry on as they said. A charter can add gates; nothing removes one. A tokens figure counts input, output and cache writes, not cache reads; dollars are the main measure.
<!-- END GENERATED: snippet:policy -->

**Reply:** the tier and why, the predicate and its final state, the units landed (PRs), every gate and how it was answered, spend against budget and estimate, what reviews found, which sessions were archived (and any kept out of git), and the run id so a reviewer can `ledger show` it.
