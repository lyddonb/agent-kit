# R42 pre-registration (written before the first judge call, 2026-11-26)

Variant under test: beau-mode step 4 ("Check for team knowledge") with the `kb` MCP server
installed as it is on Beau's machine.

Arms. Every arm gets beau-mode's SKILL.md at agent-kit 1a6aa9c in the appended system prompt,
the same kit on disk, Claude Sonnet via `claude -p`, `--setting-sources ""`, skills off,
sandboxed, $2 cap per run, the repo at the merged PR's first parent with 400 commits of history.
Only two things vary:
- full1, full2 (no KB, twice): `--strict-mcp-config`, no MCP server. For t1-t8 these are R43's
  full1 and full2 runs, made with the same command.
- kb: `--strict-mcp-config --mcp-config` holding only `kb`.
- trails: no MCP server; the system prompt ends with a list of hand-picked records of earlier
  pull requests on related work (change records, a ledger run, or for t5 two commits), each
  older than the task's base, none the task's own record.
- both: the kb server and the trails list.
The repo already contains its committed change records in every arm, as it naturally would.
The trails arm differs by naming specific ones (load by id), not by having them.

Isolation, checked before any run: each arm was asked for its mcp__ tools and named records;
no-KB and trails reported no mcp__ tools, kb and both reported the four mcp__kb__ tools, and only
trails and both named records.

Rubric (judge only): R43's five items, 1-5 each: cause, fix, proof, scope, reply. `cause` gains
one clause for the two build tasks (t9, t10): "understands what the existing code and conventions
require". Scores are not compared with R43's, which judged three answers per task.

Judge: `second_opinion.py --reviewer cli:cursor-agent:gpt-5.6-sol-high`, one call per task with
all five answers as Answer A-E in an order from random.Random(4242 + task number), plus the
merged PR's diff as one accepted fix. Status other than ok, or unparsable JSON, is a missing
verdict for that task. No rerun on the current model.

Blinding: before judging, every final reply in every arm has each line that mentions a
knowledge base, `kb`, `mcp__kb`, `search_knowledge`, or a saved article or note replaced by
"[line removed]". Diffs are not edited.

Comparisons, per item and on the per-answer mean of the five items ("overall"):
win share of X over Y = (wins + 0.5 * ties) / n over tasks where both have a verdict.
- no KB = full1 and full2 pooled (two comparisons per task).
- band = |share(full1 over full2) - 0.5|, per item and overall.
- KB beats no KB iff share_overall(kb over noKB) > 0.5 + band_overall.
- Both is not worse than trails iff share_overall(both over trails) >= 0.5 - band_overall.
- Keep step 4 as it is only if both hold. Otherwise change it to load entries by id or remove
  it: by id if trails beats no KB by more than the band, remove if not.

Also reported: kb tool calls per kb and both run, read from the transcripts. If most kb-arm runs
make no kb call, the finding is "step 4 does not trigger a lookup", stated as such.
Token count per arm: input + output + cache writes, summed from each run's result event.

Threats named in advance: the cursor-agent judge runs with Beau's rules loaded, which tell it to
search the kb before design work, and may have the kb server too. Ten tasks, so one task moves a
share by 10 points (5 against the pooled no-KB arm), and the band is one sample.

## Amendment, 2026-11-26, before any judge call (reason: call counts and a leak, not scores)

1. Discarded batches (wrong sandbox settings, then two runners writing one folder) had 19 runs
   with the kb server on and 0 kb tool calls. So a sixth arm is added:
   - kbr (KB, instructed): the kb server plus the two kb paragraphs of Beau's user rules,
     verbatim, appended after beau-mode. This is the condition live on Beau's machine today. The
     text is private and stays out of the repo; the PR describes it.
   If kbr also makes almost no kb calls, no instructed-both arm is run. If it calls, an
   instructed-both arm is considered before judging, and the arm set is fixed before any judge call.
2. A KB arm whose runs made no kb call is a replicate of no KB. Its gap from no KB is noise and
   is reported as such, not as an effect, whatever the band says.
3. The decision rule above is applied to the kb arm (step 4 alone) as written. The kbr arm is
   reported beside it with the same shares, as evidence on the KB's content.
4. t9 and t10 leaked: the kit at 1a6aa9c contains their merged solutions. For those two tasks
   every arm gets the kit and the beau-mode text from the task's base commit. t1-t8 keep the
   1a6aa9c kit, as R43 did; t3 and t4 can read an already-fixed debrief.py in the kit, which is
   equal across arms and is checked in the transcripts.
5. Judge prompt: six answers per task, Answer A-F.
6. Correction after judging t1-t8: the redaction's `kb` match was case-insensitive and removed
   one factual line ("946 KB transcript") from a t7 reply. It is now case-sensitive. No reply
   in any arm mentions a knowledge base, so redaction removes nothing. t7 was judged again on the
   corrected prompt; the first verdict is kept in judged/superseded/ and not scored.
