---
name: local-ci
description: Run a repo's CI on this machine instead of GitHub-hosted runners and report the result on the PR as the `local-ci` commit status, and run a local fallback for a job GitHub didn't start. Use to move a private repo's CI off Actions minutes, to set up or check the launchd agent that runs it, when a PR's `local-ci` status is missing, pending or red, when an Actions job failed without starting (spending limit, outage), or for "run CI locally", "post local-ci", "why is local-ci red".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Local CI

`scripts/local_ci.py` runs a repo's `scripts/ci` at a commit in a throwaway worktree and posts the result to GitHub as the commit status `local-ci`, which the PR's checks list shows. A red run on a PR also writes one PR comment with the end of the log, edited in place on later runs. A launchd agent ticks every five minutes and runs every open PR head and the default branch head that has no finished `local-ci` status yet.

## Move a repo to local CI

1. Write `scripts/ci` in the repo: an executable `#!/usr/bin/env bash` with `set -euo pipefail` that runs every step the hosted workflow ran, in order, from a clean checkout (install with the lockfile, then lint, types, tests). It must pass on a fresh worktree, so it can't rely on anything outside the repo except tools on PATH. A step that compares against the base reads `$LOCAL_CI_BASE` (for example `origin/main`), which local_ci.py fetches first.
2. Run `./scripts/ci` once from a clean worktree and fix whatever fails. Then run `python3 <this skill's folder>/scripts/local_ci.py run --repo OWNER/NAME=CHECKOUT --branch main` and confirm a `success` status lands: `gh api repos/OWNER/NAME/commits/main/statuses -q '.[0]'`.
3. Change the hosted workflow's trigger to `workflow_dispatch:` only, so it stays as a manual fallback and stops spending minutes. Leave jobs that must not trust the branch they check (a `pull_request_target` check) and deploys on Actions, and say so in the PR.
4. Add the repo to the agent: rerun `install` with every watched repo (it replaces the agent).

## The agent

```bash
python3 <this skill's folder>/scripts/local_ci.py install --repo OWNER/NAME=CHECKOUT [--repo ...]
python3 <this skill's folder>/scripts/local_ci.py status       # loaded or not, and the last 10 results
python3 <this skill's folder>/scripts/local_ci.py uninstall
```

Install from a checkout that stays put (the plist records the script's path and the current PATH). Logs: `~/Library/Logs/local-ci.log`, and one log per run under `~/Library/Caches/local-ci/logs/`.

## On a PR in a local-CI repo

- After pushing, run it now rather than waiting for the tick: `local_ci.py run --repo OWNER/NAME=CHECKOUT --pr N`. It waits for any run in progress on this machine and exits 0 only when the head's verdict is `success`, whether it ran it or found it.
- A PR is green only when its head sha has a `success` `local-ci` status. No status means the machine was off or asleep: run it yourself. Never read a missing status as passing.
- It tests the PR head, not the merge with the base. Rebase a PR that sits behind a base change before trusting a green.
- `error` means the run never started (no `scripts/ci` at that commit, a failed checkout). It stays until a new commit or `--force`.
- Red: read the PR comment or the run's log, reproduce with `./scripts/ci`, and fix the cause. `--force` reruns a sha that already has a verdict; use it only after fixing something outside the repo (a tool, the machine), never to fish for green.

## When GitHub doesn't start a job that stays on Actions

Checks that must not trust the branch they check (a `pull_request_target` job) and deploys stay on Actions. When GitHub never starts one (a spending limit, a failed payment, an outage: the job finishes with no steps and no runner), run its local fallback instead of waiting:

```bash
python3 <this skill's folder>/scripts/local_ci.py fallback --repo OWNER/NAME=CHECKOUT --pr N        # every job GitHub refused on the PR head
python3 <this skill's folder>/scripts/local_ci.py fallback --repo OWNER/NAME=CHECKOUT --branch main --job deploy --dry-run
```

- It runs `scripts/fallback/<job name>` for each refused job and posts the status `<job name> (local fallback)`. A job that ran on GitHub, passed or failed, is never replaced: fix a real failure, don't route around it.
- The script comes from the base branch (or the branch itself with `--branch`), never from the PR. The change to check is a separate checkout in `$LOCAL_CI_TARGET`: GitHub's merge commit for a PR, so the base is its first parent as in the Action. `$LOCAL_CI_EVENT` is `pull_request` or `push`.
- A script with the line `# local-ci: explicit` runs only when named with `--job`. Mark every deploy that way. A deploy is a gated action: run it with `--dry-run` first and ask before the real one.
- `--checker-ref REF` takes the script from REF instead. Use it only to try a fallback script before it reaches the base branch, and say so where the result is reported.

## Trust

Any branch pushed to a watched repo runs on this machine as your user. Watch only private repos where everyone who can push is you or your own agents. A PR from a fork never runs. The status is posted with your `gh` login, so it proves what this machine ran, not what a protected runner ran.
