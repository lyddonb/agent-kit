# Finding implicit state machines

An implicit state machine is lifecycle logic ("in this state, when this event happens, go to that state") spread across flags, conditionals and handlers instead of written in one enumerable place. The danger is not the machine; it is that nobody can list which states and transitions are possible, so illegal ones ship. Tests and review pass because they check the paths someone thought of.

## Signals

A file usually holds several of these. One signal is a lead; two or more touching the same entity is a machine.

**State spread across values**
- Two or more booleans about one thing: `isLoading`, `isError`, `isOpen`, `isSubmitting`, `hasFetched`, `isDirty`, `done`. N booleans admit 2^N combinations; count how many are meaningful.
- A `status`/`state`/`phase`/`stage`/`mode`/`step` string or enum, compared with `==` in more than one file.
- Nullable fields whose presence encodes the phase: `error?`, `result?`, `startedAt?`, `completedAt?`, `cancelledAt?`, `lockedBy?`. `{ completed: boolean; completedAt?: Date }` is the classic.
- A counter or index doing a phase's job: `step`, `attempt`, `retryCount`, `page`.
- Database columns: `status`, `state`, `*_at` timestamps, `deleted`, `archived`, `locked`, soft-delete flags. Rows have lifecycles too.

**Transitions spread across code**
- The same flag set in several handlers, or set in one and cleared in another file.
- Guards repeated at call sites (`if (!isSubmitting && !isDone)`) instead of owned by the state.
- Effect chains: `useEffect`/watchers/observers/triggers that set state that fires another effect.
- Callbacks or promise handlers that write state with no check that the world is still the one that started them (stale responses).
- Retry, timeout, polling, debounce and backoff loops.
- Event handlers, webhook handlers, queue consumers and cron jobs that update the same record.
- `try/finally` blocks that reset flags (and the exits that skip them).
- Side effects inside state updaters (`setX(prev => { storage.write(...); return ... })`), or a variable or ref assigned inside an updater and read right after the setter call. The updater may run later, twice, or never (after unmount).
- Effects whose dependencies change identity every render (an inline function or object passed to a hook that feeds a `useCallback`/`useEffect` dependency list). Each run sets state, which re-renders, which reruns the effect.
- `mounted`/`cancelled` refs and flags: a hand-rolled lifecycle that every async path has to remember to check.

**Lifecycles worth checking even when they look simple**
- Auth/session, onboarding and multi-step forms, checkout and payments, modals/drawers/popovers, file upload, connections and sockets, background jobs, sync and offline queues, feature flags with rollout phases, agent loops and tool-call protocols, CLI commands with locks or temp files, anything with "pending".

## Conflict probes

For each machine, try to reach a bad state with a concrete event sequence. A finding is a sequence plus the exact lines that allow it.

1. **Contradictory combinations.** Which flag combinations can be true at once that mean nothing (`isLoading && isError`, `open && closing`, `paid && refunded && !captured`)? Find a sequence that sets them.
2. **Events in the wrong state.** Double submit. Cancel after success. Retry while still running. Close during open animation. A webhook before the record exists. Find every input path that sends the event (button, Enter key, shortcut, URL, retry, a second component) and check that each one has the guard; a guard on the button alone is a guard on one path.
3. **Stale and duplicate messages.** A slow response from request 1 landing after request 2. The same webhook delivered twice. A message replayed after restart.
4. **Interruptions.** Crash or reload mid-transition (which writes landed?). Timeout racing success. Tab closed. Context cleared. Process killed between two writes.
5. **Two writers.** Two tabs, two workers, a job and a user, two agents, on the same record or file. Who wins, and is the loser's write detected?
6. **Exits that skip cleanup.** Early return, thrown error or cancellation that leaves a flag set (`isSubmitting` stuck true).
7. **The amended request.** The user changes the input mid-flight (new search term, edited form, added requirement). The happy-path design usually leaves this event out.
8. **Derived state drift.** A cached or derived value (count, total, badge) stored separately from its source, updated on some paths and not others.
9. **Runaway loops.** An effect or subscription that writes the state it depends on, directly or through a re-render. Count how many times the request or handler fires in one second.

## Labels

- **confirmed**: reproduced (a test, a script, the running app), or traced through code whose semantics you are sure of. When the outcome depends on framework scheduling (batching, render order, router instance reuse), a trace is not enough: reproduce it or call it suspected.
- **latent**: confirmed in the unit (hook, function, handler) but not reachable from any entry point today. Fix it before someone wires up the path.
- **suspected**: a lead. Trace or reproduce it before changing code.

To reproduce without touching a repo the user asked you only to read, copy it to a scratch directory and put the test there. Many test runners refuse files outside the project root.

## Ranking

Rank by severity x reachability x blast radius: what goes wrong (data loss, wrong money, runaway requests > wrong text), whether a normal user path reaches it, and how much of the app or data it touches. The top machine for Formalize is the highest-ranked one with a confirmed finding.

## Report

One table for all machines, one row each, ranked:

| Machine | State lives in | Writers | States intended | States reachable | Findings | Risk |
|---|---|---|---|---|---|---|

- **State lives in**: every variable, field, column, ref, storage key and file holding part of it.
- **Writers**: every function that changes it, file:line.
- **States reachable**: what the representation allows (2^N flags, nullable combos), not what the code intends.
- **Findings**: each with an id, the event sequence, the lines that allow it, the bad state, and its label.
- **Risk**: what a user or the data suffers.

End with the files you ruled out and why (single local boolean, unused component), so the reader knows they were looked at.
