# The reliability checklist

A repo's checklist holds the mistakes that have already happened there and that a diff can show coming. Each item pairs a trigger, read from the diff, with a check to run. `scripts/checklist.py` prints the items whose trigger matches the change in front of you, so a docs change gets no list and a books layout change gets the one question that matters.

## Running it

```bash
python3 <this skill's folder>/scripts/checklist.py --base origin/main
```

Run it from the repo root, or pass `--root DIR`. It compares the merge base of `--base` and the head with the head. Without `--head` the head is the working tree: commits since the merge base, uncommitted edits, and untracked files git does not ignore. With `--head REF` it is that commit only, which is how you replay the checklist over a past commit:

```bash
python3 <this skill's folder>/scripts/checklist.py --base 990c84f^ --head 990c84f
```

Each matching item prints as a block:

```text
books-layout
  fired on: plugins/bstack/skills/qualitydirector/scripts/quality.py:84: -WEEKLY_SCHEMA = ("week", ...
  question: Do books written by the last release still pass `check`?
  probe: Copy the last release's fixture books out of git ...
  source: Pull request 39 (commit 990c84f): ...
  added 2026-11-21, review by 2027-02-21
```

`fired on` names the first file that matched and, for a pattern, the line: `+` for a line the diff adds (numbered in the new file) and `-` for one it removes (numbered in the old file). An item with a command check prints `command:` in place of `question:` and `probe:`. `--json` prints the same items as a JSON list.

Standard output holds the matching items and nothing else. Empty output means the script ran and nothing matched. A count such as `checklist: 2 of 5 items match aa2b6f9..working tree (9 changed files)` goes to standard error.

| Exit | Means |
|---|---|
| 0 | It ran. The items are checks for you to run, and the script blocks nothing. A repo with no `.agents/checklist.json` also exits 0, and says so on standard error. |
| 2 | It could not run: a folder that is not the top of a git work tree, a ref git does not know, a checklist file that is not JSON or breaks the format, or `--file` naming a file that is not there. A format message names the item and the key. |

## Recording an item in a ledger run

In a run that keeps a ledger, `scripts/receipt.py --run RUN_ID --actor ACTOR_JSON --item ID` runs the item's check and appends a `verification` entry whose verdict comes from the exit code: 0 is VERIFIED, anything else NOT VERIFIED, and a dirty tree or `--not-run TEXT` makes a pass INCONCLUSIVE. A command item runs its own command, read from the checklist as HEAD has it, so an uncommitted edit cannot change what ran. A question item needs the command that answers its probe after `--`. The entry's `data.checklist` holds the item's id, the file and its hash, the command, the commit and the exit code, and the output is kept in `.evidence/<run-id>/checklist-<id>.txt`. `ledger show` lists the entry. `ledger receipts` does not: it lists spec criteria.

## The file

`.agents/checklist.json` at the repo root, or the file `--file` names:

```json
{
  "version": 1,
  "items": [
    {
      "id": "books-layout",
      "trigger": {
        "paths": ["src/books/**"],
        "pattern": "^\\s*SCHEMA\\s*="
      },
      "check": {
        "question": "Do books written by the last release still pass `check`?",
        "probe": "Run this branch's `check` on a copy of the last release's fixture books."
      },
      "source": "Pull request 39 (commit 990c84f): a column was renamed and old books stopped passing.",
      "added": "2026-11-21",
      "review_by": "2027-02-21"
    }
  ]
}
```

| Key | Holds |
|---|---|
| `id` | Lowercase words joined by hyphens, unique in the file. |
| `trigger.paths` | Globs, at least one. `**` crosses folders, `*` and `?` stay inside one, and a leading `**/` also matches a file at the top. The item is a candidate when a changed file fits any glob. Use `["**"]` for every file. |
| `trigger.pattern` | Optional. A Python regular expression, searched in each line the diff adds or removes in the files that fit `paths`. With a pattern, the item fires only when a line matches. In JSON every backslash is written twice. |
| `check` | Either `{"command": "..."}`, a command to run from the repo root that fails when the mistake is present, or `{"question": "...", "probe": "..."}`, a question and how to find its answer on the real artifact. The probe may name a `verify-<app>` drive. |
| `source` | The pull request, commit or incident behind the item. If nothing has gone wrong yet, say so and say where the item came from. |
| `added`, `review_by` | Dates as `2026-11-21`. Past `review_by` the item prints `overdue`: confirm it still catches something, or delete it. |

Any other key is refused, so a misspelled key cannot silently turn an item off.

## Writing a trigger

- Match the line that carries the decision. `books-layout` matches the schema constant, not every edit to the books script.
- A removed line counts as much as an added one, because deleting a column is a layout change too.
- Anchor a command pattern to where a command starts (`^\s*gh\s`) or to its quoted name in an argument list. A bare word matches every sentence that mentions the tool.
- Keep generated files out of `paths`. A release note that describes the mistake would otherwise fire the item.
- Replay the item before you keep it. It must fire on the commit that made the mistake (`--base C^ --head C`) and stay quiet on a docs-only commit. Put the commit in `source`.

## What it does not do

It selects checks. It does not run them, and it does not fail a build.

## A change cannot switch off its own item

The script reads the checklist twice: from the working tree, and as the merge base has it. An item in the base's copy that matches the diff is still printed when the diff removes it, or edits it so that it no longer fires, with a line that says so:

```text
gh-call
  note: this diff removes this item; shown as it was at 1e3f753
  fired on: .github/workflows/release.yml:31: +gh auth status
```

Check it like any other item. If the item is wrong, removing it is fine: say why in the pull request. Deleting the whole file does not silence it either. A new item, and an edit that keeps the item firing, are read from the working tree. This covers the checklist's content, not the script: an agent runs the installed plugin's copy, and nothing in CI runs either.
