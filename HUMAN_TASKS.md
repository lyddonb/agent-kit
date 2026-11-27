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
| H8 | Dogfood beau-mode on real tasks | **Done** (2026-11-27): real runs in Claude Code and Cursor, and `/reflect` in each |
| H9 | Share the Poteto posts | **Done** (the pstack guide parts 1 and 2) |
| H10 | Review and merge the bstack branch | **Done** |
| H11 | Review and merge the verification and planning branch | **Done** |
| H12 | Create a verification skill in one real app | Steps 1 and 2 **done** (R27); steps 3 and 4 to do |
| H13 | Protect workflow files and checker pins | Fix A **done**, step 1 **done**; steps 2 to 7 are yours |
| H14 | Allow bstack to ship R32's hooks | **Done** (yes); review each hook in R32's pull request |
| H15 | Allow a weekly job to read local transcripts for skill use | **Done** (yes) |
| H16 | Decide where the change record check enforces | **Done**: all four repos enforce |
| H17 | Decide whether a judge model may score the context-loading evals | **Done**: R42 and R43 only, judged by `cli:cursor-agent:gpt-5.6-sol-high` through R11 |
| H18 | Choose where this machine keeps flags | **Done** on the first Mac (2026-11-26); repeat steps 1 and 2 on each new machine |

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

### H8. Dogfood beau-mode on real tasks — Done
**Answer (2026-11-27):** Done in both tools. Beau's words: "i've run the beau-mode feature and
investigation in cursor as well". In
Claude Code, a feature (agentfiles R16) and an investigation ("what's next") were run under
beau-mode, then `/reflect`; Beau approved all six edits, merged in bstack 0.53.0 (pull request
141). A bug run followed under the Bug fix playbook: the agentfiles sync misreport, which
reproduced as already fixed by agentfiles pull request 43, so it stopped with no change. In
Cursor, every task in one private project ran under beau-mode, with `/reflect`.
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
**Status (2026-11-22):** Fix A is done. Run `2026-11-22-protect-gates` (its charter and ledger
are in the quality repo) moved `books` (quality, finances) and `change-record` (quality, finances,
agent-ledger, agent-kit) to run only `main`'s workflow and checker on a pull request, through
`pull_request_target`. Two closed scratch PRs proved it: each gutted its own copy of the check,
and `main`'s copy still blocked the merge. The name gap is closed (`docs/ARCHITECTURE.md`, "The
name gap is closed"). Fix A covers only checks that read files. Steps 2 to 7 are yours.
**Why a human:** Rulesets, collaborators and accounts need repo admin, and the choice of who may
approve a workflow change is yours.
**Steps:**
1. ~~**Require agent-kit's `change-record`.**~~ Done 2026-11-22: it is required, and the duplicate
   step left `validate.yml` (agent-kit PR 99).
2. **Require `change-record` in finances and agent-ledger.** It runs only from `main` there now
   and enforces (H16), but neither ruleset requires it, so a red run doesn't block a merge.
   quality and agent-kit already require it.
3. **Require agentfiles' `test`.** Its ruleset requires no checks today, so a red run doesn't
   block a merge.
4. **Decide whether agents get a GitHub identity of their own.** Nothing else in this task can
   protect `validate`, `test` or the workflow files themselves, because agents act as you. With a
   second account, a code owner review means something. The parts:
   - a machine account (GitHub allows one per person), given Write, not Admin, on the five repos;
   - agent sessions that use its SSH key and `gh` login and can't reach yours. They run as your
     macOS user today and can read your keychain, so this needs a separate user or a sandbox;
   - a `CODEOWNERS` file naming you for `.github/workflows/**` (an agent can open that pull request);
   - in each ruleset, "Require review from Code Owners", plus "Repository admin" on the bypass list
     set to "For pull requests only", so that you can still merge your own workflow changes.

   Not checked on these repos: how code owner review behaves while required approvals stay at 0.
5. **Only after step 4, and if you want it:** a push ruleset in quality and finances that
   restricts `.github/workflows/**`, with Repository admin on the bypass list. Push rulesets exist
   only for private repos. First check that Settings → Rules → Rulesets → New ruleset offers "New
   push ruleset" on this account. Before step 4 it stops nothing, because agents are the admin.
6. **Know the limit on the Mac runner.** quality and finances run their checks on `local-mac`,
   which persists between jobs and runs as you. A pull request that *attacks* the check, instead
   of loosening it by mistake, can tamper with the base-branch run there (`docs/ARCHITECTURE.md`,
   "On the Mac's self-hosted runner"). Closing that needs trusted jobs off that runner, on hosted
   runners once the spending limit allows, or on an ephemeral machine. Your call whether that's
   worth it while agents already run as you.
7. **If a base-branch check ever blocks every pull request:** `pull_request_target` runs only
   `main`'s copy, so a broken one also blocks the pull request that fixes it. Remove that check
   from the ruleset, merge the fix, and add the check back.

### H14. Allow bstack to ship R32's hooks — Done
**Answer (2026-11-27):** Yes. Beau's words: "Yes. bstack may ship R32's Stop hook and commit
gate". Every gate still starts in `observe` (R32's own rule).
**Why a human:** A hook runs code on every matching event in every session. Turning that on is
your call.
**Where the switch is:** not where this task first said. On the first Mac, Claude Code installs
bstack from the agent-kit marketplace (agentfiles' `local.yaml` sends agent-kit only to Codex,
Cursor, OpenCode and pi), and Claude Code runs a marketplace plugin's hooks with no `allow:`
step. bstack's SessionStart hook (`whats_new.py`) already runs there. agentfiles' `allow:
[hooks]` gates only a Claude Code that gets bstack through agentfiles, and agentfiles installs
no plugin hooks in Codex, Cursor or pi yet (agentfiles R2). So the real gate is R32's pull
request: its hooks run once it merges and the plugin updates.
**Still yours, in R32's pull request:**
1. Read its `hooks/hooks.json` diff and every script it calls (agentfiles `docs/SECURITY.md`).
   Check every gate defaults to `observe`.
2. The same pull request adds `allow: [hooks]` to `mine:@bstack` in agentfiles'
   `profiles/personas/builder.yaml`, for machines that install Claude Code through agentfiles.
   Run `agentfiles sync` there after it merges.
3. After a week of observe logs with no false block, decide whether to move each gate to
   `enforce`. Setting a gate to `off`, or disabling bstack, turns it back off.
**Unblocks:** R32's charter. R32 still waits on R6 and its own trigger.

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

### H16. Decide where the change record check enforces — Done
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
3. ~~To enforce in the other three, drop `--observe` from the step's `run:` line in
   `.github/workflows/changes.yml`. After quality #39 and finances #31 merge, also drop it from
   the `debrief.py check` line in their `scripts/ci`.~~ Done: quality #46, finances #34 and
   agent-ledger #39 pin agent-kit 079eca5, add their `.changes/exempt` and enforce.
   - The exempt list is per repo, not a wider `BOOKKEEPING`: each repo names its data paths in
     `.changes/exempt`, read from the base branch (bstack 0.39.0). `BOOKKEEPING` also decides when
     a verify-work receipt goes stale, and `books/` and `ledger/` are data those checks must see.
     A replay of every PR since 2026-11-21 passed the brief and import PRs and still failed the
     code PRs with no record (`.changes/2026-11-22-exempt-list/replay.txt`).
   - Left open: four records merged under observe are `VERIFIED` with no `commit` (quality and
     finances `2026-11-22-local-ci.json` and `2026-11-22-drop-ledger-bootstrap.json`). A pull
     request that edits one fails until it names the commit its check ran on.
4. ~~Separately: fix claim 4 in `.changes/2026-11-21-no-comments.json` so it cites a commit on main.~~
   Done: the claim keeps 58bc6e8, the text the trial ran on, and the tag
   `trial/2026-11-21-no-comments` keeps that commit on GitHub. The claim now names the two changes
   in main's e548abb that were never tried.

### H17. Decide whether a judge model may score the context-loading evals — Done
**Answer (2026-11-26):** A judge may score R42 and R43, and no other eval. It runs through R11's
`second-opinion` script, not a pass run by hand in Cursor. Beau's words: "R42+R43 but build R11
instead of relying on grok". The judge is `cli:cursor-agent:gpt-5.6-sol-high` (Beau's words:
"GPT-5.6 Sol High"). R42 and R43 can run once R11 has merged.
**Why a human:** Skill ops says verdicts come from rules and exit codes, with no judge model
until you say so. R42 and R43 compare outputs on judgment tasks, which no exit code can score.
Allowing a judge for these two evals, and on which model, is your call. It also costs model calls.
**Decide:**
1. Allow a judge model for R42 and R43 only, for all Eval playbook runs, or not at all.
2. If allowed, which model judges. It should differ from the candidates' model, since Scribe's
   weak point was grading with the same model.
3. If not, R43 falls back to R25's rule: no cut without an agent-ledger M3 eval covering the text.
**Evidence (2026-11-25):** Uber's skill ablation uses a blind judge, a per-skill noise band from
identical runs, and a human-annotated set to check the judge. It reports most skills made
sessions better and cheaper, and the least help from skills that teach tool discovery. R43
now asks for the noise band. Its numbers are Uber's own.

### H18. Choose where this machine keeps flags — Done
**Why a human:** R45's rule writes a flag outside a governed run only when `~/.agents/flags.yaml`
names the repo that keeps them. Flags can name private context, so that repo is a private repo
you choose, and agents must not pick it. Until the file exists, agents list the flag in their
reply instead and nothing reaches the weekly pass, so R48 never gets its two weeks of flags.
**Steps (once per machine, except step 4):**
1. ~~Give the private repo a worktree of its own on a flags branch, so the week's uncommitted
   file never dirties the checkout other jobs use, and drop the branch's upstream so a bare
   `git push` can't reach main:~~ Done on the first Mac (2026-11-26).
   ```bash
   git -C <clone> worktree add <clone's .worktrees>/<repo>-flags -b flags/rolling origin/main
   git -C <that worktree> branch --unset-upstream flags/rolling
   ```
2. ~~Write `~/.agents/flags.yaml`, exactly two lines, single-quoted (the reference reads them with
   `sed`), with an absolute path (`~` isn't expanded) and a machine slug matching
   `[a-z0-9]+(-[a-z0-9]+)*`, different on each machine:~~ Done on the first Mac.
   ```yaml
   root: '/absolute/path/to/that/worktree'
   machine: 'macbook-air'
   ```
   Check it: `test -d "$(sed -n "s/^root: *'\(.*\)'$/\1/p" ~/.agents/flags.yaml)" && echo root-ok`.
3. ~~Decide who commits the week's flags run.~~ Done: agents leave it uncommitted, because
   several sessions append to one file. Once a week, whoever reads the flags (you, later the R48
   pass) commits on `flags/rolling`, pushes with an explicit refspec
   (`git push origin refs/heads/flags/rolling:refs/heads/flags/rolling`) and opens a PR.
4. ~~Move agentfiles' `ledger` pin to a release with the flag checks.~~ Done (2026-11-26): agent-ledger
   v1.3.0 (agent-ledger PR 46, tagged on its merge commit) and agentfiles PR 36 pin it, and after
   `agentfiles sync` the installed `ledger --version` prints `ledger 1.3.0`.
