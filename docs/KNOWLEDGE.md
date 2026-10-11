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
| A lookup step in the router | `beau-mode` step 3: "Check for team knowledge" tells the agent to search a knowledge base (MCP server, docs folder or skill) before designing, and to say which entries it used. | When a KB MCP server exists, agentfiles installs it and this step starts finding real entries. No skill edit needed. |
| A destination for lessons | `reflect` routes "a fact or convention, not a behavior" to the KB; the `encode-lessons-in-structure` principle routes one-off notes there. | Lessons become KB entries instead of piling up in instruction files. |
| Provenance fields | `source` / `upstream` on adapted files, generated into [UPSTREAM.md](UPSTREAM.md). | KB entries can carry the same kind of provenance (where a practice came from, who approved it). |

## Likely shape (to decide later)

- **Storage and interface**: a local-first store with an MCP server as the agent interface, so every tool that speaks MCP can query it. agentfiles installs the server through a profile's `mcp:` entry.
- **Entry types**: principle, playbook, convention (a team rule with an enforcement pointer, which matches `correct`'s rule table), decision (an ADR), and reference (domain knowledge).
- **Direction of truth**: principles and playbooks move into the KB and are exported to agent-kit; agent-kit stays the distribution format, because every agent tool already knows how to install it.
- **Public and private**: agent-kit stays public. Employer-specific knowledge lives in a private KB and a private skills repo, and reaches agents through MCP, not through this repo.

## Rules for new work until then

- Give anything that might become knowledge (a checklist, a convention, a rubric) its own file with an `id`, instead of burying it in a long `SKILL.md`.
- Reference other units by id or by skill name, never by copying their text.
- Keep employer-specific facts out of this repo; put them where the private KB will live.
