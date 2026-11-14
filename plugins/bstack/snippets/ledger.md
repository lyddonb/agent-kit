**The `ledger` CLI.** agentfiles installs it (`commands: {ledger: agent-ledger:ci/run_ledger.py}` in a profile). Elsewhere: `pip install git+https://github.com/lyddonb/agent-ledger` (standard-library Python 3.10+). Run it inside the project's git repo; a run's records live in `.audit/runs/<yyyy-mm-dd>-<slug>/` and are committed with the work. Every write is redacted before it is recorded, and `ledger verify` checks the chain.

Every write names who is acting with `--actor` (spec S2):

- **You:** `{"kind":"agent","id":"<agent name>@<tool>#<session prefix>","on_behalf_of":"<identity.human from the policy>","tool":"<claude-code, codex, cursor, pi or opencode>","model":"<your model>","session":"<session id>"}`. The session id is your transcript file's name without `.jsonl` (see Finding transcripts); if you can't find it, make up 8 hex characters once and reuse them all session. A subagent gets its own id and the same `on_behalf_of`.
- **A human** (approvals, gate answers): `{"kind":"human","id":"<github login>","on_behalf_of":"<login>@github"}`. When you type in what they said, put their exact words in `data.quote` and your agent id in `data.relayed_by`.

Never write an entry as a person who didn't say it, and never invent an approval.
