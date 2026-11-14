---
run_id: 2026-11-20-export-retries
title: "Make export retries idempotent"
tier: 2                       # 1 routine, 2 significant, 3 critical (see the Large work item playbook)
predicate: "A 60,000-row export interrupted at row 30,000 and retried writes exactly 60,000 rows, in the integration test and on staging"
scope: [src/export/**, tests/export/**, migrations/2026_11_export_cursor.sql]
budget: {usd: 40, tokens: 6000000, wall_clock: 6h, max_parallel_agents: 4}   # at or under the policy's tier ceiling
estimate: {usd: 25, tokens: 3500000, wall_clock: 3h, calls: {rollouts: 0, reviews: 4}}
gates: [migration, delete-data, public-api, deploy, auth-permissions, new-dependency, secrets, outbound-message, license, spend]
staffing:
  - {role: code, tool: claude-code, model: sonnet, count: 2, isolation: worktree, why: "the cursor table and the writer are disjoint files"}
  - {role: reviewers, tool: claude-code, model: [opus, sonnet], count: 2, why: "interrogate each PR"}
review: {lenses: [correctness, operability, maintainer], decision_review: false}
spec_level: property-tests
rollback: {export-cursor-migration: "expand then contract: the old column stays until PR 3 merges, so reverting PR 2 needs no data change"}
soc2: {approved_before_build: true, tested: true, independent_review: true, recorded: true}
---

# Make export retries idempotent

<!-- An example of a complete tier 2 charter that passes `ledger charter check`. Start a real
one with `ledger charter new <slug> --title ... --tier N` and fill it the same way. Front matter
holds what the tools enforce; quote any value YAML would read as a number, date or boolean. -->

## Goal

Retried exports duplicate rows: a retry restarts from row 0 and appends. Customers on the large plan see duplicate invoices after any timeout. Done means a retry resumes where it stopped and the total is exact.

## Scope and non-scope

In: the export writer, a resume cursor stored per export, and its migration. Out: the export UI, the scheduler, and exports under 10,000 rows (they don't time out).

## Plan

1. Add the `export_cursor` table and backfill nothing (expand). Verified by the migration test on a copy of production's schema.
2. The writer records its cursor every 1,000 rows and resumes from it. Verified by a property test that kills the writer at random rows and checks the total.
3. Drop the old `restart_count` column (contract) once 2 has run on staging for a day.

## Gates and rollback

`migration` fires at units 1 and 3; both wait for an answer. Rollback is reverting the PR: unit 1 adds a table nothing reads yet, and unit 3 runs only after 2 has proven itself.

## Staffing and why

Two `code` agents in worktrees take units 1 and 2 in parallel, since they touch disjoint files. Two reviewers on different models interrogate each PR.

## Guardrails

The existing export tests and the new property test run in CI on every PR. No change to the export file format.

## Security notes

Exports contain customer data; test fixtures are synthetic. The cursor stores row offsets, never row contents.

## Review plan

interrogate with opus and sonnet on each PR; verify-work on staging with a real 60,000-row export before closing.

## Budget and estimate

About $25 for three units and four reviews, from the last two runs of similar size. Dollars are the main measure; tokens exclude cache reads.

## Risks (pre-mortem)

The run failed because a retry resumed from a stale cursor written by a different export: the cursor key must include the export id. Or the property test passed but staging still duplicated: verify on staging, not only the harness.
