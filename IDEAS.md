# Ideas

Possibilities that are not worth a roadmap slot yet. No commitment, no priority.
Promote one to [ROADMAP.md](ROADMAP.md) when there is a concrete need.

## Skills to consider writing
- **`one-on-one-prep`** — pull a direct report's recent PRs/tickets and prior notes into an agenda.
- **`incident-postmortem`** — blameless postmortem from a timeline and chat export.
- **`estimate-review`** — sanity-check a project estimate against scope, risks, and team capacity.
- **`eng-metrics-narrative`** — turn DORA or cycle-time numbers into a leadership update.
- **`pkm-capture`** — file meeting notes and decisions into an Obsidian vault with the right links.
- **`aec-domain-primer`** — preconstruction and cost-management vocabulary for agents working in
  construction-tech code (probably belongs in a private repo).

## Packaging ideas
- **Skill "tiers" via tags** — mark skills `core` vs `experimental` in `metadata` so consumers can
  filter. Wait until there are enough skills to need it.
- **Generate an `AGENTS.md` snippet** listing installed skills for tools that do not auto-discover them.
- **Gemini CLI extension manifest** (`gemini-extension.json`) from `kit.yaml`; obra/superpowers ships one.
- **Antigravity / Devin / Kimi plugin manifests** — superpowers ships manifests for many more clients;
  add only if you start using one of them.
- **Per-skill READMEs for humans**, generated from the frontmatter plus a "try it" prompt.

## Quality ideas
- **Description linter using an LLM** — score each description for "says what and when".
- **Token budget report** — use `claude plugin details` to track the always-on cost per plugin and fail CI
  if it jumps.
- **Cross-tool smoke test in containers** — run Codex/pi/OpenCode headless in CI against a fixture repo.
  Heavy; probably only worth it if this becomes widely used.

## bstack ideas
- **Dr Eggbot-style maintenance.** A small always-running agent per repo that tends the
  garden: notices repeated helpers, creeping lint suppressions, stale feature maps, and opens
  small cleanup PRs (pstack guide part 1). Needs R18's schedules first.
- **A `control-<app>` template.** A starter control CLI (subcommands, `--json`, `--dry-run`,
  rich `--help`) that `create-verification-skill` copies and fills, instead of writing one
  from scratch per repo.
- **Principle usage stats.** Count which principles agents cite in transcripts and which
  decisions they changed. Unused principles are candidates for deletion.
- **A "steer" cheat sheet.** One printable page of the 24 principle names with one-line
  triggers, for steering agents mid-task.
- **Per-project principle sets.** Let a project's `.agentfiles.yaml` exclude principles that
  don't apply there (for example `type-system-discipline` in a shell-script repo).
- **Write it up.** A public post on adapting pstack to work across agents, once it has been
  used for a while.
- **Mode for reviewing other people's PRs.** A playbook that reviews a teammate's PR the way
  you would, using `interrogate` plus your team's conventions from the KB.
