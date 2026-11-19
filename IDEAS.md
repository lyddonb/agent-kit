# Ideas

Possibilities that are not worth a roadmap slot yet. No commitment, no priority.
Promote one to [ROADMAP.md](ROADMAP.md) when there is a concrete need.

## Skills to consider writing
- **`one-on-one-prep`** — pull a direct report's recent PRs/tickets and prior notes into an agenda.
- **`incident-postmortem`** — blameless postmortem from a timeline and chat export.
- **`estimate-review`** — sanity-check a project estimate against scope, risks, and team capacity.
- **`eng-metrics-narrative`** — turn DORA or cycle-time numbers into a leadership update.
- **`pkm-capture`** — file meeting notes and decisions into an Obsidian vault with the right links.
- **`aec-domain-primer`** — preconstruction and cost-management vocabulary for agents working in
  construction-tech code (probably belongs in a private repo).

## Packaging ideas
- **Skill "tiers" via tags** — mark skills `core` vs `experimental` in `metadata` so consumers can
  filter. Wait until there are enough skills to need it.
- **Generate an `AGENTS.md` snippet** listing installed skills for tools that do not auto-discover them.
- **Gemini CLI extension manifest** (`gemini-extension.json`) from `kit.yaml`; obra/superpowers ships one.
- **Antigravity / Devin / Kimi plugin manifests** — superpowers ships manifests for many more clients;
  add only if you start using one of them.
- **Per-skill READMEs for humans**, generated from the frontmatter plus a "try it" prompt.

## Quality ideas
- **Description linter using an LLM** — score each description for "says what and when".
- **Token budget report** — use `claude plugin details` to track the always-on cost per plugin and fail CI
  if it jumps.
- **Cross-tool smoke test in containers** — run Codex/pi/OpenCode headless in CI against a fixture repo.
  Heavy; probably only worth it if this becomes widely used.

## bstack ideas
- **Dr Eggbot-style maintenance.** A small always-running agent per repo that tends the
  garden: notices repeated helpers, creeping lint suppressions, stale feature maps, and opens
  small cleanup PRs (pstack guide part 1). Needs R18's schedules first.
- **A `control-<app>` template.** A starter control CLI (subcommands, `--json`, `--dry-run`,
  rich `--help`) that `create-verification-skill` copies and fills, instead of writing one
  from scratch per repo.
- **Principle usage stats.** Count which principles agents cite in transcripts and which
  decisions they changed. Unused principles are candidates for deletion.
- **A "steer" cheat sheet.** One printable page of the 24 principle names with one-line
  triggers, for steering agents mid-task.
- **Per-project principle sets.** Let a project's `.agentfiles.yaml` exclude principles that
  don't apply there (for example `type-system-discipline` in a shell-script repo).
- **Write it up.** A public post on adapting pstack to work across agents, once it has been
  used for a while.
- **Mode for reviewing other people's PRs.** A playbook that reviews a teammate's PR the way
  you would, using `interrogate` plus your team's conventions from the KB.

## From "How to effectively debug with agents when you no longer read or understand the code" (2026-11-16)
Cindy Sridharan's framework is built as the `root-cause` skill. Tuning it and default data
collection are on the roadmap (R36, R37). Not committed to:
- **Develop in production.** Read-only production telemetry is fine today; anything more needs its
  own charter and the `deploy` gate.
- **Ledger the case.** Write each case event into agent-ledger too, so `ledger scan` checks it.
  Wait for an unattended debugging run that needs it.

## From "Steering AI Beyond Automation" (2026-11-15)

Ideas from Narayanan and Unger's [essay](https://www.normaltech.ai/p/steering-ai-beyond-automation) on collaboration over full automation.
Context and reasoning: [notes in agent-ledger](https://github.com/lyddonb/agent-ledger/blob/main/docs/notes/steering-beyond-automation.md). The ledger side (`steer`,
`disagreement` entries, `ledger stats`) lives in agent-ledger's IDEAS.md.

- **Mid-run steering in the Large work item playbook.** Today the human approves a charter,
  answers gates the agent raises, and merges. Add a step that checks for human `steer`
  entries between units and follows them, once agent-ledger has the entry type.
- **An `interactive` role for attended work.** For tier 1 work while the human is present, a
  fast model holds the conversation and hands deep work to `code` and `judgment` subagents in
  the background, so the human keeps flow instead of waiting on a slow agent. This is the real
  conflict D11 asks for before adding a role: latency against depth. Needs the role in
  agentfiles too.
- **Teach at seal.** An optional step at the end of a Large work item that runs `teach` over the
  ledger, so the human comes out of a run understanding the change, not only having approved it.
- **Say why the tiers trade autonomy for reliability.** The essay's trilemma (fully autonomous,
  reliable at high stakes, general-purpose: pick two) is the reason tier 3 has more gates and
  reviews. One sentence in the Large work item playbook would make that explicit.
- **Record disagreement.** When beau-mode stops because the evidence rules out the change the
  human asked for, record it as a `disagreement` entry so we can later see how often the agent
  was right to push back.
- **Ambient caution for Dr Eggbot.** The always-running maintenance agent above is what the
  essay calls an ambient agent. Give it its own charter covering what it may read and who it
  may message, beyond the `outbound-message` gate.

## From "intent over steps" (2026-11-16)

From a thread on running an agent system on intent, ideal states and evals instead of
step-by-step instructions. Context and the full mapping to this repo:
[notes in agent-ledger](https://github.com/lyddonb/agent-ledger/blob/main/docs/notes/intent-over-steps.md). The ideal-state spec landed in bstack 0.11.0; R21 to R26
in the roadmap carry the next parts.

- **A notifier for scheduled jobs.** One place that reads each scheduled job's result (CFO
  brief, quality brief, maintain-verification-skill) and decides: a message now, a line in a
  daily digest, or nothing. Worth it once three or more jobs run on a schedule.
- **"Should work" is not a status.** A check in `unslop` or `verify-work` that flags replies
  and PR bodies claiming something works without a VERIFIED result or a receipt.
- **Hillclimb on the books.** R17's Hillclimb playbook, fed from the quality books and the
  CFO books: pick one number below target, run experiments, keep only what the numbers support.
- **A pointer to life goals, not the goals themselves.** A private profile could point
  agents at the goals in the PKM vault, so a project's VISION.md can say which life goal it
  serves. Keep the content out of this public repo.
- **The surprising level as an eval target.** Collect the "Surprising" lines from shipped
  specs and see which ones actually happened, to learn whether level 3 steers anything.

## From "How the Claude Code team thinks about verification" (2026-11-16)

Addy Osmani's post on how the Claude Code team verifies agent-written code. What we committed
to is in the roadmap's Verification loops section (R27 to R35). Not committed to:

- **Checks written by code owners.** The owner of a path writes the check for it and tunes it
  until it flags what they would. Worth it with more than one owner. One person owns
  everything here today.
- **A daily reviewer eval.** The post's team replays past incidents against the reviewer every
  day. R34 replays when an escape is booked, which fits this volume.
- **`/goal` as the cheap-checks loop.** Lighter than R32's Stop hook, but a small model reading
  the transcript decides when the goal is met. The kit takes verdicts from exit codes.
- **Pre-existing means not the author's problem.** The post's reviewer doesn't hold an author
  to a bug that was already there. beau-mode's "green means every check" is stricter and stays;
  R33 only tags such findings so the fix gets its own PR.
- **Deleting a flaky test outright.** The post lets the agent delete a flake it can't
  root-cause and write down why. Here that is at most a proposal (R35).
- **Rounds to green in the books.** CI attempts per PR head and how often the first push is
  red. Needs the branch or PR number in `runs.csv`, a books layout change, so wait until R32
  needs the number.
- **Verify-skill health in the books.** Duration and pass rate of each `verify-<app>` run,
  read from receipts, once R27's skills have run for a few weeks.
