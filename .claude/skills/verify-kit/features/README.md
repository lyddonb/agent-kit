# agent-kit verification map

This folder is the maintained record of what a user can do with an agent-kit plugin in Claude Code and how to prove each thing still works. Read this page, then use the matching feature file as the recipe. `control-kit drive <feature>` runs each recipe as written here.

## Baseline preconditions

- `$C` is `<repo>/.claude/skills/verify-kit/scripts/control-kit`, as an absolute path.
- `$C launch` has made a fresh workspace. Every other command gets it as `--ws <ws>`, or from `VERIFY_KIT_WS` in one persistent shell. Its `home/`, `profile/` (the `CLAUDE_CONFIG_DIR`), `state/` and `tmp/` are the only places a `claude` call may write.
- `$C doctor` exits 0. Its `no-credentials` line says `apiKeySource 'none'`. `drive` and `cli` refuse to run until it has passed.
- Never drive with the `claude` profile you work in, or with a workspace that `launch` didn't create.

## Driving conventions

- Run `claude` through `control-kit drive` or `control-kit cli -- <claude args>`. Both run the `claude` that `launch` resolved, under a scrubbed environment: only `PATH`, `HOME`, `TMPDIR`, `CLAUDE_CONFIG_DIR` and `AGENT_KIT_STATE` are set, all inside the workspace, and the working directory is `<ws>/cwd`. Nothing is inherited from your shell.
- The plugin comes from the target checkout, added as a directory marketplace. A directory marketplace is read in place, so a session loads the source tree and not the copy under `<profile>/plugins/cache/`.
- Every session uses `claude -p "<prompt>" --output-format stream-json --verbose --max-turns 1` with stdin closed. The profile has no login, so the CLI answers `Not logged in` before any model call, and that exit 1 is the expected result. The checks read the init event and the session file, not a model's answer.
- Each feature that starts a session has its own `AGENT_KIT_STATE` file under `<ws>/state/`. The what's-new hook marks entries seen on the first session, so a shared file would leave a later feature no first notice to check.
- The `install` feature runs first in `drive all`. After it passes, the other features run side by side. If it fails they report `blocked`.
- A feature runs once per workspace. To drive it again, run `cleanup`, then `launch` a new workspace.

## Proof and skip reporting

- Proof for each command is its argv, stdout, stderr and exit code in `<evidence>/<feature>/steps.jsonl`. Each session's full stream is kept next to it as `session-N.jsonl`.
- A change on disk is proved by reading the file back (`installed_plugins.json`, the seen-state file, the session file), not by trusting stdout. `<evidence>/profile-snapshot/` keeps those files, with a sha256 manifest, because cleanup deletes the workspace.
- Report an entry point you didn't drive as not verified. A pass here is no proof for an install from GitHub, a model choosing a skill, another plugin, or another tool.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then has exactly four H2 sections, in this order:

1. `Sub-features`: short IDs, one line each.
2. `How to get to it (user POV)`: every entry point, and which one the drive covers.
3. `Driving it with control-kit`: starts with `Preconditions:`, then labeled bullets, each pairing a user action with the exact command and its observable result.
4. `Gotchas`: traps that waste or invalidate a run.

## Features

- [Install](./install.md): add the marketplace, install bstack, and see it and `principles` listed.
- [Skills load](./skills-load.md): a session lists every bstack skill and agent.
- [Slash trigger](./slash-trigger.md): `/bstack:beau-help` expands the skill body with no login.
- [What's new hook](./whats-new-hook.md): the SessionStart hook shows the newest version once.

Not mapped yet: a model choosing a skill from plain words, an install from GitHub, the six other plugins, the research-tools MCP server, and Codex, Cursor and pi.
