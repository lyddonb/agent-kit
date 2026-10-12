# Your first bstack session

In this tutorial we fix one real bug with `beau-mode`, from handing it off to capturing what the session taught. By the end you will have a merged-ready fix with proof that it works, a skeptical review of it, and a first edit to bstack that came from your own session.

Plan on about an hour. Most of that is the agent working.

## Before you start

You need:

- bstack and principles installed in the tool you'll use. With agentfiles, `agentfiles sync builder` (or `beau`) does it. Without it, follow [INSTALL.md](INSTALL.md) for both plugins.
- A repo you work in, with a small bug you understand. Pick one you could fix yourself in under an hour, so you can judge the agent's work. Something with a visible symptom is best: wrong output, a bad value on screen, a failing request.
- `git` and `gh` signed in, so the agent can read history and open a PR.

How you call a skill depends on the tool. In Claude Code, plugin skills carry the plugin name, so `beau-mode` is `/bstack:beau-mode`. In Cursor, Codex, pi and OpenCode, type `/beau-mode` or name the skill in plain words ("use beau-mode"). This tutorial writes `/beau-mode`; use whichever form your tool takes.

## 1. Check that beau-mode is on

Start a session in your repo and ask:

```text
which instructions about beau-mode did you load, and where from?
```

You should see the agent name the agentfiles block (in Claude Code, `~/.claude/rules/agentfiles.md`) and say it will use `beau-mode` for non-trivial work. If it has never heard of beau-mode, the always-on block is missing. Run `agentfiles status` and fix that first. In Cursor, check that you pasted the user rule from `agentfiles sync`'s output.

Now ask where its model roles come from:

```text
which model would you use for a "reviewers" subagent here?
```

It should read `~/.agents/roles.yaml` and give the entry for your tool. If it says the file is missing, subagents will run on the current model, which works but makes reviews less independent.

## 2. Hand off the bug

Describe the outcome and how you'll know it's done. Don't name a playbook or list steps.

```text
/beau-mode the invoice total on the review page is off by the tax amount when a
discount is applied. repro first, then fix it and prove it on the real page.
```

Swap in your own bug. The two parts that matter are a symptom you can observe and "repro first".

## 3. Watch the first minute

Before touching code, the agent should do three things you can see:

1. **Restate the task** in a sentence or two. Read it. If it misread the bug, correct it now. This is the cheapest moment to catch a wrong reading.
2. **Pick the Bug fix playbook** and copy its steps into the todo list word for word. You'll see items like "Restate the problem", "Reproduce it yourself", "Binary-search the cause" and "Run Opening a PR".
3. **Read the principles it will apply**, such as `fix-root-causes` and `prove-it-works`.

If it jumps straight to editing files, say so: "follow beau-mode: playbook first." That correction is also good material for step 7.

## 4. Steer with a principle name

Partway through, the agent will propose a cause or a fix. Push on it with a principle name instead of a paragraph:

```text
apply fix-root-causes. why does the discount path compute tax at all?
```

```text
apply prove-it-works. show me the total on the actual page, not the unit test.
```

Each name points at a full rule the agent has read. You should see it change course and say which decision the principle changed.

## 5. Read the reply

When it finishes, the reply should contain:

- Its restatement of the problem.
- What was broken and the root cause, with file and line.
- The fix, and the PR it opened (or the branch, if it can't open one).
- The repro output failing before the fix and passing after, or a screenshot path.
- A verdict from **verify-work**: VERIFIED, NOT VERIFIED or INCONCLUSIVE.
- The principles it applied, each with the decision it changed.

Check two things yourself. First, open the evidence (the screenshot, the command output) and confirm it shows the real symptom gone. Second, look for any claim with no evidence or label next to it. "Should work now" is not a verdict.

If the verdict is INCONCLUSIVE because the agent couldn't drive your app, note it. That's what step 8 fixes.

## 6. Get a skeptical review

Before you merge, have other models try to break the change:

```text
/interrogate review this branch skeptically. no nitpicks unless it's a real bug.
```

You get a verdict, not edits: the intent it reviewed against, one line per reviewer with its model, then findings sorted into **Act on**, **Consider**, **Noted** and **Dismissed**. Fix the Act on items, or ask the agent to. If every reviewer ran on the same model, the reply says so; set two models under `reviewers` in your profile to fix that.

## 7. Capture what the session taught

Now turn the session into a better bstack:

```text
/reflect what slowed us down, and what should the next run do differently?
```

Three reviewers read the transcript, a synthesizer sorts their findings, and you get three lists: **Accepted**, **Rejected** and **Backlog**. Nothing changes until you approve. Pick the items that match how you work. Approved edits to bstack land as a branch in your agent-kit checkout, for a PR like any other change.

If the session had no lessons, that's a fine result. Don't approve edits written from one odd moment.

## 8. Where to go next

You've run the core loop: hand off, steer, verify, review, reflect. Three things make the next sessions better.

- **Give the app a verification skill.** In the same repo, run `/create-verification-skill`. It builds a `control-<app>` CLI and a `verify-<app>` skill with a feature map, and proves it end to end. After that, every playbook verifies through it, and INCONCLUSIVE verdicts get rare. Then schedule `/maintain-verification-skill` daily.
- **Try a different kind of task.** An investigation (`/beau-mode how does the export retry work? are we sure it's idempotent?`) or a design (`/architect ...`). The [bstack guide](BSTACK.md) has examples for each.
- **Leave one running.** Once you trust the verification, hand off a task with a goal, a finish condition and permission to commit, and catch up later with `/show-me-your-work catch me up`. The guide's "Run work while you're away" section shows a good handoff.

For what each skill does, needs and returns, see the [skill reference](BSTACK-SKILLS.md).
