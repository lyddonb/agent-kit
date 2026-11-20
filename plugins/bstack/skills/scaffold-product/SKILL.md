---
name: scaffold-product
description: Set up a repo for product work with agents, either a new product or an existing repo that predates this workflow. Writes the vision, decision log, phase specs, roadmap and agent instructions, then creates its verification skill, and checks the result with check-product.py. Use for "start a new product", "scaffold this repo", "adopt this repo into beau-mode", or when beau-mode's Product phase playbook finds no docs/VISION.md.
license: MIT
---

# Scaffold a product repo

Gives a repo the layout that beau-mode's **Product phase** playbook works from. Read [references/layout.md](references/layout.md) first: it says what each file is for and which rules the checker enforces.

Three modes. Pick by whether the repo already has code, and whether it already has this layout.

## New product (empty or nearly empty repo)

1. **Interview for the vision.** Ask about the problem, who has it, and what "good" would look like, one round of questions at a time (the **grilling** skill's style if it is installed). For each goal also ask what measures it (how they would read where it stands today), what moves it (the lever: something they can change), and the first move on that lever. Stop when you can fill every cell of the goals table. Don't invent goals, measures or levers: every cell comes from an answer.
2. **Copy the templates** from [references/templates/](references/templates/) into the repo root, keeping their paths. Rename `docs/phases/P1-SLUG.md` to `P1-<slug>.md`. Fill every `{{...}}` placeholder from the interview. Leave none.
3. **Spec the first phase** as the smallest slice that delivers one goal end to end. Its first PR sets up the skeleton and the verification skill.
4. **Record the first decisions** (stack, layout, hosting) in `docs/DECISIONS.md` as `Proposed` until the human accepts them.
5. Continue at **Every mode**.

## Adopt an existing repo

The code and its history are the evidence. Draft from them; the human confirms in the PR.

1. **Read before you write.** Run the **how** skill over the repo, or read the code and `git log` yourself if it isn't installed. Read the README, any existing AGENTS.md, CLAUDE.md, `.cursor/` rules, decision records, PRDs, plans and TODO files.
2. **Map what exists onto the layout.** Make a table: each existing doc, which layout file it becomes, and whether you move, merge or leave it. Move rather than duplicate, but never delete a file: list files you think should go (for example plans for finished work) as proposed deletions in the PR body. Architecture, API and reference docs stay in `docs/` and are linked from AGENTS.md's read order.
3. **Draft the vision from evidence.** Mark every statement a person hasn't confirmed with `(draft, from <source>)`. A target nobody has measured says so: "target, not measured". Don't invent goals the evidence doesn't support. Draft each goal's Measure, Lever and First move the same way, from what the repo already counts and what its roadmap does next. A cell the evidence can't fill says `Not known (draft)` and becomes an open question in the PR.
4. **Reconstruct the roadmap.** Everything already shipped becomes one phase, P0, with status Done. If the repo had its own phase numbers, keep them as a table inside P0's spec rather than renumbering. Write what already works as P0's criteria and anti-criteria, each with its probe, and check a box only with `Evidence:` saying how you checked it (`Evidence: ran <command>` or `Evidence: read <file>`). Leave P0's `**Confirmed.**` line as `Not yet`; the human confirms it in the PR. Add P1 onward only where the evidence names planned work. A roadmap with only P0 is valid.
5. **Decisions.** If the repo has decision records in another format (for example `docs/decisions/NNN-*.md`), keep the files and give each one an entry in `docs/DECISIONS.md`: heading, status line, the decision in one sentence, and a link. Don't pad the other fields. Then back-fill decisions the code embodies but nobody recorded (language, storage, framework) as `Accepted` with the date of the commit that made them, citing it. Run the **why** skill if the reason isn't obvious.
6. **Instruction files.** Fold the rules from the old AGENTS.md or CLAUDE.md into the new AGENTS.md. Move reference material (API tables, test patterns) to a doc in `docs/` and link it. `CLAUDE.md` becomes exactly `@AGENTS.md`.
7. **README.** Keep it. Add a status line that matches `ROADMAP.md`, and replace any roadmap table it carries with a link. Fix stale facts you can confirm from the code, and list the rest in the PR body.
8. **REVIEW.md.** Draft it from what reviews of this repo have caught: review comments on merged PRs, fix commits that follow a review, and reverts in `git log`. Mark each line `(draft, from <source>)`. Leave out what CI already enforces.

## Upgrade a repo on the older spec format

A repo scaffolded before bstack 0.11.0 has phase specs with an `## Acceptance` checklist and no ideal state. `check-product.py` names each spec that needs this.

1. For each spec, rename `## Acceptance` to `## Criteria` and give each box an id (`**C1.**`, `**C2.**`...) and a `Probe:`. Keep the wording. Checked boxes keep their evidence, written as `Evidence: ...`.
2. Add `## Anti-criteria` with what must never happen in that phase, drafted from the spec's Rules, the AGENTS.md rules and past bug fixes in `git log`. Mark each `(draft, from <source>)`.
3. Add `## Ideal state` with the three levels, drafted from the outcome and marked `(draft, from <source>)`, and `**Confirmed.** Not yet.`
4. Open one PR with only these changes. A phase that is Planned, Building, In progress or Gated fails the checker until a person confirms its levels 1 and 2, so ask for that in the PR body and record the answer on the `**Confirmed.**` line. Done phases don't need it until new criteria reopen them.

## Add measure, lever and first move to the goals

A `docs/VISION.md` written before bstack 0.22.0 has a goals table without the Measure, Lever and First move columns. `check-product.py` prints a `note:` for it and fails nothing. Do this when the human asks for it, or when the vision is being rewritten anyway. Don't start it because the note appeared.

1. Add the three columns to the goals table. From then on the checker fails any goal row with one of them empty.
2. Fill each cell from evidence and mark it `(draft, from <source>)`: the phase specs that serve the goal, the roadmap's next phase, numbers the repo already records. A cell the evidence can't fill says `Not known (draft)`. Never write a measure nobody can read or a lever nobody can pull.
3. Open one PR with only this change. Its body lists each `Not known` cell as a question for the human, who confirms or replaces the drafts.

## Every mode

1. **Verification skill.** If there's no `verify-<app>` skill, run **create-verification-skill**. `<app>` is the repo's folder name. AGENTS.md names it.
2. **agentfiles profile.** If the user has agentfiles (`~/.agents/roles.yaml` exists, or another repo has `.agentfiles.yaml`), copy [references/templates/.agentfiles.yaml](references/templates/.agentfiles.yaml) to the repo root and fill it.
3. **Check.** Run `python3 <this skill's folder>/scripts/check-product.py <repo>` and fix every problem it prints. 0 problems is the bar. It also counts `(draft` markers: those stay until the human confirms them. A `note:` line is not a problem: report it and leave it.
4. Run beau-mode's **Opening a PR** playbook: one PR for the scaffold, separate from any feature work. In adopt mode the PR body carries the mapping table, the drafted goals, proposed deletions and open questions, and the human confirms drafts by reviewing it. A follow-up PR removes the `(draft` markers they confirm.

**Reply:** the mode, the file mapping (adopt) or the goals (new), the checker's output with its draft count, open questions for the human, and the PR link.
