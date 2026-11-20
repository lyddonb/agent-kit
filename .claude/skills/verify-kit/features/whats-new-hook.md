# What's new hook

bstack ships a SessionStart hook (`hooks/hooks.json`) that runs `skills/beau-help/scripts/whats_new.py --hook`. On a user's first session it says which agent-kit versions are new and marks them seen in `$AGENT_KIT_STATE`. On the next session it prints nothing.

## Sub-features

- `hook-runs`: a first session has one SessionStart `hook_response` with exit code 0.
- `first-notice`: that response's `systemMessage` names the newest bstack version from `changes.json`.
- `state-written`: the feature's own seen-state file appears in `<ws>/state/` and lists the newest bstack entry.
- `second-silent`: a second session's hook exits 0 with empty output.

## How to get to it (user POV)

- Start a Claude Code session with bstack installed. The notice shows once after an update. Not driven by hand.
- `claude -p "/bstack:beau-help"` with `AGENT_KIT_STATE` pointing at a fresh file. **The drive uses this one**, twice, with the same state file.

## Driving it with control-kit

Preconditions:

- bstack is installed in the workspace profile (the `install` feature, or a `precondition:` step).
- `<ws>/state/whats-new-hook.json` doesn't exist. The drive checks this first. No other feature or `doctor` uses that file.

- **First session.** `claude -p "/bstack:beau-help" --output-format stream-json --verbose --max-turns 1`. The stream has one `hook_response` event for `SessionStart` with `exit_code` 0. Its `output` is JSON whose `systemMessage` contains `bstack <newest version>`. The state file now exists inside the workspace and lists `bstack@<newest version>`.
- **Second session.** Same command, same state file. The `hook_response` has exit code 0 and an empty `output`.

## Gotchas

- `whats_new.py` shows only the last 14 days of entries on a first run. If the newest bstack entry in `changes.json` is older than that, a silent first notice is correct, and the drive checks for silence instead. The first-notice check is then not exercised, so report it as not verified.
- Empty `hooks.json`'s `hooks` and the first session has no SessionStart `hook_response` at all. That is the failure this feature is for.
- The hook runs `python3` from the scrubbed `PATH`, which finds the system `python3`. The script supports 3.9.
- The `-p` session fires the `startup` matcher, which is the one the hook uses.
