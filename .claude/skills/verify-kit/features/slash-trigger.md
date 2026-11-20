# Slash trigger

A user types `/bstack:beau-help`. Claude Code expands the skill's `SKILL.md` into the conversation before any model call, so the skill triggers whether or not the user is logged in. This is the login-free proof that a skill loads and triggers. It does not show that a model chooses the skill from plain words, which is what the triggering evals are for.

## Sub-features

- `slash-expands`: the session file's user turn holds the skill body, with `Base directory for this skill:` and the skill's first heading.
- `source-is-target`: that base directory is the target checkout's `plugins/bstack/skills/beau-help`.
- `no-model`: the session exits 1 with `Not logged in` and a `total_cost_usd` of 0.

## How to get to it (user POV)

- Type `/bstack:beau-help` in a Claude Code session. Not driven.
- `claude -p "/bstack:beau-help"` in a terminal. **The drive uses this one**, with stream-json output.

## Driving it with control-kit

Preconditions:

- bstack is installed in the workspace profile (the `install` feature, or a `precondition:` step).

- **Run the trigger.** `claude -p "/bstack:beau-help" --output-format stream-json --verbose --max-turns 1`. **Exit 1 is the passing result.** The result text is `Not logged in · Please run /login` and `total_cost_usd` is 0, because the profile has no credential. The skill body was written before the login check.
- **Read the session file.** `<ws>/profile/projects/*/<session id>.jsonl`, with the session id from the init event. It must exist inside the workspace, and a copy is kept in the evidence.
- **Find the body.** A user turn holds `Base directory for this skill: <path>`, and the same turn holds the first `# ` heading of `plugins/bstack/skills/beau-help/SKILL.md` (read at drive time). The path must resolve to `<target>/plugins/bstack/skills/beau-help`.

## Gotchas

- Don't read exit 1 as a failure. If the exit is 0 or the result has no `Not logged in`, something is different: a login in the profile, or a CLI change. `doctor`'s `no-credentials` line is the first thing to check.
- The session file's layout is not a documented format. The check matches only two stable strings, `Base directory for this skill:` and the heading. After a Claude Code update, recheck both if the step fails.
- A slash command that doesn't exist is passed to the model as text. That is why `doctor` and every session kill the process when the init event shows a credential.
