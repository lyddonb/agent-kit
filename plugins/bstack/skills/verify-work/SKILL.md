---
name: verify-work
description: Prove a change works by checking the real artifact (run the feature, read the actual value, drive the real surface) and return VERIFIED, NOT VERIFIED or INCONCLUSIVE with evidence. Use before saying any task is done, when asked "does it work", "prove it", "verify", or when a claim rests on "it compiles" or "tests pass".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Verify work

Check the real thing, not a proxy. A green build, a passing unit test or a subagent's summary is not proof that the behavior works.

## Steps

1. **Write the claim as a predicate** you could hand to someone else: "importing the 60k-row file writes 60,000 rows and no duplicates", not "import works".
2. **Use the project's verification skill if it has one.** Look for `verify-<app>` in `.agents/skills/` or `.claude/skills/`. Follow its launch, doctor, drive and cleanup steps, and use its feature map: drive every entry point the map lists for the feature you changed, not just the convenient one. If the map is wrong, fix it in its own change or note it for **maintain-verification-skill**.
3. **Otherwise pick the surface the user touches** and drive it yourself: the browser (automation or screenshots), the CLI, the API with real requests, the app or simulator, the database. If the project has no verification skill and agents will verify this app again, say so in the reply and offer **create-verification-skill**: a one-time setup that makes every later check cheaper.
4. **Capture a baseline first** when the claim is a change ("faster", "no longer duplicates", "looks the same"): the same check on the code before the change.
5. **Run the check and read the actual output**: the rows in the database, the HTTP response body, the rendered screen, the file on disk. When it passes suspiciously easily, suspect the observation before the system (`prove-it-works`).
6. **Script it when you can.** A small script that reruns the check is better evidence than a one-time look, because a reviewer can rerun it. Keep it with the change or link it.
7. **Run the repo's reliability checklist** when it has one (`.agents/checklist.json`), with the branch's base as `--base`:

   ```bash
   python3 <this skill's folder>/scripts/checklist.py --base origin/main
   ```

   It prints the past mistakes this diff could repeat, each with the line that fired it and a check. No output means nothing matched. Run each item's command, or answer its question by running its probe, and put the result in the evidence beside the item's id. An item whose check fails makes the verdict NOT VERIFIED. An item you could not check makes it INCONCLUSIVE, however well the predicate held. In a run with a ledger, run each item through the script, so its verdict comes from the exit code and not from you:

   ```bash
   python3 <this skill's folder>/scripts/receipt.py --run <run-id> --actor '<you>' --item <item id>
   ```

   An item whose check is a command runs that command as the committed checklist states it. For an item whose check is a question, put the command that answers its probe after `--`, and pass `--not-run '<what>'` for any part you did not run. Commit your work first, as in step 9: a dirty tree is recorded as INCONCLUSIVE. Record by hand, with `ledger append`, only an item no command can answer. `references/checklist.md` has the file format and how to write an item.

   When the diff touches Python tests, run `python3 <this skill's folder>/scripts/test_guard.py --base origin/main` too, whether or not the repo has a checklist. It prints every test the diff deletes and every skip, retry, wider timeout or tolerance, dropped assertion or weaker assertion it adds, and exits 0. Each line needs a reason in the evidence, such as a rename, a move or a split. An unexplained one makes the verdict NOT VERIFIED. Its docstring lists what it cannot see.
8. **Give a verdict**:
   - **VERIFIED**: the predicate held on the real surface. Show the evidence.
   - **NOT VERIFIED**: it failed. Show what you saw.
   - **INCONCLUSIVE**: you couldn't observe the real thing (wrong surface, missing access, flaky environment). Say exactly what is missing. Inconclusive is never reported as a pass.
9. **Write a receipt when the claim is a spec criterion.** If the predicate is a criterion or anti-criterion in a phase spec (`C8` in `docs/phases/P2e-...md`), run its probe through the script, so the verdict comes from the exit code and not from you:

   ```bash
   python3 <this skill's folder>/scripts/receipt.py --run <run-id> --actor '<you>' \
     --spec docs/phases/<spec>.md --criterion C8 -- <the probe command>
   ```

   It records which probe ran, on which commit, and what came back, as a ledger entry (**show-me-your-work** says how to start a run and write `--actor`; a PR with no run yet starts one for itself). Commit your work, and the criterion itself, before you run it, and make that commit with `--trailer 'Verified: receipt <run-id>'`: a probe run on uncommitted changes or beside an untracked file is recorded as INCONCLUSIVE. Ticking the box and updating `ROADMAP.md` can come before or after. Pass `--not-run '<what>'` when the spec's probe has a part you did not run, which also records INCONCLUSIVE. When the probe has an exit code that means the run said nothing, such as harness-lab's 2 for UNJUDGEABLE (the plugin didn't load, the budget ran out), pass `--inconclusive-exit 2`: that code records INCONCLUSIVE instead of NOT VERIFIED, with the exit code kept. Give it only for a probe that documents such a code, since many probes exit 2 for an ordinary failure. Never write a receipt by hand for a probe a command can run. When a person is the probe (their words after a trial period), record their exact words with `ledger append`, with them as the actor.
10. **Stamp the commit** that holds the change with a `Verified:` git trailer. VERIFIED earns `Verified: verify-work`. NOT VERIFIED and INCONCLUSIVE are `Verified: none <reason>`. A commit a receipt names keeps the `receipt` stamp from step 9 and is never amended. The Opening a PR playbook in **beau-mode** has the values and the command.

## Output

The predicate, the surface, the command or steps you ran, the evidence (output, screenshot path, numbers with units), and the verdict. If you measured performance, vet the number with the benchmark checklist in the **principles** skill first, and collect enough samples to trust it (the **swarm** skill can run interleaved baseline and change lanes in parallel).
