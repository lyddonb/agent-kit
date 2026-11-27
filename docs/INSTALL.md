# Installing agent-kit

Pick your tool. Every route installs the same skills; plugin routes also bring MCP
servers and (in Claude Code) any hooks or agents.

> If you use several tools or also want third-party skills, use
> [agentfiles](https://github.com/lyddonb/agentfiles) instead of following each
> section by hand — it does all of this from one profile.

| Tool | Skills | MCP servers | Route | Checked on a real install |
|---|---|---|---|---|
| Claude Code | ✅ | ✅ | plugin marketplace | yes |
| Codex CLI (0.172.0 or later) | ✅ | ✅ | plugin marketplace | yes, CLI only ([results](#tested-installs)) |
| Codex app and IDE | ✅ | ✅ | plugin marketplace | not verified |
| Cursor | ✅ | ✅ | plugin (Agent Plugins / `.cursor-plugin`) | skills only, from a local clone ([results](#tested-installs)) |
| GitHub Copilot / VS Code | ✅ | ✅ | Agent Plugins | not verified |
| pi | ✅ | ❌ (pi has no built-in MCP) | pi package | not verified |
| OpenCode | ✅ | manual | shared skills directory | not verified |
| Anything else | ✅ | manual | `npx skills` or `scripts/install.sh` | not verified |

The ✅ marks say what each tool supports. The last column says whether an install of this
repo was actually run there. Until it says yes, treat that row as written from the
vendor's docs.

---

## Claude Code

```text
/plugin marketplace add lyddonb/agent-kit
/plugin install essentials@agent-kit
/plugin install eng-leadership@agent-kit
/plugin install research-tools@agent-kit
```

Or from a shell (handy in dotfiles and CI):

```bash
claude plugin marketplace add lyddonb/agent-kit
claude plugin install essentials@agent-kit            # --scope project to share with a repo
```

Update later with `claude plugin marketplace update agent-kit`. Skills appear as
`/essentials:commit-message` etc., and Claude also invokes them automatically when
relevant.

## Codex

Needs a Codex CLI with the `plugin` command. 0.172.0 has it. 0.39.0 does not: it stops at
`error: unexpected argument 'marketplace' found`, and has no `codex update`. Check with
`codex plugin --help`. To update, run `npm i -g @openai/codex@latest`, or on Homebrew
install the `codex` cask (`brew install --cask codex`). The old `codex` formula can stay at
0.39.0, so `brew upgrade codex` may not change anything.

```bash
codex plugin marketplace add lyddonb/agent-kit
# pin a version:
codex plugin marketplace add lyddonb/agent-kit --ref v0.1.0

codex plugin list                       # every agent-kit plugin, "not installed"
codex plugin add essentials@agent-kit   # repeat for each plugin you want:
# eng-leadership, research-tools, principles, bstack, cfo, video
```

`codex plugin add` installs the plugin and writes `enabled = true` for it in
`~/.codex/config.toml`. You can also enable plugins from the Plugins directory in the
ChatGPT/Codex app, or per project in `.codex/config.toml`:

```toml
[plugins."essentials@agent-kit"]
enabled = true
```

Codex reads each plugin's root `plugin.json` (Agent Plugins 1.0) and `mcp.json`. Skills
show up namespaced, as `bstack:beau-mode` or `essentials:commit-message`. After installing
`research-tools`, `codex mcp list` shows `context7`.

## Cursor

Cursor loads Agent Plugins (`plugin.json` at the plugin root) and its own
`.cursor-plugin/` format, and this repo ships a `.cursor-plugin/marketplace.json`.

Add the repository as a marketplace. This applies to your Cursor account, not one machine:

```bash
cursor-agent plugin marketplace add https://github.com/lyddonb/agent-kit
cursor-agent plugin marketplace list          # agent-kit shows with scope "user"
```

The CLI has no command to install a plugin from a marketplace. Install the plugins in the
Cursor app, following [Cursor's plugin docs](https://cursor.com/docs/plugins).

To load the plugins from a clone for one session, without installing anything:

```bash
git clone https://github.com/lyddonb/agent-kit ~/src/agent-kit
cursor-agent --plugin-dir ~/src/agent-kit/plugins/essentials \
             --plugin-dir ~/src/agent-kit/plugins/research-tools    # one flag per plugin
```

If `~/.cursor/mcp.json` already has a server named `context7`, you can't tell which one a
session is using: the plugin's server doesn't show up under a name of its own. Skills-only alternative: Cursor also reads `~/.agents/skills`, so
`scripts/install.sh` works.

## GitHub Copilot (VS Code, Copilot CLI, Copilot app)

Copilot supports Agent Plugins 1.0. Point it at a plugin folder such as
`plugins/research-tools` or add this repo as a plugin source; see
[GitHub's plugin docs](https://docs.github.com/en/copilot/concepts/agents/about-plugins).

## pi

```bash
pi install git:github.com/lyddonb/agent-kit          # all skills
pi install git:github.com/lyddonb/agent-kit@v0.1.0   # pinned
pi install -l git:github.com/lyddonb/agent-kit       # this project only
```

The repo root `package.json` declares the skill folders under its `pi` key. pi has no
MCP support, so `library-docs` falls back to web lookups or reading installed sources.

## OpenCode, Amp, Gemini CLI, and others

Any tool that reads the shared `~/.agents/skills` directory (OpenCode, Codex, Cursor,
pi, ...):

```bash
git clone https://github.com/lyddonb/agent-kit ~/src/agent-kit
~/src/agent-kit/scripts/install.sh            # symlinks into ~/.agents/skills
~/src/agent-kit/scripts/install.sh --project . # or into ./.agents/skills
```

Or with the community installer, which knows each tool's directory:

```bash
npx skills add lyddonb/agent-kit
npx skills add lyddonb/agent-kit --skill design-review -a opencode
```

### MCP servers by hand

`research-tools` uses one remote server:

| Tool | Config |
|---|---|
| OpenCode (`opencode.json`) | `"mcp": { "context7": { "type": "remote", "url": "https://mcp.context7.com/mcp" } }` |
| Codex (`~/.codex/config.toml`) | `[mcp_servers.context7]` with `url = "https://mcp.context7.com/mcp"`. Needs a Codex with HTTP MCP servers: 0.39.0 rejects it with `missing field 'command'` |

## Avoiding duplicate skills

Cursor and OpenCode read **both** `~/.agents/skills` and `~/.claude/skills`. If you
install a skill into both, those tools may list it twice. Rule of thumb: put shared
skills in `~/.agents/skills` only, and give Claude Code its skills through the
plugin marketplace. (agentfiles does exactly this.)

Cursor CLI 2026.11.22 also lists the skills of plugins installed in Claude Code (under
`~/.claude/plugins/cache/`). On a machine where agent-kit is in Claude Code, a Cursor
session sees each agent-kit skill twice even with the rule above.

## Uninstall

| Route | Command |
|---|---|
| Claude Code | `claude plugin uninstall essentials@agent-kit` |
| Codex | `codex plugin remove essentials@agent-kit`, or `codex plugin marketplace remove agent-kit` |
| Cursor | uninstall in the Cursor app, or `cursor-agent plugin marketplace remove agent-kit` |
| pi | `pi remove git:github.com/lyddonb/agent-kit` |
| install.sh | `scripts/install.sh --uninstall` |

## Tested installs

Each row is one install of this repo, run in a real client. A row records what was run
and what came back. "not verified" means nobody has run it yet.

| Date | Tool and version | agent-kit commit | What was run | What was seen | Result |
|---|---|---|---|---|---|
| 2026-11-27 | Codex CLI 0.172.0 (npm), scratch `HOME` and `CODEX_HOME`, not signed in | `1819b59` | `codex plugin marketplace add lyddonb/agent-kit`, then `codex plugin add <plugin>@agent-kit` for all 7 plugins, `codex plugin list`, `codex mcp list` | All 7 plugins `installed, enabled`. `codex debug prompt-input` lists all 44 skills as `<plugin>:<skill>`. The app server's `mcpServerStatus/list` reports `context7` from `research-tools@agent-kit`, connected (Context7 4.9.1), with tools `resolve-library-id` and `query-docs` | ✅ skills, ✅ MCP |
| 2026-11-27 | Codex CLI 0.39.0 (Homebrew and npm) | `1819b59` | `codex plugin marketplace add lyddonb/agent-kit`; by-hand `[mcp_servers.context7] url = ...` | `error: unexpected argument 'marketplace' found`; `codex mcp list` fails with `missing field 'command'` | ❌ too old: update first |
| 2026-11-27 | Cursor CLI 2026.11.22, signed in | `1819b59` | one `cursor-agent -p --mode ask` prompt with `--plugin-dir` for all 7 plugins of a fresh clone, asking for each skill's path and each MCP server | All 44 skills listed with paths inside the clone. A `context7` server connected, but the user's `~/.cursor/mcp.json` already defines `context7` and no server appeared under the plugin's name, so it can't be told apart from the user's own. `--plugin-dir … mcp list` in a scratch home listed no servers. The tool call was refused in `-p` mode | ✅ skills (local clone); MCP not verified |
| | Cursor app: install from the marketplace | | | | not verified |
| | Codex app and IDE | | | | not verified |
| | GitHub Copilot in VS Code | | | | not verified |
| | pi | | | | not verified (not installed on the test machine) |
| | OpenCode | | | | not verified (not installed on the test machine) |

[HUMAN_TASKS.md H4](../HUMAN_TASKS.md#h4-verify-installs-in-each-tool-you-use--to-do) has
the steps for the rows still marked not verified.
