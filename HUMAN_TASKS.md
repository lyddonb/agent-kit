# Human tasks

Things an agent cannot or should not do: creating accounts, publishing, spending money,
legal choices, and judgment calls. **🚧 BLOCKER** items block other work (listed under
"Unblocks"). Check items off as you go.

| # | Task | Status |
|---|---|---|
| H1 | Create and publish the GitHub repo | **Done** |
| H2 | Confirm the license | **Done** |
| H3 | Turn on GitHub Actions and branch protection | **Done** |
| H4 | Verify installs in each tool you use | **Skipped** |
| H5 | Decide what is public, and keep employer content separate | **Done** |
| H6 | Review the example skills | To do |
| H7 | Review beau-mode and unslop for your voice | To do |
| H8 | Dogfood beau-mode on real tasks | 🚧 **BLOCKER** for ROADMAP R10, R12, R13 |
| H9 | Share the Poteto posts | **Done** (the pstack guide parts 1 and 2) |
| H10 | Review and merge the bstack branch | **Done** |
| H11 | Review and merge the verification and planning branch | 🚧 **BLOCKER** for agentfiles picking it up |
| H12 | Create a verification skill in one real app | 🚧 **BLOCKER** for ROADMAP R18 |

---

### H1. Create and publish the GitHub repo — Done
**Why a human:** Needs your GitHub account and a choice of owner/visibility.
**Steps:**
1. Create `github.com/lyddonb/agent-kit` (or rename: then update `marketplace.repository`
   and `owner` in `kit.yaml`, run `make gen`, and search-replace `lyddonb/agent-kit` in docs).
2. From the unpacked scaffold:
   ```bash
   cd agent-kit
   git init -b main && git add -A && git commit -m "feat: initial agent-kit scaffold"
   git remote add origin git@github.com:lyddonb/agent-kit.git
   git push -u origin main
   ```
3. Tag the first release: `git tag v0.1.0 && git push --tags`.
**Unblocks:** H3, H4, R1 (ROADMAP), and every install command in the docs. agentfiles'
`mine` source also points at this repo.

### H2. Confirm the license — Done
**Why a human:** A legal choice. The scaffold assumes **MIT** (`LICENSE`, `kit.yaml`,
every `SKILL.md`). Confidential or employer-specific material stays out of this repo.
**Steps:** Keep MIT, or change `LICENSE` + `kit.yaml` `license` fields + skill
frontmatter, then `make gen`.

### H3. Turn on Actions and protect `main` — Done
**Why a human:** Repository settings.
**Steps:** Ensure Actions are enabled; add a branch protection rule requiring the
`validate` check to pass.

### H4. Verify installs in each tool you use — Skipped
**Why a human:** Needs your machines, logged-in apps, and judgment on what "works".
**Status:** Deferred for now. The steps below are unchanged when you pick this up.
**Steps:** Follow [docs/INSTALL.md](docs/INSTALL.md) for Codex, Cursor, pi, and any
others; note anything wrong in an issue. This is ROADMAP R1.
**Note:** Codex plugin enabling happens in the ChatGPT/Codex app UI; Cursor's flow for
adding a third-party plugin repo should be checked against its current docs.

### H5. Decide what is public, and keep employer content separate — Done
**Why a human:** Confidentiality and IP.
**Decision:** This repo stays personal and public, with generic public-safe skills only.
Employer-specific skills (internal systems, process docs, customer details) belong in a
separate private repo built from this same template (`kit.yaml` + `tools/`). Leadership
signed off on publishing standard engineering capabilities.

### H6. Review the example skills
**Why a human:** They were written by Claude as useful starting points. Read
`design-review`, `interview-kit`, `commit-message`, `handoff-notes`, and `library-docs`
and adjust them to how you actually work (for example, your real interview loop and
competencies, and your team's RFC template).

### H7. Review beau-mode and unslop for your voice
**Why a human:** They encode personal style, and they were written from pstack plus what
you have said, not from watching you work.
**What to check:**
- `plugins/bstack/skills/beau-mode/SKILL.md`: the Autonomy rules (what may proceed without
  asking, what always pauses), the reply style, and the non-negotiables. Delete anything that
  isn't you.
- `plugins/bstack/skills/unslop/SKILL.md` is Lauren Tan's standard almost unchanged. It bans
  em dashes and mid-sentence colons, which is a taste call. Keep, loosen or drop those rules.
- The 24 principles in `plugins/principles/`. Remove any you disagree with rather than
  leaving rules agents will follow that you don't believe.

### H8. Dogfood beau-mode on real tasks — 🚧 BLOCKER for R10, R12, R13
**Why a human:** Only real work shows what the skill gets wrong.
**Steps:** Run `/beau-mode` on a real bug, a feature and an investigation in Claude Code and in
Cursor. After each, run `/reflect` and approve or reject its proposals. Note anything that felt
slow or heavy.

### H9. Share the Poteto posts — Done
You pasted "The complete guide to pstack" parts 1 and 2. They were folded in on
`feat/bstack-verification-and-planning`. The three original status posts were not pasted; if
they add anything beyond the guide, paste them the same way.

### H10. Review and merge the bstack branch — Done

### H11. Review and merge the verification and planning branch — 🚧 BLOCKER for agentfiles
**Why a human:** Merging to `main` publishes it.
**Steps:** Review `feat/bstack-verification-and-planning` (start with `docs/BSTACK.md`,
`create-verification-skill` and the Multi-phase plan playbook), merge it, then in agentfiles run
`agentfiles lock` (or bump `mine` in `agentfiles.lock`) and `agentfiles sync`.

### H12. Create a verification skill in one real app — 🚧 BLOCKER for R18
**Why a human:** It runs against your app, its dev setup and its test accounts, and you decide
which app goes first.
**Steps:**
1. In the app's repo, run `/create-verification-skill`. Have test users and seed data ready, or
   tell the agent where they come from.
2. Review and merge its PR (the `verify-<app>` skill, the feature map and the control CLI).
3. Use it for a week: `/beau-mode` bug fixes and features will verify through it.
4. Schedule `/maintain-verification-skill` daily for that repo with your tool's scheduler
   (for example a Claude Code scheduled task or a Cursor automation).
