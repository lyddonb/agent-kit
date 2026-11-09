# Making a machine explicit

The target: state is one value, decisions live in one pure function, and IO lives at the edge. Making it explicit does not make it correct. It makes the whole logic visible and enumerable, so types, tests and model checks can enforce correctness.

## The shape

1. **State is a discriminated union.** One variant per state, each carrying only its own data. Booleans and nullable phase fields become derived values or disappear.
2. **Events are a discriminated union.** Every input the machine reacts to: user actions, responses, timers, webhooks, restarts. External input is parsed into an event at the boundary.
3. **One pure transition function.** `transition(state, event) -> (nextState, effects)`. No IO, no clock, no randomness, no globals: time, ids and random values arrive inside events. It matches exhaustively on state and event, so a new variant fails compilation until handled.
4. **Effects are data.** The function returns descriptions (`{ kind: "startUpload", uploadId, file }`, `{ kind: "abort", uploadId }`); a thin shell executes them and feeds results back as events. This is what makes the core testable without mocks.
5. **Surfaces do not decide.** Components, routes, commands and handlers translate input into events and render state. Any `if` about the lifecycle in a surface moves into the transition function.

```ts
type State =
  | { kind: "idle" }
  | { kind: "uploading"; uploadId: string; file: File; attempts: number }
  | { kind: "failed"; file: File; attempts: number; error: string }
  | { kind: "done"; url: string };

type Event =
  | { kind: "select"; file: File; uploadId: string }
  | { kind: "succeed"; uploadId: string; url: string }
  | { kind: "fail"; uploadId: string; error: string }
  | { kind: "cancel" } | { kind: "retry"; uploadId: string } /* ... */;

type Effect = { kind: "start"; uploadId: string; file: File } | { kind: "abort"; uploadId: string };

function transition(s: State, e: Event): [State, Effect[]] {
  switch (s.kind) {
    case "uploading":
      if (e.kind === "succeed") return e.uploadId === s.uploadId ? [{ kind: "done", url: e.url }, []] : [s, []];
      // ...
    // ...
    default: return assertNever(s);
  }
}
```

The same shape in other languages: Rust `enum` + `match`; Python `@dataclass(frozen=True)` variants + `match` with `assert_never`; Go a sealed interface with a type switch plus an exhaustiveness linter; Elixir/Erlang `gen_statem`; Kotlin sealed classes.

## Choosing the vehicle

- **Plain union + function** for most machines. No dependency, easy to read.
- **A reducer** (`useReducer`, Redux, Elm update) when the framework already wants one. Same function, different name.
- **XState or another statechart library** when you need hierarchy (nested states), parallel regions, history, delayed transitions or spawned actors, or want its visual tooling. Don't adopt it for a four-state machine.
- **A database `status` column with a check constraint plus transition guards in SQL** (`UPDATE ... SET status = 'paid' WHERE id = ? AND status = 'pending'`) when the machine is a row's lifecycle shared by several processes. The `WHERE` clause is the guard; zero rows updated is the "wrong state" result.

## Persistence and concurrency

- Persist the discriminant and its variant's data, not a bag of flags. Parse it back into the union at load; reject rows that match no variant.
- When more than one writer exists, give every transition a compare-and-set on the current state or a version number. The losing writer gets a clear "state changed" result, never a silent overwrite.
- Make each transition's effects idempotent or keyed (upload id, idempotency key), since crash recovery will replay them.

## Migrating

Follow `migrate-callers-then-delete-legacy-apis`: introduce the union and transition function, route every writer through it one caller at a time, then delete the old flags in the same PR as the last caller. Never leave the flag and the union both writable.

## Tests

- **Table-driven:** `check-machine.py SPEC.md --json` gives every row. One test per row: build the state, send the event, assert the next state (and that `(ignore)` returns the same state with no effects). Guards are prose in the spec, so keep a small map from each guard name to a fixture that makes it true; a row whose guard has no fixture fails the test. The spec and the tests can't drift.
- **Properties:** generate random event sequences from the initial state (fast-check, Hypothesis, proptest) and assert every invariant from the spec after each step.
- **Model checking:** for multi-writer or distributed processes with no single pure core, model the machine in Quint or TLA+ and let the checker search for a sequence that breaks an invariant, before writing code. For a single pure transition function, property tests usually find the same bugs cheaper.
