# Install

A user adds the agent-kit marketplace to Claude Code and installs bstack. Claude Code installs bstack's dependency, `principles`, with it, and `claude plugin list` shows both, enabled, at the versions in the marketplace.

## Sub-features

- `marketplace-add`: `plugin marketplace add <checkout>` exits 0 and records `agent-kit` in the profile.
- `install-bstack`: `plugin install bstack@agent-kit --json` exits 0 with outcome `ok`, and writes `installed_plugins.json` in the profile.
- `list-both`: `plugin list --json` shows `bstack` at its `kit.yaml` version and `principles`, both enabled.
- `reads-target`: bstack's `readFromFolder` is the target checkout's `plugins/bstack`.

## How to get to it (user POV)

- `claude plugin marketplace add lyddonb/agent-kit`, then `claude plugin install bstack@agent-kit` in a terminal. Not driven: it needs the network and GitHub.
- `/plugin marketplace add` and `/plugin install` inside a session. Not driven.
- The same two commands with a local checkout path as the marketplace source. **The drive uses this one**, with the target checkout.

## Driving it with control-kit

Preconditions:

- A fresh workspace from `$C launch`, with `$C doctor` exiting 0.
- An empty `profile/`. `drive all` refuses a profile that already has plugins.

- **Add the marketplace.** `claude plugin marketplace add <target>`. Exit 0, and `profile/plugins/known_marketplaces.json` names `agent-kit`.
- **Install.** `claude plugin install bstack@agent-kit --json`. Exit 0, `outcome` is `ok`, `pluginId` is `bstack@agent-kit`, and `profile/plugins/installed_plugins.json` exists.
- **List.** `claude plugin list --json`. Exit 0, a JSON list holding `bstack@agent-kit` (enabled, version equal to bstack's `version` in `kit.yaml`) and `principles@agent-kit` (enabled). bstack's `readFromFolder` resolves to `<target>/plugins/bstack`. The list is saved as `<evidence>/install/plugin-list.json`.

## Gotchas

- Drop `principles` from the target's `marketplace.json` and the install step fails with a non-zero exit. That is the failure this feature is for.
- `file://` URLs are refused as marketplace sources, and a local clone path is treated as a directory again. Pass the checkout path.
- The marketplace is read in place. A missing file in a published copy would not show here.
- `plugin install` with no `--scope` installs at user scope, which is the workspace profile. It never touches `~/.claude`, because `CLAUDE_CONFIG_DIR` points elsewhere.
