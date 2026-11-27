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

## Add a principle

1. Create `plugins/principles/skills/principles/references/<id>.md`:

   ```markdown
   ---
   id: <id>                 # kebab-case, equals the file name, never changes once published
   title: Readable Title
   group: core              # core | architecture | verification | delegation | meta
   when: "The trigger, as one sentence."
   rule: "The rule, in one or two sentences."
   source: where it came from (omit for your own)
   ---
   # Readable Title

   The full rule, why it matters, the pattern, and when to stop.
   ```

2. `make gen` adds it to the index in `principles`, the compact list in `beau-mode`, and
   `docs/PRINCIPLES.md`. Link other principles as `[Title](<other-id>.md)`.

## Add a beau-mode playbook

Create `plugins/bstack/skills/beau-mode/playbooks/<id>.md` with `id`, `title` and `when` in its
frontmatter (`when` is the trigger the router matches on), then numbered steps and a
**Reply:** line. `make gen` adds it to the router's playbook list.

## Generated blocks and snippets

Text that appears in more than one skill lives once, in `plugins/<plugin>/snippets/<name>.md`,
and is pulled into each skill with an empty block:

```markdown
<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
<!-- END GENERATED: snippet:roles -->
```

`make gen` fills it; `make check` (CI) fails if it is stale. Never edit inside a block. Other
block types: `principles-index`, `principles-compact`, `playbooks-index`, `upstream-files`.

## Adapting someone else's skill

Keep their license terms (add them to `THIRD_PARTY_NOTICES.md`), record the origin in a
`source` or `metadata.upstream` field or an `Adapted from <path> @ <commit>` header comment,
and `make gen` lists the file in `docs/UPSTREAM.md`.

## Portability rules (enforced by `make validate`)

These keep a skill behaving the same in every client:

| Do | Don't | Why |
|---|---|---|
| Use only `name`, `description`, `license`, `compatibility`, `metadata` in frontmatter | Add tool-specific frontmatter keys | Unknown keys are ignored by most clients (OpenCode drops them) |
| Reference files relative to the skill folder: `scripts/run.sh`, `[guide](references/guide.md)` | Use `${CLAUDE_PLUGIN_ROOT}` or pi's `{baseDir}` in skill bodies | Those placeholders only resolve in one tool |
| Keep `SKILL.md` under ~500 lines; move detail into `references/` | Paste whole manuals into `SKILL.md` | The full body loads into context when the skill activates |
| Prefer CLI scripts (`scripts/`) for tool access | Require MCP for core behavior | pi has no MCP; scripts run everywhere a shell exists |
| Give skill names that are unique across the whole repo | Reuse a name in two plugins | All skills share one `~/.agents/skills` directory |
| Quote frontmatter values that contain `: ` | Write `description: does X: a, b` unquoted | It is invalid YAML; some tools then skip the skill silently |
| Name a model role (`judgment`, `reviewers`) | Hard-code a model id in a skill | Model ids differ per tool and change often; agentfiles maps roles to models |
| Write descriptions with trigger phrases ("Use when ...") | Write "Helps with X" | Agents choose skills from the description alone |

## Commands a skill names (enforced by `make validate`)

When a skill tells an agent to run one of the kit's scripts, the script, the subcommand and
every flag must exist. `tools/validate.py` reads what each script under a skill's `scripts/`
accepts from its source (it never runs one) and checks every command in the inline code and
fenced blocks of each `SKILL.md`, playbook, reference and snippet:

```
error:   plugins/cfo/skills/cfo-brief/SKILL.md:45: passes --weekly to `books.py summary`, which does not accept it (it accepts --as-of, --help, --json, --month)
```

Fix the doc or the script. Inline code that names a kit script is read as a command, so
`` `books.py and quality.py` `` fails: give each its own code span.

Three things keep the check able to read a script:

- Build an argparse parser with each parser bound to a variable and every flag a string
  literal. A helper that adds arguments to a parser passed in, or a loop over flag names,
  fails the check: it can't tell which flags exist or which subcommand they belong to.
- A script that reads `sys.argv` itself keeps its flag literals in a function that takes `argv`.
- Two skills never ship a script with the same file name, since docs name a script by file name.

What the check leaves alone:

- A flag written on its own (`` `--peek` `` in a sentence), a subcommand written without its
  script (`` `next CASE` ``), and a script named outside code formatting. Write the whole
  command when it matters.
- Words after a pipe, a redirect, `&&`, `;`, a bare `--` or a `#` comment. A kit script run after one of
  those (`cd DIR && python3 scripts/x.py ...`) is still checked.
- A script that another program reads (`cat scripts/x.sh`, `ruff check scripts/x.py`), a file
  of the same name in another folder, and `./scripts/...`, which is the project's own.
- Short flags, and whether a flag's value is valid.

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
| Hooks | `hooks/hooks.json` for Claude Code. `hooks/cursor.json` for Cursor. The generator points `.cursor-plugin/plugin.json` at the Cursor file so Cursor does not load the Claude one. | Claude Code and Cursor |
| Subagents | `agents/*.md` | Claude Code, Codex (format differs slightly), and Cursor when the plugin has `.cursor-plugin/plugin.json` |
| Slash commands | prefer a skill instead | — |
| Cursor rules | `rules/*.mdc` | Cursor (the generator adds `.cursor-plugin/plugin.json` for rules, agents, commands, or hooks) |

Treat these as optional enhancements: the plugin must still be useful through its
skills alone. `docs/CATALOG.md` labels them "client-specific".

## Versioning and releases

- Bump the plugin's `version` in `kit.yaml` whenever any file under `plugins/<name>/` changes,
  then `make gen`. Claude Code re-fetches an installed plugin only when its version changes, so
  an unbumped change never reaches marketplace installs. CI enforces this on every PR
  (`make versions`); run it locally before pushing.
- Every bump needs an entry in `changes.yaml` for that plugin and version, newest first; `make gen`
  fails without one. Write each line as what a user can now do. The entries become
  `docs/CHANGELOG.md` and what `beau-help new` (and Claude Code's session-start notice) shows.
  Because the `beau-help` skill ships the changelog, releasing any plugin also bumps bstack.
- Tag releases as `vX.Y.Z` for whole-repo releases. Users can pin with
  `codex plugin marketplace add lyddonb/agent-kit --ref vX.Y.Z` or
  `pi install git:github.com/lyddonb/agent-kit@vX.Y.Z`.

## Testing a change locally

```bash
claude --plugin-dir plugins/essentials            # Claude Code, without installing
claude plugin marketplace add ./ && claude plugin install essentials@agent-kit
scripts/install.sh --project /path/to/scratch-repo # any .agents/skills reader
```
