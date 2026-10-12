# Export retry plan

Retries that land mid-run no longer write duplicate rows. The rule is that one export run writes each source row once. PRs run in order EXP-1, then EXP-2.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, such as a file, a log line, a screenshot, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs the beau-mode Autonomous run playbook. The owner merges EXP-1. EXP-2 stops at merge-ready for the human.

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Before you start

- [ ] Show this plan to the human, then stop. Start only on an explicit go.
- [ ] Read the current versions of the execution playbook, the swarm skill, the verification skill `.agents/skills/verify-exporter`, and the Opening a PR playbook.

### Order and boundaries

- [ ] EXP-2 after EXP-1.
- [ ] Hold the file boundaries. EXP-1 touches only `src/export/**`.

### For every PR

- [ ] Run `make lint test` before pushing.

## Make export writes idempotent (EXP-1)

**Depends on.** None.

**Files.**

- [ ] Edit `src/export/writer.py`.

**Build.**

- [ ] Key each write by `run_id` and `source_row_id` in `ExportWriter.write`.

**You see.**

- [ ] A retried run logs `skipped 120 rows already written`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_writer.py` gains a retry case. Run `pytest tests/test_writer.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. 3 lanes at the PR head through `verify-exporter`.

- [ ] Lane 1. Regression lane against trunk. Export the 60k fixture at trunk and head. Save `export-60k.txt`. Pass when head writes 60000 rows and trunk's count is recorded.
- [ ] Lane 2. Kill the run at row 30000 and retry. Save `retry.txt`. Pass when the table holds 60000 distinct rows.
- [ ] Lane 3. Retry twice in a row. Save `retry-twice.txt`. Pass when the table still holds 60000 distinct rows.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Wall time to export the 60k fixture.
- [ ] Probe. Run `make bench-export` at trunk and head, interleaved, ten times each.
- [ ] Baseline. Record the trunk median first.
- [ ] Rule. Fail when the head median is more than 5 percent slower.

**Review gate.** None. EXP-1 changes no interaction.

**Merge.**

- [ ] Every lane passed at the exact head SHA.

## Show retry progress in the CLI (EXP-2)

**Depends on.** EXP-1.

**Files.**

- [ ] Edit `src/cli/export.py`.

**Build.**

- [ ] Print skipped rows in `export_command`.

**You see.**

- [ ] The CLI prints `resumed, 30000 rows already written`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_cli.py` gains a resume case. Run `pytest tests/test_cli.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. 3 lanes at the PR head through `verify-exporter`.

- [ ] Lane 1. Regression lane against trunk. Resume a killed export at trunk and head. Save `resume.png`. Pass when head prints the resume line.
- [ ] Lane 2. Resume with nothing left to write. Save `resume-done.png`. Pass when the CLI prints `nothing to resume`.
- [ ] Lane 3. Run a fresh export. Save `fresh.png`. Pass when no resume line appears.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Not perf-sensitive. It changes one print call.

**Review gate.** The human reviews before merge.

- [ ] Post the lane screenshot and a short video to the human. Stop at merge-ready.

**Merge.**

- [ ] The human merges after review.

## Close the program

- [ ] Every box above is checked with its evidence.

## Appendix A. Prototype evidence

The prototype on branch `proto/idempotent-writes` showed the unique key costs 2 percent.
