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
