# Installing agent-kit

Pick your tool. Every route installs the same skills; plugin routes also bring MCP
servers and (in Claude Code) any hooks or agents.

> If you use several tools or also want third-party skills, use
> [agentfiles](https://github.com/lyddonb/agentfiles) instead of following each
> section by hand — it does all of this from one profile.

| Tool | Skills | MCP servers | Route |
|---|---|---|---|
| Claude Code | ✅ | ✅ | plugin marketplace |
| Codex (CLI, app, IDE) | ✅ | ✅ | plugin marketplace |
| Cursor | ✅ | ✅ | plugin (Agent Plugins / `.cursor-plugin`) |
| GitHub Copilot / VS Code | ✅ | ✅ | Agent Plugins |
| pi | ✅ | ❌ (pi has no built-in MCP) | pi package |
| OpenCode | ✅ | manual | shared skills directory |
| Anything else | ✅ | manual | `npx skills` or `scripts/install.sh` |

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

```bash
codex plugin marketplace add lyddonb/agent-kit
# pin a version:
codex plugin marketplace add lyddonb/agent-kit --ref v0.1.0
```

Then enable the plugins from the Plugins directory in the ChatGPT/Codex app, or per
project in `.codex/config.toml`:

```toml
[plugins."essentials@agent-kit"]
enabled = true
```

Codex reads each plugin's root `plugin.json` (Agent Plugins 1.0) and `mcp.json`.

## Cursor

Cursor loads Agent Plugins (`plugin.json` at the plugin root) and its own
`.cursor-plugin/` format, and this repo ships a `.cursor-plugin/marketplace.json`.
Add the repository as a plugin source using the current flow in
[Cursor's plugin docs](https://cursor.com/docs/plugins). Skills-only alternative:
Cursor also reads `~/.agents/skills`, so `scripts/install.sh` works.

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
| Codex (`~/.codex/config.toml`) | `[mcp_servers.context7]` with `url = "https://mcp.context7.com/mcp"` |

## Avoiding duplicate skills

Cursor and OpenCode read **both** `~/.agents/skills` and `~/.claude/skills`. If you
install a skill into both, those tools may list it twice. Rule of thumb: put shared
skills in `~/.agents/skills` only, and give Claude Code its skills through the
plugin marketplace. (agentfiles does exactly this.)

## Uninstall

| Route | Command |
|---|---|
| Claude Code | `claude plugin uninstall essentials@agent-kit` |
| Codex | disable in the Plugins directory, or `codex plugin marketplace remove agent-kit` |
| pi | `pi remove git:github.com/lyddonb/agent-kit` |
| install.sh | `scripts/install.sh --uninstall` |
