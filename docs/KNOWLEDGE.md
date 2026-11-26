# Knowledge base integration (design only)

A future knowledge base (KB) will hold content and best practices that this system uses in two directions:

1. **To build the system.** Principles, playbooks and conventions are knowledge. The KB becomes their source of truth, and agent-kit generates skills from it.
2. **As material for agents at work.** Skills look up the team's conventions, past decisions and domain knowledge while they work, instead of relying on what the model already knows.

Nothing here is implemented yet. This page records the seams that exist today so the KB can plug in without rework.

## Seams that exist today

| Seam | Where | What the KB will do with it |
|---|---|---|
| Stable ids | Every principle has an `id` that matches its file name (`prove-it-works`). Playbooks have ids too. Both are validated by `tools/kitgen.py`. | KB entries reference principles and playbooks by id. Renames stay safe because the id, not the title, is the key. |
| One file per unit, with frontmatter | `plugins/principles/skills/principles/references/<id>.md` has `id`, `title`, `group`, `when`, `rule`, `source`. | The KB exports in this exact shape. `make gen` then rebuilds the indexes in `principles` and `beau-mode` with no other change. |
| Generated indexes | `GENERATED` blocks in skills, filled by `make gen`. | The same mechanism can pull other KB-derived lists into skills (approved libraries, review checklists). |
| No lookup step in the router | `beau-mode` had a "Check for team knowledge" step that told the agent to search a knowledge base by similarity before designing. R42 removed it in bstack 0.50.0: with a KB MCP server installed, agents never called it (see below). | A KB lookup comes back only as entries loaded by id, named by the chosen playbook or by the files the change touches, and needs a passing R42-style eval first. Installing a KB server changes nothing on its own. |
| A destination for lessons | `reflect` routes "a fact or convention, not a behavior" to the KB; the `encode-lessons-in-structure` principle routes one-off notes there. | Lessons become KB entries instead of piling up in instruction files. |
| Provenance fields | `source` / `upstream` on adapted files, generated into [UPSTREAM.md](UPSTREAM.md). | KB entries can carry the same kind of provenance (where a practice came from, who approved it). |

## What R42 measured (2026-11-26)

R42 ran the Eval playbook on ten past tasks: R43's eight (bug fixes, two small features and one read-only audit) and two build tasks in areas a personal library of AI-engineering reading covers. Every arm had beau-mode, Claude Sonnet through `claude -p` with no user settings, and the same repo snapshot. Arms differed only in what else they had: no KB (run twice, for the noise band), a KB MCP server searched by similarity, the server plus an instruction to search it before design, hand-picked change records of earlier related PRs named in the prompt, and the server plus those records. A GPT-5.6 judge scored each task's six answers blind, 1 to 5 on five items.

- None of the 30 runs that had the server called it, and none looked for it with a tool search. The server was connected in every one. The instruction applies clearly to two of the ten tasks, and neither of those runs searched. In this harness a call would have been refused (`claude -p` in `acceptEdits` mode doesn't grant MCP tools, shown by a run asked outright to search), but an agent only learns that by calling, and none did. Over all 60 runs, agents read a playbook in 41 and a principle file in 1, and no reply mentioned a knowledge base.
- The arms that had the server were therefore replicates of no KB. Their win shares over no KB (0.62 and 0.47 overall) show how far two identical conditions land apart on ten tasks, which is wider than the 0.05 band between the two no-KB runs.
- Agents did open the change records named in the prompt (9 of 15 in that arm, against 2 of 15 without the list). That arm lost to no KB (0.35 overall), just outside the spread of the two replicates, so it is weak evidence that the records don't help, not proof that they hurt. The records plus the server beat the records alone (0.60), which, with no KB call, is noise too.

By the rule as first written the KB arm "beat" no KB; the removal rests on the rule's amendment, made before any judge call, that an arm with no KB call is noise. So a lookup that the agent has to decide to make didn't happen here, and an instruction didn't make it happen on the two tasks it covered. If a KB comes back, the skill loads named entries itself and an eval shows the result is better.

## Likely shape (to decide later)

- **Storage and interface**: a local-first store with an MCP server as the agent interface, so every tool that speaks MCP can query it. agentfiles installs the server through a profile's `mcp:` entry.
- **Entry types**: principle, playbook, convention (a team rule with an enforcement pointer, which matches `correct`'s rule table), decision (an ADR), and reference (domain knowledge).
- **Direction of truth**: principles and playbooks move into the KB and are exported to agent-kit; agent-kit stays the distribution format, because every agent tool already knows how to install it.
- **Public and private**: agent-kit stays public. Employer-specific knowledge lives in a private KB and a private skills repo, and reaches agents through MCP, not through this repo.

## Rules for new work until then

- Give anything that might become knowledge (a checklist, a convention, a rubric) its own file with an `id`, instead of burying it in a long `SKILL.md`.
- Reference other units by id or by skill name, never by copying their text.
- Keep employer-specific facts out of this repo; put them where the private KB will live.
