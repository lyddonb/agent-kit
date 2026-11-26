# Flag a wrong or missing skill

Write a flag when a skill's text, a reference or a pointer was wrong or missing: a command that doesn't exist, a step that no longer works, a path that moved. Then finish the task the way that worked. Never edit the skill in the same task: a weekly pass reads the flags and proposes the edits.

A flag is a `lesson` ledger entry with `data.kind: "flag"`, as agent-ledger's S3 spec defines it under "Flag entries". One flag per fault.

## Where it goes

- **In a governed run** (this task keeps a ledger run, as show-me-your-work or Large work item does): append to that run and commit it with the work. Skip the weekly-run steps below.
- **Otherwise:** the week's `flags-<machine>` run in the repo that `~/.agents/flags.yaml` names. The file has two lines:

  ```yaml
  root: '/absolute/path/to/the/repo/that/keeps/flags'
  machine: 'mac'
  ```

  `machine` fits `[a-z0-9]+(-[a-z0-9]+)*`. Flags can name private context, so `root` is a private repo.
- **No file, no `root`, or a step below fails or is denied:** write nothing anywhere else. List the flag's fields under "Flags not written" in your reply and carry on.

## Write it

`ACTOR` is your actor JSON from the show-me-your-work skill.

```bash
root=$(sed -n "s/^root: *'\(.*\)'$/\1/p" ~/.agents/flags.yaml)
machine=$(sed -n "s/^machine: *'\(.*\)'$/\1/p" ~/.agents/flags.yaml)
set -- $(python3 -c 'import datetime as d; t = d.datetime.now(d.timezone.utc).date(); print(t, t - d.timedelta(days=t.weekday()))')
today=$1 monday=$2
run=$(ls "$root/.audit/runs" 2>/dev/null | grep -E "^[0-9]{4}-[0-9]{2}-[0-9]{2}-flags-$machine\$" | awk -v m="$monday" '$0 >= m' | sort | tail -n 1)
if [ -z "$run" ]; then
  run="$today-flags-$machine"
  ledger init "flags-$machine" --root "$root" --date "$today" --actor "$ACTOR" --why "the first flag this week"
fi
ledger append --root "$root" --run "$run" --actor "$ACTOR" --type lesson \
  --summary "<what was wrong, one line>" \
  --why "<how you found it, one line>" \
  --evidence '<the command you ran>' \
  --evidence '<an output line that shows the fault>' \
  --data '{"kind": "flag", "target": "<plugin:skill, or path:line>", "did_instead": "<what you did so the task went on>", "suggested_fix": "<the edit you would make>"}'
```

- `evidence` holds the command and only the output lines that show the fault, one per `--evidence`. No other transcript text: no conversation, no task details, no file contents beyond those lines.
- If `ledger append` refuses the flag, fix the fields it names and append again.
- Don't commit in the flags repo: other sessions append to the same file, and the weekly pass commits the week's run.
