---
name: parallel-next
description: Find the next planned work that can run alongside what other sessions are already doing, without touching their files or branches, and start the ones you pick, each in its own session under beau-mode. It reads what waits on you, every worktree, dirty checkout, open pull request and live agent session, ranks the roadmap items whose trigger is met, checks each against that work in flight, and recommends the ones that are clear. You pick zero or more. Use for /parallel-next, "what can run in parallel", "start more sessions", "what else can agents work on", "fan out the next work", or when you want more sessions going without collisions.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Parallel next

Load beau-mode first if it isn't loaded. This skill ends in a short list of items that won't collide with work in flight, and one session per item the user picks. It never starts an item the user didn't pick, and zero picks is a fine answer.

`PATHS` below means the repos to read, or the folder that holds them, the same every time.

## 1. See what is in flight

1. Run `git fetch` in each repo, so roadmaps and branches are read as the remote has them.
2. Run waiting-on-me's `scripts/waiting.py` (in the `waiting-on-me` folder beside this skill's) over `PATHS`, with any flags the project's instructions give it. Report blockers, open gates and pull requests waiting on the user first, as waiting-on-me says.
3. If your tool can list its agent sessions, write them to a scratch file. Claude Code desktop's `list_sessions` output goes in as it is: don't rename its keys, and ask for enough rows (it returns 20 unless you pass a higher `limit`), since a session cut from the list reads as free. From any other tool, write a JSON list of `{"title", "cwd", "running", "last_active", "pr_state"}` with exactly those keys in every row: `running` is true or false, `last_active` is ISO 8601, and `pr_state` is the pull request's state, or null when there is none. With no session list, leave out `--sessions` and say in the reply that sessions without a worktree or pull request were not seen.
4. Run the in-flight check from this skill's folder:

   ```bash
   python3 scripts/inflight.py PATHS --sessions SESSIONS.json
   ```

   It lists every claim (worktree, dirty checkout, open pull request, live session), the hot files per repo, and stale worktree folders. It only reads. Exit 1 means part of it went unread: say which part, and never treat an unread repo as free. When it refuses the session list, it prints no report, only the rows it could not read and the keys it needs: fix the file and run it again, never drop `--sessions` to get past it.

## 2. Pick candidates

1. Set the limit. Read `budgets.tier2.max_parallel_agents` from the project's `.agents/policy.yaml` and from `~/.agents/policy.yaml`, and take the lower (4 if neither sets it). Subtract the sessions whose `running` (`isRunning` in `list_sessions` output) is true. If the project's instructions cap how many items to propose, the limit is the lower of the two.
2. Rank the planned work by the project's own rules for choosing what comes next (its `AGENTS.md` or `CLAUDE.md`). With none, take roadmap items whose trigger is met, by priority, then in roadmap order. Blockers, open gates and work already started never take a proposal slot: they were reported in step 1. Skip an item whose trigger isn't met, whose dependency isn't done, or that a human task holds. Read only as far as it takes to settle that, and say which one held it.
3. Take about twice the limit. For each, read the item and the code it names, and list the files or globs you would edit by hand. Leave out files a generator writes; the repo's hot files cover most of them. These are guesses: label them inferred everywhere you show them.
4. Write the candidates to a scratch file, best first, as a JSON list of `{"id", "repo", "paths"}`. `repo` is the repo's folder name. Use the item's id as the roadmap writes it; for an item with none, use its heading as written (`phase 1b`). An item whose work lands in more than one repo gets one entry per repo, all with the same id, and its state is the worst of its entries. Then run:

   ```bash
   python3 scripts/inflight.py PATHS --sessions SESSIONS.json --candidates CANDIDATES.json
   ```

5. Act on each state:

   | State | Do |
   |---|---|
   | `taken` | Drop it, and name the claim that has it. A claim from a session in a folder of repos (`*`) takes the id in every repo: if its title shows it means another repo's item, keep the candidate and say why |
   | `conflict` | Drop it. Name the claim or the better candidate it overlaps, and the files |
   | `unknown` | A worktree with no changes yet may belong to a session that is about to write. Find the session working in that folder in the session list. If it is running and its title could touch the candidate's files, drop the candidate. Otherwise keep it, and show the worktree and its idle hours in the proposal |
   | `rebase` | Keep it. Its pull request will need a rebase and a regenerate after the other one merges |
   | `clear` | Keep it |

## 3. Propose, then let the user pick

Propose up to the limit. For each item give:

- its id, the roadmap file, and a link to the item's line
- why now: the trigger that is met, or what it unblocks
- impact: who notices, and what changes for them
- the inferred paths and the check's state, with any `unknown` or `rebase` reason
- whether a test or a metric can prove it, or it needs the user's judgment. Put the judgment items first, since each one takes the user's attention

Then ask which to start. Use a multi-select question if your tool has one. Any subset is a valid answer, the empty one included. Start nothing until the user answers.

## 4. Start one session per pick

Write each brief from [references/brief.md](references/brief.md). Then start it:

- **A tool that starts sessions** (Claude Code desktop's `start_session`, for example): one fresh session per pick, in the item's repo, in its own worktree, with the item's id in the worktree or branch name. The user picked these, so they count as the user asking.
- **Claude Code CLI:** save each brief to a file, then print one command per pick for the user to run in its own terminal: ``cd REPO && claude -w ID-SLUG "$(cat BRIEF.md)"``. `-w` makes the worktree and a `worktree-ID-SLUG` branch, so the id is visible at once.
- **Any other tool:** print each brief and tell the user to start it in a new session from the item's repo.

Every brief starts with `/beau-mode`, so each session runs the full workflow.

## 5. Check the launch

Run the step 1 check again. Every session you started must show up as a claim carrying its item's id. Name any that don't. In the reply, list each started session with its item, its worktree, and its link.

When a started session asks whether it may edit a file another claim also touches, read that claim's diff for the file (`git -C OTHER_WORKTREE diff DEFAULT_BRANCH -- FILE`) before you answer. If both pull requests bump the same version, say that the second to merge will need a re-bump.
