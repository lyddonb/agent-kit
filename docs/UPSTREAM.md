# Upstream provenance

`bstack` and `principles` adapt Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/main/pstack)
(MIT). This page says what came from where, what we changed, and how to take in her later
improvements on purpose instead of drifting apart silently.

## What we kept, changed and left out

| Area | pstack | Here |
|---|---|---|
| Principles | 24 skills, one per principle, Cursor frontmatter | One `principles` skill with 24 reference files and a generated index. Text nearly verbatim; cross-links rewritten; "brain note" became the knowledge base |
| Router | `poteto-mode` with 23 playbooks, a Cursor custom mode | `beau-mode` with 13 playbooks; always-on behavior comes from agentfiles' instruction block instead of a Cursor mode. Adds a "restate the task" start step from the pstack guide |
| Models | Cursor `Task` calls with Grok and Opus model ids, configured in `.cursor/rules/pstack-models.mdc` | Four roles (`code`, `judgment`, `explorer`, `reviewers`) read from `.agents/roles.yaml` in the project or `~/.agents/roles.yaml`, per tool, written by agentfiles |
| Workflow skills | how, why, architect, arena, swarm, interrogate, show-me-your-work, figure-it-out, reflect, correct, unslop, technical-writing, tdd, ... | how, why, teach, recall, architect, arena, swarm, technical-writing, interrogate, verify-work (new), create- and maintain-verification-skill, show-me-your-work, figure-it-out, reflect, correct, unslop |
| Transcripts | Cursor's `agent-transcripts/` only | Claude Code, Codex, Cursor and pi, via a shared snippet and `find-transcripts.py` |
| Dependencies | `cursor-team-kit` (deslop, control-ui, control-cli), Cursor built-ins (`create-skill`, `/loop`, `/babysit`) | None; replaced with tool-neutral steps. Verification skills generate a project `control-<app>` CLI instead of relying on control-ui and control-cli |
| Verification skills | Generated into `.cursor/skills/verify-<app>/` | Generated into `.agents/skills/verify-<app>/`, linked into `.claude/skills/` for Claude Code |
| Plan checker | `check-plan.mjs` (Node), fixed ten live lanes, Cursor cloud VMs, Bugbot, `/loop` audit ticks | `check-plan.py` (Python, unit-tested), 3 to 10 lanes through the project's verification skill, perf may be declared not perf-sensitive, plan deleted at close |
| Workflow references | `why/references/**`, `architect/references/**`, the feature-map example | Copied from pstack @ 11713c6 with principle cross-links rewritten; they carry no frontmatter, so the generated table below lists only their parent skills |

Not ported yet (see [ROADMAP.md](../ROADMAP.md)): `automate-me`, `blast-radius`, `tdd`, `no-comments`,
`ketchup`, and the babysit, shipping, orchestrate, autopilot, hillclimb, forensics, visual-parity
and worktree-cleanup playbooks. Upstream's prompt distillation (00b14f1) is adopted only in the
skills ported at 11713c6; the files still marked `@ ccb5507` predate it.

## Taking in upstream changes

agentfiles watches pstack as a source without installing it (`sources.yaml`, `watch: [pstack]`).

```bash
agentfiles update pstack --diff     # what changed under pstack/ since the commit we adapted
```

For each change, decide one of three things and note it in the PR that acts on it:

1. **Adopt**: the change is generic. Port it into the matching file below, keep our tool-neutral
   wording, bump the commit in the file's `source`/`upstream` field, and run `make gen validate`.
2. **Adapt**: the idea is good but Cursor-specific. Rewrite it in terms of roles, snippets and
   tool-neutral steps.
3. **Skip**: it doesn't fit how you work. No action.

Accept the new commit into agentfiles' lock only after the PR lands, so the next `update` shows
only what is still unreviewed.

## Adapted files

<!-- BEGIN GENERATED: upstream-files (tools/kitgen.py) -->
| File | Adapted from |
|---|---|
| `plugins/bstack/skills/architect/SKILL.md` | `pstack architect @ 11713c6` |
| `plugins/bstack/skills/arena/SKILL.md` | `pstack arena @ 11713c6` |
| `plugins/bstack/skills/beau-mode/SKILL.md` | `pstack poteto-mode @ ccb5507, playbooks updated from 11713c6` |
| `plugins/bstack/skills/beau-mode/playbooks/authoring-a-skill.md` | `pstack/skills/poteto-mode/playbooks/authoring-a-skill.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/autonomous-run.md` | `pstack/skills/poteto-mode/playbooks/autonomous-run.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/bug-fix.md` | `pstack/skills/poteto-mode/playbooks/bug-fix.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/eval.md` | `pstack/skills/poteto-mode/playbooks/eval.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/feature.md` | `pstack/skills/poteto-mode/playbooks/feature.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/investigation.md` | `pstack/skills/poteto-mode/playbooks/investigation.md @ 11713c6` |
| `plugins/bstack/skills/beau-mode/playbooks/multi-phase-plan.md` | `pstack/skills/poteto-mode/playbooks/multi-phase-plan.md @ 11713c6` |
| `plugins/bstack/skills/beau-mode/playbooks/opening-a-pr.md` | `pstack/skills/poteto-mode/playbooks/opening-a-pr.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/pause-safely.md` | `pstack/skills/poteto-mode/playbooks/pause-safely.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/perf-issue.md` | `pstack/skills/poteto-mode/playbooks/perf-issue.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/prototype.md` | `pstack/skills/poteto-mode/playbooks/prototype.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/refactoring.md` | `pstack/skills/poteto-mode/playbooks/refactoring.md @ ccb5507` |
| `plugins/bstack/skills/beau-mode/playbooks/session-pickup.md` | `pstack/skills/poteto-mode/playbooks/session-pickup.md @ ccb5507` |
| `plugins/bstack/skills/correct/SKILL.md` | `pstack correct @ ccb5507` |
| `plugins/bstack/skills/create-verification-skill/SKILL.md` | `pstack create-verification-skill @ 11713c6` |
| `plugins/bstack/skills/figure-it-out/SKILL.md` | `pstack figure-it-out @ ccb5507` |
| `plugins/bstack/skills/how/SKILL.md` | `pstack how @ ccb5507` |
| `plugins/bstack/skills/how/references/explainer-prompt.md` | `pstack/skills/how/references/explainer-prompt.md @ ccb5507` |
| `plugins/bstack/skills/how/references/explorer-prompt.md` | `pstack/skills/how/references/explorer-prompt.md @ ccb5507` |
| `plugins/bstack/skills/interrogate/SKILL.md` | `pstack interrogate @ ccb5507` |
| `plugins/bstack/skills/interrogate/references/code-quality-review.md` | `pstack/skills/interrogate/references/code-quality-review.md @ ccb5507` |
| `plugins/bstack/skills/interrogate/references/lead-judgment.md` | `pstack/skills/interrogate/references/lead-judgment.md @ ccb5507` |
| `plugins/bstack/skills/interrogate/references/reviewer-prompt.md` | `pstack/skills/interrogate/references/reviewer-prompt.md @ ccb5507` |
| `plugins/bstack/skills/interrogate/references/rubric.md` | `pstack/skills/interrogate/references/rubric.md @ ccb5507` |
| `plugins/bstack/skills/maintain-verification-skill/SKILL.md` | `pstack maintain-verification-skill @ 11713c6` |
| `plugins/bstack/skills/recall/SKILL.md` | `pstack recall @ 11713c6` |
| `plugins/bstack/skills/reflect/SKILL.md` | `pstack reflect @ ccb5507` |
| `plugins/bstack/skills/reflect/references/divergent-reviewer.md` | `pstack/skills/reflect/references/divergent-reviewer.md @ ccb5507` |
| `plugins/bstack/skills/reflect/references/judgment-reviewer.md` | `pstack/skills/reflect/references/judgment-reviewer.md @ ccb5507` |
| `plugins/bstack/skills/reflect/references/synthesizer.md` | `pstack/skills/reflect/references/synthesizer.md @ ccb5507` |
| `plugins/bstack/skills/reflect/references/tooling-reviewer.md` | `pstack/skills/reflect/references/tooling-reviewer.md @ ccb5507` |
| `plugins/bstack/skills/show-me-your-work/SKILL.md` | `pstack show-me-your-work @ ccb5507` |
| `plugins/bstack/skills/show-me-your-work/scripts/log.sh` | `pstack/skills/show-me-your-work/scripts/log.sh @ ccb5507` |
| `plugins/bstack/skills/swarm/SKILL.md` | `pstack swarm @ 11713c6` |
| `plugins/bstack/skills/teach/SKILL.md` | `pstack teach @ 11713c6` |
| `plugins/bstack/skills/technical-writing/SKILL.md` | `pstack technical-writing @ 11713c6` |
| `plugins/bstack/skills/unslop/SKILL.md` | `pstack unslop @ ccb5507` |
| `plugins/bstack/skills/why/SKILL.md` | `pstack why @ 11713c6` |
| `plugins/essentials/skills/grilling/SKILL.md` | `mattpocock/skills skills/productivity/grilling/SKILL.md @ 95249b0` |
| `plugins/principles/skills/principles/SKILL.md` | `pstack @ ccb5507` |
| `plugins/principles/skills/principles/references/attack-the-premise.md` | `pstack/skills/principle-attack-the-premise @ ccb5507` |
| `plugins/principles/skills/principles/references/boundary-discipline.md` | `pstack/skills/principle-boundary-discipline @ ccb5507` |
| `plugins/principles/skills/principles/references/build-the-lever.md` | `pstack/skills/principle-build-the-lever @ ccb5507` |
| `plugins/principles/skills/principles/references/checklists/benchmark.md` | `pstack/skills/benchmark-checklist @ ccb5507` |
| `plugins/principles/skills/principles/references/encode-lessons-in-structure.md` | `pstack/skills/principle-encode-lessons-in-structure @ ccb5507` |
| `plugins/principles/skills/principles/references/exhaust-the-design-space.md` | `pstack/skills/principle-exhaust-the-design-space @ ccb5507` |
| `plugins/principles/skills/principles/references/experience-first.md` | `pstack/skills/principle-experience-first @ ccb5507` |
| `plugins/principles/skills/principles/references/explain-the-number.md` | `pstack/skills/principle-explain-the-number @ ccb5507` |
| `plugins/principles/skills/principles/references/fix-root-causes.md` | `pstack/skills/principle-fix-root-causes @ ccb5507` |
| `plugins/principles/skills/principles/references/foundational-thinking.md` | `pstack/skills/principle-foundational-thinking @ ccb5507` |
| `plugins/principles/skills/principles/references/guard-the-context-window.md` | `pstack/skills/principle-guard-the-context-window @ ccb5507` |
| `plugins/principles/skills/principles/references/laziness-protocol.md` | `pstack/skills/principle-laziness-protocol @ ccb5507` |
| `plugins/principles/skills/principles/references/make-operations-idempotent.md` | `pstack/skills/principle-make-operations-idempotent @ ccb5507` |
| `plugins/principles/skills/principles/references/migrate-callers-then-delete-legacy-apis.md` | `pstack/skills/principle-migrate-callers-then-delete-legacy-apis @ ccb5507` |
| `plugins/principles/skills/principles/references/minimize-reader-load.md` | `pstack/skills/principle-minimize-reader-load @ ccb5507` |
| `plugins/principles/skills/principles/references/model-the-domain.md` | `pstack/skills/principle-model-the-domain @ ccb5507` |
| `plugins/principles/skills/principles/references/never-block-on-the-human.md` | `pstack/skills/principle-never-block-on-the-human @ ccb5507` |
| `plugins/principles/skills/principles/references/outcome-oriented-execution.md` | `pstack/skills/principle-outcome-oriented-execution @ ccb5507` |
| `plugins/principles/skills/principles/references/prove-it-works.md` | `pstack/skills/principle-prove-it-works @ ccb5507` |
| `plugins/principles/skills/principles/references/redesign-from-first-principles.md` | `pstack/skills/principle-redesign-from-first-principles @ ccb5507` |
| `plugins/principles/skills/principles/references/separate-before-serializing-shared-state.md` | `pstack/skills/principle-separate-before-serializing-shared-state @ ccb5507` |
| `plugins/principles/skills/principles/references/sequence-verifiable-units.md` | `pstack/skills/principle-sequence-verifiable-units @ ccb5507` |
| `plugins/principles/skills/principles/references/subtract-before-you-add.md` | `pstack/skills/principle-subtract-before-you-add @ ccb5507` |
| `plugins/principles/skills/principles/references/test-behavior-not-implementation.md` | `pstack/skills/principle-test-behavior-not-implementation @ ccb5507` |
| `plugins/principles/skills/principles/references/type-system-discipline.md` | `pstack/skills/principle-type-system-discipline @ ccb5507` |
<!-- END GENERATED: upstream-files -->
