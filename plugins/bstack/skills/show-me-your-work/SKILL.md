---
name: show-me-your-work
description: Keep a reviewable, tamper-evident decision trail for long, unattended or multi-phase work (one ledger entry per decision with what, why, evidence and result, recorded with the ledger CLI), then audit it against the transcript and have a different model flag what deserves attention. Use for /show-me-your-work, "keep a decision log", autonomous or overnight runs, or "catch me up on what you did".
license: MIT
metadata:
  author: lyddonb
  version: "0.2.0"
  upstream: "pstack show-me-your-work @ ccb5507 (MIT, Lauren Tan)"
---

# Show me your work

Keep one canonical trail so a human can audit decisions instead of re-reading a whole run. The trail is a run in the project's ledger: a hash-chained file in `.audit/runs/<run-id>/ledger.jsonl` that `ledger verify` checks, so an edited or deleted entry shows.

<!-- BEGIN GENERATED: snippet:ledger (tools/kitgen.py; edit plugins/bstack/snippets/ledger.md) -->
**The `ledger` CLI.** agentfiles installs it (`commands: {ledger: agent-ledger:ci/run_ledger.py}` in a profile). Elsewhere: `pip install git+https://github.com/lyddonb/agent-ledger@v1.0.0` (standard-library Python 3.10+). Run it inside the project's git repo; a run's records live in `.audit/runs/<yyyy-mm-dd>-<slug>/` and are committed with the work. Every write is redacted before it is recorded, and `ledger verify` checks the chain.

Every write names who is acting with `--actor` (agent-ledger spec S2):

- **You:** `{"kind":"agent","id":"<agent name>@<tool>#<session prefix>","on_behalf_of":"<identity.human from the policy>","tool":"<claude-code, codex, cursor, pi or opencode>","model":"<your model>","session":"<session id>"}`. The session id is your transcript file's name without `.jsonl` (see Finding transcripts), when you can tell which file is yours; parallel sessions in one project make the newest file a guess. If you can't tell, or don't know your model, write `unknown`. Never put a guess in the record. A subagent gets its own id and the same `on_behalf_of`.
- **A human** (approvals, gate answers): `{"kind":"human","id":"<github login>","on_behalf_of":"<login>@github"}`. Whenever you type in what they said, always record their exact words (`data.quote`, or `--quote` on `charter approve`) and your agent id (`data.relayed_by`, or `--relayed-by`). A human typing the command in their own terminal passes `--typed-by-me` instead, which records `data.self_typed`. Never pass `--typed-by-me` yourself: it claims the human typed the entry. `ledger` refuses a human's approval or gate answer that carries neither.

Never write an entry as a person who didn't say it, and never invent an approval.
<!-- END GENERATED: snippet:ledger -->

## Start the run

Once per effort, from the project's root: `ledger init <slug> --actor '<you>' --why '<one line: what this effort is for>'`. The run id is `<today>-<slug>`; use it for every entry. Large work started with the Large work item playbook already has a run (its charter's folder); reuse that id. A run adds to an existing effort when it picks one up: check with `ledger show <run-id>`, and make your first entry a `state` entry naming the entries before it that you did not write.

## Record decisions

One entry per decision:

```bash
ledger append --run <run-id> --actor '<you>' --type <type> \
  --summary '<what was chosen or done, one line>' --why '<the reason in plain words>' \
  --evidence '<commit, PR, file:line or artifact path>' --data '{"phase": "<phase>", "result": "<outcome>"}'
```

- **type**: `decision` for a fork chosen or a unit finished, `verification` for a check and its verdict (a spec criterion's check is a receipt, and a checklist item's check is recorded the same way, both written by **verify-work**'s `scripts/receipt.py`, not by hand), `state` for a phase moving (`{"state": "..."}`), `review` for a review and what came of it, `lesson` for something a future run should know, `spend` for cost (`usd_micros`, `tokens`, and `estimate: true` when estimated). `gate` and `gate-answer` are for gates; `approval` is a human's and comes from the Large work item playbook.
- **evidence**: a pointer, never a paragraph. Repeat `--evidence` for more than one.
- **result** in `data`: the outcome, such as `tests green`, `reverted`, `pixel-diff 0`, `INCONCLUSIVE`, `open`.

Record decision points, not every action: a fork chosen, a unit finished with its verification result, a pivot or revert and its trigger, a blocker. In a loop, one entry per iteration. Write entries the way you'd tell a teammate (the **unslop** rules apply). `ledger append` refuses to write to a run whose chain is broken; that is a finding to report, not something to work around.

Only one agent appends to a run: the one orchestrating the work, on one branch. Subagents and parallel workers report back, and the orchestrator records what they did; two branches appending to one ledger conflict, and fixing that means rewriting history.

Entries are append-only: a wrong call gets a new entry that supersedes it. Never edit or delete history; `ledger verify --base origin/main` in CI fails if merged entries change.

## Where it lives

`.audit/runs/<run-id>/` in the project, committed with the work, so the PR carries its own trail and CI checks it (the `ledger-verify` Action). For a throwaway or private exploration you don't want in the repo, use a scratch git repo instead, and pass the same `--root <scratch repo>` on every `ledger` command for that run. Older trails kept as `decisions.tsv` stay readable as they are.

## Before handing back

1. **Audit the trail against what happened.** Read it with `ledger show <run-id>`, then walk this run's entries against its transcript. Every entry maps to a real action, every evidence pointer resolves, and every fork or abandoned approach that shaped the work has an entry. Fix gaps by appending entries, never by editing old ones. Run `ledger verify` and `ledger scan`.

<!-- BEGIN GENERATED: snippet:transcripts (tools/kitgen.py; edit plugins/bstack/snippets/transcripts.md) -->
**Finding transcripts.** Read only the current project's sessions. Never search other projects' transcripts: they hold private conversations that have nothing to do with this work.

| Tool | Session files |
|---|---|
| Claude Code | `~/.claude/projects/<project path, non-alphanumerics as ->/<session-id>.jsonl` |
| Codex | `~/.codex/sessions/<yyyy>/<mm>/<dd>/*.jsonl` (match the project by the `cwd` in the first line) |
| Cursor | `~/.cursor/projects/<workspace>/agent-transcripts/` |
| pi | `~/.pi/agent/sessions/--<project path>--/<timestamp>_<id>.jsonl` |
| OpenCode | no portable file; use its export command if it has one |

The reflect skill ships `scripts/find-transcripts.py`, which lists the current project's newest sessions across these tools. If no transcript resolves, write a tight digest of the session from your own context and use that instead. Say which one you used.
<!-- END GENERATED: snippet:transcripts -->

2. **Get an outside read.** Start a subagent that doesn't edit files, on a model different from the one that did the work (the first `reviewers` entry that differs from yours). It reads `ledger show <run-id>` and the transcript and flags: decisions with weak evidence, verification claimed without proof, choices that look risky in hindsight, and gaps a casual skim would miss. Record its read as a `review` entry.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- An entry that starts with `cli:` (for example `cli:cursor-agent:gpt-5.6-sol-high`) names another agent's CLI, not a model for your tool. Don't start a subagent for it. Write its brief to a file in your scratch folder and run `python3 ../beau-mode/scripts/second_opinion.py --reviewer ENTRY --prompt-file FILE --json` from this skill's folder (the script lives in the beau-mode skill, next to this one), adding `--cwd` with the worktree when it must read code. It only reads, so never give it a step that edits files or runs a repro. Exit 2 means the entry itself is wrong (an unknown agent or a malformed spec): name the entry in the reply. Any `status` other than `ok` means that reviewer gave no answer: name the status in the reply. In both cases, if the step needs that seat filled, run it on the current model and say the review was not independent.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

3. **End the reply with an Attention section**: `reviewed by <model>` on its own line, then each flag with the entries (by `seq`) or moments it points at. "No flags" is a valid result.

To review a trail: `ledger show <run-id>` prints it as a table after checking the chain.
