---
name: maintain-verification-skill
description: Periodic pass that keeps a project's verification skill and feature map honest. Read-only subagents check each feature against source, one live session drives every feature, and at most one PR ships proven corrections. Use for /maintain-verification-skill, "audit the verify skill", "is the feature map still right", or as a daily scheduled task.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack maintain-verification-skill @ 11713c6 (MIT, Lauren Tan)"
---

# Maintain a verification skill

A feature map goes stale the moment the app changes. This is the upkeep loop for a skill made by **create-verification-skill**, or any project-local verification skill with a feature map. The unit of rigor is the feature, not the sentence: check every feature file against source and drive every feature live, without proving every bullet.

## Outcomes

End with exactly one, and say which:

- **clean**: every feature got source and live coverage, and nothing needs changing. No branch, no PR.
- **changed**: one PR ships proven corrections to the docs, the harness or the map.
- **blocked**: coverage couldn't finish, or a proven fix couldn't ship safely. Say exactly what blocked it.

## Edit scope

Edit only the verification skill's own folder: its `SKILL.md`, `features/`, and the scripts it owns (including the control CLI, if it lives there). Never edit product code during a run. When the app no longer does what the map says, it's either doc drift (fix the map) or a product regression (report it; don't paper over it in the docs).

## Pass

0. **Find the target.** Look for a project-local skill with launch and drive sections and a feature map, usually `.agents/skills/verify-*/` or `.claude/skills/verify-*/`. Paths that resolve to the same folder (a `.claude/skills` link to `.agents/skills`) are one target. Several real candidates: ask which one, or if no one is watching, do all of them one at a time. None: stop and point at **create-verification-skill**. Don't invent a target.

1. **Index hygiene.** Read `features/README.md` and list its sibling files. Fix missing, extra, duplicate or dead entries.

2. **Source wave.** Start one read-only `explorer` subagent per feature file, all at once. Each explains how the feature works from source, flags likely drift with file and line citations, and returns one live-verification recipe. They never drive the app and never edit files. Return shape: feature summary, source entry points, likely drift or "none", one recipe.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

3. **Reconcile.** Every feature file has a summary. Merge overlapping recipes into as few app states as practical. Spot-check the cited drift; don't re-prove clean claims. Check recent commits for user-facing surfaces the map is missing. Call one missing only with a concrete source path.

4. **Live pass.** Required even when the source looks clean. You do all the driving yourself. Follow the skill's own launch model: one long-lived instance driven in order for servers and UIs, or a fresh isolated session per drive for short-lived CLIs. Drive every feature at least once, and hold three rules the whole time, whatever fails:
   - Never drive an instance you haven't health-checked since it last surprised you. Run doctor before the first drive, on each fresh session, and after any failed drive. Where doctor can't see the problem (a stuck UI on a healthy process), reset to a known state or relaunch.
   - Evidence captured so far survives every cleanup. Check it at its named location; don't assume.
   - Nothing a drive started outlives its usefulness. Clean up after failed attempts whether the session is stuck, exited or shared. For a shared instance, clean the residue, not the instance.

   A doctor failure caused by drift in the skill is drift: fix it within the edit scope and retry once, restarting only what the fix invalidated, before you call the pass blocked. A feature you can't reach is `verified-unreachable` only with the concrete prerequisite (auth, entitlement, OS, external state) and the route you tried. If the map doesn't mention that prerequisite, that's drift too. Re-drive every harness fix live before it ships. Tear down after the last drive, re-proofs included. The evidence stays.

5. **Triage.**
   - Wrong or missing user-POV description: doc drift. Fix it.
   - Working behavior the harness can't drive: harness gap. Fix it. Scripts stay executable and the skill body shows how to call them.
   - App behavior that's broken: product gap. Report it to the user and keep it out of this PR.

6. **Ship or stop.** For **changed**, re-read every changed file, then open one PR of proven corrections with **Opening a PR** from **beau-mode**. For **clean** or **blocked**, open no PR. Report the outcome and the coverage honestly.

Keep short run notes (features covered, unreachable prerequisites, confirmed drift, outcome) in a scratch location outside the repo. Don't commit them.

**Reply:** the outcome, one line per feature (covered, drift fixed, harness gap fixed, unreachable with prerequisite, or product gap), the PR link if any, and the product gaps for the user to triage.
