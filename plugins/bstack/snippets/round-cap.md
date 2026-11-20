**Round cap.** A round is one fix aimed at one failing check, then a run of that check. A check is the smallest thing that names the failure: a test, a CI job, a repro, a step of the predicate. Keep a count per check. The count is yours across every subagent you hand a fix to, so a fresh subagent doesn't start it again.

- A fix that clears one failure and uncovers a different one further on is progress. The new failure starts its own count.
- A failure that comes back keeps its count.

When a check still fails after its third round, stop work on that check:

1. Leave the check as it is. Don't skip, loosen, delete or special-case it, and don't run it again hoping for a pass.
2. Take out your fixes that didn't move it. A fix someone else committed stays: say it didn't move the check and let them decide.
3. Tell the human which check it is, the command and its last output, each fix you tried with what the check said after it, and why you think it is stuck.
4. In a run with a ledger, record the stop as a `gate` entry that names the check, and the human's reply as a `gate-answer` entry.

Independent work continues. "Don't stop" and "run until done" don't lift the cap: a fourth patch on the same check needs the human's answer.
