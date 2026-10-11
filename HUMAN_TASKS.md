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
| H9 | Share the three Poteto posts | To do |
| H10 | Review and merge the bstack branch | 🚧 **BLOCKER** for agentfiles' builder profile |

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

### H9. Share the three Poteto posts
**Why a human:** X blocks automated reading, so the bstack build used pstack's code and
guide but not these posts:
`x.com/poteto/status/2102050467505430555`, `x.com/poteto/status/2108290818746528017` and
`x.com/poteto/status/2094457600259842065`.
**Steps:** Paste their text into a session and ask for anything they add to be folded into
bstack.

### H10. Review and merge the bstack branch — 🚧 BLOCKER for agentfiles
**Why a human:** Merging to `main` publishes the change, and agentfiles' `builder` profile
installs `bstack@agent-kit` from GitHub.
**Steps:** Review the `feat/bstack` branch (start with `docs/BSTACK.md` and
`plugins/bstack/skills/beau-mode/SKILL.md`), merge it, then run `agentfiles lock` in agentfiles.
