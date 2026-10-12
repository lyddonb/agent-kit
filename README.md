# agent-kit

Portable skills and plugins for AI coding agents. Write them once; install them in
**Claude Code, Codex, Cursor, GitHub Copilot, pi, OpenCode**, and anything else that
speaks the open [Agent Skills](https://agentskills.io) or
[Agent Plugins](https://agent-plugins.org) standards.

```
/plugin marketplace add lyddonb/agent-kit        # Claude Code
codex plugin marketplace add lyddonb/agent-kit   # Codex
pi install git:github.com/lyddonb/agent-kit      # pi
npx skills add lyddonb/agent-kit                 # any agent, skills only
```

Full per-tool instructions: **[docs/INSTALL.md](docs/INSTALL.md)**.
Everything in the repo: **[docs/CATALOG.md](docs/CATALOG.md)**.

## What's inside

| Plugin | What it gives you |
|---|---|
| `essentials` | `commit-message` (Conventional Commits from the staged diff), `handoff-notes` (resume work in another session or another tool) |
| `eng-leadership` | `design-review` (senior-level RFC/design critique), `interview-kit` (competencies, loop, questions, rubric) |
| `research-tools` | `library-docs` skill + the Context7 MCP server for version-correct library docs |
| `bstack` | **`beau-mode`**, a rigorous engineering workflow: routes each task to a playbook, applies named principles, proves the work on the real artifact, keeps a decision trail. Plus `how`, `interrogate`, `verify-work`, `show-me-your-work`, `figure-it-out`, `reflect`, `correct`, `unslop` |
| `principles` | 24 named engineering principles ("prove it works", "subtract before you add", ...) that steer agents by name |

### bstack and beau-mode

If you want to go fast, go deep first. `bstack` is the foundation for doing engineering work
with agents at a high bar, in any tool. Start a task with:

```text
/beau-mode the export writes duplicate rows when a retry lands mid-run. repro first, then fix and verify.
```

It picks the Bug fix playbook, copies its steps into the todo list, applies the principles
that fit, proves the fix on the real surface, and says which principle changed which
decision. Steer it mid-task by principle name: "apply prove it works", "subtract before you add".

The ideas, and much of the text, come from Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/main/pstack)
(MIT), reworked to run in Claude Code, Codex, Cursor, pi and OpenCode instead of Cursor alone.
Guide: **[docs/BSTACK.md](docs/BSTACK.md)**. Principles: **[docs/PRINCIPLES.md](docs/PRINCIPLES.md)**.
What came from where: [docs/UPSTREAM.md](docs/UPSTREAM.md).

## How it works (one minute)

- A **skill** is a folder with a `SKILL.md` ([Agent Skills spec](https://agentskills.io/specification)).
  Every tool above reads the same format, so skills are written once.
- A **plugin** is a folder that bundles skills (and optionally MCP servers, hooks,
  agents). Each tool has its own manifest file name, so every plugin carries several:

  ```
  plugins/research-tools/
  ├── skills/library-docs/SKILL.md   ← you write this
  ├── plugin.json                    ← Agent Plugins 1.0 (Codex, Cursor, Copilot, ...)   generated
  ├── mcp.json                       ← Agent Plugins MCP config                         generated
  ├── .claude-plugin/plugin.json     ← Claude Code                                      generated
  └── .mcp.json                      ← Claude Code MCP config                           generated
  ```

- **`kit.yaml` is the source of truth.** `make gen` writes every manifest, the three
  marketplaces (`.claude-plugin/`, `.agents/plugins/`, `.cursor-plugin/`), pi's
  `package.json`, `docs/CATALOG.md` and `docs/PRINCIPLES.md`. It also fills the
  `GENERATED` blocks inside skills (the principle and playbook indexes, shared snippets),
  so an index can never drift from the files it lists. Generated output is committed so
  installs straight from git work; CI fails if anything is stale.

Design rationale: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Working on this repo

```bash
pip install pyyaml          # the only dependency
make gen                    # regenerate after editing kit.yaml or adding a skill
make validate               # Agent Skills spec + portability lint
make claude-validate        # `claude plugin validate --strict` (needs the claude CLI)
```

Adding a skill or plugin: [docs/AUTHORING.md](docs/AUTHORING.md).

## Related

- **[agentfiles](https://github.com/lyddonb/agentfiles)** — the *consumer* side: pick
  skills and plugins from this repo and from others (Anthropic, OpenAI, obra/superpowers, ...),
  group them into profiles, pin them, and sync them into every tool on a machine.
  This repo is just one of its sources.

## Project docs

| File | Purpose |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Planned work that is intentionally not done yet, with priorities |
| [HUMAN_TASKS.md](HUMAN_TASKS.md) | Things only a person can do (accounts, publishing, decisions) — **includes blockers** |
| [IDEAS.md](IDEAS.md) | Maybe-someday ideas that are not on the roadmap |
| [docs/KNOWLEDGE.md](docs/KNOWLEDGE.md) | How a future knowledge base plugs into principles and skills (design only) |

## License

MIT. See [LICENSE](LICENSE). Parts of `bstack` and `principles` are adapted from pstack
(MIT, Copyright (c) 2026 Lauren Tan); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Other third-party content is not vendored here; agentfiles pulls it under its own licenses.
