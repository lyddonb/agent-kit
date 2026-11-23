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
| H11 | Review and merge the verification and planning branch | **Done** |
| H12 | Create a verification skill in one real app | Steps 1 and 2 **done** (R27); steps 3 and 4 to do |
| H13 | Protect workflow files and checker pins | Fix A in progress (run 2026-11-22-protect-gates); steps 1 to 6 are yours |
| H14 | Allow hooks in agentfiles | 🚧 **BLOCKER** for ROADMAP R32 |
| H15 | Allow a weekly job to read local transcripts for skill use | **Done** (yes) |
| H16 | Decide where the change record check enforces | agent-kit **enforced**; the other three to do |

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

### H11. Review and merge the verification and planning branch — Done
Merged 2026-10-11 as pull requests 4 and 5. agentfiles' lock has moved past it since.

### H12. Create a verification skill in one real app — steps 1 and 2 done
**Why a human:** It runs against your app, its dev setup and its test accounts, and you decide
which app goes first.
**Steps:**
1. In the app's repo, run `/create-verification-skill`. Have test users and seed data ready, or
   tell the agent where they come from.
2. Review and merge its PR (the `verify-<app>` skill, the feature map and the control CLI).
3. Use it for a week: `/beau-mode` bug fixes and features will verify through it.
4. Schedule `/maintain-verification-skill` daily for that repo with your tool's scheduler
   (for example a Claude Code scheduled task or a Cursor automation).

**Status (2026-11-21):** R27 did steps 1 and 2 on the runtime's own repos: `verify-ledger`
(agent-ledger pull request 23), `verify-kit` (pull request 62 here) and `verify-quality` (the
quality books' pull request 19) are merged. Step 4, the daily `/maintain-verification-skill`
schedule for each, is yours and was not confirmed when this was written. R18 no longer waits on
this task: its own trigger is two apps with verification skills and local lanes colliding.

### H13. Protect workflow files and checker pins
**Status (2026-11-22):** Run `2026-11-22-protect-gates` (its charter and ledger are in the quality
repo, approved by you) is moving `books` and `change-record` to read their workflow and checker pin
from `main`, through `pull_request_target`, in quality, finances and agent-ledger. It is also adding
a base-branch `change-record` check to agent-kit. The name gap is closed: a pull request can't outvote
a base-branch run with a job of the same name (`docs/ARCHITECTURE.md`, "The name gap is closed").
That run fixes only checks that read files. Everything else here needs you.
**Why a human:** Rulesets, collaborators and accounts need repo admin, and the choice of who may
approve a workflow change is yours.
**Steps:**
1. **Require agent-kit's `change-record`.** Wait for the agent-kit pull request that adds
   `.github/workflows/change-record.yml` to merge, and for that check to pass on a later pull
   request. Then add `change-record` (GitHub Actions) to the required checks of the "protect main"
   ruleset. Until you do, it runs but blocks nothing. Afterwards an agent removes the duplicate
   step from `validate.yml`.
2. **Require agentfiles' `test`.** Its ruleset requires no checks today, so a red run doesn't
   block a merge.
3. **Decide whether agents get a GitHub identity of their own.** Nothing else in this task can
   protect `validate`, `test` or the workflow files themselves, because agents act as you. With a
   second account, a code owner review means something. The parts:
   - a machine account (GitHub allows one per person), given Write, not Admin, on the five repos;
   - agent sessions that use its SSH key and `gh` login and can't reach yours. They run as your
     macOS user today and can read your keychain, so this needs a separate user or a sandbox;
   - a `CODEOWNERS` file naming you for `.github/workflows/**` (an agent can open that pull request);
   - in each ruleset, "Require review from Code Owners", plus "Repository admin" on the bypass list
     set to "For pull requests only", so that you can still merge your own workflow changes.

   Not checked on these repos: how code owner review behaves while required approvals stay at 0.
4. **Only after step 3, and if you want it:** a push ruleset in quality and finances that
   restricts `.github/workflows/**`, with Repository admin on the bypass list. Push rulesets exist
   only for private repos. First check that Settings → Rules → Rulesets → New ruleset offers "New
   push ruleset" on this account. Before step 3 it stops nothing, because agents are the admin.
5. **Know the limit on the Mac runner.** quality and finances run their checks on `local-mac`,
   which persists between jobs and runs as you. A pull request that *attacks* the check, instead
   of loosening it by mistake, can tamper with the base-branch run there (`docs/ARCHITECTURE.md`,
   "On the Mac's self-hosted runner"). Closing that needs trusted jobs off that runner, on hosted
   runners once the spending limit allows, or on an ephemeral machine. Your call whether that's
   worth it while agents already run as you.
6. **If a base-branch check ever blocks every pull request:** `pull_request_target` runs only
   `main`'s copy, so a broken one also blocks the pull request that fixes it. Remove that check
   from the ruleset, merge the fix, and add the check back.

### H14. Allow hooks in agentfiles — 🚧 BLOCKER for R32
**Why a human:** A hook runs code on every matching event in every session. Turning that on is
your call, per machine.
**Steps:**
1. Read R32's charter when it is written. It lists the two hooks and what each runs.
2. Add `hooks` to `allow:` in your agentfiles profile, starting with the gate in `observe`.
3. After a week of observe logs with no false block, decide whether to move to `enforce`.

### H15. Allow a weekly job to read local transcripts for skill use — Done
**Answer (2026-11-19):** Yes. Beau's words: "yes to H15 and H6". The quality books' H6 got the same
yes. The limits in **Decide** below are the terms: counts and names only, no transcript text
booked, none leaves the Mac.
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

### H16. Decide where the change record check enforces
**Answer (2026-11-22):** Enforce now. Beau's words: "i want to enforce now". agent-kit
enforces from this pull request on. quality, finances and agent-ledger stay in observe until
the exempt list is widened (step 3).
**Why a human:** Enforcing turns a required check into a merge block. In agent-kit the step sits
inside `validate`, and quality requires `change-record` directly. Which repos block, and when, is
your call.
**What the observe run showed (review of 2026-11-22, PRs opened 2026-11-21 and 2026-11-22):**
- agent-kit: 15 PRs checked. 8 had a good record, 2 were bookkeeping only, 5 would have failed.
  All 5 were real: #76, #78, #81 and #85 change `quality.py` and its tests with no record, and #88's
  record cites commit 58bc6e8, which was rewritten before the push and is on no branch.
- agent-ledger: 3 would have failed. #32 and #33 touch only `docs/notes/` (noise). #35 was a
  closed scratch PR.
- finances: 1 would have failed, #29, which touches only `questions.md` (noise).
- quality: none failed in CI. The weekly brief PRs never ran the check: some came before it, and
  #38 hit the Actions spending limit. By their changed files they would fail every week: quality's
  touch `books/`, `briefs/` and `questions.md`; finances' touch `ledger/`, `briefs/` and
  `questions.md`.
**Recommendation:** Enforce in agent-kit now. In quality, finances and agent-ledger, widen the
exempt list first, then enforce. The list is `BOOKKEEPING` in
`plugins/bstack/skills/debrief/scripts/debrief.py`, so widening is an agent-kit PR plus a bump of
the pinned checker (951bae9) in each of the three repos. Wait for quality #39 and finances #31
(CI moves to the Mac) to merge, since they rewrite the check's line.
**Steps:**
1. Choose: enforce in agent-kit now, widen the list first, or keep observing.
2. ~~To enforce in agent-kit, drop `--observe` from `.github/workflows/validate.yml` line 41.~~ Done.
3. To enforce in the other three, drop `--observe` from the step's `run:` line in
   `.github/workflows/changes.yml`. After quality #39 and finances #31 merge, also drop it from
   the `debrief.py check` line in their `scripts/ci`.
4. Separately: fix claim 4 in `.changes/2026-11-21-no-comments.json` so it cites a commit on main.

