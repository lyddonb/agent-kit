# second-opinion: a reviewer or judge from another agent's CLI

`scripts/second_opinion.py` sends one prompt to another installed agent CLI and returns its
answer. It gives a skill a model from a different family even inside a tool that only offers
its own models: a Claude Code session can ask a GPT model through `cursor-agent`.

It makes one call and never retries. It starts the CLI in that CLI's read-only mode (the table
below), which is a permission setting, not a sandbox, and the script itself writes nothing.

## The spec

A roles-file entry or a `--reviewer` value in the form `cli:<agent>:<model>`:

```yaml
reviewers:
  claude-code: [opus, "cli:cursor-agent:gpt-5.6-sol-high"]
```

`<model>` is whatever that CLI's `--model` accepts (`cursor-agent models` lists them). Every
character after the second colon belongs to the model.

| Agent | Runs | Read-only through | Loads your rules and skills |
|---|---|---|---|
| `claude` | `claude -p --output-format json` | `--permission-mode plan` | No: `--setting-sources ""`, `--disable-slash-commands`, `--strict-mcp-config` |
| `cursor-agent` | `cursor-agent -p --output-format json` | `--mode ask` | Yes, and no flag turns that off |

`codex` is not supported yet. When its sign-in fails, `codex exec` exits 0 with an empty
answer, so it needs its own real runs before it is trusted.

## Running it

Run it from the beau-mode skill's folder, where `scripts/` is. From a checkout of agent-kit,
that is `plugins/bstack/skills/beau-mode/`.

```
python3 scripts/second_opinion.py --reviewer cli:cursor-agent:gpt-5.6-sol-high --prompt-file prompt.md --cwd ../worktree --json
```

- `--prompt-file FILE` holds the prompt. `-` reads it from stdin.
- `--cwd DIR` is the folder the CLI starts in. It is not a sandbox: a reviewer can still read
  files outside it. Without it, the CLI starts in a new empty folder, so it finds no project
  files or project rules nearby. Pass the worktree when the reviewer must read code.
- `--timeout SECONDS` (default 600) kills the CLI's process group. A child that started its own
  session leaves that group and is not killed.
- `--json` prints the result object below. Without it, the answer goes to stdout and a
  failure goes to stderr.
- `--list` prints each supported agent and whether its binary is on PATH, then exits.

## The result

```json
{"reviewer": "cli:cursor-agent:gpt-5.6-sol-high", "agent": "cursor-agent", "model": "gpt-5.6-sol-high",
 "status": "ok", "answer": "...", "seconds": 41.2, "cost_usd": null, "detail": ""}
```

| `status` | Means | Exit |
|---|---|---|
| `ok` | The CLI reported success and the answer is not blank | 0 |
| `empty` | The CLI reported success with a blank answer | 1 |
| `error` | The CLI exited non-zero, reported an error, or printed output that isn't its JSON | 1 |
| `timeout` | `--timeout` passed; the CLI and its children were killed | 1 |
| `missing` | The agent's binary is not on PATH | 1 |

An unknown agent or a malformed spec is a usage error: exit 2 and no result. `detail` holds
the last lines of stderr, or why the output was rejected. `cost_usd` is filled in when the CLI
reports a cost (`claude` does, `cursor-agent` doesn't).

## Limits

- A `cursor-agent` reviewer has your user rules and skills loaded. It is an independent model,
  but not an independent reader of your conventions.
- A read-only reviewer can't run a repro. Use one for a review or a judgment that reading can
  settle, not as an `interrogate` adversary.
- Each call costs a full session start: about 40,000 input tokens for `claude` and 15,000 for
  `cursor-agent` before the prompt (measured 2026-11-26).
