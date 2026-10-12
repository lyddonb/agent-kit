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
7. **Give a verdict**:
   - **VERIFIED**: the predicate held on the real surface. Show the evidence.
   - **NOT VERIFIED**: it failed. Show what you saw.
   - **INCONCLUSIVE**: you couldn't observe the real thing (wrong surface, missing access, flaky environment). Say exactly what is missing. Inconclusive is never reported as a pass.

## Output

The predicate, the surface, the command or steps you ran, the evidence (output, screenshot path, numbers with units), and the verdict. If you measured performance, vet the number with the benchmark checklist in the **principles** skill first, and collect enough samples to trust it (the **swarm** skill can run interleaved baseline and change lanes in parallel).
