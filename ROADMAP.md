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
**Why not done:** It is Beau's call (HUMAN_TASKS H11 in agentfiles), and the gain is
shorter prompts, not new behavior.
**Prioritize when:** before the next round of beau-mode tuning (R10), so edits land on the
current text.

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
schedule **maintain-verification-skill** daily per app; and an automation that takes a user
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
