---
run_id: 2026-11-27-r32-hook-gates
title: "Gates get observe and enforce modes; bstack ships a commit gate and a Stop hook (agent-kit R32)"
tier: 2                      # 1 routine, 2 significant, 3 critical
predicate: "agent-ledger's S2 spec and agentfiles' policy carry a `checks:` map (check id to off, observe or enforce; stricter wins; a missing id is observe), and `agentfiles sync` writes it to ~/.agents/policy.yaml; bstack ships a commit gate (PreToolUse on git commit) and a Stop hook in plugins/bstack/hooks/hooks.json that read that mode; in a real headless Claude Code session in observe mode, a commit made without verify-work or a review appends one would-block lesson to the machine's weekly flags run and the commit succeeds; in enforce mode the same session is denied twice and the third commit goes through with the reason recorded; with the Stop hook in enforce, a session that leaves a failing test is sent back to the agent with the failing output; agentfiles' builder profile allows bstack's hooks; ROADMAP R32 is marked done and R6 says why it was not needed; every unit PR is merged with all checks green"
scope: [".audit/runs/2026-11-27-r32-hook-gates/**", "plugins/bstack/hooks/**", "plugins/bstack/skills/verify-work/scripts/**", "tests/**", ".agents/checks.yaml", "kit.yaml", "changes.yaml", "docs/**", "ROADMAP.md", "HUMAN_TASKS.md", ".changes/**", "generated files `make gen` rewrites", "agent-ledger: docs/specs/S2-policy-and-identity.md", "agent-ledger: .changes/**", "agentfiles: agentfiles/policy.py", "agentfiles: agentfiles/cli.py", "agentfiles: tests/**", "agentfiles: profiles/personas/builder.yaml", "agentfiles: docs/PROFILES.md", "agentfiles: .changes/**", "scratch git repos under the session's scratch folder"]
budget: {usd: 50, tokens: 8000000, wall_clock: 8h, max_parallel_agents: 3}
estimate: {usd: 30, tokens: 5000000, wall_clock: 5h, calls: {rollouts: 0, reviews: 4}}
gates: [migration, delete-data, public-api, deploy, auth-permissions, new-dependency, secrets, outbound-message, license, spend]
staffing:
  - {role: orchestrator, tool: claude-code, model: opus, count: 1, why: "grounded this charter; writes the hook code and the spec and policy changes itself, since each is small and the risk is in the hook contract; keeps the ledger"}
  - {role: reviewers, tool: claude-code, model: [opus, "cli:cursor-agent:gpt-5.6-sol-high"], count: 2, why: "interrogate the commit gate PR and the Stop hook PR from two model families, with a security lens"}
review: {lenses: [correctness, security, operability], decision_review: false}
spec_level: types
rollback: {spec: "revert the agent-ledger PR; the key is optional, so old policy files stay valid", agentfiles: "revert the PR; a policy without `checks:` parses as before", hooks: "set the check to `off` in a profile and run `agentfiles sync`, or revert the bstack PR and bump the version so Claude Code re-fetches", allow-line: "remove `allow: [hooks]` from the bstack entry and run `agentfiles sync`"}
soc2: {approved_before_build: true, tested: true, independent_review: true, recorded: true}
---

# Gates get observe and enforce modes; bstack ships a commit gate and a Stop hook (agent-kit R32)

## Goal

Agents push red commits, and they commit without proving the change works. Two Claude Code hooks catch both at the moment they happen. A Stop hook runs the repo's cheap checks when the agent finishes, so a red tree goes back to the agent instead of to CI. A commit gate stops a commit when the session ran neither verify-work nor a review. Each check has a mode: `off`, `observe` (log what it would have blocked, block nothing) or `enforce`. Everything ships in observe. Beau moves a check to enforce after a week of logs shows no false block (H14 step 3).

Done means the predicate above holds on real headless Claude Code sessions, not only on unit tests.

## What I measured before writing this

- **Plugin hooks run in Beau's sessions.** A headless `claude -p` run on 2026-11-27 ran bstack's SessionStart hook: with `AGENT_KIT_STATE` pointed at a scratch file, the hook created that file. Desktop session transcripts record `hook_success` for the same hook, most recently on 2026-11-27. Claude Code installs bstack from the agent-kit marketplace and runs `hooks/hooks.json` with no extra allow step, so new hooks run once this ships and the plugin updates.
- **The trigger.** R32 waits for "an agent has pushed a red first commit at least twice". lyddonb/agent-ledger#19 had a red first commit, and lyddonb/agent-kit#85 had a red later commit. Other red pull-request runs point at commits no longer on any pull request, so whether those were first commits is unknown. Both cited cases come from GitHub's own check history. Labelled: one first commit measured, the second inferred.
- **The ledger already takes the observe log.** On a scratch repo, `ledger append --type lesson` with `data.kind: "would-block"` was accepted and `ledger verify` passed. No S3 change is needed.
- **The policy file rejects unknown keys.** agentfiles' `parse_policy` allows only version, gates, budgets, security, audit, identity and approvers. So the mode needs a spec change (S2 in agent-ledger) and a parser change (agentfiles).

## R6 is not in this run

R32's roadmap entry depends on R6, the neutral hook definition in `kit.yaml` emitted per tool. Its Claude Code half would generate the `hooks/hooks.json` that Claude Code already reads as hand-written source. That changes no behavior. No second tool can take a plugin hook today: agentfiles installs plugin hooks natively only in Claude Code, and agentfiles R2 (native installs in Codex, Cursor and pi) is deferred. R6's own trigger is "a hook worth having in at least two tools", and both hooks here are Claude Code only.

So this run writes the hooks by hand, like the existing SessionStart hook, and drops R6 from R32's dependencies. R6 stays at P2. If Beau wants these gates in Cursor too, that is R6 plus agentfiles R2, a separate run.

## Data shapes

**The mode.** A new optional S2 key:

```yaml
checks:                 # verification checks, by id: off | observe | enforce
  commit-gate: observe
  stop-checks: observe
```

Stricter wins across profiles, `local.yaml` and a project's `.agents/policy.yaml`: enforce beats observe, which beats off. A missing id is observe. Known ids: `commit-gate`, `stop-checks`, and the three that already print observe lines (`spec-drift` for R22, `receipts`, `test-guard` for R29). This run wires only the first two; the other three keep printing until R29's trigger ("before any gate moves to enforce") makes them read the mode. `checks:` is not `gates:`. A gate waits for a person. A check is a machine verdict with an anti-stall rule.

**What the hooks read.** Each hook gets Claude Code's JSON on stdin (`session_id`, `transcript_path`, `cwd`, `tool_input` or `stop_hook_active`). It reads the mode from the project's `.agents/policy.yaml`, then `~/.agents/policy.yaml`, stricter wins. Its per-session state, the count of blocks so far, is one small JSON file per session id under `~/.agents/state/checks/`.

**The cheap checks.** A repo declares them in `.agents/checks.yaml`:

```yaml
stop: ["make check"]    # commands the Stop hook runs from the repo root
timeout_s: 120
```

No file means the Stop hook does nothing for that repo.

**The observe log.** One `lesson` entry per would-block, `data.kind: "would-block"`, in the machine's weekly flags run that `~/.agents/flags.yaml` names, through `ledger append` as `references/flags.md` writes flags. `data` holds the check id, the repo name, the reason and the session id. Evidence holds the command only. No transcript text. The flags repo is private.

## The state machine per check and session

`clear` → (a commit with no verify-work or review in the transcript) → `would-block` (observe: log, allow) or `blocked 1` (enforce: deny with the reason) → `blocked 2` → (the third attempt) `let-through`: allow, and log why. Running verify-work or a review returns the session to `clear`. The Stop hook follows the same counts: Claude Code's `stop_hook_active` flag plus the per-session count cap it at two send-backs. Any error inside a hook allows the action and prints to stderr. A broken hook must never block work.

## Scope and non-scope

In: the S2 spec text, agentfiles' policy parser, `sync` output, `policy check` and the builder profile's allow line, bstack's two hooks and their tests, agent-kit's own `.agents/checks.yaml`, the roadmap and human tasks, and this run's folder.

Out: Codex, Cursor and pi hooks (R6 and agentfiles R2); wiring `spec-drift`, `receipts` and `test-guard` to the mode (R29); the quality brief's section counting would-block lines (quality phase 1h follow-up); moving any check to enforce (Beau, H14 step 3); any CI or workflow change.

## Plan

1. **S2 gains `checks:` (agent-ledger PR).** Spec text, the stricter-wins rule, the known ids, the default. Change record included. The `public-api` gate fires here: the policy file is a contract that agentfiles and bstack read. I stop and ask at this PR.
2. **agentfiles parses and merges `checks:` (agentfiles PR).** `parse_policy` accepts it, the merge keeps the stricter mode, `policy check` rejects a project file that loosens one, `sync` writes it, and `_policy_summary` prints it. Tests for each rule. The same PR adds `allow: [hooks]` to `mine:@bstack` in `profiles/personas/builder.yaml`. Drafted beside unit 1; merges after it.
3. **The commit gate (agent-kit PR, bstack minor bump).** `plugins/bstack/hooks/commit_gate.py` on `PreToolUse` with matcher `Bash`. It acts only on a command that runs `git commit`. It looks in the transcript for a Skill call to verify-work, interrogate or code-review, or a review subagent, since the session's last commit. The mode reader and the observe logger are shared with unit 4. Tests on fixture transcripts cover every edge of the state machine above.
4. **The Stop hook (agent-kit PR).** `plugins/bstack/hooks/stop_checks.py` on `Stop`. It runs only when the session changed the working tree or HEAD, and the repo has `.agents/checks.yaml`. In enforce it blocks with the tail of the failing output. agent-kit gets its own `.agents/checks.yaml` (`make check`). Tests as in unit 3.
5. **Prove it on real sessions.** Headless `claude -p` sessions in scratch git repos, with `AGENT_KIT_STATE`, the flags root and the policy pointed at scratch copies so nothing real is touched:
   - Observe: a commit without verifying logs one would-block line, and the commit lands.
   - Enforce: two denies, then the third commit lands with the reason logged.
   - Stop hook in enforce: a session that leaves a failing test gets the failing output back and fixes it.

   Raw output goes in this run's `evidence/`, with private paths removed.
6. **Roadmap and human tasks (agent-kit PR).** R32 is marked done. R6 records why it wasn't needed. H14 keeps step 3 (the observe week).
7. **Close.** verify-work on the predicate, spend, lessons, archived sessions, seal. The run branch merges last, with a merge commit.

Units 1 and 3 don't depend on each other. Unit 2 needs 1. Unit 4 shares unit 3's mode reader, so it stacks on 3. Unit 5 needs 2, 3 and 4 merged. Unit 6 needs 5.

## Gates and rollback

- `public-api` fires at unit 1, the S2 policy format. I stop that thread and ask before opening it as ready.
- `auth-permissions` doesn't fire. The hooks decide whether an agent may commit, which is a workflow check, not access control. You merge every unit PR yourself.
- `new-dependency` doesn't fire. The hooks are standard-library Python 3, like `whats_new.py`.
- `secrets` doesn't fire. No token is read. The hooks read the transcript path Claude Code hands them, and log only ids, reasons and the command.
- `spend` if a limit or the stop-loss is reached.

Rollback is in the front matter. The real risk is a hook that blocks every commit or every stop. Observe by default, fail-open on any error, and the anti-stall cap bound it, and `off` in a profile turns it off at once.

## Staffing and why

I write every change myself. Each unit is a few hundred lines at most, and the design evidence is already in this session. Two reviewers interrogate units 3 and 4 with a security lens: opus in Claude Code, and GPT-5.6 through `cli:cursor-agent:gpt-5.6-sol-high` (the roles file's reviewers list), so the review crosses two model families. Every change is made in a new worktree cut from `origin/main` and pushed with an explicit branch name. Run attended: you are around for the gate at unit 1 and each merge. If you leave mid-run, I pause before anything that would run unattended, since the policy sandboxes tier 2 unattended runs and this tool can't sandbox.

## Guardrails

- Every hook fails open. An exception, a missing file or a timeout allows the action and prints one line to stderr.
- The default mode is observe. No profile in this run sets enforce. Unit 5 sets it only on scratch policies.
- Unit 5 never touches the real flags run, the real policy or the real seen-state. Each probe points them at scratch copies.
- The observe log holds no transcript text and no private repo details beyond the repo's name, and it goes only to the private flags repo.
- No CI or workflow file changes.

## Security notes

The Stop hook runs commands a repo declares in `.agents/checks.yaml`, on every stop in a session that changed that repo. A session can edit that file. That is the R29 shape, "a change can edit the check that judges it", so this is a convenience check, never a merge gate. CI stays the gate. The commit gate reads the session transcript, which holds everything typed and read. It reads it in place, keeps nothing from it, and logs only a reason and the command. Hook commands run with your permissions, like every plugin hook (agentfiles `docs/SECURITY.md`).

## Review plan

interrogate (opus and GPT-5.6, security lens) on units 3 and 4. Units 1, 2 and 6 get verify-work and their own CI. verify-work on the predicate at close, against real sessions.

## Budget and estimate

About $30: six PRs (one spec, one parser, two hooks, one docs, plus the run branch), about eight headless probe sessions on a small model, four review calls, and the close. Based on this session's cost so far and the size of the protect-gates run, which was larger and is also stored in a ledger. Most wall-clock time is waiting for merges. Dollars are the main measure; tokens exclude cache reads.

## Risks (pre-mortem)

- **The run failed because the commit gate blocked commits that had been verified.** For example, a review ran in a subagent whose call the transcript records differently, or verify-work ran under another name. Unit 3's fixtures come from real transcripts of sessions that did verify, and the observe week catches the rest before enforce.
- **The Stop hook made every stop slow.** It only runs when the tree changed and the repo declares checks, under a timeout, and agent-kit declares only `make check`.
- **Claude Code's hook payload differed from what I assumed** (field names, how a deny reads). Unit 5 drives real sessions, not mocks, and the units are cheap to fix before merge.
- **Two sessions wrote the same per-session state file.** It is keyed by session id, and a lost count only fails open.
