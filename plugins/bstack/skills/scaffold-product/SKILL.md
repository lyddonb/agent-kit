---
name: scaffold-product
description: Set up a repo for product work with agents, either a new product or an existing repo that predates this workflow. Writes the vision, decision log, phase specs, roadmap and agent instructions, then creates its verification skill, and checks the result with check-product.py. Use for "start a new product", "scaffold this repo", "adopt this repo into beau-mode", or when beau-mode's Product phase playbook finds no docs/VISION.md.
license: MIT
---

# Scaffold a product repo

Gives a repo the layout that beau-mode's **Product phase** playbook works from. Read [references/layout.md](references/layout.md) first: it says what each file is for and which rules the checker enforces.

Two modes. Pick by whether the repo already has code.

## New product (empty or nearly empty repo)

1. **Interview for the vision.** Ask about the problem, who has it, and what "good" would look like, one round of questions at a time (the **grilling** skill's style if it is installed). Stop when you can fill the goals table with measurable rows. Don't invent goals: every row comes from an answer.
2. **Copy the templates** from [references/templates/](references/templates/) into the repo root, keeping their paths. Rename `docs/phases/P1-SLUG.md` to `P1-<slug>.md`. Fill every `{{...}}` placeholder from the interview. Leave none.
3. **Spec the first phase** as the smallest slice that delivers one goal end to end. Its first PR sets up the skeleton and the verification skill.
4. **Record the first decisions** (stack, layout, hosting) in `docs/DECISIONS.md` as `Proposed` until the human accepts them.
5. Continue at **Both modes**.

## Adopt an existing repo

The code and its history are the evidence. Draft from them; the human confirms in the PR.

1. **Read before you write.** Run the **how** skill over the repo, or read the code and `git log` yourself if it isn't installed. Read the README, any existing AGENTS.md, CLAUDE.md, `.cursor/` rules, decision records, PRDs, plans and TODO files.
2. **Map what exists onto the layout.** Make a table: each existing doc, which layout file it becomes, and whether you move, merge or leave it. Move rather than duplicate, but never delete a file: list files you think should go (for example plans for finished work) as proposed deletions in the PR body. Architecture, API and reference docs stay in `docs/` and are linked from AGENTS.md's read order.
3. **Draft the vision from evidence.** Mark every statement a person hasn't confirmed with `(draft, from <source>)`. A target nobody has measured says so: "target, not measured". Don't invent goals the evidence doesn't support.
4. **Reconstruct the roadmap.** Everything already shipped becomes one phase, P0, with status Done. If the repo had its own phase numbers, keep them as a table inside P0's spec rather than renumbering. Each checked acceptance box says how it was checked: `(ran: <command>)` or `(read: <file>)`. Add P1 onward only where the evidence names planned work. A roadmap with only P0 is valid.
5. **Decisions.** If the repo has decision records in another format (for example `docs/decisions/NNN-*.md`), keep the files and give each one an entry in `docs/DECISIONS.md`: heading, status line, the decision in one sentence, and a link. Don't pad the other fields. Then back-fill decisions the code embodies but nobody recorded (language, storage, framework) as `Accepted` with the date of the commit that made them, citing it. Run the **why** skill if the reason isn't obvious.
6. **Instruction files.** Fold the rules from the old AGENTS.md or CLAUDE.md into the new AGENTS.md. Move reference material (API tables, test patterns) to a doc in `docs/` and link it. `CLAUDE.md` becomes exactly `@AGENTS.md`.
7. **README.** Keep it. Add a status line that matches `ROADMAP.md`, and replace any roadmap table it carries with a link. Fix stale facts you can confirm from the code, and list the rest in the PR body.

## Both modes

1. **Verification skill.** If there's no `verify-<app>` skill, run **create-verification-skill**. `<app>` is the repo's folder name. AGENTS.md names it.
2. **agentfiles profile.** If the user has agentfiles (`~/.agents/roles.yaml` exists, or another repo has `.agentfiles.yaml`), copy [references/templates/.agentfiles.yaml](references/templates/.agentfiles.yaml) to the repo root and fill it.
3. **Check.** Run `python3 <this skill's folder>/scripts/check-product.py <repo>` and fix every line it prints. 0 problems is the bar. It also counts `(draft` markers: those stay until the human confirms them.
4. Run beau-mode's **Opening a PR** playbook: one PR for the scaffold, separate from any feature work. In adopt mode the PR body carries the mapping table, the drafted goals, proposed deletions and open questions, and the human confirms drafts by reviewing it. A follow-up PR removes the `(draft` markers they confirm.

**Reply:** the mode, the file mapping (adopt) or the goals (new), the checker's output with its draft count, open questions for the human, and the PR link.
