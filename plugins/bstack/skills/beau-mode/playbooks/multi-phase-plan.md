---
id: multi-phase-plan
title: Multi-phase plan
when: "Turning an agreed design into a tactical execution plan of small, verifiable PRs: \"turn this design into a plan\", a migration, or any change too big for one PR."
source: pstack/skills/poteto-mode/playbooks/multi-phase-plan.md @ 11713c6
---

# Multi-phase plan

**You own the plan, not the code.** The plan is a checklist that an owner runs box by box and a reviewer audits from the evidence. The plan is the deliverable. Don't implement.

Plan after the design is settled, not instead of settling it. Open questions get answered with code (the Prototype playbook, the **architect** skill), not with a longer document. Don't run an adversarial review on an abstract plan: reviewers invent theoretical risks for code that doesn't exist yet.

1. If the change is one or two files with an obvious approach, skip the plan. Say so and stop.
2. Settle open questions by prototype before you write. Run the Prototype playbook for each one and keep the branch, the SHA and the screenshots for Appendix A. Ask the human only about product or preference calls that no run can settle, and give options (`never-block-on-the-human`).
3. Explore with `explorer` subagents (`guard-the-context-window`). Each returns file pointers, conventions, test commands and entry points, not pasted file contents. Find the project's verification skill (`verify-<app>`). If there is none, the plan's first PR runs **create-verification-skill**, or Appendix C names the risk.
4. Copy the skeleton below into the plan file and fill every placeholder. Keep every heading and sub-block in the order shown. One section per PR, and one PR is one change with its own evidence (`sequence-verifiable-units`). Name the execution playbook in **How to read this**: Autonomous run when one agent drives the whole program unattended, or Feature, Refactoring or Bug fix per PR when a human starts each one.
5. Choose where the plan lives. By default, write it outside the repo (your scratch or notes folder). For a program that runs for days with several agents, commit it temporarily at `docs/plans/<slug>.md` so every agent sees the work in progress, and delete it in the last PR. Plans don't stay in the codebase.
6. Write it with the **technical-writing** skill, then **unslop**. The body is one Diátaxis mode, how-to. The appendices hold explanation and reference. Each heading states the task or the finding.
7. Run `python3 <beau-mode skill folder>/scripts/check-plan.py <plan.md>` and fix every line it prints (`encode-lessons-in-structure`).
8. Hand back the plan path and the checker's output, then stop. Execution starts only on the human's explicit go, under the playbook the plan names.

**Verification.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked (`prove-it-works`). That sentence is the verification rule, and every verification block opens with it.

- **Live** is mandatory. Lanes drive the real surface at the PR head through the project's verification skill, run in parallel with the **swarm** skill. Use 3 to 10 lanes, more for riskier PRs. Each lane is one box with a concrete scenario, the screenshot or transcript it saves, and its pass predicate.
- **Lane 1 is the regression lane against trunk.** It runs the same main scenario on trunk and on the head. If trunk doesn't have the feature, the lane records that and checks the behavior the diff adds and the end state the user waits for, instead of inventing a trunk result.
- **Perf** names the metric, the probe (run on trunk and head, interleaved), the trunk baseline measured first, and the rule with the number that fails it. If trunk lacks the feature, set an absolute budget for the added work instead of a ratio between unlike scenarios. A PR that can't affect performance says `Not perf-sensitive.` with the reason and has no boxes.
- **Review gate.** A PR that changes an interaction is reviewed by the human before merge, with screenshots and a short video. A PR that changes no interaction says `None.` and has no boxes.

````markdown
# <Program> plan

<Under ten lines. What changes, for whom, the rule the program enforces, and the PR ids in order.>

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, such as a file, a log line, a screenshot, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs the beau-mode <Autonomous run, or Feature per PR> playbook. <Who merges, and which PR ids stop at merge-ready for the human.>

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Before you start

- [ ] Show this plan to the human, then stop. Start only on an explicit go.
- [ ] Read the current versions of the execution playbook, the swarm skill, the verification skill `<path>`, and the Opening a PR playbook.
- [ ] Start a decision trail with the show-me-your-work skill.

### Order and boundaries

- [ ] Follow this dependency graph. Start dependent work only after its parent merges, or stack it on the parent branch.
  - [ ] <PR id> and <PR id> are independent and first. Both branch from `main`.
  - [ ] <PR id> after <PR id>.
- [ ] Hold the file boundaries. <PR id> touches only `<glob>`.
- [ ] Hold the review gate. <PR ids> change an interaction and wait for the human's review before merge.

### For every PR

- [ ] Run the repo's lint, typecheck, and tests before pushing.
- [ ] Run the unslop skill on the PR body and commit messages.
- [ ] Open the PR per the Opening a PR playbook.
- [ ] Run the live lanes and the perf probe with the swarm skill at the final head SHA. A new head gets fresh lanes.
- [ ] Rebase onto current trunk before the merge-ready report.

## <Task as a verb phrase> (<PR id>)

**Depends on.** <PR id, or None.>

**Files.**

- [ ] Edit `<path>`.
- [ ] Create `<path>`.
- [ ] Delete `<path>`.

**Build.**

- [ ] <One change. Name the symbol and the file.>

**You see.**

- [ ] <One observable result, with the exact log line or screen state.>

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] <Test file and the case it gains.> Run `<command>`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. <N> lanes at the PR head through `<verification skill>`.

- [ ] Lane 1. Regression lane against trunk. Run <the main scenario> at trunk and head. Save `<slug>.png`. Pass when <predicate>.
- [ ] Lane 2. <Scenario.> Save `<slug>.png`. Pass when <predicate>.
- [ ] Lane 3. <Scenario.> Save `<slug>.png`. Pass when <predicate>.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. <What is measured at both trunk and head.>
- [ ] Probe. <The command, run at trunk and head, interleaved.>
- [ ] Baseline. Record the trunk <value> first.
- [ ] Rule. <Head against trunk, with the number that fails.>

**Review gate.** The human reviews before merge.

- [ ] Copy the lane screenshots to `<media path>/<pr-id>-review-<slug>.png`.
- [ ] Record a 30 to 60 second video of the change. Save it as `<media path>/<pr-id>-review.mp4`.
- [ ] Post the screenshots and the video to the human. Stop at merge-ready.

**Merge.**

- [ ] Every lane passed at the exact head SHA.
- [ ] Review comments triaged.
- [ ] <Who merges, and how.>

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] Delete this plan file if it was committed.
- [ ] Reply to the human with the report the execution playbook names.

## Appendix A. Prototype evidence

<Each open question a prototype answered, with the branch, the SHA, and the artifacts. Each question that stays unproven.>

## Appendix B. Alternatives rejected

<Each approach weighed and why it lost.>

## Appendix C. Risks

<Each risk with the PR it lands in and what the owner watches.>

## Appendix D. Links and reading list

<Docs to read before editing. Which PRs need the how skill first and the interrogate skill before merge.>
````

**Reply:** the plan path, the PR ids with their dependencies and the review-gated set, what the prototypes proved and what stays unproven, and the checker's output.
