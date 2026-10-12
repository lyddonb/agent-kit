# bstack guide

bstack is a way of working with agents: describe the outcome and how you'll know it's done, and let the agent pick the playbook, apply the principles, prove the result, and show you the evidence. It works best when you stop micromanaging and start steering.

New to it? Follow the [tutorial](BSTACK-TUTORIAL.md) first. For what each skill needs and returns, see the [skill reference](BSTACK-SKILLS.md).

It has two plugins:

- **`bstack`**: the `beau-mode` router and its 13 playbooks, plus the workflow skills it calls.
- **`principles`**: 24 named rules, one file each, that the router and the playbooks cite.

## Set it up

Install both plugins in every tool you use. With [agentfiles](https://github.com/lyddonb/agentfiles), the `builder` profile does this, and also:

- writes a short always-on instruction into each tool's global instructions, telling the agent to use `beau-mode` for non-trivial engineering work, and
- writes `~/.agents/roles.yaml` (and `.agents/roles.yaml` in projects that differ), which says which model each subagent role uses in each tool. Skills read the project file first.

Without agentfiles, install the plugins per [INSTALL.md](INSTALL.md) and add this to your global instructions (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, Cursor's User Rules, `~/.pi/agent/AGENTS.md`):

```markdown
For any non-trivial engineering task (a bug, a feature, a refactor, a perf problem, an
investigation, a prototype, a skill edit, or an unattended run), load the `beau-mode` skill
first and follow it. Skip it for casual questions.
```

## Give it a goal and a way to check it

```text
/beau-mode the export writes duplicate rows when a retry lands mid-run. repro first, then fix and verify.
```

You don't name a playbook or list skills. "Repro first" and a checkable outcome are enough for beau-mode to pick the Bug fix playbook, copy its steps into the todo list, and call `how`, `verify-work` and the rest as each step needs them.

More examples:

```text
/beau-mode how do we cancel runs? do we have an n+1 when we look up each run?
/beau-mode build two prototypes of the settings layout behind a switcher and screenshot both.
/beau-mode migrate every caller to the new parser in a fresh branch. done means zero old callers,
           all parser fixtures pass, old api deleted. keep a decision log. don't ask before committing.
/beau-mode read this thread. restate in your own words and in plain english what you think the underlying issue is.
/recall my work on the export retries from the past week, then /teach me why the current fix keeps regressing.
/architect a rate limiter for the public api. prototype the two strongest shapes before picking one.
/beau-mode turn this design into a plan. small, verifiable PRs.
/interrogate review this branch skeptically. no nitpicks unless it's a real bug.
/reflect that took too long. capture what we learned so the next run doesn't repeat it.
/correct agents keep calling the database client directly instead of the repository layer.
```

## The playbooks

| Playbook | For |
|---|---|
| Investigation | A read-only question: how, why, are we sure, X or Y. |
| Bug fix | Reproduce, root-cause and fix with runtime evidence. |
| Feature | New or changed behavior, built from a named data shape. |
| Refactoring | A structure change that holds behavior constant against a pinned contract. |
| Prototype | A throwaway sketch to decide a design, or to settle a factual question by observing it. |
| Perf issue | Measure, find the limiter, fix cheapest-first against a baseline. |
| Autonomous run | Drive to a checkable predicate without stopping. |
| Session pickup | Resume another agent's work from its trail without redoing it. |
| Pause safely | Stop cleanly with a resume note any tool can pick up. |
| Authoring a skill | Write or edit a skill, playbook or principle. |
| Eval | Test a skill change blind before keeping it. |
| Multi-phase plan | Turn an agreed design into a checklist of small, verifiable PRs, checked by a script. |
| Opening a PR | The last step of every code playbook. |

Large, cross-cutting or unattended work that fits none of them goes to **figure-it-out**, which designs a playbook for the task first.

## Make verification infrastructure

An agent is only as good as its ability to check its own work, so give every app you work on a way for agents to drive it.

```text
/create-verification-skill
```

Run once per app repo. It reads the repo, works out how to launch and drive the app, builds a small `control-<app>` CLI (subcommands, `--json` output, `--dry-run` for destructive commands, clear errors and `--help`), and writes a `verify-<app>` skill with a **feature map**: one file per user-facing feature, with every way a user reaches it, the exact commands that drive it, and the traps. It proves the skill by running it end to end before handing it over. From then on, `verify-work` and every playbook verify through it.

The map goes stale as the app changes, so keep it honest:

```text
/maintain-verification-skill
```

It checks every feature against source with parallel read-only subagents, drives every feature live, and opens at most one PR of proven fixes. Schedule it daily per repo.

Use **swarm** when one run isn't enough: ten lanes driving different scenarios to fuzz a change, or interleaved baseline and change runs to get a perf number you can trust.

## Understand before you change it

You're supervising agents that read code faster than you. Make them explain themselves.

- Ask for a restatement. "Restate in your own words what you think the issue is" catches a wrong reading before it costs anything. `beau-mode` now does this as its first step.
- **how** explains what the code does. **why** finds out why it's that way: it searches git and PRs plus whatever ticket, doc, chat, observability and error tools you have connected, and keeps what's known apart from what's inferred.
- **teach** combines the two into a plain, layered explanation with diagrams that build up one part at a time. Use it whenever you want to understand and trust the work, not just get an answer.
- **recall** rebuilds your own recent context on a topic from your agent transcripts (Claude Code, Codex, Cursor and pi), the PRs and tickets around it, and live git state, and ends with the next move.

## Plan with code

Abstract plans look productive and contain little. Plan with things you can check:

- **Write the README first** with **technical-writing**: the tutorial a user would follow, the how-to guides, the reference, and the design reasoning, each in its own Diátaxis mode. The agent builds to it and checks its work against it.
- **Prototype open questions** (the Prototype playbook) instead of debating them.
- **architect** grounds itself with how and why, sketches types and signatures in at least two structurally different shapes on different models (through **arena**), picks one, and implements against it, scrapping the sketch when friction shows the shape is wrong.
- Don't run adversarial reviews on abstract plans. Reviewers invent risks for code that doesn't exist yet. Review the implemented diff with **interrogate** instead.
- When the design is settled and the work spans several PRs, ask for a plan. The Multi-phase plan playbook writes a checklist where every PR has unit, live and perf verification, and `check-plan.py` checks its structure. For a week-long program, commit the plan temporarily so other agents see it, and delete it at the end.

## Steer with principle names

The 24 principles are the vocabulary. You don't invoke them; you use their names to redirect the agent. Each name points at a complete rule the agent has read.

```text
subtract before you add. delete the obsolete adapters first, then design what's left.
apply prove it works. run the real import and show me the written rows.
separate before serializing shared state. give each attempt its own worktree.
```

The agent must say, in its reply, which decision each principle changed. A citation with no decision behind it is the tell that it name-dropped. Full list: [PRINCIPLES.md](PRINCIPLES.md).

## Run work while you're away

An agent you can trust to verify its own work is an agent you can leave with a hard task. Earn that trust first: do the task once while watching, give the agent the same tools you'd use, and turn repeated failures into checks.

A good handoff has a goal, a finish condition, permissions, and an escape hatch:

```text
/beau-mode i'm going to bed. migrate every caller to the new parser in a fresh worktree.
done means zero old callers, all parser fixtures pass, old api deleted.
keep a decision log. don't ask me before committing.
if you're truly stuck after a few hours, stop and write up why.
```

A duration ("work on this for four hours") is not a finish condition. In the morning, ask `/show-me-your-work catch me up` and read its **Attention** section first: a reviewer on a different model has already flagged what deserves your scrutiny.

## Models and roles

Playbooks delegate to subagents by role: `code`, `judgment`, `explorer` and `reviewers`. agentfiles writes the model for each role per tool into `~/.agents/roles.yaml` (a project's `.agents/roles.yaml` wins when present); when a role has no entry, the subagent runs on the current model. Review panels (`interrogate`, `reflect`, the trail review in `show-me-your-work`) get their value from model diversity, so give `reviewers` at least two different models where your tool allows it.

Within one tool, diversity is limited to that tool's models (Claude Code offers Claude models; Cursor offers several families). Running reviewers through other agents' CLIs is on the [roadmap](../ROADMAP.md).

## Make it yours

`beau-mode` is a starting point. Three loops improve it:

- **`/reflect`** after a session that taught you something. Three reviewers read the transcript, a synthesizer proposes edits, and nothing changes until you approve. Approved edits land as a PR here.
- **`/correct`** when you keep correcting agents for the same mistake. It fixes the repo at the strongest level that holds: architecture, then types, then lint, then tests, and docs last.
- **The Eval playbook** before you keep a skill change, so a fix written from one bad session doesn't make the skill worse elsewhere.

Don't edit a skill mid-task because it misbehaved. Fix it in its own PR.

## Where this came from

bstack adapts Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT), which is built for Cursor. The principles are nearly verbatim. The router, playbooks and workflow skills are rewritten to work in any agent: model choices moved to a roles file, Cursor-only features became tool-neutral steps, and transcript handling covers Claude Code, Codex, Cursor and pi. [UPSTREAM.md](UPSTREAM.md) maps every file to its source and explains how to pull in upstream improvements.
