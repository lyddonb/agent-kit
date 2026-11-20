---
name: verify-kit
description: Prove an agent-kit plugin still installs into Claude Code and that a skill still loads and triggers, by running the real `claude` CLI in a throwaway profile, and keep the evidence. Covers marketplace add and install, the skills a session lists, a login-free /bstack:beau-help trigger, and the what's-new hook. Use when verifying a change under plugins/ or .claude-plugin/, before saying a plugin or skill works, or when verify-work asks for a live run.
---

# verify-kit

agent-kit's product is plugins that Claude Code installs and loads. `make test` only lints their files. This skill runs the real `claude` CLI against a checkout of agent-kit: it adds the marketplace, installs `bstack`, starts sessions, and checks what the CLI reports and what it wrote. Every command, its output and the files it wrote are kept as evidence.

Everything goes through one helper, `control-kit`. Run it from anywhere as shown below. It is standard library Python and runs on the system `python3` (3.9 is enough). It needs the `claude` CLI on PATH. It never makes a model call and needs no login.

**The isolation rule.** Every `claude` call runs under a scrubbed environment: nothing is inherited from your shell, and only `PATH`, `HOME`, `TMPDIR`, `CLAUDE_CONFIG_DIR` and `AGENT_KIT_STATE` are set, all inside a throwaway workspace. Without that, a run writes to your real `~/.agents/state/agent-kit-seen.json` and copies `CLAUDE_CODE_USER_EMAIL` into the session file. Don't run `claude` by hand for this and call it proof. Use `control-kit cli -- <args>`.

## Cold start: the whole sequence

Each line below works as its own shell call, so the sequence survives a tool that resets the working directory and environment between commands. `<repo>` is the absolute path of the agent-kit checkout, and `<ws>` is the absolute path on the `workspace` line that `launch` prints.

```bash
<repo>/.claude/skills/verify-kit/scripts/control-kit launch
#   workspace <ws>
#   evidence  <repo>/.verify/kit/<ws name>
#   target    <repo> @ <commit>
#   ready: export VERIFY_KIT_WS=<ws>
<repo>/.claude/skills/verify-kit/scripts/control-kit doctor --ws <ws>
#   every line "ok", last line "doctor: ready to drive", exit 0
<repo>/.claude/skills/verify-kit/scripts/control-kit drive all --ws <ws>
#   one PASS line per feature, last line "PASSED: 4/4 features; evidence in <evidence>", exit 0
<repo>/.claude/skills/verify-kit/scripts/control-kit cleanup --ws <ws>
#   "removed <ws>; evidence kept in <evidence>"
```

The evidence is then in the `evidence` folder that `launch` printed, and `drive-all.json` in it says `"ok": true`. In one persistent shell, you can `export VERIFY_KIT_WS=<ws>` once and leave out `--ws`. The examples below write the script as `$C` and leave out `--ws`.

To drive one feature, run `drive <feature> --ws <ws>` with a name from the map below. On a fresh workspace a feature other than `install` first adds the marketplace and installs `bstack` itself, as its own steps, so it needs no earlier `drive install`. It ends with `PASSED: 1/1 features`. Each feature runs once per workspace. To drive it again, run `cleanup`, then `launch` a new workspace. To drive another checkout, such as a copy with a change you want to test, pass `launch --target <checkout>`.

Pass looks like this: `drive` exits 0, every feature line says `PASS`, and `<evidence>/drive-all.json` has `"ok": true`.

**Inside a passing `slash-trigger`, the `claude` command exits 1, while `drive` itself exits 0.** The step runs `claude -p "/bstack:beau-help"`, and the profile has no login, so the CLI answers `Not logged in · Please run /login` and exits 1. That is the expected result, and the proof: the skill body is expanded into the session before the login check, and `total_cost_usd` is 0, so no model was called. The feature checks for exactly that exit and message, and for the body in the session file. Don't "fix" it by logging in. A login would make every drive a paid model call, and `doctor` fails on it.

Fail looks like this: `drive` exits 1, and the failing feature prints `FAIL`, the failed step, and each failed check with what it saw. For example:

```text
FAIL skills-load     2 steps, 0.81s
     failed step: session init lists the skills
     - init lists all 25 bstack skill folders as bstack:<name>: missing ['bstack:how']
```

If `install` fails, the other three features print `FAIL ... blocked: install failed`, because there is no plugin for them to check. Fix `install` first.

Exit 2 means the harness itself couldn't run, for example a missing workspace, no `claude` on PATH, a target that isn't an agent-kit checkout, or `drive` before `doctor` has passed. The message says what to do.

## Launch

`control-kit launch` creates `$TMPDIR/verify-kit-XXXX/`, which holds:

- `home/`: `HOME` for every claude call, so nothing is read from or written to your real home.
- `profile/`: `CLAUDE_CONFIG_DIR`. The marketplace, the installed plugins, settings and session files go here.
- `state/`: one `AGENT_KIT_STATE` file per feature, so each feature's what's-new hook starts from nothing.
- `tmp/`: `TMPDIR`. `cwd/`: the working directory of every claude call.
- `control-kit.json`: the record of this workspace (target checkout and commit, the absolute path of `claude`, evidence path). Every other command reads it, and `cleanup` refuses a folder without it.

It's ready once `launch` prints `ready:`. There is no server, and every claude command is a short-lived process.

Options: `--target <checkout>` drives another agent-kit checkout, `--evidence-root <dir>` moves the evidence, and `--parent <dir>` moves the workspace. Two workspaces never share anything, so parallel runs are safe.

## Doctor

`control-kit doctor` checks the workspace. It writes only inside the workspace (it starts one probe session). Run it after launch, and again whenever something looks off. Each line is `ok` or `FAIL`:

| Check | What it proves |
|---|---|
| `claude-cli` | `claude --version` runs, and its version is recorded. |
| `no-credentials` | A session's init event says `apiKeySource` is `none`. Any other value is `FAIL`: a logged-in profile would make paid model calls. The probe is killed as soon as its init event shows a credential. |
| `isolated-profile`, `isolated-home`, `isolated-state` | `CLAUDE_CONFIG_DIR`, `HOME` and `AGENT_KIT_STATE` are inside the workspace. |
| `target` | The checkout has `.claude-plugin/marketplace.json`, and its commit hasn't moved since launch. |
| `evidence-dir` | The evidence folder exists and is writable. |

`doctor --json` prints the same as JSON. Exit 0 means every line is ok. `drive` and `cli` refuse to run `claude` until the workspace's doctor has passed.

## Drive

`control-kit drive <feature>` runs the journey written in `features/<feature>.md`. Each step runs one real `claude` command, then checks its exit code and what it wrote. The first failed step stops that feature, and the other features still run. Every step is written to `<evidence>/<feature>/steps.jsonl` as it runs.

| Feature | Map | What the drive proves |
|---|---|---|
| `install` | [features/install.md](features/install.md) | `plugin marketplace add` and `plugin install bstack@agent-kit` exit 0; `plugin list` shows bstack at the `kit.yaml` version and `principles`, both enabled |
| `skills-load` | [features/skills-load.md](features/skills-load.md) | a session's init event lists every folder under `plugins/bstack/skills/` as `bstack:<name>`, and the bstack agents |
| `slash-trigger` | [features/slash-trigger.md](features/slash-trigger.md) | `/bstack:beau-help` writes a session whose user turn holds the skill body, with no login and no model call |
| `whats-new-hook` | [features/whats-new-hook.md](features/whats-new-hook.md) | the SessionStart hook exits 0 and names the newest bstack version on a first session, writes its state file, and prints nothing on the second |

`install` runs first. If it passes, the other three run side by side, which is how three sessions on one profile behave. For a claude command the map doesn't cover, use `control-kit cli -- <claude args>`, for example `$C cli -- plugin list --json`. It runs that one command in the workspace, prints its output, exits with its code, and records it in `<evidence>/cli/NNN.json`.

**Not mapped yet:** a model choosing a skill from plain words (it needs a credential and spend, differs run to run, and belongs to the triggering evals), an install from GitHub (a directory marketplace is read in place, so a file missing from a published copy would not show), the six other plugins (essentials, eng-leadership, research-tools, principles on its own, cfo, video), the research-tools MCP server, and Codex, Cursor and pi. Report anything in that list as not verified. Drive it with `cli` and add a feature file when one becomes routine.

## Evidence

The evidence for a workspace is at `<repo>/.verify/kit/<workspace name>/`, which is git-ignored. `launch` prints the path. With `--evidence-root <dir>` it is `<dir>/<workspace name>/`. It holds:

- `launch.json` and `doctor.json`: the workspace record and the doctor result.
- `<feature>/steps.jsonl`: one line per step, with argv, exit code, stdout, stderr, seconds and each check (`{check, ok, detail}`).
- `<feature>/session-N.jsonl`: the full stream-json output of each session. `<feature>/plugin-list.json`: the plugin list, in `install` and in any feature that ran its own install steps. `slash-trigger/profile-session-<id>.jsonl`: a copy of the session file the CLI wrote.
- `<feature>/result.json`: pass or fail, and the failed step and checks.
- `drive-<feature or all>.json`: the summary, with the target commit.
- `profile-snapshot/` and its `MANIFEST.sha256`: the plugin records, settings, state files and session files the drive wrote, with a sha256 each.
- `cli/NNN.json`: one per `cli` command. `cleanup.json`: written when the workspace is removed.

Proof standards:

- Drive the real CLI as a user does. Don't read the plugin files and call that a check of what Claude Code loads.
- Check what the CLI wrote (the plugin record, the seen-state file, the session file), not only stdout. The checks match only stable parts: the init event's `skills`, `agents`, `plugins` and `apiKeySource`, the hook's `exit_code` and `output`, and two strings in the session file.
- To show the drive can fail, copy the checkout and break one thing by hand: delete one skill's `SKILL.md` (fails `skills-load`), empty `hooks.json`'s `hooks` (fails `whats-new-hook`), or remove `principles` from the copy's `marketplace.json` (fails `install`). Then `launch --target <copy>` and drive it. These are hand-made breaks, not past commits. `drive all` was run against the 35 commits on main that touch `plugins/bstack` or `.claude-plugin`. The 24 since beau-help and the hook were added pass 4/4. The 11 older ones fail only because a feature did not exist yet (no `bstack:beau-help`, no hook, or no bstack plugin), so no real bug in history fails these checks.

## Cleanup

`control-kit cleanup` removes the workspace folder, and only one that has `control-kit.json` in it. It never touches the evidence. `--dry-run` prints what it would remove. No process outlives a command, so there's nothing to kill. Run cleanup after a failed run too.

## Helpers

Both scripts are executable and standard library only. Each has `--help` with an example.

- `scripts/control-kit`: `launch`, `doctor`, `drive`, `cli`, `snapshot`, `cleanup`.
- `scripts/stress-kit --runs 20 --evidence-root <dir>`: runs the cold-start sequence (launch, doctor, drive all, cleanup) N times in a row with no retries. A run passes only when every command exits as expected, `drive-all.json` survives cleanup with `"ok": true`, the workspace is gone, and the profile record, the seen-state file and a session file were each found inside the workspace before cleanup. It prints each run's time and `N/N passed in <s>s`, and writes `stress.jsonl` and `stress-summary.json`. The summary also notes the sha256 of your real `~/.agents/state/agent-kit-seen.json` and `~/.claude/plugins/installed_plugins.json` before and after. A change there is a note, not a failure, because your own sessions write those files.
