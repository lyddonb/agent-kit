# Skills load

When Claude Code starts a session with bstack installed, its init event lists every skill folder under `plugins/bstack/skills/` as `bstack:<name>`, the bstack agent as `bstack:beau-agent`, and the plugin as loaded from the target checkout. A skill folder that is missing from that list is a skill a user can't call.

## Sub-features

- `skills-listed`: each folder under `plugins/bstack/skills/` appears as `bstack:<folder name>` in the init event's `skills`.
- `agents-listed`: each file under `plugins/bstack/agents/` appears as `bstack:<file stem>` in `agents`.
- `plugin-path`: the init event's `plugins` entry for bstack points at the target checkout.

## How to get to it (user POV)

- Start any Claude Code session and type `/` to see the skills. Not driven.
- `claude -p` with `--output-format stream-json --verbose` prints the same init event as its first line. **The drive uses this one.**

## Driving it with control-kit

Preconditions:

- bstack is installed in the workspace profile. The `install` feature does this, and driving `skills-load` alone does it as a `precondition:` step.

- **Start a session.** `claude -p "/bstack:beau-help" --output-format stream-json --verbose --max-turns 1`. The init event says `apiKeySource` is `none`, which means no credential and no model call.
- **Compare the lists.** The expected skills are the directory names under `<target>/plugins/bstack/skills/`, read at drive time, so adding or removing a skill needs no edit here. Every one must be in `skills`, and `bstack:beau-agent` (and any other file in `plugins/bstack/agents/`) must be in `agents`.
- **Check the source.** The `plugins` entry named `bstack` has a `path` equal to `<target>/plugins/bstack`.

## Gotchas

- The expected list counts folders, not folders that hold a `SKILL.md`. A folder whose `SKILL.md` is deleted is missing from `skills`, and that is the failure this feature is for.
- The init event's fields come from the CLI and aren't a documented format. Re-run this feature after a Claude Code update and recheck the field names if it fails on every skill at once.
- The `skills` list also holds skills from other sources (such as `deep-research`). The check looks only for `bstack:` names.
