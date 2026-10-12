# bstack skill reference

Every skill in the `bstack` and `principles` plugins, what it needs, and what it hands back. For how they fit together, read the [guide](BSTACK.md). For a first session, follow the [tutorial](BSTACK-TUTORIAL.md).

Every skill is plain text an agent reads, so all of them work in Claude Code, Codex, Cursor, pi and OpenCode. In Claude Code, call one as `/bstack:<name>`. In the other tools, use `/<name>` or name the skill in plain words. Agents also load a skill on their own when your request matches its description.

**Subagents** in the tables below means the skill starts helper agents by role (`code`, `judgment`, `explorer`, `reviewers`), with models from `.agents/roles.yaml` in the project or `~/.agents/roles.yaml`. In a tool that can't start subagents, the skill does that work itself, step by step, and says the review was not independent.

## The router

### beau-mode

| | |
|---|---|
| Use for | Any non-trivial engineering task: a bug, a feature, a refactor, a perf problem, an investigation, a prototype, a skill edit, a plan, an unattended run. agentfiles' `builder` profile makes it always on. |
| Needs | The **principles** plugin. |
| Does | Restates the task, picks one of 13 playbooks and copies its steps into the todo list, reads the principles that apply, checks for team knowledge, then calls the skills below as the steps need them. |
| Returns | What the playbook's **Reply** line names. Every reply leads with who the work is for, labels each claim as measured, inferred or a guess, and names each principle with the decision it changed. |
| Example | `/beau-mode the export writes duplicate rows when a retry lands mid-run. repro first, then fix and verify.` |

Playbooks are in `plugins/bstack/skills/beau-mode/playbooks/`; the [guide](BSTACK.md#the-playbooks) has the table.

### principles

| | |
|---|---|
| Use for | Steering. Say a principle's name ("apply subtract-before-you-add") and the agent reads the full rule and applies it. |
| Needs | Nothing. |
| Returns | Nothing on its own. beau-mode and the playbooks cite it. |
| List | [PRINCIPLES.md](PRINCIPLES.md): 24 rules in five groups, each with when it applies. |

## Understand the code

### how

| | |
|---|---|
| Use for | "How does X work", a walkthrough before a change, "where should this live". |
| Needs | The code. Subagents (`explorer`) for questions that span several files or services. |
| Returns | Overview, Key concepts, How it works, Where things live, Gotchas. Diagrams when the flow has more than three hops. |
| Example | `/how how does a run get cancelled, end to end?` |

### why

| | |
|---|---|
| Use for | "Why is it built this way", "why did we pick Y", where a number or threshold came from, a regression's history. |
| Needs | `git` and `gh`. Each connected tool adds a source: issue tracker (Linear, Jira), docs (Notion, Confluence, Google Docs), chat (Slack), observability (Datadog), error tracking (Sentry), analytics warehouse. Subagents: one `explorer` per source, a `judgment` synthesizer. |
| Returns | The Question, The Code in Question, What We Found (cited), What We Can Reasonably Infer (hedged), Competing Hypotheses, What We Don't Know, Sources Consulted (one line per source, including empty and skipped ones), Confidence Summary. Before a change, a Preserve / Change / Avoid / Risk list. |
| Example | `/why why does the importer cap batches at 500 rows?` |

It searches every connected source in parallel, so a full run is slow. Narrow it in the request ("just git and Linear") when you only need part of the story.

### teach

| | |
|---|---|
| Use for | When you want to understand and trust the work, not just get an answer: a subsystem, a change, or "prove to me this approach is better". |
| Needs | Runs **how** and **why** itself. |
| Returns | A plain explanation, smallest complete answer first, then deeper layers when you ask. Diagrams that build up one part at a time. |
| Example | `/teach me how virtualization works here and why it flickers on fast scroll` |

### recall

| | |
|---|---|
| Use for | Starting or resuming work on a topic you've touched recently: "catch me up on the export retries". |
| Needs | Your agent transcripts for this project (Claude Code, Codex, Cursor or pi). `git` and `gh`. Connected tools for the shared record, through **why**. The **reflect** skill installed next to it (it uses reflect's transcript script). |
| Returns | **Capsule** (up to 5 bullets), **Threads** (one line each with a status tag such as `[open PR #12]` or `[reverted #9]`), **Problems** (up to 5), **Next move**. |
| Example | `/recall my work on virtualization from the past 7 days` |

It reads only the current project's transcripts. To resume one specific session instead, use beau-mode's Session pickup playbook.

## Prove it works

### verify-work

| | |
|---|---|
| Use for | Before saying any task is done, and whenever a claim rests on "it compiles" or "tests pass". Every beau-mode playbook calls it. |
| Needs | A way to drive the real surface. Uses the project's `verify-<app>` skill when there is one. |
| Returns | The claim as a predicate, the surface, the steps run, the evidence, and a verdict: **VERIFIED**, **NOT VERIFIED** or **INCONCLUSIVE**. Inconclusive is never a pass. |
| Example | `/verify-work prove the 60k-row import writes 60,000 rows with no duplicates` |

### create-verification-skill

| | |
|---|---|
| Use for | Once per app repo, so agents can launch, drive and check the real app. |
| Needs | An app that builds and starts locally, plus seed data and test users (or a way to make them). Run it inside the app's repo. |
| Returns | A PR with `.agents/skills/verify-<app>/` (linked into `.claude/skills/`), a `control-<app>` CLI, a feature map of the top 3 to 5 features, and evidence from one end-to-end run of the new skill. |
| Example | `/create-verification-skill` |

### maintain-verification-skill

| | |
|---|---|
| Use for | Keeping the feature map true as the app changes. Run it daily on a schedule. |
| Needs | A `verify-<app>` skill. Subagents (`explorer`, one per feature). |
| Returns | One outcome (**clean**, **changed** or **blocked**), one line per feature, at most one PR of proven fixes, and a list of product bugs it found for you to triage. It never edits product code. |
| Example | `/maintain-verification-skill` |

### swarm

| | |
|---|---|
| Use for | Many parallel lanes: covering every package or feature, fuzzing a change, live checks at a PR head, or enough perf samples to trust a number. |
| Needs | Subagents (`explorer` to read, drive or measure; `code` to write). Cloud agents if your tool has them, for lanes that run the app. |
| Returns | One report: a result table, one line per proven issue with evidence, gaps and dropouts, and which models and environments ran. |
| Example | `/swarm run the checkout perf probe 10 times on main and on this branch, interleaved` |

## Design and plan

### architect

| | |
|---|---|
| Use for | Designing before code: a new module, a one-way-door API or schema, anything where the first shape you try might be wrong. |
| Needs | **how**, **why** and **arena**. |
| Returns | The caller's usage first, then a type sketch (types and signatures with unimplemented bodies) and a one-page rationale: problem, usage, shape, synthesis decision, trade-offs, alternatives, open questions, next step. Run alone, it then implements against the sketch. Called from a playbook, it stops after the sketch. |
| Example | `/architect a rate limiter for the public api. prototype the two strongest shapes first.` |

### arena

| | |
|---|---|
| Use for | Several attempts at one artifact, judged against a rubric, when one attempt would lock in the wrong shape. **architect** uses it for sketches. |
| Needs | Subagents: one per `reviewers` entry, plus a judge on a different model. |
| Returns | One synthesized artifact and a note: the base and why, the judge's verdict, each graft and where it came from, what was rejected. |
| Example | `/arena write the public README for the new sdk` |

### technical-writing

| | |
|---|---|
| Use for | Docs, READMEs, design docs, plans, PR bodies and commit messages. Also README-first planning: write the docs a user would read, then build to them. |
| Needs | Nothing. Pairs with **unslop**. |
| Returns | The text, in one Diátaxis mode per document (tutorial, how-to, reference or explanation). |
| Example | `/technical-writing write the tutorial for the new virtualization package before we build it` |

### Multi-phase plan (a beau-mode playbook)

| | |
|---|---|
| Use for | Turning an agreed design into small, verifiable PRs: "turn this design into a plan". |
| Needs | A settled design. A `verify-<app>` skill for the live checks, or a first PR that creates one. |
| Returns | A plan file where every PR has files, build steps, what you'll see, and unit, live (3 to 10 lanes, the first against trunk) and perf checks, plus the output of `beau-mode/scripts/check-plan.py`. It doesn't implement anything. |
| Example | `/beau-mode turn this design into a plan. small, verifiable PRs.` |

## Review and trails

### interrogate

| | |
|---|---|
| Use for | A skeptical review of a diff, branch or PR before shipping something risky or contested. Not for abstract plans. |
| Needs | Subagents (`reviewers`, ideally two model families). |
| Returns | Intent, one line per reviewer with its model, then **Act on**, **Consider**, **Noted**, **Dismissed** and an agreement map. It doesn't edit unless you ask. |
| Example | `/interrogate review this branch skeptically. no nitpicks unless it's a real bug.` |

### show-me-your-work

| | |
|---|---|
| Use for | Long, unattended or multi-phase work, and "catch me up on what you did". |
| Needs | Subagents (a reviewer on a different model). |
| Returns | A TSV decision trail (`decisions.tsv`, one row per decision with why, evidence and result) and a catch-up reply that ends with an **Attention** section from the other model. |
| Example | `/show-me-your-work catch me up` |

### figure-it-out

| | |
|---|---|
| Use for | Large or cross-cutting work no playbook fits, especially work you'll review after stepping away. |
| Needs | **show-me-your-work** for the trail. |
| Returns | The playbook it designed for the task, the rigor level and why, the trail path, what's verified and what's open. |
| Example | `/figure-it-out migrate every service off the old auth client. i'll review in the morning.` |

## Get better over time

### reflect

| | |
|---|---|
| Use for | After a session that taught something: "capture what we learned". |
| Needs | This session's transcript (it finds it). Subagents: three reviewers and a synthesizer. |
| Returns | **Accepted**, **Rejected** and **Backlog** lists. Nothing changes until you approve. Approved edits to bstack go to your agent-kit checkout as a branch. |
| Example | `/reflect that took too long. what should the next run do differently?` |

### correct

| | |
|---|---|
| Use for | A mistake agents keep repeating in a repo. |
| Needs | The repo and examples of the mistake. |
| Returns | Each mistake class with evidence, the fix at the strongest level that holds (architecture, then types, then a lint or CI check, then a test, then docs), and proof the new check fails on a real past mistake. |
| Example | `/correct agents keep calling the database client directly instead of the repository layer` |

### unslop

| | |
|---|---|
| Use for | Any prose: replies, docs, PR bodies, commit messages, skill files. beau-mode applies it to every reply. |
| Needs | Nothing. |
| Returns | The text with AI writing tells removed (filler, inflated words, em dashes, padding, vague metaphors). |
| Example | `/unslop tighten this PR description` |
