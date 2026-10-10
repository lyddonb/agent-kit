# Authoring skills and plugins

## Add a skill to an existing plugin

1. Create `plugins/<plugin>/skills/<skill-name>/SKILL.md`:

   ```markdown
   ---
   name: skill-name            # must equal the folder name; a-z, 0-9, single hyphens, <= 64 chars
   description: What it does AND when to use it, with the words a user would actually say. <= 1024 chars.
   license: MIT
   metadata:
     author: lyddonb
     version: "0.1.0"          # metadata values must be strings - quote numbers
   ---

   # Skill title

   Steps, rules, examples...
   ```

2. Optional folders next to `SKILL.md`: `scripts/` (code the agent runs),
   `references/` (docs loaded on demand), `assets/` (templates, data).
3. Run `make gen validate` and commit everything, including generated files.

## Add a plugin

1. `mkdir -p plugins/<name>/skills`
2. Add an entry to `plugins:` in `kit.yaml` (name, description, keywords, category, optional `mcp`).
3. `make gen validate claude-validate`

The generator refuses plugin directories that are not declared in `kit.yaml`, and
declared plugins whose directory is missing.

## Portability rules (enforced by `make validate`)

These keep a skill behaving the same in every client:

| Do | Don't | Why |
|---|---|---|
| Use only `name`, `description`, `license`, `compatibility`, `metadata` in frontmatter | Add tool-specific frontmatter keys | Unknown keys are ignored by most clients (OpenCode drops them) |
| Reference files relative to the skill folder: `scripts/run.sh`, `[guide](references/guide.md)` | Use `${CLAUDE_PLUGIN_ROOT}` or pi's `{baseDir}` in skill bodies | Those placeholders only resolve in one tool |
| Keep `SKILL.md` under ~500 lines; move detail into `references/` | Paste whole manuals into `SKILL.md` | The full body loads into context when the skill activates |
| Prefer CLI scripts (`scripts/`) for tool access | Require MCP for core behavior | pi has no MCP; scripts run everywhere a shell exists |
| Give skill names that are unique across the whole repo | Reuse a name in two plugins | All skills share one `~/.agents/skills` directory |
| Write descriptions with trigger phrases ("Use when ...") | Write "Helps with X" | Agents choose skills from the description alone |

## MCP servers

Declare them once in `kit.yaml` using the Agent Plugins shape:

```yaml
mcp:
  my-remote:
    type: streamable-http          # or sse
    url: https://example.com/mcp
  my-local:
    type: stdio
    command: ./bin/server          # ./ = inside the plugin; or a bare name like npx
    args: ["--data", "${PLUGIN_DATA}/cache"]
```

`make gen` writes `mcp.json` (Agent Plugins) and `.mcp.json` (Claude Code), translating
`${PLUGIN_ROOT}`/`${PLUGIN_DATA}` to `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_DATA}` and
`streamable-http` to Claude's `http`. Never put secrets in `headers` or `env`; both
files are public package data.

## Client-specific extras (hooks, agents, commands, rules)

Agent Plugins 1.0 standardizes only skills and MCP. Other components are per-tool:

| Component | Where to put it | Who loads it |
|---|---|---|
| Hooks | `hooks/hooks.json` | Claude Code (Codex and Cursor have their own formats) |
| Subagents | `agents/*.md` | Claude Code, Codex (format differs slightly) |
| Slash commands | prefer a skill instead | — |
| Cursor rules | `rules/*.mdc` | Cursor (the generator adds `.cursor-plugin/plugin.json` automatically) |

Treat these as optional enhancements: the plugin must still be useful through its
skills alone. `docs/CATALOG.md` labels them "client-specific".

## Versioning and releases

- Bump `version` in `kit.yaml` (per plugin, or in `defaults`) when behavior changes.
  Claude Code pins users to the manifest version until it changes.
- Tag releases as `vX.Y.Z` for whole-repo releases. Users can pin with
  `codex plugin marketplace add lyddonb/agent-kit --ref vX.Y.Z` or
  `pi install git:github.com/lyddonb/agent-kit@vX.Y.Z`.

## Testing a change locally

```bash
claude --plugin-dir plugins/essentials            # Claude Code, without installing
claude plugin marketplace add ./ && claude plugin install essentials@agent-kit
scripts/install.sh --project /path/to/scratch-repo # any .agents/skills reader
```
