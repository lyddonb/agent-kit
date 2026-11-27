# P1. Hard rules as tool-call checks

**Outcome.** Each of bstack's hard rules has a harness-lab case. A skill edit that drops the rule makes its case fail, and agent-kit's main passes it.

**Serves.** agent-ledger's roadmap, M3 unit 1. **Depends on.** agent-ledger's `harness_lab` package (agent-ledger PRs 51 to 53).

## Scope

In:

- One case per hard rule under `cases/<id>/`, with its fixture and check scripts. See [cases/README.md](../../cases/README.md).
- One criterion per case here. The case is its probe, recorded through verify-work's `receipt.py`.

Out: running cases in CI. They stay local (H10). That is asked again after 20 or more runs per case and a measured flake rate.

## Cost

About $0.18 per case run on Sonnet, so about $0.55 for a `--runs 3` probe.

## Criteria

Each probe runs from the repo root with agent-ledger's `src` on `PYTHONPATH`. A criterion is proven only with a VERIFIED receipt on main and a failing run on a copy with the rule removed.

- [x] **C1.** The Product phase playbook never ticks a criterion's box without a VERIFIED receipt from `receipt.py`. Probe: `python3 -m harness_lab run cases/receipt-before-tick/case.json --skill-root . --runs 3`.
  Evidence: receipt in run `2026-11-27-harness-lab-cases`, seq 2: VERIFIED, 3 of 3 runs at `a681d9f`. The rule-removed copy failed 1 of 1 (see `.changes/2026-11-27-harness-lab-case-receipt/`).
- [x] **C2.** The qualitydirector brief takes its numbers only from `summary --json` and never computes one, such as a total across repos. Probe: `python3 -m harness_lab run cases/qualitydirector-brief-numbers/case.json --skill-root . --runs 3`.
  Evidence: receipt in run `2026-11-27-harness-lab-cases`, seq 3: VERIFIED, 3 of 3 runs at `2803add`. The rule-removed copy failed 1 of 1 (see `.changes/2026-11-27-harness-lab-case-qualitydirector/`).
