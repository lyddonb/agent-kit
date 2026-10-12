---
name: why
description: Find out why code is the way it is (design rationale, past decisions, regressions, where a threshold came from) by searching git, PRs and every connected ticket, doc, chat and observability tool in parallel, and return a cited, confidence-tiered answer. Use for "why does X work this way" or "why did we pick Y". Use how for what code does.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack why @ 11713c6 (MIT, Lauren Tan)"
---

# Why

Find the forces that gave code its shape. **how** answers what the code does. **why** answers what led to it.

Work like a careful, cautious investigator. Say what you know and what you're inferring, and keep them apart. Read [references/epistemics.md](references/epistemics.md) for the confidence tiers and phrasing; the synthesizer must follow it.

Investigators and the synthesizer only read. Don't run them in a read-only or "ask" mode if your tool strips MCP access in that mode: most evidence sources are MCP servers.

## 1. Pin the target and the question

The **target** is usually code, a pattern, a feature or a named decision. The **question** is a rationale, a trade-off, a motivating edge case, an outside constraint, dead code, or a broad history sweep.

If the target is vague, make your best guess from the conversation (open files, recent edits, what was just discussed), state it in one line so the user can redirect, and proceed.

## 2. Build the code anchor

Before starting investigators, collect the seed context yourself:

- File paths with line ranges, and the key symbols.
- Last-touch commits: `git blame -L <start>,<end> <file>`.
- History through renames: `git log --follow -p -- <file>`, and `git log --oneline -20 -- <file>` for recent commits with PR numbers.
- PR numbers from commit subjects (`(#1234)`) and `git log -1 --format=%B <commit>`.
- PR bodies and discussion for substantive commits: `gh pr view <number> --json title,body,author,createdAt,mergedAt,labels,closingIssuesReferences,comments,reviews`.
- Ticket IDs mentioned in commits or PR bodies.

Every investigator and the synthesizer gets this anchor.

## 3. Investigate in parallel

Default to the full sweep. The goal is a complete coverage map: an empty search is a finding, so record it instead of skipping the search.

**Map your sources.** List the MCP servers and tools available in this session and assign each to one evidence category. Source control is always available through `git` and `gh`.

| Category | Best at | Examples |
|---|---|---|
| Source control | Rationale captured at review time | git, `gh` (always run this one) |
| Issue tracker | The product or business forcing function | Linear, Jira, GitHub Issues, Shortcut |
| Long-form docs | Design rationale written before the code | Notion, Confluence, Google Docs, a knowledge base |
| Team chat | Deliberation that never reached a doc | Slack, Teams, Discord |
| Infrastructure observability | Runtime reality behind timeouts, retries, limits | Datadog, Grafana, Honeycomb, New Relic |
| Error tracking | The exceptions that motivated defensive code | Sentry, Rollbar, Bugsnag |
| Analytics warehouse | Data behind flags, experiments and thresholds | Databricks, Snowflake, BigQuery, dbt |

When a server fits two categories, pick the one matching its main evidence and note it in the coverage map.

**Start one `explorer` subagent per category that has a source**, all at once, each owning exactly one source. Don't give one agent several sources. Each gets:

- [references/investigator-prompt.md](references/investigator-prompt.md), filled in.
- The playbook for its category from [references/source-playbook.md](references/source-playbook.md), adapted to the actual tool.
- [references/sources/incident-postmortem.md](references/sources/incident-postmortem.md) as well, when the target looks defensive (null checks, retries, timeouts, rate limits, feature flags, egress guards, OOM handlers).
- The code anchor and the user's question, word for word.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

**Skipping a category** needs a written reason that goes into Sources Consulted. Two reasons are valid:

- No source for that category exists in this session. That's a gap, not a choice: "Team chat not searched. No chat tool is connected, so the conversational record was not searchable."
- The source is provably irrelevant, not just probably: "Error tracking skipped. The target is a build-time script with no runtime path."

For a single-commit target whose PR description already holds the complete answer, you may answer inline, but only after confirming the other searches would be redundant, and say so. This should be rare.

## 4. Synthesize

Start one `judgment` subagent with [references/synthesizer-prompt.md](references/synthesizer-prompt.md) filled in. It gets every investigator's findings (null results included), the skipped categories with reasons, the code anchor, the question, and [references/epistemics.md](references/epistemics.md).

## 5. Present

Give the user the synthesizer's output. Edit lightly for clarity or add conversation context, but **don't rewrite the confidence language**: the hedges are findings.

The structure is the synthesizer's: The Question, The Code in Question, What We Found, What We Can Reasonably Infer, Competing Hypotheses, What We Don't Know, Sources Consulted, Confidence Summary. Keep Sources Consulted as one line per category, including the empty and skipped ones with the reason.

If the question is a step toward changing this code, end with a **Preserve / Change / Avoid / Risk** list that turns the history into constraints for the change.

## Common failure modes

- **Recency bias.** The latest commit is not the whole story. The current shape is often many earlier decisions piled up. Trace back.
- **Confirming the user's guess.** "I assume it's for performance?" is a candidate to check, not a conclusion.
- **Code as evidence of its own intent.** Code shows mechanics, not motivation.
- **Filling a gap with a plausible story.** "We searched A, B and C and found nothing" is a useful answer.
