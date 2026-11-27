# harness-lab cases

Each folder here checks that one of bstack's hard rules holds when an agent uses the skill. A case is a prompt, a fixture repo and assertions on the tool calls the agent makes and the state it leaves. The format and the judge are agent-ledger's `harness_lab` package; its `src/harness_lab/README.md` is the contract.

| Case | Rule | Criterion |
|---|---|---|
| `receipt-before-tick` | The Product phase playbook never ticks a box without `receipt.py` | [P1-C1](../docs/phases/P1-harness-lab.md) |

A case folder holds `case.json`, its `fixture/`, any `checks/` scripts the `after` assertions run (kept beside the case, out of the agent's reach), and `rule-removed.patch`, the skill edit the case must catch.

## Running

Each run starts `claude -p` and costs about $0.18, so cases run on a developer's machine and never in CI (H10). From the repo root, with a `git archive` of agent-ledger's main in a scratch folder:

```sh
export PYTHONPATH=<agent-ledger archive>/src
python3 -m harness_lab run cases/receipt-before-tick/case.json --skill-root . --runs 3
```

It exits 0 when every run passed, 1 when one failed, and 2 when a run could not be judged.

## Recording a receipt

A case is the probe of its criterion, so record it with verify-work's `receipt.py` and a ledger run open here. Keep `PYTHONPATH` in the environment, not after `--`, so the probe in the ledger holds no local path:

```sh
python3 plugins/bstack/skills/verify-work/scripts/receipt.py --run RUN_ID --actor ACTOR_JSON \
  --spec docs/phases/P1-harness-lab.md --criterion C1 \
  -- python3 -m harness_lab run cases/receipt-before-tick/case.json --skill-root . --runs 3
```

## The rule-removed copy

To see the case fail, build a copy with the rule removed in a scratch folder, never in this repo:

```sh
git archive HEAD | tar -x -C <scratch>
cd <scratch> && patch -p1 < cases/receipt-before-tick/rule-removed.patch
git init -q && git add -A && git commit -qm 'rule removed'
```

Then run the same command there. Its receipt goes into a ledger in that scratch repo, because its commit exists nowhere else.
