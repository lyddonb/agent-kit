# Architecture and decisions

## Goals

1. Author a skill or plugin **once** and have it install natively in every major agent.
2. Keep the authored content tool-neutral; isolate tool-specific packaging in generated files.
3. Make installs work straight from git (no build step on the consumer side).

## The standards this builds on (as of October 2026)

| Layer | Standard | Status |
|---|---|---|
| Skill format | [Agent Skills](https://agentskills.io/specification) (`SKILL.md`) | Supported by essentially every agent |
| Skill location | `~/.agents/skills`, `.agents/skills` | Read by Codex, Cursor, OpenCode, pi; Claude Code uses `~/.claude/skills` |
| Plugin package | [Agent Plugins 1.0](https://agent-plugins.org/specification) (`plugin.json`, `skills/`, `mcp.json`) | Codex, Cursor, Copilot/VS Code, Kiro, OpenHands, others. **Not** Claude Code, OpenCode, or pi |
| Claude Code plugin | `.claude-plugin/plugin.json`, `.mcp.json` | Claude Code's native format |
| pi package | `package.json` with a `pi` key | pi's native format |

## Decisions

### D1. One monorepo, plugins are the unit, skills live inside plugins
Every tool expects one marketplace file per repo, and plugins contain skills, so a
single repo with `plugins/<name>/skills/<skill>` serves every distribution channel.
A skill lives physically inside exactly one plugin (not symlinked from a shared
folder) because Agent Plugins rejects paths that resolve outside the plugin root and
some clients copy plugins into a cache. pi's glob and `npx skills` still find skills
under `plugins/*/skills`, so nothing is duplicated.

### D2. Generate manifests from `kit.yaml`; commit the output
Hand-maintaining four manifest flavors per plugin drifts quickly. A ~300-line
generator with one dependency (PyYAML) is cheaper than the drift. Output is committed
because every consumer (Claude marketplaces, Codex marketplaces, `pi install git:`)
reads the repo as-is.

### D3. Ship Agent Plugins as the portable floor, plus Claude's format
`plugin.json` + `mcp.json` cover Codex, Cursor, Copilot and others. Claude Code still
needs `.claude-plugin/plugin.json` and a differently shaped `.mcp.json`. We do not
emit `.codex-plugin/plugin.json` (Codex treats it as a fallback) or
`.cursor-plugin/plugin.json` unless the plugin has Cursor-only parts (`rules/`).

### D4. Portability lint over trust
`tools/validate.py` enforces the parts of the spec that differ between clients in
practice (name/folder match, string metadata, placeholders, cross-plugin name
collisions). It also checks that every kit script, subcommand and flag a skill names
exists, read from the script's source. `claude plugin validate --strict` covers Claude
specifics in CI.

### D5. This repo publishes; it does not curate
Choosing third-party skills, grouping them into personas, and pinning versions is the
job of [agentfiles](https://github.com/lyddonb/agentfiles). Keeping curation out of
here keeps this repo shareable and free of personal preferences.

### D6. Fork pstack's ideas into a tool-neutral bstack instead of installing pstack
pstack is the best available model of rigorous agent work, but nearly all of it is bound to
Cursor: model ids in subagent calls, a `.cursor/rules` config, Cursor's transcript folder,
custom modes and Cursor-only plugins. Its 24 principles have no Cursor references at all.
So the principles are adapted nearly verbatim, and the router and workflow skills are
rewritten around tool-neutral roles and steps. pstack stays a watched upstream
(see [UPSTREAM.md](UPSTREAM.md)) so improvements are pulled in deliberately.

### D7. Principles are one skill with reference files, not 24 skills
Every installed skill adds its description to every session in every tool. pstack hides its
24 principle skills with Cursor's `disable-model-invocation`, which other tools ignore. One
`principles` skill with one file per principle costs about 120 tokens instead of about 900,
works identically everywhere, and keeps each principle addressable by a stable id (D9).

### D8. Model choice lives in a roles file, not in skills
Skills name a role (`code`, `judgment`, `explorer`, `reviewers`); agentfiles writes which model
each role uses per tool to `~/.agents/roles.yaml` (a project's `.agents/roles.yaml` wins when present). Model ids change monthly and differ by tool
and subscription, so hard-coding them (as pstack does) would make every skill tool-specific
and stale. A missing entry means "use the current model", so the skills still work with no
roles file at all.

### D9. Shared text and indexes are generated, never copied
The principle index in `principles` and `beau-mode`, the playbook list, the roles and
transcript snippets, and the provenance table are `GENERATED` blocks filled by `make gen`
from one source each, and CI fails when they are stale. This applies the
`encode-lessons-in-structure` principle to the repo itself, and it is the seam a future
knowledge base will use to feed skills (see [KNOWLEDGE.md](KNOWLEDGE.md)).

### D10. Project verification skills live in the app repo, under `.agents/skills`
`create-verification-skill` writes `verify-<app>` into the app's own repo, not into agent-kit,
because it is about one app's launch commands, test users and selectors. It goes in
`.agents/skills/` (read by Codex, Cursor, pi and OpenCode) with a link from `.claude/skills/`
for Claude Code. Its feature map is per-feature files with a fixed set of headings, the same
one-file-per-unit shape as the principles, so tools (and a future knowledge base) can index it.

### D11. New subagent jobs reuse the four roles
Arena runners and judges, why investigators, recall miners, swarm workers and verification
source readers all map onto `code`, `judgment`, `explorer` and `reviewers` instead of adding
roles. A new role would need a change in agentfiles and in every profile; a mapping in the
skill text costs nothing. Add a role only when one job's model choice genuinely conflicts with
another's.

## Can a pull request change the check that judges it?

An audit of every verification gate in the runtime's five repos, as of 2026-11-21 (roadmap
R29, unit 1). It answers one question per gate: when a pull request is checked, do the
check's code and config come from somewhere the pull request can write? A gate that answers
"the PR" can be turned off by the change it is meant to judge. Nothing is fixed here. The
table is the input to H13 in `HUMAN_TASKS.md`.

Each cell was read from the workflow files on each repo's `main` and from
`gh api repos/lyddonb/REPO/rulesets/ID` (for agent-ledger, `branches/main/protection`), unless
it is marked inferred or untested.

Three rules decide every row. They are GitHub's documented behaviour, not something this
audit measured:

- A workflow triggered by `pull_request` is read from the pull request's merge commit. The
  pull request can edit the workflow file, and with it any pin, flag or argument written there.
- A workflow triggered by `pull_request_target` is read from the base branch. The pull
  request cannot edit it. Whether it is safe then depends on what it checks out and runs.
- A required check is matched by its name and by the GitHub Actions app. The requirement
  doesn't say which workflow file or event must produce it.

| Gate (check name) | Repo | Required on `main` | Code at PR time | Config at PR time | Who can change it | Fix or owner |
|---|---|---|---|---|---|---|
| `books` | finances | Yes (ruleset) | `books.py check` from agent-kit, at a commit SHA written in `main`'s `books.yml` | `main`'s `books.yml`. On a pull request the trigger is `pull_request_target` only (H13 fix A, 2026-11-22); the merge commit is checked out as data | Not the PR. Proved on a closed scratch PR in quality (below). On the `local-mac` runner, only against mistakes | Done (fix A) |
| `books` | quality | Yes (ruleset) | `quality.py check` from agent-kit, at a commit SHA written in `main`'s `books.yml` | Same as above | Not the PR. Proved: lyddonb/quality#48 rewrote a booked row and gutted its own copy; `main`'s run failed and the PR stayed `BLOCKED`. On the `local-mac` runner, only against mistakes | Done (fix A) |
| `ledger-verify` | finances, quality | Yes (ruleset) | The `lyddonb/agent-ledger` Action at a commit SHA. It runs its own copy of the CLI under `python -I` and checks out the pull request's merge commit as data (read at the pinned commit, v1.0.0, which is older than receipts) | `ledger.yml` on the base branch. Trigger is `pull_request_target`. The CLI reads no settings file from the tree it checks (read: `scan.py` and `repo_verify.py` have no allow or ignore list) | Not the PR. A second job with the same name can't outvote it (measured, see below) | No change |
| `ledger-verify` | agent-ledger | Yes (branch protection) | The Action as the base commit has it (`ref: base.sha`, checked out to `trusted/`), with the pull request's merge commit as data | `ledger.yml` on the base branch for the `pull_request_target` run | Not the PR for that run. The same file also triggers on `pull_request`, where the pull request's copy defines a job with the same name. Today it is skipped by an `if:`, and each pull request already shows two `ledger-verify` check runs (measured on PRs 29 to 31). Both must pass (measured, see below) | No change |
| `ledger-verify-self` | agent-ledger | No | The pull request's own Action | The pull request's `ledger.yml` | **The PR**, by design: it exercises Action changes before they merge | Owner: Beau. Never add it to the required list |
| `test (3.10)`, `test (3.12)`, `test (3.13)` | agent-ledger | Yes (branch protection) | The pull request's tests and source. The recorder is `quality.py record` from agent-kit, at a SHA written in `test.yml` | `test.yml`. Trigger is `pull_request` | **The PR** | H13 for `test.yml`. R29 unit 3 for a diff that weakens tests |
| `test` | agentfiles | No. The ruleset requires no checks | The pull request's tests and source. Recorder pinned in `ci.yml` | `ci.yml`. Trigger is `pull_request` | **The PR**, and a red run doesn't block the merge | H13: require `test` first, then protect `ci.yml`. R29 unit 3 for the tests |
| `validate` | agent-kit | Yes (ruleset) | All from the pull request: `validate.yml`, the `Makefile`, `tools/*.py`, `tests/` | The same files, plus `kit.yaml` | **The PR**. This repo is the checker's source, so a pin can't help | H13 for `validate.yml`. R29 unit 3 for the tests. Changes to `tools/` rely on review |
| `change-record` | agent-kit | Yes (ruleset, since 2026-11-22) | `main`'s `debrief.py`, checked out to `trusted/` from the base commit and run under `python -I` | `main`'s `change-record.yml`, `pull_request_target` only. The step inside `validate` is gone | Not the PR. Proved: lyddonb/agent-kit#100 had no record, gutted its own copy and added a same-name job; `main`'s run failed and the PR stayed `BLOCKED`. A change to `debrief.py` takes effect from the next PR | Done (fix A) |
| `change-record` | agent-ledger, finances, quality | quality: yes (ruleset). The other two: no. Enforced in all three (H16) | `debrief.py check --base` from agent-kit, at a SHA written in `main`'s `changes.yml`. Its exempt paths come from `.changes/exempt` on `origin/main` | `main`'s `changes.yml`, `pull_request_target` only | Not the PR. On the `local-mac` runner (quality, finances), only against mistakes | Done (fix A) |
| `check-product.py` | None of the five. A product repo's agent runs it before each PR | Not a CI check anywhere | The copy in the bstack plugin installed on the author's machine (inferred from the Product phase playbook; no workflow calls it) | The repo's `docs/` files in the pull request | **The PR**: its author decides whether to run it, and nothing records that it ran | R22 puts it in CI. R29 unit 2 covers a probe edited in the diff that checks its box |
| Receipts (`receipt.py`, `check-product.py --receipts`) | None of the five, same as above | Not a CI check anywhere | The installed plugin copy and `ledger` on the author's PATH (inferred, as above) | The criterion's `Probe:` text and the command given to `receipt.py`, both chosen in the pull request | **The PR**. Where `ledger-verify` runs, it proves the ledger holding the receipts is intact. It doesn't check that a ticked box has a receipt (read: `verify.py` and `repo_verify.py` don't mention receipts) | R29 unit 2, then the receipts gate in R32 |
| Reliability checklist (`checklist.py`, run by `verify-work`) | agent-kit keeps a `.agents/checklist.json`. agent-ledger's is in its pull request 34 | Not a CI check anywhere. It prints checks and exits 0 | The copy in the bstack plugin installed on the author's machine | `.agents/checklist.json`, read from the working tree and from the merge base. An item the pull request removes or turns off still prints, marked (bstack 0.33.0) | **The PR** for whether it runs at all and whether each printed check is done. The base for which items apply | None needed for the content. Running it is the author's choice until a gate reads its result (R32) |

**Fix A, the pattern `ledger-verify` already uses in finances and quality.** Trigger on
`pull_request_target`, keep the checker's SHA in the base branch's workflow, check out the
pull request's merge commit as data, and run the checker in a way that can't import from that
checkout. It fits `books` and `change-record`, which only read files. It doesn't fit `test` or
`validate`, which run the pull request's own code by design. It needs no admin rights, but it
takes two pull requests per repo (inferred from the trigger rules, not tried): the first adds
the `pull_request_target` trigger beside the old one, and the second removes `pull_request`.
One pull request that swaps the trigger would get no run of the required check at all, because
the base's file lacks the new trigger and its own file lacks the old one. Fix A is also only as
good as the name gap below.

**The name gap is closed (measured 2026-11-22, H13).** When two check runs share a required
check's name, every one of them must pass. A later run that passes doesn't replace an earlier
one that failed.

- On branch protection: scratch pull request lyddonb/agent-ledger#36. A bad run folder made
  the base-branch `pull_request_target` run of `ledger-verify` fail at 02:33:46Z. The pull
  request's own `ledger.yml` added a `pull_request` job with the same name, which passed at
  02:36:39Z. GraphQL `isRequired` was true for both, every other required check passed, and
  `mergeStateStatus` stayed `BLOCKED`.
- On a ruleset: scratch pull request lyddonb/agent-kit#92. A stale generated file made
  `validate` fail. A second workflow's job, also named `validate`, passed two minutes later.
  The result was the same: both runs were required, and the pull request stayed `BLOCKED`.

The raw GraphQL answers are in the quality repo, in
`.audit/runs/2026-11-22-protect-gates/evidence/`. Both tests ran in one order, with the
failure first. That is the order a pull request would need to outvote the base run.

So a pull request can't get past a base-branch run by adding a job of the same name. The same
rule makes fix A's first step safe: while a workflow has both triggers, the base-branch copy
must pass whatever the pull request does to its own copy.

**`pull_request_target` always runs the default branch's workflow** (GitHub's docs, "Events
that trigger workflows"; observed when a pull request into a side branch got no
`pull_request_target` run). This makes fix A stronger, because no branch can carry an older,
weaker copy. It also means a new `pull_request_target` job can't run before it merges. Once a
required job like that is on `main`, a broken one blocks every pull request, including the one
that would fix it. The only way out then is to drop the check from the ruleset, merge the fix,
and add the check back.

**Fix A depends on the checker.** It holds only while the checker reads nothing from the tree
it checks that could steer it. Read for H13: `debrief.py` keeps its exempt list in the script.
`books.py` and `quality.py` read the books' data files, which are what they check. None of
them loads code, an allow list or an ignore list from the checked tree. A future checker that
reads its settings from the repo would reopen the gap.

**On the Mac's self-hosted runner, fix A guards against mistakes, not hostile code.**
quality and finances run `books`, `change-record` and `ledger-verify` on the `local-mac` runner.
It isn't ephemeral, and it runs as the owner's macOS user (read 2026-11-22: three
`Runner.Listener` processes as that user, with work folders that persist between jobs). A pull
request's own `pull_request` job, or any workflow file it adds, runs its own code there. That
code could plant a git hook in the reused checkout, edit `~/.gitconfig` or replace `uv`, and the
next base-branch run would execute it (found in H13's security review, inferred end to end).
A job that holds `actions: write` could also cancel or delete the base-branch run; whether a
deleted run still counts toward the requirement is unmeasured. Neither is new with fix A, and
`ledger-verify` was already exposed. Both need code written to attack the check. An agent that
loosens a check in good faith, which is what fix A stops, doesn't write that. Agents on that Mac
already run as that user with the owner's keys, so a pull request that did this would gain
nothing an agent doesn't already have. Closing it needs trusted jobs on runners that pull
request code can't reach, such as hosted runners or a separate ephemeral machine.

**Under fix A, a checker change lands in two pull requests.** The base-branch run judges every
pull request with `main`'s checker. Take a pull request that changes what the checker accepts,
such as a new record key, a new books column or a pin bump that migrates a format, and that also
uses the change: the old checker fails it. The first pull request changes the checker, or moves
the pin, and nothing else. The second uses the change.

**What H13 has to work with.** No repo has a `CODEOWNERS` file. Every ruleset, and
agent-ledger's branch protection, asks for a pull request with zero approvals. Every ruleset's
bypass list is empty, so nobody can merge past a failing required check without editing the
ruleset first, not even the owner. Agents open pull requests as the owner's account, and GitHub
doesn't let an author approve their own pull request. GitHub offers these repos the following
(its docs, read 2026-11-22):

- **Code owner review.** It needs an approval from someone other than the author. While agents
  use the owner's account, nobody can give it.
- **Required reviewers**, a rule that makes a team approve changes to given paths, isn't
  available on user-owned repos, which have no teams.
- **Restrict file paths** is a push ruleset rule. Push rulesets exist only for private and
  internal repos, which here means quality and finances. Whether this account's plan offers
  them is unchecked. The rule blocks the push itself for everyone not on its bypass list. With
  an empty list the owner can't change workflows either. With "Repository admin" on the list,
  agents bypass it too, because they are that admin.

So fix A is the one fix that needs no admin rights, and only for checks that read files. Every
other protection depends on agents having an identity of their own. That covers `validate` and
`test`, which run the pull request's own code by design. It also covers a pull request that
weakens a workflow for the *next* pull request: fix A judges that change with the old, strict
copy, which passes it.

**Other things the audit turned up.**

- quality requires `change-record` while the check runs with `--observe`. The requirement
  proves the job ran, not that a record exists.
- agent-ledger's `ledger.yml` lacks the step the finances and quality copies have, which fails
  the run when `refs/pull/N/merge` doesn't yet hold the pull request's current head.
- Every workflow uses `actions/checkout@v4`, `actions/setup-python@v5` and the like by tag.
  A pull request can't move those tags, so they are outside this question, but they are not
  pinned by SHA.

## Generated vs. authored files

| Authored | Generated (`make gen`) |
|---|---|
| `kit.yaml` | `plugins/*/plugin.json`, `plugins/*/mcp.json` |
| `plugins/*/skills/**` | `plugins/*/.claude-plugin/plugin.json`, `plugins/*/.mcp.json` |
| `plugins/*/hooks`, `agents`, `rules` | `plugins/*/.cursor-plugin/plugin.json` (if rules) |
| docs, tools, scripts | `.claude-plugin/`, `.agents/plugins/`, `.cursor-plugin/` marketplaces |
| `plugins/*/snippets/*.md` (shared text) | `package.json`, `docs/CATALOG.md`, `docs/PRINCIPLES.md`, `.generated` |
| `principles/references/*.md`, `beau-mode/playbooks/*.md` | `GENERATED` blocks inside skills and `docs/UPSTREAM.md` |
