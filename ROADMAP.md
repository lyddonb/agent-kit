# Roadmap

Work that is planned but intentionally **not** done in the initial scaffold. Each item
says why it was deferred and what would trigger doing it.

**Priority key:** **P0** do before relying on the repo daily · **P1** next, high value ·
**P2** worthwhile once there is real usage · **P3** only if a need appears.

Items needing a person (accounts, publishing, decisions) live in
[HUMAN_TASKS.md](HUMAN_TASKS.md), not here.

---

## P0

### R1. Verify installs end-to-end in each real client
**What:** Install from the published GitHub repo in Codex (CLI + app), Cursor, Copilot
in VS Code, and pi; confirm each skill appears and `research-tools`' MCP server connects.
Record results in a table in `docs/INSTALL.md`.
**Why not done:** The scaffold was built and tested in a sandbox with only the Claude
Code CLI available. Claude Code installs (marketplace, all three plugins, MCP) were
verified there; the others are written from current vendor docs but not exercised.
**Effort:** ~1 hour.
**Status (2026-11-27):** Codex CLI and Cursor CLI done; results are in
[docs/INSTALL.md, Tested installs](docs/INSTALL.md#tested-installs). Codex CLI 0.172.0
installs all 7 plugins from GitHub, and its skills and context7 load. Cursor loads every
skill from a clone; its marketplace install and MCP are unproven. The Codex app, Cursor
app, Copilot in VS Code, pi and OpenCode wait on Beau in HUMAN_TASKS H4.

## P1

### R2. Release automation
**What:** A `release` workflow that, on tag `vX.Y.Z`, checks every plugin version in
`kit.yaml` was bumped since the last tag when its files changed, and creates a GitHub
release with a changelog generated from Conventional Commits.
**Why not done:** No release has happened yet; the convention should be proven
manually once first (see AUTHORING.md "Versioning").
**Prioritize when:** a second person contributes, or after the third manual release.

### R3. Skill evals
**What:** Add `evals/` per plugin and run `claude plugin eval` in CI on changed
plugins (prompt cases + graders), so description changes that break triggering are caught.
**Why not done:** Evals need real prompts drawn from use; inventing them up front
produces tests of the wrong things. They also cost API tokens in CI (needs a secret).
**Prioritize when:** a skill misfires (does not trigger, or triggers wrongly) twice. Review
evals get their cases from R34's escapes book. The wait for real prompts ends with R38, which
shows which sessions invoked a skill. The first evals are the tool-call checks in agent-ledger's
M3 unit 1. Their criteria live in this repo and they need no `evals/` tree. Its trigger
replaces this one for those checks: R38 has four weeks of rows, or beau-mode's non-negotiables
are about to change. The triggering evals above are still planned and draw on the same
sessions.

### R4. `skills-ref validate` in CI
**What:** Run the reference validator from the Agent Skills project alongside
`tools/validate.py`.
**Why not done:** Its install method and CLI were not verified in the sandbox; our
validator already covers the spec's frontmatter rules.
**Prioritize when:** the spec changes (new required fields or constraints).

## P2

### R5. Codex and Cursor overlays
**What:** Let `kit.yaml` carry Codex `interface` metadata (display name, icon, default
prompt) under `extensions.com.openai`, and Cursor-specific metadata, so plugins look
polished in those directories.
**Why not done:** Cosmetic. Codex and Cursor load the plugins fine without it, and the
exact overlay shape should be copied from a working example rather than guessed.
**Prioritize when:** publishing to a public or team directory.

### R6. Client-specific hooks across tools
**What:** A neutral hook definition in `kit.yaml` emitted as Claude `hooks/hooks.json`,
Codex `hooks.json`, and Cursor `hooks/hooks.json`.
**Why not done:** No plugin here needs hooks yet, hooks are the least portable component
(different events and payloads per tool), and they carry the most risk (they run code
on every matching event).
**Prioritize when:** there is a concrete hook worth having in at least two tools. R32 (a Stop
hook for cheap checks and a commit gate) was the first concrete case, and shipped without this:
both of its hooks are Claude Code only, and Claude Code reads a plugin's hand-written
`hooks/hooks.json`, so the Claude Code half would only regenerate that file. This waits for a hook
worth having in a second tool, which also needs agentfiles R2 (native plugin installs there).

### R7. Bundled stdio MCP server example
**What:** A plugin that ships its own small MCP server (e.g. an internal API
reader) to exercise the `./bin/...` + `${PLUGIN_DATA}` path translation.
**Why not done:** The only MCP need so far is remote (Context7). The translation code
exists and is unit-testable, but there is no real server to ship.
**Prioritize when:** a skill needs API access that a CLI script cannot provide.

## P3

### R8. Submit to public directories
**What:** Submit selected plugins to Anthropic's plugin directory, the Codex plugin
directory, and Cursor's marketplace.
**Why not done:** Requires public-facing polish, support commitments, and listing
fields (privacy policy, support URL). Only worth it for plugins others will use.
**Prioritize when:** a plugin is useful beyond you (and see H5).

### R9. Split heavy plugins into their own repos
**What:** Move a plugin with its own build (e.g. a compiled MCP server) to a separate
repo and reference it from the marketplace with a git source.
**Why not done:** No plugin has its own build. Splitting early multiplies release work.
**Prioritize when:** a plugin needs its own CI, dependencies, or release cadence.

---

# bstack and principles

Work deferred from the first bstack build (October 2026). The first build ported the parts
that matter most for daily rigor; these are the rest, in priority order.

## P0

### R10. Tune beau-mode from real use
**What:** Use `/beau-mode` on at least three real tasks (one bug, one feature, one
investigation) in Claude Code and Cursor, then run `/reflect` after each and merge the
approved edits.
**Why not done:** `beau-mode` is written from pstack's poteto-mode and what Beau has said
about how he works. Only real sessions show which rules are wrong for him. Inventing
evidence would overfit.
**Status (2026-11-27):** open. H8 is done, and the first round is merged: a `/reflect` on a
Claude Code session gave six edits, which Beau approved and which shipped in bstack 0.53.0
(pull request 141). R12 and R13 now wait only on their own triggers. Rounds after each further
real task are what remain.

## P1

### R11. Cross-model reviewers through other agents' CLIs
**Done 2026-11-26** in bstack 0.47.0 (pull request 121). The beau-mode skill's `scripts/second_opinion.py` sends one
prompt, read-only, to `claude` or `cursor-agent` and returns a checked answer or a named failure.
A roles-file entry `cli:<agent>:<model>` names one, and the roles rules say how to run it. The
contract is `plugins/bstack/skills/beau-mode/references/second-opinion.md`. It came ahead of its
own trigger because Beau chose it as the judge route for R42 and R43 (HUMAN_TASKS H17).
**Still open:** `codex exec` and `pi -p`. Measured 2026-11-26: `codex exec` exits 0 with an empty
answer when its sign-in fails, so it needs real runs on a signed-in machine first. A
`cursor-agent` reviewer has the user's rules loaded, and no flag turns that off. No profile sets a
`cli:` entry yet, so no panel changed.

### R12. `automate-me`: refine beau-mode from transcripts
**What:** Port pstack's automate-me. Mine the current project's transcripts (with
`find-transcripts.py`) for repeated preferences and corrections, ask which ones are really
Beau's, and propose edits to `beau-mode`.
**Why not done:** It needs a few weeks of sessions that used beau-mode to have anything
worth mining.
**Prioritize when:** R10 has run and corrections start repeating.

### R13. Evals for bstack
**What:** Run the Eval playbook comparing beau-mode against no mode on three organic tasks,
and add `claude plugin eval` cases that check `beau-mode`, `verify-work` and `interrogate`
trigger on the right prompts and stay quiet on casual ones.
**Why not done:** Same reason as R3: good eval prompts come from real use. Also costs model
calls in CI.
**Prioritize when:** before changing beau-mode's description or core rules, or after R10.
`interrogate`'s cases come from R34. The hard rules (a rule an agent must never break, checked
on its tool calls) are agent-ledger's M3 unit 1, and its trigger replaces this one for them:
R38 has four weeks of rows, or beau-mode's non-negotiables are about to change. The Eval
playbook comparison and the triggering cases stay here and draw their sessions from R38.

### R14. Adopt upstream's distillation in the older bstack files
**What:** Upstream commit 00b14f1 tightened the prompts of principles, reflect, unslop and
why. `why` came over already distilled (ported at 11713c6). Diff the rest against
`agentfiles update pstack --diff` and adopt what keeps meaning while cutting words.
**Why not done:** It is Beau's call (agentfiles' HUMAN_TASKS, "Review the pending pstack changes"), and the gain is
shorter prompts, not new behavior.
**Prioritize when:** before the next round of beau-mode tuning (R10), so edits land on the
current text.

### R22. Spec drift gate: CI first, then a hook
**What:** `check-product.py --base REF` fails a PR that changes source files but neither
changes a phase spec nor cites a criterion id (`P1-C3`) in its commits or body. Ship it as a
CI step in the scaffold templates so it holds in every tool. Then, behind agentfiles'
`allow: [hooks]`, an optional Claude Code hook that stops an edit when the session hasn't read
the active spec.
**Why not done:** The rule needs criterion ids (now in place) and a tuned list of paths that
count as source. A hook alone would only hold in Claude Code (see R6).
**Prioritize when:** a merged PR changes behavior a spec doesn't describe. Criterion receipts, which
this was waiting on, shipped in bstack 0.13.0. Ship it in observe mode first (R32).

### R23. Rejections sharpen the criteria
**What:** When the human rejects work whose checks passed, the agent records a `rejection`
ledger entry: what was rejected, the criterion or probe that was missing, and the new
criterion it added. `reflect` and `correct` read past rejections across sessions, not only
the current transcript, and a fix counts only when the new probe fails on the rejected work
and passes on the fix. This is the persistent complaint log (ERRATA in the source thread).
**Why not done:** The Product phase playbook now does this inside one spec; a cross-session
log needs the `rejection` entry type in agent-ledger.
The entry also names what the agent read that turned out not to matter (`misled_by`: a
skill, reference or file id, never transcript text), so rejections list the distractors per
skill over time (R42, R43). Knowledge factory flags carry the same field.
**Prioritize when:** the same kind of rejection happens twice.

### R26. The round cap and the two-fix trigger, checked against a real case
**What:** bstack 0.21.0 shipped the three-round cap (Bug fix, Feature, Autonomous run) and the
Bug fix trigger that sends two fixes that didn't hold to `root-cause`. Three things are open.
The trigger was worded without a real case: in 5 fixture runs the agent stopped patching and
found the cause from facts itself, and never ran the `root-cause` skill. And the Perf issue
playbook has no cap: one fixture run on it kept patching a latency check and reran it eight
times until it passed. Its fix ladder has seven rungs, so three rounds may be the wrong number.
Third, agents miscount: two runs that stopped after two rounds said they had made three, and
one counted the user's two fixes and stopped at two. The snippet may need to say that several
fixes checked by one run are one round.
**Where:** `plugins/bstack/snippets/round-cap.md`, `playbooks/bug-fix.md`, `playbooks/perf-issue.md`.
**Playbook:** Authoring a skill.
**Why not done:** No fixture got an agent past two rounds, so the third-round stop itself has
only been seen reported, not forced.
**Prioritize when:** the first real session where a third patch lands or a check is rerun
until it passes.

## P2

### R15. `lead-mode` for engineering leadership work
**What:** A second router with playbooks for leadership work: a hiring loop end to end, a
design review round, quarterly planning, incident communication, 1:1 preparation. It
reuses the principles and the `eng-leadership` skills.
**Why not done:** Deferred by choice. pstack has nothing in this area, so it is new design,
and it should follow once beau-mode has settled.
**Prioritize when:** beau-mode has had a month of use, or a leadership workflow repeats weekly.

### R16. Knowledge base integration
**What:** Make a knowledge base the source of truth for principles, playbooks and
conventions, and give agents a KB MCP server to query while they work. Design notes and the
seams that already exist: [docs/KNOWLEDGE.md](docs/KNOWLEDGE.md).
**Why not done:** Planned as its own follow-up project.
**Prioritize when:** the KB has an MCP interface. R42 lands first: no KB reaches beau-mode without its eval.

### R17. The remaining pstack playbooks
**What:** Babysit and Shipping (drive PRs to merged), Hillclimb (loop on one metric),
Visual parity, runtime and trace forensics, Orchestrate and the autopilot pair (fleets of
PRs), and worktree cleanup.
**Why not done:** They depend on forge, CI and UI-driving tools that differ per setup, and
on trust that has to be earned with the core playbooks first (pstack's own guide says the same).
**Prioritize when:** you start leaving multi-PR work running overnight.

### R18. Verification at scale: cloud lanes and automatic repros
**What:** Three things the pstack guide does once every app has a verification skill:
run **swarm** lanes on cloud agents instead of local worktrees (no port or CPU contention);
set up the daily **maintain-verification-skill** schedule per app automatically (today the
human creates it, HUMAN_TASKS H12); and an automation that takes a user
report (Slack, a ticket), reproduces it through the verification skill, and posts the
evidence back.
**Why not done:** The skills are tool-neutral, but cloud agents, schedules and chat triggers
are per tool and per org (Cursor background agents, Claude Code scheduled tasks, Codex
cloud). Each needs a verification skill in a real app first (agent-kit H12, which R27 closes
on the runtime's own repos).
**Prioritize when:** two apps have verification skills and local lanes start colliding.

### R19. A shared transcript script
**What:** `recall` calls `reflect`'s `find-transcripts.py` by its sibling folder. Move the
script to a small shared location (or have kitgen copy it into each skill that needs it) so
installing one skill alone still works.
**Why not done:** Both skills ship in bstack and install side by side in every supported tool,
so the sibling path works today.
**Prioritize when:** someone installs `recall` without `reflect`, or R38's weekly pass needs
the script outside `reflect`.

### R25. Skills describe outcomes; cut steps a smarter model wouldn't need
**What:** Audit each bstack skill and playbook with one test: would a stronger model need
this step? Keep steps that enforce a gate, a verification or a record (those are the point).
Cut steps that only teach how. The audit also covers the always-on block agentfiles writes
(the mode plus profile `instructions:`), which every session pays for.
**Method:** Ablation. A cut is proposed with the results of the evals from agent-ledger's M3
unit 1 before and after it, and the always-on and per-skill token count before and after it.
Text that no eval covers is not cut.
**Why not done:** Playbooks are step-by-step on purpose, so weaker models in Codex or pi
still hit the gates. Cutting needs evidence from runs in more than one tool (R10, R13).
**Prioritize when:** agent-ledger's M3 unit 1 has an eval covering the text to cut (R13's cases
add to them), so a cut can be shown not to lose a gate. R35's monthly prune brief supplies the
size numbers, and R41 adds uses per skill. R43 can propose the first cut to beau-mode's
always-on text.

---

# video

## P1

### R20. `frame-review`: mark up frames and send the regions back to the agent
**What:** A command that blocks until a person has reviewed a set of images.
`review <images> --scenes scenes.json` opens a local page. The person drags a box around
anything they want changed and types a note. On submit the command prints the review as JSON
and exits. Each note carries the region in source pixels, a crop, a copy of the frame with
numbered boxes drawn on it, the frame number and time, and the scene and source file the
frame maps to. Frames with no notes are listed with their hashes, so "approved" says what was
looked at. First consumer: `explainer-video` gets an optional human pass between its frame
check (step 5) and the full render. Second: a ledger review entry (agent-ledger M1) built
from the same JSON.
**Evidence so far:** A throwaway prototype (November 2026; plain Node and DOM, no
dependencies, about 350 lines) ran end to end on four synthetic 1920x1080 frames, once driven
by an agent in a browser and once by Beau. Regions came back correct with the page showing
the frame at about a fifth of its size, and each note resolved to the right scene file. No
canvas library was needed for boxes, notes, delete and keyboard navigation.
**Decide before building:**
- Where it lives: a skill in the `video` plugin, or a general review skill in bstack that
  `verify-work` can also call for screenshots. Only the `source` field is specific to video.
- Where the scene list comes from. The prototype read a hand-written `scenes.json` (`id`,
  `file`, `from`, `durationInFrames`). The Remotion project has to emit it; how is not yet
  checked.
- Crops need padding, or the marked-up frame should lead. A tight box in the prototype
  produced a crop that was ambiguous on its own.
- The note prompt. The prototype asks "What's wrong here?", but Beau's first note was a
  change request ("i want this bold"), so ask what should change.
- The skill must start the command in the background and wait for it to exit. A person can
  take longer than an agent's command timeout.
**Not tested:** real Remotion stills (the prototype assumes the frame number is the last
number in the file name), the zero-notes approval path, and launching the browser from the
command.
**Why not done:** `explainer-video` has not made a real video yet, and the human pass should
be shaped by one real round of fixes.
**Prioritize when:** `explainer-video` is merged and the first real video needs changes that
are awkward to describe in prose.
**Effort:** about a day with the skill text and the scene-list step (a guess).

---

# root-cause

## P1

### R36. Tune `root-cause` from real cases
**What:** Run `root-cause` on at least three real bugs in agent-written code, then adjust two
first guesses from the evidence. (1) What counts as a strong signal: today one fitting
hypothesis, or at most a third of the live ones. (2) The gate 1 (signals) and gate 2 (matrix)
reviews: today they are reminders from `next`, and only the validation review blocks a root
cause. Make them blocking if agents skip them.
**Why not done:** Both thresholds need real cases to set. Beau chose soft reviews for now
(November 2026).
**Prioritize when:** the third real case closes, or an agent reaches a root cause that a
skipped gate 1 or 2 review would have caught.

## P2

### R37. Default data collection for debugging
**What:** Have each project's `verify-<app>` skill capture traces, config snapshots and timing
on every run, so the first facts of the next bug are already on disk. Today a fact's
`--check` only re-collects what a case already found.
**Why not done:** Which data is worth capturing by default depends on the project; it belongs in
`create-verification-skill`'s template once real cases show what was missing.
**Prioritize when:** two `root-cause` cases record a `gap` or start with a gather step that
default capture would have covered.

---

# Verification loops

From Addy Osmani's "How the Claude Code team thinks about verification" (2026-11-16). The kit
already verifies on the real artifact and ties receipts to a commit. These items add the part
it lacks: the checks themselves get measured, kept out of reach of the changes they judge,
and pruned. Not-committed ideas from the same post are in [IDEAS.md](IDEAS.md).

**How to work these.** Each entry is one PR unless it lists units, and then each unit is one
PR. Take the first entry whose **Depends on** is met. Build each PR in its own worktree and
branch, run the beau-mode playbook the entry names, and stop at merge-ready: Beau merges.
**Done when** is the predicate to hand to `verify-work`. A check added here must be proven to
fail on a real past commit, as `correct` requires. A new gate on what an agent did in a
session ships in observe mode (R32) and is never switched to enforce in the PR that adds it. A
static check in `make validate` is not such a gate: it may ship as an error when a replay over
the repo's history shows no false failure, as the command lint did (PR 61: 137 commits, 0
errors). An entry that spans repos gets a
tier 2 charter (Large work item playbook) before the first PR.

Order: R27, R28, R30, R31, R33, R40 and R44 are done, and R29's three units are built. Next: R43 (its trigger, R11, has merged). R32 is done (bstack 0.58.0). R34 waits on R23.
R35's units are independent.

## P0

### R27. Verify skills for the runtime's own repos
**Done 2026-11-19.** All three merged: `verify-ledger` (agent-ledger pull request 23, 2026-11-18),
`verify-kit` (pull request 62 here, 2026-11-19) and `verify-quality` (the quality books' pull
request 19, 2026-11-19). Each lives in its repo under `.claude/skills/`. This closes steps 1 and
2 of H12. R30's items can name a `verify-<app>` drive as their check, and agentfiles R16 has
`verify-kit` to call it.

### R28. The quality summary says what tests catch, by kind
**What:** `quality.py summary --json` gains, per repo, `caught_on_pr` (tests with a failure
row in a `pull_request` run this week, with the count and the evidence links) beside the
existing `failed_on_main`, and cost and catches grouped by test kind (`unit`, `e2e`,
`property`, `differential`). The skill and the brief template then say: a proposal about a
slow test states its kind and its catches, and a property or differential test is not
proposed for a schedule on cost alone.
**Units:** (1) `caught_on_pr`, which needs only `failures.csv` and `runs.csv`. (2) kinds.
Settle by prototype first whether a kind comes from a naming rule (`PropertyTest` exists
today) or from a hand-edited `books/kinds.csv` like `watched.csv`. (3) in the books repo: move
the pin, add the rows to `briefs/TEMPLATE.md` (see the quality roadmap, phase 1b).
**Where:** `plugins/bstack/skills/qualitydirector/**`, `tests/test_quality*.py`,
`tests/fixtures/quality/**`, `kit.yaml`, `changes.yaml`, generated files.
**Depends on:** nothing.
**Playbook:** Feature. Run `how` on `summary` first and `interrogate` before merge: every brief
number comes from this output, and it must stay the same bytes on every run.
**Done when:** on the current books, `summary --json --week 2026-W46` lists
`test_agentfiles.ConfigTests.test_cycle_detected` under agentfiles `caught_on_pr` and nothing
under any `failed_on_main`; the property test "summary equals a recomputation from the raw
artifacts" passes with the new keys; `check` still passes books written before the change.
**Done 2026-11-26.** Units 1 and 2 shipped here: `caught_on_pr` in bstack 0.14.0 (pull
request 52) and `by_kind` in pull request 56, where a kind comes from an optional hand-edited
`books/kinds.csv`. Unit 3 merged in the books repo: its brief template has a cost-and-catches
table by kind, lists `caught_on_pr` under Reliability, and holds a slow-test proposal to its
kind and catches, with its first `books/kinds.csv`. Rechecked on the books on 2026-11-26:
`summary --json --week 2026-W46` lists `test_agentfiles.ConfigTests.test_cycle_detected` under
agentfiles `caught_on_pr` and nothing under any `failed_on_main`. Still unchecked: the first
brief written from the new template.

## P1

### R29. Checks out of reach of the change they judge
**What:** If a PR can edit the check that judges it, the check is broken. Three units.
(1) An audit table in `docs/ARCHITECTURE.md`: every gate (books check, ledger verify,
`check-product.py`, receipts, `validate`), and where its code and config come from at PR
time. Known case: the books workflow pins the checker by SHA, but the pin and the workflow
file are in the PR. (2) `check-product.py --base REF` reports a criterion whose `Probe:` text
changed in the same diff that checks its box, and passes it only with a new `**Confirmed.**`
line. (3) A test guard, `--base REF`, that reports a diff which deletes a test, adds a skip,
widens a timeout, adds a retry or loosens an assertion. It moves here from quality phase 2
and needs no dependency.
**Depends on:** nothing for the units. Protecting workflow files needs H13.
**Playbook:** Investigation for (1), Feature for (2) and (3).
**Done when:** (1) the table names a fix or an owner for every row that answers "the PR".
(2) fails on a fixture PR that edits a probe and checks its box, passes when confirmed.
(3) run against agent-kit's history it reports commit 990c84f (three tests renamed or
replaced) and stays quiet on a docs-only commit. Units 2 and 3 print and exit 0 (observe).
**Status (2026-11-26):** unit 1 is done (the gate table in `docs/ARCHITECTURE.md`, pull request 79).
Unit 2 is built: `check-product.py --base REF` (and `--receipts`, against its base) prints an
`observe:` line for a box checked in the diff that rewrote its `Probe:` or added the criterion, and
exits 0. A new `**Confirmed.**` line in the item clears it. Before it, a fixture branch that
rewrote C1's probe to `true`, took a receipt and ticked the box passed with no line at all. Unit 3 is built: verify-work's
`scripts/test_guard.py --base REF` prints and exits 0, `verify-work` and agent-kit's checklist
(`tests-weakened`) run it, and on 990c84f it reports the three tests that commit renamed or
replaced. Left open: running it in CI from the base branch's copy, which edits workflow files (H13).
**Prioritize when:** before any gate moves to enforce.

### R30. A reliability checklist that triggers on the diff
**What:** A checklist file per repo. Each item has an id, a trigger readable from a diff (path
globs or a pattern), a check (a command, or a question with a probe) and the PR or incident
behind it, plus `added` and `review_by`. `checklist.py --base REF` prints only the items whose
trigger matches the diff. `verify-work` runs it before a verdict, and in a governed run each
item gets a receipt. `correct` gains one rule: a mistake class that can be read from a diff
becomes a checklist item, and the rest stay in the rule table. Seed agent-kit's with five:
books layout change (do books written by the last release still pass `check`?), phase spec
format change (does an existing product repo still pass, or is there an upgrade path?),
anything under `plugins/` (`kit.yaml`, `changes.yaml` and generated files in step), a script
that calls `gh` (works where `gh auth status` fails), a skill description change (still
triggers on its "Use for" phrases). agent-ledger's first item: an entry format change keeps
existing chains verifying.
**Where:** `plugins/bstack/skills/verify-work/scripts/checklist.py` and a reference file,
`plugins/bstack/skills/verify-work/SKILL.md`, `plugins/bstack/skills/correct/SKILL.md`, the
checklist file, tests. Standard library only. Settle the file format (Markdown table or
JSON) by prototype; the repo has no YAML parser to lean on at run time.
**Depends on:** nothing. Receipts per item use bstack 0.13.0's `receipt.py`.
**Playbook:** Feature, then Authoring a skill for the two skill edits.
**Done when:** `checklist.py --base` at commit 990c84f (`tests-weekly.csv` went from
`p50_ms` to `total_ms`) prints the books item and not the `gh` item; at fix 02faa18 it prints
the `gh` item; on a docs-only commit it prints nothing.
**Why not done:** New idea. `correct`'s rule table pairs rules with enforcement but nothing
selects rules by what a diff touches.
**Done 2026-11-21** in pull requests 80, 82 and 86: `checklist.py --base`, the base copy of
the checklist file, and a receipt per item. Its change record proves the done-when on 990c84f,
02faa18 and a docs-only commit. Still unchecked: an agent following verify-work's step runs it.

### R31. Every commit says how it was verified
**Done 2026-11-18** in bstack 0.15.0 (pull request 53). The Opening a PR playbook writes the
`Verified:` trailer and beau-agent carries the rule. Still open, and tracked in the quality
roadmap's phase 1b: the summary reporting the share of commits on main by stamp. R32's commit
gate reads the stamp.

### R32. Gates start in observe mode; two Claude Code hooks
**Done 2026-11-27** in bstack 0.58.0, run `2026-11-27-r32-hook-gates` (agent-kit pull requests 139
and 145, agent-ledger 55, agentfiles 42). S2 has a `checks:` map: a check id to `off`, `observe` or
`enforce`, stricter wins, `observe` when nobody names it. agentfiles merges and writes it. bstack's
commit gate (PreToolUse) and Stop hook (`.agents/checks.yaml`) read it. In observe they log a
`would-block` lesson to the weekly flags run. In enforce they stop the action twice, then let it
through and log why. A repo's own `.agents/` files count only when its GitHub `origin` is under
`identity.human`'s login. Proven in real headless sessions with the merged plugin
(`evidence/probes-merged-plugin.txt` in the run). R6 was not needed: both hooks are Claude Code
only, and Claude Code reads the plugin's hand-written `hooks/hooks.json`.
**Still open:** `spec-drift`, `receipts` and `test-guard` print their observe lines but don't read
the mode yet (R29's trigger: before any gate moves to enforce). The quality brief doesn't count
would-block lines yet. Replayed over past transcripts, the commit gate's rule fires on most commits,
most of them after a test run, so what counts as verification needs deciding before enforce (H14).
**What:** (1) Every verification gate has a mode: `off`, `observe` (log what it would have
blocked, block nothing) or `enforce`. The agent policy carries the mode per gate (an
agentfiles change), and observe logs go where the quality books can read them. This covers
the spec drift gate (R22 in the bstack section), the receipts gate, R29's guards and the
commit gate below. (2) A Stop hook that runs the repo's declared cheap checks (`make test`,
lint) when the agent finishes, so nothing is pushed red. (3) A commit gate hook that blocks a
commit whose session ran neither `verify-work` nor a review. After two blocks in one
session it lets the next commit through and records why. That anti-stall rule never applies
to a policy gate (`deploy`, `secrets`, `spend` and the rest): those wait for a person.
**Depends on:** R6 (the neutral hook definition; this is its concrete case), R31, and H14
(done 2026-11-27: Beau allowed the Stop hook and commit gate). Spans agent-kit and agentfiles: charter first.
**Playbook:** Large work item.
**Done when:** in observe mode a session that commits without verifying logs one
would-have-blocked line and the commit succeeds; in enforce mode the same session is blocked
twice and passes the third time with the reason recorded; the Stop hook turns a session with
a failing test back to the agent with the failing output.
**Why not done:** Hooks are the least portable part and run code on every event (R6).
**Prioritize when:** R31 has merged and an agent has pushed a red first commit at least twice
(the quality books show red pull-request runs).

### R33. One tuned reviewer: `REVIEW.md` and rounds that build
**Done 2026-11-18** in bstack 0.18.0 (pull request 57): `REVIEW.md` at the root of this repo, read
from the default branch by `interrogate`, review rounds that build on the last one, and a starter
`REVIEW.md` from `scaffold-product`. R11's script is built, but a `cli:` reviewer on a review
panel still waits on R34: add a reviewer only when a replay shows it finds what the first one
misses.

### R44. Pull request cycle time in the quality books
**What:** the books say how long a merged pull request was open and where that time went, in
three measured parts: CI running, time between CI runs (an agent or a person reworking the
change), and the head commit's last CI finishing to the merge (waiting on a person to merge).
`fetch` lists the pull requests merged in the window and reads each one's commits, its
check runs and its commit statuses (local-ci reports through statuses). `ingest` books one
row per merged pull request in an optional, append-only `books/pulls.csv`. `summary --json`
gains `pulls` per repo: the count, and p50 and p95 for open time and each part. Never one
summed share: a few pull requests left open overnight would set it.
**Units:** (1) the book, `fetch`, `ingest`, `check` and `summary` in one change, with the
bucket rule in `SKILL.md`. (2) in the books repo: move the pin, backfill, add the table to
`briefs/TEMPLATE.md` (the quality roadmap, phase 1f).
**Where:** `plugins/bstack/skills/qualitydirector/**`, `tests/test_quality*.py`, `kit.yaml`,
`changes.yaml`, generated files.
**Depends on:** nothing. It comes from `plans/ci-speed.md` in the agent-runtime workspace, the
second half of its first recommendation; the first half is the job books (R-A, phase 1d).
**Playbook:** Feature.
**Done when:** a prototype's per pull request numbers for one public watched repo match the
booked rows to the second; `check` passes books written before the change; `summary` stays the
same bytes on books without the file.
**Prioritize when:** now. A prototype on 2026-11-24 over agent-kit's 56 pull requests merged in
the previous seven days found medians of 7.4 minutes open, 1.9 in CI, 0.1 reworking and 2.1
waiting to merge, with no pull request where the parts summed past its open time.
**Done 2026-11-26.** Unit 1 shipped in bstack 0.43.0 (pull request 112), whose change record
proves the done-when: booked rows match a prototype's per pull request numbers, and books
without `books/pulls.csv` give the same bytes. Unit 2 merged in the books repo: the pulls book
is adopted and the brief template has the cycle time table.

## P2

### R34. Grade the checks on bugs that mattered
**What:** (1) An escapes book in the quality books, `books/escapes.csv`, append-only: date,
repo, sha or PR, kind (`revert`, `fix-forward`, `rejection`, `incident`), the check that
should have caught it, a one-sentence answer key, evidence. `quality.py` adds rows from
reverts in `git log` and from ledger `rejection` entries (R23); a person confirms each answer
key. The summary reports escapes, rejections before merge and a size-matched count of clean
merges. (2) Replay: check out the parent of a booked escape, run `interrogate` on the diff,
and give credit only for a finding that matches the answer key. Clean merges are the controls.
Keep a tuning set apart from a fixed test set. Book `interrogate`'s counts per stage (raw,
after rerun, final) so a real bug dropped by the rerun step shows. (3) `correct` gains a
disprove step: before a mined rule lands, adversaries look for a clean PR it would flag wrongly.
**Depends on:** R23 (the `rejection` entry type), R28. This is where R3 and R13 get real cases.
**Playbook:** Feature for (1); Eval for (2).
**Done when:** (1) `check` rejects an edited escapes row; the summary's escape count equals the
rows for the week. (2) a replay of one booked escape prints found or missed against its key.
**Why not done:** No escape is recorded anywhere. agent-kit has no revert in its history, so
the first cases will be rejections and fix-forwards.
**Prioritize when:** unit 1 when the first rejection is recorded; unit 2 at five booked escapes.

### R35. Three small follow-ups
**What:** Independent units, each one PR.
(1) **Differential tests by name.** A reference for the Refactoring playbook and migration
charters: run old and new on the same generated or sampled inputs, normalize what doesn't
matter, keep an approved-differences file for intended changes. The Quality Director's
recorder-against-plain-unittest parity test is the worked example.
(2) **A flaky test with no root cause.** The Quality Director may propose deleting one only
with a closed `root-cause` case that found no cause attached, as a question. It still never
deletes. Needs Beau's answer in the books repo first (its H5).
(3) **Prune on a schedule.** Rule-table and checklist entries carry `added`, `origin` and
`review_by`. A monthly prune brief lists entries past review, checklist items that never
triggered, and instruction-file size over time. This gives R25 a schedule. R41 adds a skills
table to this brief.
**Depends on:** (2) the books repo's H5; (3) R30.
**Playbook:** Authoring a skill.
**Done when:** each unit's skill text is followed correctly by a fresh subagent on one fixture case.
**Why not done:** None is urgent.
**Prioritize when:** (1) the next rewrite or migration; (2) the first unsolved flake; (3) R30
has run for a month.

---

# Skill ops

From Akshay's "[Our Claude skills and guidance, six months later](https://akshay.co/posts/our-claude-skills-and-guidance-six-months-later/)"
(read 2026-11-19). That team's skills passed lint and review and still did badly in use, so
they added behavioral evals, a verdict on every invocation, and retirement after 60 days
without use. The kit's checks are static too: nothing tests whether an agent follows a
skill's text, and no skill use is booked. These items give skills what the Quality Director
gives tests: measure them in use, test their behavior, then prune. Measuring comes first
because it finds the real sessions R3 and R13 have waited for. Not-committed ideas from the
same post are in [IDEAS.md](IDEAS.md).

The work spans four repos. Each item has one full entry, in the repo where its code lands:

| Item | Entry | Other repos |
|---|---|---|
| Book skill use from transcripts | R38. Done 2026-11-21: rows are booked weekly | The book and the brief section: quality phase 1c, also done |
| Lint: a skill never names a command that doesn't exist | Done: `check_commands` in `tools/validate.py` | None |
| Behavioral evals, deterministic half | agent-ledger M3 unit 1 | The criteria live here. R3 and R13 point at it |
| Every skill loads in every target tool | agentfiles R16 | `verify-kit` (R27) calls it |
| A breaking format change ships with its sweep | R40. Done 2026-11-22 | Reads the quality books' `watched.csv` |
| The prune brief covers skills | R41 | The profile half: agentfiles R18. The brief section: quality phase 1c |
| Cuts are proposed by ablation | R25 (edited in place) | The always-on block is agentfiles' |
| Upstream skills pass the same lint | agentfiles R17 | Uses the lint above (was R39) |
| Tokens per skill use | R49. Done 2026-11-26: `book-skills` books tokens per use | The book's new columns: quality phase 1g |

**How to work these.** The rules under Verification loops apply: one PR per entry or unit, its
own worktree and branch, stop at merge-ready, and a new check is proven to fail on a real past
commit, or on a planted fault with that said in the PR. Six more hold across all of it:

- No new eval system. Receipts, the ledger and the quality books carry everything.
- Verdicts come from rules and exit codes. No judge model until Beau says so.
- No transcript text leaves the Mac. The books get counts, signals and verdicts.
- Nothing retires a skill without Beau's answer. The Quality Director proposes and never acts.
- `quality.py` stays standard library only, and `summary --json` stays byte-stable.
- No health score and no dashboard. Skills get one section in the weekly brief.

Order: R38 is done and booking rows since 2026-11-21. agentfiles R17 can start, since the lint
it runs has shipped.
agentfiles R16 with its R0 or R11. R40 is done. agent-ledger's M3 unit 1 waits on four
weeks of R38 rows and two answers from Beau (agent-ledger H8 and H9). R41 waits on 60 days of
rows.

## P0

### R38. Book skill use from transcripts
**What:** A second pass inside cfo's `weekly-claude-code.sh`, which already reads this Mac's
agent logs every week (one launchd job, one read), appends one row per skill invocation to
`books/skill-uses.csv` in the quality books: week, skill, its source, its version, tool, how
it was invoked, and three counts for the window after the skill loads (tool calls, tool
searches, tool errors). The verdict column exists and every row is `unjudged` for now. The
unit is every installed skill, keyed on `agentfiles.lock`, not only the kit's own.
`quality.py summary --json` gains uses per skill. No transcript text is booked.

What the prototype settled (unit 1, run on four weeks of real transcripts, 2026-11-19):

- **Claude Code is the first tool.** A use is a `Skill` tool call, a typed slash command, or a
  `Read` of an installed `SKILL.md`. A `Read` of a `SKILL.md` in a checkout is someone editing
  the skill and is not a use. All three are read from `user` and `assistant` records only:
  other record types repeat the same content.
- **Drop duplicates by tool-call id.** About one invocation in seven also sits in another file
  (resumed and forked sessions). No copy differed from the one kept.
- **How invoked has four values:** `typed` (a slash command), `named` (the turn before names
  the skill), `auto`, and `subagent`. A typed turn is a user record whose `origin.kind` is
  `human`. Records from older sessions may lack `origin`: count those rows and report them.
- **The window is bounded.** From a skill load to the next typed turn the median is 29 tool
  calls and one window in ten passes 111, and in one window in six another skill loads first.
  "More than 3 errors" fired for 23% of windows of 20 or more calls and for none of the
  shorter ones, so over the whole window it measures the length of the task. Book the counts
  over the first 20 tool results, with the call count beside them. Pick a threshold from a few
  weeks of rows before any rule fills a verdict.
- **The version comes from `agentfiles.lock` on the day.** The transcript shows where a skill
  was loaded from (installed plugin, marketplace copy, worktree) and almost never its version.
- **Cursor gives a use count and nothing else.** Its only trace is a `Read` of a `SKILL.md`.
  It records no tool results and no time per record, so a row is dated by its file and its
  counts are empty.
- **Codex is left out** until it has sessions: none in the four weeks.
- **No correction signal in the first version** (Beau, 2026-11-19). A rule on the next typed
  turn matched 2 of 1,158 turns, so it can't be told apart from noise without reading the
  text. A correction can come back later from a ledger `rejection` entry (R23), and never
  from a guess at the next user turn.

**Units:** all three done. (1) Prototype: findings above. (2) The pass and the `quality.py`
changes: pull requests 70 and 71. (3) In the books repo: the new book, the pin move and the
brief section (quality phase 1c, its pull request 25).
**Where:** `plugins/cfo/skills/cfo-books/scripts/weekly-claude-code.sh`,
`plugins/bstack/skills/qualitydirector/**`, `plugins/bstack/skills/reflect/scripts/find-transcripts.py`,
tests, `kit.yaml`, `changes.yaml`, generated files.
**Depends on:** H15 and the books repo's H6, both answered yes on 2026-11-19. R19 if the
transcript reader has to live outside `reflect`. agentfiles H13 decides whether cfo's own
skills are counted. For governed runs the pass can read the redacted archives
`ledger session add` keeps under `.audit/runs/<run>/sessions/`.
**Playbook:** Feature, from the findings above.
**Done when:** a run over the last four weeks of real transcripts books rows, `check` passes,
a second run changes nothing, and ten rows picked at random match the transcripts by hand.
**Done 2026-11-21.** `quality.py book-skills` books the rows, `check` and `summary` read the book, and the Mac
job runs the pass with `--quality-repo` and `--agentfiles-lock`. Before anything was booked, a run over four weeks of
real transcripts into a scratch copy of the books passed `check`, changed nothing on a second run, and ten rows
matched the transcripts by hand. The installed job's first run booked the closed weeks still inside log retention
into the quality books (its pull request 26). Three things the build added to the findings above: each row carries
`use`, a hash of the tool-call id, so a rerun adds nothing and `check` refuses a duplicate; only closed weeks are
booked; and a `Read` counts once per session and skill. Two things to know when reading the rows: the week a
Sunday brief is for never has skill rows yet, so the brief's Skills section reads the latest booked week from a
second `summary --week` run; and a skill outside the lock (cfo's, until agentfiles H13 is answered) is booked with
its plugin name and an empty version.
**Still open:** no rule fills `verdict`. Pick a threshold from a few weeks of rows first. The first rule that
needs no threshold is R48: a skill use with an agent's flag in its window.
**Feeds:** agent-ledger's M3 unit 1 (after four weeks of rows), R41 (after 60 days) and R3.

## P1

### R40. A breaking format change ships with its sweep
**What:** One rule in the Authoring a skill playbook and one script. When a change breaks an
artifact the kit generates in other repos (phase specs, `verify-<app>` skills, `REVIEW.md`),
the PR lists the repos in the quality books' `watched.csv` that hold one, and opens or names
the upgrade PR for each. CI only touches what changes, so old artifacts never meet a new rule
unless something carries it to them. Add it to R30's checklist as a diff-triggered item.
**Where:** `plugins/bstack/skills/beau-mode/playbooks/authoring-a-skill.md`, one script, R30's
checklist file, tests.
**Depends on:** R30.
**Playbook:** Authoring a skill.
**Done when:** replayed against the 0.12.0 spec change, it lists the product repos that broke.
**Why not done:** 0.12.0's spec change was breaking for product repos, and no step lists the
repos that hold an affected artifact.
**Prioritize when:** R30 lands, or the next breaking format change.
**Done 2026-11-22** in bstack 0.33.0 (pull request 84): `beau-mode/scripts/sweep.py`, the
Authoring a skill playbook's sweep step, and the `generated-artifact-format` checklist item.
Replayed read-only on 2026-11-26 against 088cd28, the 0.12.0 spec change, reading each repo as
it was the day before: 1 of 4 watched repos held a spec in the old `## Acceptance` format. On
the repos as they are today, 0 do. Still open: the script lists the repos that hold an artifact,
but nothing names or proposes the upgrade pull request for each. No repo is waiting for one, so
take it up at the next breaking format change.

## P2

### R41. The prune brief covers skills
**What:** R35 unit 3's monthly prune brief gains a skills table from R38: uses in the last 60
days per skill, per tool, and what the skill costs (its always-on tokens times sessions, priced
with the CFO's pricing table). Proposals are ranked by cost as well as use. Third-party skills
come first, because they can be measured and dropped but not fixed. The brief proposes at most
three retirements, each as a question, and proposes dropping a skill from an agentfiles
profile (agentfiles R18) before deleting it from the kit. A skill marked `rare: true` in
`kit.yaml` with a reason (`root-cause`, the formal verification pair) is listed and never
proposed.
**Where:** `plugins/bstack/skills/qualitydirector/**`, `kit.yaml`, `tools/` (the `rare` field),
generated files. The brief section lands in the books repo (quality phase 1c).
**Depends on:** R38, R35 unit 3.
**Playbook:** Authoring a skill.
**Done when:** on fixture books with 60 days of rows, the brief lists every skill, proposes no
more than three, proposes none marked `rare`, and every number matches `summary --json`.
**Why not done:** R35 unit 3 prunes rules and checklist items. No skill has ever been retired
on evidence, since there is none.
**Prioritize when:** R38 has 60 days of rows.

### R49. Tokens per skill use
**What:** `quality.py book-skills` books what each skill use cost: input, output and cache-write
tokens over the window R38 already counts (the first 20 tool results after the skill loads),
read from the usage each Claude Code assistant record carries. Cursor rows stay empty, since
Cursor records no usage. `summary --json` gains tokens per use per skill. This is the method in
Uber's "[How Uber Evals 1 Million Agent Skill Invocations a Month](https://www.uber.com/us/en/blog/optimizing-ubers-agent-skills/)"
(read 2026-11-25): the session's cost just after a skill call minus the cost just before,
averaged per call. R41 prices a skill's always-on cost; this gives the cost of using it, which
R25 and R43 need to show a cut saves anything.
**Where:** `plugins/bstack/skills/qualitydirector/**` (`book-skills`, `check`, `summary`), tests,
generated files. The book's new columns land in the books repo.
**Depends on:** R38.
**Playbook:** Feature.
**Done when:** a run over four weeks of real transcripts into a scratch copy of the books fills
the token columns, `check` passes, a second run changes nothing, and five rows picked at random
match the transcripts' usage by hand.
**Why not done:** R38 booked counts first. Uber's post shows the cost per use is the number
its cuts were judged on (one skill 46% cheaper after a change, another unchanged).
**Prioritize when:** now. It costs one more read in a pass that already runs, and R41, R25 and
R43 all assume a cost column.
**Done 2026-11-26** in bstack 0.46.0: three token columns on `books/skill-uses.csv`, and
`tokens_per_use` per skill in `summary --json`. A use's tokens are the usage of the model
responses in the window the counts cover, each response once (Claude Code repeats its usage on
every record it splits a response into) and the response that made the load left out. A book on
the earlier header keeps working, and `book-skills` appends rows to it in that shape with no
tokens. `migrate-skills` moves it to the new header once the books' CI pin has this version, and
the rows booked before keep empty token cells. A run over four weeks of real transcripts into a
scratch book filled the columns on every Claude Code row, `check` passed, a second run changed
nothing, and five random rows matched a recount from the raw records. Its change record has the
counts.

# Context loading

From Jennifer Smith's "[The context layer has a clutter problem](https://x.com/scribeceo/status/2123460060299030733)"
(Scribe, read 2026-11-23) and Matt Stockton's take on it. The claim: retrieval gives agents text
that looks relevant but isn't, and even one such distractor lowers model output. A record of how
the work was actually done beats docs, because a person already filtered it. In Scribe's test (30
tasks, one model, graded by that same model), adding the wiki on top of workflow recordings made
output worse. That evidence is weak, so these items test the claim on the kit's own tasks before
anything changes. Full analysis: the Agent Kit project's `plans/context-clutter.md`.

| Item | Entry | Other repos |
|---|---|---|
| Knowledge base lookup only behind a passing eval, by id not similarity | R42 (done 2026-11-26: step 4 removed) | R16 depends on it |
| Ablate beau-mode's always-on load | R43 | Feeds R25's cuts |
| The curator learns from PR trails, not docs | A line here until lyddonb/curator is in the workspace | curator's roadmap (knowledge factory K2) |
| Rejections and flags name what misled the agent | R23 (edited in place) | agent-ledger's `rejection` type |

Both evals need a judge model. Beau allowed one for these two only (H17, 2026-11-26):
`cli:cursor-agent:gpt-5.6-sol-high`, run through R11.

## P1

### R42. Knowledge base lookup only behind a passing eval
**Done 2026-11-26** in bstack 0.50.0 (pull request 132). Step 4 is removed. With the KB MCP server installed as it is,
none of 30 runs called it, so the KB arms were replicates of no KB. That includes an arm given
Beau's own kb instruction, which applies clearly to 2 of the 10 tasks (t9, t10): neither searched.
Removal rests on the amendment made before any judge call (a KB arm with no KB call is noise); the
rule as first written would have read "keep". Naming related change records lost to no KB (0.35
win share overall). The scores, the noise band and token counts are in `.changes/2026-11-26-r42-kb-eval/`, and
[docs/KNOWLEDGE.md](docs/KNOWLEDGE.md) says what R42 measured. A KB lookup returns only as entries
loaded by id behind a passing eval like this one.
**What:** beau-mode step 4 ("Check for team knowledge") reads a knowledge base before design.
[docs/KNOWLEDGE.md](docs/KNOWLEDGE.md) says it starts returning entries as soon as a KB MCP
server is installed, with no skill edit. Before that happens, run the Eval playbook with four
arms on 8 to 10 past tasks taken from ledger runs and merged PRs: no KB, the KB, the decision
trails of past PRs on similar work, and both. Keep step 4 only if the KB arm beats no KB and the
both arm is not worse than trails alone. When step 4 reads a KB, it loads entries by id, named
by the chosen playbook or by the files the change touches, never by similarity to the task text.
Change KNOWLEDGE.md's "no skill edit needed" to "needs a passing R42 eval".
**Where:** `plugins/bstack/skills/beau-mode/SKILL.md` step 4, `docs/KNOWLEDGE.md`.
**Depends on:** R11. The judge is `cli:cursor-agent:gpt-5.6-sol-high` (H17).
**The KB under test (Beau, 2026-11-26):** the KB MCP server already installed on Beau's machine, as it
is: a personal library of saved reading, searched by similarity, not R16's conventions KB keyed by
id. Beau's words: "Yes, test kb as is". His agent setup already tells every agent to search it
before design work, so the lookup this item gates is live today. The no-KB arm must run with that
server and that instruction off (`claude -p` with `--strict-mcp-config` and `--setting-sources ""`
drops both), or the arms don't differ.
**Playbook:** Eval.
**Done when:** the eval's reply is in the PR with every arm's scores, and step 4 either loads by
id or is removed.

### R43. Ablate beau-mode's always-on load
**What:** beau-mode's `SKILL.md` is about 3,000 words, and beau-agent loads it and the
principles index before any work. Nothing has tested whether that much text helps or distracts.
Run the Eval playbook on 8 past tasks with two arms: beau-mode as it is, and a slim router that
restates the task, picks a playbook and loads only that playbook and the principles it names.
Judge on a different model from the candidates, blind to which arm wrote which answer. Run the
full arm twice and report each rubric item's win share beside the gap between those two
identical runs, so a difference smaller than that noise band counts as none. Uber's skill
ablation (below) reports wins the same way. If the slim arm holds on every rubric item,
propose moving playbook-only text out of `SKILL.md`, through R25's cut rules.
**Where:** `plugins/bstack/skills/beau-mode/**`. Changes nothing until the eval passes.
**Depends on:** R11. The judge is `cli:cursor-agent:gpt-5.6-sol-high` (H17). It has the user's
rules loaded, beau-mode among them. Say so in the reply, or judge through a CLI that runs clean.
**Playbook:** Eval.
**Done when:** the eval's reply is in a PR with a keep or slim recommendation and the token
count of each arm.
**Why not done:** found 2026-11-23. It is the cheapest test of the claim above and needs no KB.
**Prioritize when:** R11 has merged. Before R13's beau-mode comparison, which can reuse its tasks.
**Done 2026-11-26: keep.** 8 tasks, beau-mode's full `SKILL.md` run twice against a slim
router, judged blind by `cli:cursor-agent:gpt-5.6-sol-high`. The slim arm held on cause, fix and
proof, and fell outside the noise band on scope and reply, so nothing is cut. The full arm adds
7,505 tokens and the slim arm 2,169, with no measurable cost difference per run because the
prompt is cached. The full arm skipped its playbook in 6 of 16 runs, and no run in either arm
opened a principle file. The report, rubric, verdicts and harness are in
`.changes/2026-11-26-beau-mode-ablation/`, and R13 can reuse its tasks.

# Knowledge factory

From Harrison Chase's "[The Knowledge Factory](https://www.langchain.com/blog/knowledge-factory)"
(LangChain, read 2026-11-23), with evidence from Uber's
"[How Uber Evals 1 Million Agent Skill Invocations a Month](https://www.uber.com/us/en/blog/optimizing-ubers-agent-skills/)"
(read 2026-11-25). The kit has skills as procedural memory and the rule that agents propose
and a human decides. What it lacks is the agent-raised flag: a call any agent makes mid-task
when a skill, reference or pointer is wrong or missing, with what it did instead and a
suggested fix. R38 could not get a correction signal from the next user turn (it matched 2 of
1,158 turns). Uber runs exactly this as an always-on skill and reports thousands of reports in
three months and hundreds fixed, among them bugs no review caught: concurrent sessions
overwriting one temp file, seconds passed where milliseconds were needed. Both posts' numbers
are their authors' own.

| Item | Entry | Other repos |
|---|---|---|
| The flag convention and how to append one | agent-ledger, Flags unit | Entries go in a weekly flags run per machine |
| Agents flag a wrong skill and carry on | R45 | Uses the agent-ledger convention |
| Flags fill a verdict | R48 | The books' `verdict` column (R38) |
| Data access as pointers | R46 | None |
| One list of what waits on Beau | R47 | Reads every repo's `HUMAN_TASKS.md` and the ledger |
| A narrow profile for the agent that reads flags and proposes edits | agentfiles R19 | None |

**How to work these.** A flag is never edited and no agent edits a skill because of one. A
separate weekly pass reads the flags and proposes at most three skill edits, each a PR that
shows the flag's evidence failing before and a probe passing after. Beau merges every PR.
Flag entries hold no transcript text.

Order: agent-ledger's Flags unit and R45 are done. R48 after two weeks of flags (H18 is done, so flags land from 2026-11-26). R47 is done. R46 any time.

## P1

### R45. Agents flag a wrong or missing skill and carry on
**What:** One rule in beau-mode's Non-negotiables and the same line in beau-agent: when a
skill's text, a reference or a pointer was wrong or missing (a command that doesn't exist, a
step that no longer works, a path that moved), append a flag with agent-ledger's convention and
carry on with the task. Never edit the skill in the same task. The flag names the skill, what
was wrong, what the agent did instead, a suggested fix, and the command and output that showed
it.
**Where:** `plugins/bstack/skills/beau-mode/SKILL.md`, `plugins/bstack/agents/beau-agent.md`,
generated files.
**Depends on:** agent-ledger's Flags unit.
**Playbook:** Authoring a skill.
**Done when:** in a real session, a planted wrong command in a skill produces one flag that
passes `ledger verify`, holds no transcript text, and the task still finishes.
**Why not done:** the convention it writes doesn't exist yet.
**Prioritize when:** agent-ledger's Flags unit has merged.
**Done 2026-11-26** in bstack 0.48.0: one Non-negotiable in beau-mode and the same line in
beau-agent point at beau-mode's `references/flags.md`, which holds S3's commands. It replaces
the old rule to fix a broken skill in its own change. Outside a governed run, flags go to the
repo `~/.agents/flags.yaml` names; choosing it is H18. In a real session in a scratch repo, a
skill with a wrong flag in its command produced one flag that passed `ledger verify` and held
only the command and its error line, and the task finished. The change record has the run.

### R47. One list of what waits on Beau
**What:** A read-only command that lists everything waiting on Beau across the repos: open
`HUMAN_TASKS.md` items and blockers, pull requests waiting for his merge, open ledger gates,
and proposals from the weekly briefs. One place to look instead of five files and a PR list.
It sends nothing. A notifier can read its output later.
**Where:** a script in `plugins/bstack/skills/`, with a short skill or a `beau-help` section,
tests, generated files.
**Depends on:** nothing.
**Playbook:** Feature.
**Done when:** run on this machine, it lists every open human task in the five repos and every
open PR waiting on review, and each item links to its source.
**Why not done:** it was an idea (a notifier for scheduled jobs) waiting for three jobs to run
on a schedule. That trigger is met: the CFO and skill-use weekly job, local-ci, and the weekly
quality brief.
**Prioritize when:** now, or the next time a human task waits more than a week unnoticed.
**Done 2026-11-26** in bstack 0.45.0: the `waiting-on-me` skill and `waiting.py`. Run on the
workspace on 2026-11-26, it listed every open human task in the five repos and every open pull
request a plain `gh pr list` showed, each with a link. Its change record has the counts. It
reads the books' open questions, which is where every brief proposal is decided, so it lists
proposals as questions. Open ledger gates are proven on fixtures only: every run on the
workspace's default branches was sealed that day.

## P2

### R46. Data access as pointers
**What:** One reference file per area whose data an agent reads (the quality books, the CFO
books, ledger runs) that says where each fact lives and the command that reads it, owned by
the skill that writes the data. `docs/KNOWLEDGE.md` gains a `pointer` entry type beside
`reference`. A pointer never copies the data.
**Where:** `plugins/bstack/skills/qualitydirector/references/`, `plugins/cfo/skills/cfo-books/references/`,
`docs/KNOWLEDGE.md`.
**Depends on:** nothing.
**Playbook:** Authoring a skill.
**Done when:** an agent asked three factual questions about the books answers each by running
the command its pointer names, with no file search.
**Why not done:** agents find the books by reading the skills today. Nothing has shown that to
fail, so this waits for a flag that says it did.
**Prioritize when:** a flag names a wrong or missing path to data.

### R48. Flags fill a verdict
**What:** R38 left every `verdict` as `unjudged` because no count could decide one. A skill use
with a flag on that skill in its window is `partially effective`, and `harmful` when the flag
names a command or path that doesn't exist (checked with `tools/validate.py`'s
`check_commands`). That is the first verdict the books fill without a judge model.
**Where:** `plugins/bstack/skills/qualitydirector/**`, tests.
**Depends on:** R45, R38.
**Playbook:** Feature.
**Done when:** on fixture books and flags, every use with a flag in its window gets the rule's
verdict, every other use stays `unjudged`, and a second run changes nothing.
**Why not done:** there are no flags yet.
**Prioritize when:** R45 has two weeks of flags.
