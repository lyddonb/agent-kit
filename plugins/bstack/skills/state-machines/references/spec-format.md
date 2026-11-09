# Machine spec format

One Markdown file per machine, reviewed before code changes. It is the design the human accepts or rejects, and the source the tests are generated from. `scripts/check-machine.py` parses it with no dependencies.

## Rules

- `# Machine: <name>` as the first heading.
- `states:`, `events:`, `initial:` and optional `final:` lines, comma-separated identifiers, lowercase keys, before the first `##` heading.
- One transition table whose header starts `| state | event | next |`, with an optional fourth `note` column. It can sit anywhere; other tables (a flag inventory, say) are skipped. Write a literal pipe in a cell as `\|`.
- `next` is one of:
  - a declared state (a self-loop is allowed: it means "handle it, stay here");
  - `(ignore)`: the event can arrive here and is dropped on purpose (a late response, a double click);
  - `(impossible)`: the event cannot arrive here. The note must name what prevents it (a type, a disabled control, a lock). If nothing enforces it, it is not impossible; decide it.
- Guards go in brackets after the target: `retrying [attempts < 3]`. When a cell has several rows, every row needs a guard and one must be `[else]`.
- `*` in the event column covers every event without its own row in that state. It may only say `(ignore)` or `(impossible)`, and needs a note. Use it for final states; anywhere else it hides decisions.
- `## Invariants`, `## Interruptions` and `## Assumptions` are required, each a bullet list.
  - **Invariants**: facts the machine must keep in every reachable state. They become property-test assertions. When the spec models today's code, mark each one the code breaks `(violated today: F1)` with the finding id.
  - **Interruptions**: every actor and interruption the design must survive (crash, reload, timeout, cancel, a second writer, a stale or duplicate message, the user changing the request mid-flight). Each bullet names the event that models it, in backticks, so the table is forced to decide it in every state.
  - **Assumptions**: every choice the human might make differently, including what is left out, each one acceptable or rejectable on its own.
- Optional `## Data`: one bullet per state that carries data, starting with the state in backticks (`` - `uploading`: uploadId, file, attempts ``). This is the payload of that variant in the union.
- Optional `## Effects` (what the shell does on each transition) and `## Where it lives` (file:line of today's implicit version) sections are carried along but not checked.
- Guards are prose. The checker only requires an `[else]`; it cannot tell whether guards overlap. Name each guard the way the code will (`same uploadId`), since table-driven tests need one predicate per guard.

## What the checker enforces

Undeclared or twice-declared names, undecided state x event cells, unreachable states, trap states (non-final with no exit), transitions out of final states, unguarded duplicate rows, guarded cells without `[else]`, `(impossible)` without a reason, interruptions that name no event, and `## Data` bullets that name no state. `--matrix` prints the grid (`??` marks an undecided cell), `--mermaid` a diagram of moves between states (self-loops are in the matrix), `--json` the table for table-driven tests.

## Example

```markdown
# Machine: upload

states: idle, uploading, failed, done
events: select, progress, succeed, fail, cancel, retry, restart
initial: idle
final: done

| state | event | next | note |
|---|---|---|---|
| idle | select | uploading | |
| idle | progress | (ignore) | late event from a cancelled upload |
| idle | succeed | (ignore) | late response from a cancelled upload |
| idle | fail | (ignore) | late response from a cancelled upload |
| idle | cancel | (impossible) | cancel button only renders while uploading |
| idle | retry | (impossible) | retry button only renders in failed |
| idle | restart | idle | |
| uploading | select | (impossible) | file picker disabled while uploading |
| uploading | progress | uploading [same uploadId] | |
| uploading | progress | (ignore) [else] | stale upload |
| uploading | succeed | done [same uploadId] | |
| uploading | succeed | (ignore) [else] | stale upload |
| uploading | fail | failed [same uploadId] | |
| uploading | fail | (ignore) [else] | stale upload |
| uploading | cancel | idle | aborts the request |
| uploading | retry | (impossible) | retry button only renders in failed |
| uploading | restart | failed | in-flight request is lost on reload |
| failed | select | uploading | |
| failed | progress | (ignore) | |
| failed | succeed | (ignore) | a response after timeout-fail is discarded |
| failed | fail | (ignore) | |
| failed | cancel | idle | |
| failed | retry | uploading [attempts < 3] | |
| failed | retry | failed [else] | shows "too many attempts" |
| failed | restart | failed | |
| done | * | (ignore) | terminal; the URL is final |

## Invariants
- `uploading` carries exactly one `uploadId`; no other state carries one.
- `done` carries a URL and nothing can replace it.

## Interruptions
- Page reload mid-upload: `restart`.
- Response for an upload the user already cancelled: `succeed`, `fail`, `progress` arriving in `idle`.
- Network timeout: surfaces as `fail`.

## Data
- `uploading`: uploadId, file, attempts
- `failed`: file, attempts, error
- `done`: url

## Assumptions
- A reload does not resume an upload; it lands in `failed` and the user retries.
- Three attempts, then the user must pick the file again.
- Progress events are not persisted.
```
