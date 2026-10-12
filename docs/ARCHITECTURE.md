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
collisions). `claude plugin validate --strict` covers Claude specifics in CI.

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

## Generated vs. authored files

| Authored | Generated (`make gen`) |
|---|---|
| `kit.yaml` | `plugins/*/plugin.json`, `plugins/*/mcp.json` |
| `plugins/*/skills/**` | `plugins/*/.claude-plugin/plugin.json`, `plugins/*/.mcp.json` |
| `plugins/*/hooks`, `agents`, `rules` | `plugins/*/.cursor-plugin/plugin.json` (if rules) |
| docs, tools, scripts | `.claude-plugin/`, `.agents/plugins/`, `.cursor-plugin/` marketplaces |
| `plugins/*/snippets/*.md` (shared text) | `package.json`, `docs/CATALOG.md`, `docs/PRINCIPLES.md`, `.generated` |
| `principles/references/*.md`, `beau-mode/playbooks/*.md` | `GENERATED` blocks inside skills and `docs/UPSTREAM.md` |
