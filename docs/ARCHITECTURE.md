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

Three rules decide every row:

- A workflow triggered by `pull_request` is read from the pull request's merge commit. The
  pull request can edit the workflow file, and with it any pin, flag or argument written there.
- A workflow triggered by `pull_request_target` is read from the base branch. The pull
  request cannot edit it. Whether it is safe then depends on what it checks out and runs.
- A required check is matched by its name and by the GitHub Actions app. The requirement
  doesn't say which workflow file or event must produce it.

| Gate (check name) | Repo | Required on `main` | Code at PR time | Config at PR time | Who can change it | Fix or owner |
|---|---|---|---|---|---|---|
| `books` | finances | Yes (ruleset) | `books.py check` from agent-kit, at a commit SHA written in `books.yml` | `books.yml`: the SHA and the `--base origin/main` argument. Trigger is `pull_request` | **The PR** | H13, or fix A below |
| `books` | quality | Yes (ruleset) | `quality.py check` from agent-kit, at a commit SHA written in `books.yml` | `books.yml`, same as above. Trigger is `pull_request` | **The PR** | H13, or fix A |
| `ledger-verify` | finances, quality | Yes (ruleset) | The `lyddonb/agent-ledger` Action at a commit SHA. It runs its own copy of the CLI under `python -I` and checks out the pull request's merge commit as data | `ledger.yml` on the base branch. Trigger is `pull_request_target`. The CLI reads no settings file from the tree it checks (read: `scan.py` and `repo_verify.py` have no allow or ignore list) | Not the PR. One gap: a pull request could add a second job with the same name (untested, see below) | H13 decides the name gap |
| `ledger-verify` | agent-ledger | Yes (branch protection) | The Action as the base commit has it (`ref: base.sha`, checked out to `trusted/`), with the pull request's merge commit as data | `ledger.yml` on the base branch for the `pull_request_target` run | Not the PR for that run. The same file also triggers on `pull_request`, where the pull request's copy defines a job with the same name. Today it is skipped by an `if:`, and each pull request already shows two `ledger-verify` check runs (measured on PRs 29 to 31) | H13 decides the name gap |
| `ledger-verify-self` | agent-ledger | No | The pull request's own Action | The pull request's `ledger.yml` | **The PR**, by design: it exercises Action changes before they merge | Owner: Beau. Never add it to the required list |
| `test (3.10)`, `test (3.12)`, `test (3.13)` | agent-ledger | Yes (branch protection) | The pull request's tests and source. The recorder is `quality.py record` from agent-kit, at a SHA written in `test.yml` | `test.yml`. Trigger is `pull_request` | **The PR** | H13 for `test.yml`. R29 unit 3 for a diff that weakens tests |
| `test` | agentfiles | No. The ruleset requires no checks | The pull request's tests and source. Recorder pinned in `ci.yml` | `ci.yml`. Trigger is `pull_request` | **The PR**, and a red run doesn't block the merge | H13: require `test` first, then protect `ci.yml`. R29 unit 3 for the tests |
| `validate` | agent-kit | Yes (ruleset) | All from the pull request: `validate.yml`, the `Makefile`, `tools/*.py`, `tests/` | The same files, plus `kit.yaml` | **The PR**. This repo is the checker's source, so a pin can't help | H13 for `validate.yml`. R29 unit 3 for the tests. Changes to `tools/` rely on review |
| `change-record` (a step of `validate`, `--observe`) | agent-kit | Only as part of `validate`. In observe it can't fail on content | `debrief.py` from the pull request | `validate.yml`: the `--observe` flag | **The PR** | H13. Keep it in observe until then |
| `change-record` (`--observe`) | agent-ledger, finances, quality | quality: yes (ruleset). The other two: no | `debrief.py check --base` from agent-kit, at a SHA written in `changes.yml`. The list of files that need no record is inside that script | `changes.yml`: the SHA and the `--observe` flag. Trigger is `pull_request` | **The PR** | H13, or fix A. Keep it in observe until then |
| `check-product.py` | None of the five. A product repo's agent runs it before each PR | Not a CI check anywhere | The copy in the bstack plugin installed on the author's machine (inferred from the Product phase playbook; no workflow calls it) | The repo's `docs/` files in the pull request | **The PR**: its author decides whether to run it, and nothing records that it ran | R22 puts it in CI. R29 unit 2 covers a probe edited in the diff that checks its box |
| Receipts (`receipt.py`, `check-product.py --receipts`) | None of the five, same as above | Not a CI check anywhere | The installed plugin copy and `ledger` on the author's PATH (inferred, as above) | The criterion's `Probe:` text and the command given to `receipt.py`, both chosen in the pull request | **The PR**. Where `ledger-verify` runs, it proves the ledger holding the receipts is intact. It doesn't check that a ticked box has a receipt (read: `verify.py` and `repo_verify.py` don't mention receipts) | R29 unit 2, then the receipts gate in R32 |

**Fix A, the pattern `ledger-verify` already uses in finances and quality.** Trigger on
`pull_request_target`, keep the checker's SHA in the base branch's workflow, check out the
pull request's merge commit as data, and run the checker in a way that can't import from that
checkout. It fits `books` and `change-record`, which only read files. It doesn't fit `test` or
`validate`, which run the pull request's own code by design. It needs no admin rights, only a
pull request in each repo, and that pull request is the last one able to change its own check.

**The name gap is untested.** The agent-ledger rows show two check runs named `ledger-verify`
on every pull request, one a success and one skipped, and the merges went through. Nobody has
tried a pull request where the base-branch run fails and a second run of the same name passes.
H13 should try that once on a scratch pull request before treating any `pull_request_target`
check as out of reach.

**What H13 has to work with.** No repo has a `CODEOWNERS` file. Every ruleset and
agent-ledger's branch protection ask for a pull request with zero approvals. The last 30
merged pull requests in each repo were all opened by the owner's account, agents included, and
GitHub doesn't let an author approve their own pull request. So "a change under
`.github/workflows/**` needs your review" can't be met by a review rule alone while agents
open pull requests as that account. The options are fix A where it fits, a second account for agents so that a
code-owner review means something, or a ruleset that restricts who may change those paths
(not checked: whether GitHub offers that rule for these repos).

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
