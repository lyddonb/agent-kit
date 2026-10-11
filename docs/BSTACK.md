# bstack guide

bstack is a way of working with agents: describe the outcome and how you'll know it's done, and let the agent pick the playbook, apply the principles, prove the result, and show you the evidence. It works best when you stop micromanaging and start steering.

It has two plugins:

- **`bstack`**: the `beau-mode` router and its playbooks, plus the workflow skills it calls.
- **`principles`**: 24 named rules, one file each, that the router and the playbooks cite.

## Set it up

Install both plugins in every tool you use. With [agentfiles](https://github.com/lyddonb/agentfiles), the `builder` profile does this, and also:

- writes a short always-on instruction into each tool's global instructions, telling the agent to use `beau-mode` for non-trivial engineering work, and
- writes `~/.agents/roles.yaml`, which says which model each subagent role uses in each tool.

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
| Opening a PR | The last step of every code playbook. |

Large, cross-cutting or unattended work that fits none of them goes to **figure-it-out**, which designs a playbook for the task first.

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

Playbooks delegate to subagents by role: `code`, `judgment`, `explorer` and `reviewers`. agentfiles writes the model for each role per tool into `~/.agents/roles.yaml`; when a role has no entry, the subagent runs on the current model. Review panels (`interrogate`, `reflect`, the trail review in `show-me-your-work`) get their value from model diversity, so give `reviewers` at least two different models where your tool allows it.

Within one tool, diversity is limited to that tool's models (Claude Code offers Claude models; Cursor offers several families). Running reviewers through other agents' CLIs is on the [roadmap](../ROADMAP.md).

## Make it yours

`beau-mode` is a starting point. Three loops improve it:

- **`/reflect`** after a session that taught you something. Three reviewers read the transcript, a synthesizer proposes edits, and nothing changes until you approve. Approved edits land as a PR here.
- **`/correct`** when you keep correcting agents for the same mistake. It fixes the repo at the strongest level that holds: architecture, then types, then lint, then tests, and docs last.
- **The Eval playbook** before you keep a skill change, so a fix written from one bad session doesn't make the skill worse elsewhere.

Don't edit a skill mid-task because it misbehaved. Fix it in its own PR.

## Where this came from

bstack adapts Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT), which is built for Cursor. The principles are nearly verbatim. The router, playbooks and workflow skills are rewritten to work in any agent: model choices moved to a roles file, Cursor-only features became tool-neutral steps, and transcript handling covers Claude Code, Codex, Cursor and pi. [UPSTREAM.md](UPSTREAM.md) maps every file to its source and explains how to pull in upstream improvements.
