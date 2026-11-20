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
| H12 | Create a verification skill in one real app | 🚧 **BLOCKER** for ROADMAP R18, R27 |
| H13 | Protect workflow files and checker pins | To do (after R29 unit 1) |
| H14 | Allow hooks in agentfiles | 🚧 **BLOCKER** for ROADMAP R32 |
| H15 | Allow a weekly job to read local transcripts for skill use | 🚧 **BLOCKER** for ROADMAP R38 |

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

**Shortcut (November 2026):** R27 proposes agent-ledger as the first app, then agent-kit and
the quality books. None needs test accounts or seed data from you. Saying "go on R27" is the
decision; reviewing and merging the three PRs is the rest.

### H13. Protect workflow files and checker pins
**Why a human:** Rulesets and CODEOWNERS need repo admin, and you choose who may approve.
**Steps:**
1. Read R29's audit table once it merges (`docs/ARCHITECTURE.md`). It lists each gate a PR can
   currently change for itself.
2. For each repo it names, add a ruleset or CODEOWNERS entry so a change under
   `.github/workflows/**` (and the pinned checker SHA in the books repos) needs your review.

### H14. Allow hooks in agentfiles — 🚧 BLOCKER for R32
**Why a human:** A hook runs code on every matching event in every session. Turning that on is
your call, per machine.
**Steps:**
1. Read R32's charter when it is written. It lists the two hooks and what each runs.
2. Add `hooks` to `allow:` in your agentfiles profile, starting with the gate in `observe`.
3. After a week of observe logs with no false block, decide whether to move to `enforce`.

### H15. Allow a weekly job to read local transcripts for skill use — 🚧 BLOCKER for R38
**Why a human:** Transcripts hold everything you typed and everything an agent read. Whether a
scheduled job may read them, and what it may write down, is your call.
**Decide:** May the weekly Mac job (a second pass in cfo's `weekly-claude-code.sh`) read this
Mac's agent transcripts and book one row per skill invocation into the quality books? A row
holds the week, the skill, its source and version, the tool, how it was invoked, counts of tool
calls, tool searches and tool errors, and a verdict that stays `unjudged` for now. No transcript
text is booked and none leaves the Mac. A prototype has already read four weeks of transcripts
once, at your request, and printed counts and names only (R38 has what it found).
**Related, in other repos:** the quality books' H6 (is that repo private enough for skill names
and counts per week?), agentfiles H13 (are cfo's skills counted?), and agent-ledger H8 and H9
(when the evals that use these rows start, and whether they may spend model calls in CI).
**Unblocks:** R38, and through it R41 and agent-ledger's M3 unit 1.
