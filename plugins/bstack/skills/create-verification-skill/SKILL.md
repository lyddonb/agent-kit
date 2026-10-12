---
name: create-verification-skill
description: Generate a project-local verify-<app> skill that launches the real app, drives it like a user through a control CLI, captures evidence, and keeps a feature map. Any stack or surface. Use for /create-verification-skill, "make a control skill for this repo", or when a project has no scripted way to prove behavior.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack create-verification-skill @ 11713c6 (MIT, Lauren Tan)"
---

# Create a verification skill

An agent that can't drive the real app can't prove its work, and an agent that can't prove its work needs a human to check every change. This skill builds the missing piece once per project: a skill named `verify-<app>` that launches the app, drives it like a user, and captures evidence. **verify-work** uses it whenever it exists.

Write the generated skill for the next agent, not for a human. That agent reads it cold, mid-task, and has never seen the app.

## 1. Interview the repo, not the user

Answer these from the codebase. Ask the user only for what you can't observe.

- **Surface.** What does a user touch: a web UI, a CLI or TUI, a desktop app, an API, a mobile app, a library? A repo can have several. Pick the primary one and note the rest.
- **Run.** How does the app start locally? Prefer the repo's own dev command (package scripts, Makefile, README quickstart). Note ports, env vars, seed data and auth.
- **Dev environment.** What does a realistic run need: seeded data, test users, a logged-in session, feature flags, a fake for a paid external service? An agent that can't log in or has an empty database can't verify much.
- **Drive.** How can an agent interact with it? Use existing harnesses first: Playwright or Cypress specs, expect scripts, PTY helpers, curl-able endpoints, a debug port. Only then pick a generic recipe: browser automation or CDP for web and Electron, tmux or a PTY for CLIs and TUIs, plain HTTP for services.
- **Observe.** What evidence can you capture: screenshots, accessibility snapshots, terminal transcripts, response bodies, logs, exit codes, database state?
- **Isolate.** Can two instances run side by side (ports, data dirs, profiles)? If not, say so in the generated skill. Refusing to drive a shared instance beats corrupting the user's session.

If the checkout doesn't build or start as-is, fix that first or report exactly what fails. A skill written against a broken base teaches wrong steps. When an irrelevant missing asset blocks startup (a static dir the API never serves, a sample config), the generated skill may create it, marked as verification scaffolding, and remove it in cleanup.

## 2. Build the lever: a control CLI

Give the agent one command it can drive the app through, `control-<app>`, unless the repo already has one (`build-the-lever`). Wrap the harness from step 1 in it. A good control CLI for agents has:

- **Subcommands** for each job: `launch`, `doctor`, `browser click`, `cli -- <cmd>`, `snapshot`, `screenshot`, `seed`, `cleanup`.
- **Rich `--help`** on every subcommand, with an example. The agent reads help before it guesses.
- **JSON output** behind a flag (`--json` or `--format json`) for anything an agent will assert on.
- **Descriptive errors** that say what failed and what to try ("port 4173 is owned by pid 812, not this run; pass --port").
- **`--dry-run`** on anything destructive (reset, seed over existing data, delete).
- **Composable, deep commands.** Each command does one complete user-level step and hides the harness details behind it.

Keep it small. Grow it when a feature needs a new capability, not ahead of time.

## 3. Generate the skill

Put it where every tool you use will load it:

- `.agents/skills/verify-<app>/` (Codex, Cursor, pi and OpenCode read `.agents/skills`).
- If anyone uses Claude Code on the repo, also link `.claude/skills/verify-<app>` to it (`ln -s ../../.agents/skills/verify-<app> .claude/skills/`). Claude Code reads only `.claude/skills`.
- If the repo already keeps skills somewhere else, follow that instead.

Write `SKILL.md` with frontmatter (`name: verify-<app>` and a `description` naming the app, the surface, and when to use it; without frontmatter the skill never loads) and these sections. Ground each one in what you found. Leave no placeholders.

- **Launch.** The exact command that starts the app for verification, and how to tell it's ready (a log line, a port answering, a prompt). Include teardown. A short-lived CLI or TUI has no server to keep alive: launch means build or install once, then start each drive in its own isolated PTY or tmux session.
- **Doctor.** One read-only check that answers "is this instance worth driving?": process up, right build, port owned by this run, auth valid. Run it first, and again whenever anything looks off.
- **Drive.** The control CLI with real selectors and commands from this repo, not examples. Prefer stable handles (ARIA roles and names, data attributes, prompt strings, route paths) over coordinates and tab order.
- **Evidence.** What to capture and where it goes. State the proof standards: exercise the real user path, not internal setters or test-only endpoints. Capture the action and the resulting state, not only the final screen. Check side effects (files written, rows inserted, messages sent) alongside what's visible. Use mocks only where a production boundary already isolates the external system. When the safe path is a dry-run or test mode, observe what it actually skips (files, network, git refs) rather than trusting its name.
- **Cleanup.** How to tear down what the run created. Never kill by process name; kill what you started. Cleanup removes instances and scratch state, never the evidence. Proof artifacts survive teardown in a location the skill names.
- **Helpers.** Every script the skill ships is executable, and the skill body shows how to call it. A helper the reader has to reverse-engineer is not a helper.

## 4. Seed the feature map

The feature map is the project's maintained record of what users can do and how to prove each thing works. Create `features/README.md` in the skill folder plus one file per user-facing feature. Start with the top 3 to 5 features you can find in routes, commands, menus or docs.

Follow the shape in [references/feature-map-example/](references/feature-map-example/README.md): a README with baseline preconditions, driving conventions, proof rules and an index, then one file per feature. Each feature file opens with an H1 and one paragraph of user-visible behavior, then exactly these H2s in order:

1. `Sub-features`: short IDs, one line each.
2. `How to get to it (user POV)`: every entry point a user has.
3. `Driving it with <harness>`: starts with `Preconditions:`, then labeled bullets pairing each user action with an exact command and the observable result.
4. `Gotchas`: traps that waste or invalidate a run.

Keep implementation details out of the map. A proof that drives one convenient entry point is incomplete when the map lists others.

## 5. Prove the generated skill

Follow its instructions end to end once: launch, doctor, drive one mapped feature, capture evidence, clean up. Then confirm the evidence still exists at the named location. A cleanup that deletes the proof fails this step. Fix what fails, and run the generated cleanup after every failed attempt so broken runs don't strand processes and ports. A skill that was never run is a draft, not a deliverable.

## 6. Hand it over

Commit the skill and the control CLI on a branch and run **Opening a PR** from **beau-mode**. In the reply, give the skill path, the features mapped, the evidence from step 5, and anything you couldn't make drivable and why.

Point the user at **maintain-verification-skill** to keep the map honest as the app changes, and recommend running it daily with their tool's scheduler (for example a scheduled task or automation).
