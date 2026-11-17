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
**Prioritize when:** a skill misfires (does not trigger, or triggers wrongly) twice.

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
**Prioritize when:** there is a concrete hook worth having in at least two tools.

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
**Blocked by:** HUMAN_TASKS H8.

## P1

### R11. Cross-model reviewers through other agents' CLIs
**What:** A `second-opinion` script that runs a review prompt through another installed
agent CLI (`claude -p`, `cursor-agent -p`, later `codex exec` and `pi -p`) and returns its
answer, plus a roles-file syntax for it, for example
`reviewers: {claude-code: [opus, "cli:cursor-agent:gpt-5"]}`. `interrogate`, `reflect` and
the trail review in `show-me-your-work` would then get reviewers from a different model
family even inside Claude Code.
**Why not done:** Deferred by choice in the first build. It needs each CLI signed in on the
machine and real runs to settle timeouts, output parsing and cost. The roles file already
takes lists, so adding a `cli:` entry type changes no skill text.
**Prioritize when:** a review panel inside one tool keeps agreeing with itself, or a
cross-family review catches something a same-family panel missed.

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
this was waiting on, shipped in bstack 0.13.0.

### R23. Rejections sharpen the criteria
**What:** When the human rejects work whose checks passed, the agent records a `rejection`
ledger entry: what was rejected, the criterion or probe that was missing, and the new
criterion it added. `reflect` and `correct` read past rejections across sessions, not only
the current transcript, and a fix counts only when the new probe fails on the rejected work
and passes on the fix. This is the persistent complaint log (ERRATA in the source thread).
**Why not done:** The Product phase playbook now does this inside one spec; a cross-session
log needs the `rejection` entry type in agent-ledger.
**Prioritize when:** the same kind of rejection happens twice.

### R24. Goals say what measures them, what moves them and the first move
**What:** The `docs/VISION.md` goals table gains three columns: Measure, Lever and First move.
`check-product.py` fails a goal row with any of them empty. The scaffold interview asks for
them, and a phase that serves a goal names which lever it pulls.
**Why not done:** Kept out of 0.11.0 so the spec format change landed alone.
**Prioritize when:** the next VISION.md is written or upgraded.

### R26. A bug that survives two fixes goes to root-cause
**What:** bstack 0.11.0's `root-cause` skill covers two failed *theories*. Extend the Bug fix
playbook's trigger to two fixes that didn't hold: stop patching and run `root-cause` from the
symptom with a fresh subagent that hasn't seen the failed fixes.
**Why not done:** Small, but it should come from a real case so the wording fits.
**Prioritize when:** the first time a third patch is about to land.

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
**Prioritize when:** the KB has an MCP interface.

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
cloud). Each needs a verification skill in a real app first (agent-kit H12).
**Prioritize when:** two apps have verification skills and local lanes start colliding.

### R19. A shared transcript script
**What:** `recall` calls `reflect`'s `find-transcripts.py` by its sibling folder. Move the
script to a small shared location (or have kitgen copy it into each skill that needs it) so
installing one skill alone still works.
**Why not done:** Both skills ship in bstack and install side by side in every supported tool,
so the sibling path works today.
**Prioritize when:** someone installs `recall` without `reflect`.

### R25. Skills describe outcomes; cut steps a smarter model wouldn't need
**What:** Audit each bstack skill and playbook with one test: would a stronger model need
this step? Keep steps that enforce a gate, a verification or a record (those are the point).
Cut steps that only teach how. Measure the always-on and per-skill token cost before and
after.
**Why not done:** Playbooks are step-by-step on purpose, so weaker models in Codex or pi
still hit the gates. Cutting needs evidence from runs in more than one tool (R10, R13).
**Prioritize when:** R13's evals exist, so a cut can be shown not to lose a gate.

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

### R21. Tune `root-cause` from real cases
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

### R22. Default data collection for debugging
**What:** Have each project's `verify-<app>` skill capture traces, config snapshots and timing
on every run, so the first facts of the next bug are already on disk. Today a fact's
`--check` only re-collects what a case already found.
**Why not done:** Which data is worth capturing by default depends on the project; it belongs in
`create-verification-skill`'s template once real cases show what was missing.
**Prioritize when:** two `root-cause` cases record a `gap` or start with a gather step that
default capture would have covered.
