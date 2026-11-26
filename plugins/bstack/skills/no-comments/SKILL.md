---
name: no-comments
description: Delete the comments a change adds and fix the code that leaned on them. A subagent removes every comment outside a short keep-list and flags the symbols a comment was covering for; you fix those at the root and offer to turn "do not remove" notes into a type, a test or a check. Also ships a check that fails when a diff adds a comment to a Python file. Use for /no-comments, "strip the comments", "remove the comments from this diff", "check this diff for comments", or before review of agent-written code.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack no-comments @ 2f87c85 (MIT, Lauren Tan)"
---

# No comments

A comment in agent-written code is narration, or cover for code that should have been shaped differently. An agent that reads it later trusts it over the code. Delete the comments in the scope, fix the code they excused, and turn the constraints they stated into something a machine enforces.

The keep-list is in [references/brief.md](references/brief.md). It is the only list: don't restate it or add to it.

## Scope

The files or diff the caller names. Otherwise the current branch's diff from its merge base with the base branch (`main` unless told otherwise), through the working tree.

## Steps

1. **Start the hunter.** One fresh subagent on the `code` role, with the scope. Use the `comment-sicko` agent when your tool has an agent of that name. Otherwise give a subagent [references/brief.md](references/brief.md) as its brief. It read the code cold: step 2 checks its facts, and never overrules a deletion on taste.
2. **Audit its report and its diff.** Read both yourself. Proof, here and in the brief, is code you traced or a document the comment links. It may sit outside the scope.
   - **Reject the report** when it edited application code, edited outside the scope, or gave a `MUST KILL` reason the code contradicts. A rejected report gets one more run: revert the hunter's edits and start a fresh hunter with the failure named. If you reject the second report too, stop, say the skill failed and report the scope as open.
   - **A reason that claims more than the code shows** is not a rejection. Accept the flag and correct the reason.
   - **A comment it deleted** comes back only when you can name its keep-list entry and show the proof. Restore it yourself, with the link, and drop any flag raised on its code. That is not a rejection. A deletion that is merely arguable stays deleted, and so does a comment that explained a surprise in our own code: its flag stays open.
   - **A comment it kept** stays only with proof of its keep-list entry. Add the link when the hunter did not. A keep you refute, or still doubt, is deleted.
   - **A keep or a deletion that rests on `IMPORTANT` or `do not remove`**: trace the symbol through its callers before you accept it, and run the **why** skill when the trace does not settle it.
   - **Suppressions the hunter missed.** Look for lint and type suppressions in the scope. One that silences a correctness or safety rule is a `MUST KILL`.
3. **Fix the trivial flags yourself**: delete a dead path, drop a parameter, call the real API. If any accepted flag needs a new shape, run the **architect** skill once for the whole accepted set and the code around it, and stop at its sketch.
4. **Implement the smallest root-cause fix inside the scope** (`fix-root-causes`, `redesign-from-first-principles`). Remove every workaround a flag named. Those principles guide the fix. They do not widen the scope: when the root cause lies outside it, land the smallest fix inside and report the rest as open. Never add a guard that hides the symptom.
5. **Encode the constraints.** A constraint comment says `do not remove`, `do not change the wording` or `talk to X before changing`. The hunter deleted each one the keep-list does not protect, and they stay deleted. For each deleted one whose claim the code bears out, or that you could not settle, offer the cheapest thing inside the scope that enforces it: a type, a runtime check, a test or a lint rule. With a user present, wait for the answer. In an unattended run, put the offer in the reply and encode only what the caller approved beforehand. Without approval, report the constraint as unenforced and sketch the work that would enforce it. A claim the trace refuted needs no offer: say what refuted it.
6. **Run the check** on a scope that holds Python, as the next section describes. It must exit 0. When it lists a comment you kept, add the link that proves the keep. A keep with nothing to link is not proven: delete it.

<!-- BEGIN GENERATED: snippet:roles (tools/kitgen.py; edit plugins/bstack/snippets/roles.md) -->
**Model roles.** Before you start a subagent, look up its role in `.agents/roles.yaml` in the project, then `~/.agents/roles.yaml` (agentfiles writes both). Use the entry for the tool you are running in: `claude-code`, `cursor`, `codex`, `pi` or `opencode`. A list means one subagent per entry.

- If the file, the role, or your tool's entry is missing, or the value is `inherit`, don't pass a model. The subagent runs on the current model.
- If your tool rejects a model name, rerun that subagent on the current model and say so in the reply.
- An entry that starts with `cli:` (for example `cli:cursor-agent:gpt-5.6-sol-high`) names another agent's CLI, not a model for your tool. Don't start a subagent for it. Write its brief to a file in your scratch folder and run `python3 ../beau-mode/scripts/second_opinion.py --reviewer ENTRY --prompt-file FILE --json` from this skill's folder (the script lives in the beau-mode skill, next to this one), adding `--cwd` with the worktree when it must read code. It only reads, so never give it a step that edits files or runs a repro. Exit 2 means the entry itself is wrong (an unknown agent or a malformed spec): name the entry in the reply. Any `status` other than `ok` means that reviewer gave no answer: name the status in the reply. In both cases, if the step needs that seat filled, run it on the current model and say the review was not independent.
- When a step asks for a *different* model and none is configured, pick a different one your tool offers if you can choose models. Otherwise use the current model and say in the reply that the review was not independent.
- If your tool can't start subagents, do the subagent's work yourself, one step at a time, and say in the reply that the review was not independent.

Roles: `code` writes code to a precise brief, `judgment` handles design, prose, synthesis and the hardest changes, `explorer` reads in bulk and returns findings, `reviewers` is the review panel (model diversity is the point).
<!-- END GENERATED: snippet:roles -->

**Reply:** comments deleted, comments restored and why, reruns of the hunter, the architect sketch if one ran, each fix, each encoding offered and each one made, constraints left unenforced, and other open work.

## The check

```bash
python3 <this skill's folder>/scripts/comments.py --base origin/main
```

Run it from the repo root, with the scope's base branch as `--base`. It prints each comment the diff adds to a Python file as `path:line: text` and exits 1 when there is one, 0 when there is none, and 2 when it could not run. `--head REF` reads that commit and not the working tree, and `--json` prints a list.

- **What counts as added.** A comment whose text the changed files hold more copies of than they did at the merge base. Moving a comment adds nothing. Editing its words does.
- **What it never lists.** A shebang, an encoding line, a directive a tool reads (`noqa`, `type:`, `pragma:`, `fmt:` and the like), a license header, and a comment with an `http(s)` link, along with the rest of an unbroken block of whole-line comments that holds one. These are the keeps a script can decide. A suppression passes the check and still gets step 2's audit.
- **A keep it cannot decide** (a constraint from a dependency, a platform or a protocol) passes when the comment links the issue, RFC or documentation that states the constraint.
- **Other languages.** The script reads Python only. Elsewhere, write the rule in the project's own linter, with the same keep-list.

To hold a repo to it, add an item to the repo's reliability checklist (`.agents/checklist.json`, read by **verify-work**) whose trigger is the repo's Python files and whose check is this command.
