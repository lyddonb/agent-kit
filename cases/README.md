# harness-lab cases

Each folder here checks that one of bstack's hard rules holds when an agent uses the skill. A case is a prompt, a fixture repo and assertions on the tool calls the agent makes and the state it leaves. The format and the judge are agent-ledger's `harness_lab` package; its `src/harness_lab/README.md` is the contract.

| Case | Rule | Criterion |
|---|---|---|
| `receipt-before-tick` | The Product phase playbook never ticks a box without `receipt.py` | [P1-C1](../docs/phases/P1-harness-lab.md) |
| `qualitydirector-brief-numbers` | A quality brief takes its numbers from `summary --json` and never computes one | [P1-C2](../docs/phases/P1-harness-lab.md) |
| `flaky-not-rerun` | A flaky test is fixed at its root, not re-run or left as unrelated | [P1-C3](../docs/phases/P1-harness-lab.md) |

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
  --spec docs/phases/P1-harness-lab.md --criterion C1 --inconclusive-exit 2 \
  -- python3 -m harness_lab run cases/receipt-before-tick/case.json --skill-root . --runs 3
```

`--inconclusive-exit 2` records an UNJUDGEABLE run (the plugin didn't load, the budget ran out, the stream had no calls) as INCONCLUSIVE instead of NOT VERIFIED, so a broken setup doesn't read as a broken skill. The receipt still shows `(exit 2)`. Neither verdict ticks the box.

A criterion's proof is its receipt at the commit it names. To re-check one, or to close a unit that rests on these cases, run every case on current main and its rule-removed copy, and record each main run with `receipt.py` at that commit. The rule-removed run goes in the scratch repo's ledger, as below. A re-check whose runs passed but left no receipt proves nothing about the new commit, so the box keeps pointing at the old one.

## The rule-removed copy

To see the case fail, build a copy with the rule removed in a scratch folder, never in this repo:

```sh
git archive HEAD | tar -x -C <scratch>
cd <scratch> && patch -p1 < cases/receipt-before-tick/rule-removed.patch
git init -q && git add -A && git commit -qm 'rule removed'
```

Then run the same command there. Its receipt goes into a ledger in that scratch repo, because its commit exists nowhere else.

### When the patch no longer applies

A rule-removed patch is a diff against skill text, so an edit to the lines it removes stops it applying, and `tests/test_cases.py` fails. Rebuild it from today's text:

1. In a scratch copy (`git archive HEAD | tar -x -C <scratch>`), remove the same rule from the current text of each file the old patch touched. Read the old patch to see what the rule was, and remove any new sentence that restates it.
2. Write the patch from the repo root, one file at a time: `diff -u --label kit/FILE --label kit-norule/FILE FILE <scratch>/FILE >> cases/<case>/rule-removed.patch`, after emptying the old one.
3. Check that it applies (`git apply --check -p1 cases/<case>/rule-removed.patch`) and that applying it to a fresh archive gives the same files as your scratch copy.
4. Commit the scratch copy and run the case there once. It must fail. A patch that applies but leaves the case passing has removed the wrong text, so nothing yet shows the case catches its rule.
