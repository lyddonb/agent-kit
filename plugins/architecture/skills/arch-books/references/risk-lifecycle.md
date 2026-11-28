# Machine: risk

states: unseen, observed, open, proposed, accepted, declined, mitigating, closed
events: observe, open, rescore, propose, accept, decline, mitigate, close, reopen
initial: unseen

A risk's state is a fold over its rows in `risks.csv`, in file order, starting from `unseen`. Each row is one event. A move not in this table is illegal and `arch.py check` reports it. `scripts/arch.py` holds this table as `TRANSITIONS`, and `tests/test_arch_register.py` fails if the two differ.

| state | event | next | note |
|---|---|---|---|
| unseen | observe | observed | the first row of a risk fixes its component and failure_mode |
| unseen | open | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| unseen | rescore | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| unseen | propose | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| unseen | accept | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| unseen | decline | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| unseen | mitigate | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| unseen | close | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| unseen | reopen | (impossible) | `arch.py check` rejects it: no risk with that id exists yet |
| observed | observe | (impossible) | `arch.py check` rejects it: the id is taken |
| observed | open | open | scores must equal the rubric row for the failure_mode |
| observed | rescore | (impossible) | `arch.py check` rejects it: an observed risk has no scores yet, so there is nothing to rescore; `open` sets them |
| observed | propose | (impossible) | `arch.py check` rejects it: a risk is opened and scored before it is proposed |
| observed | accept | (impossible) | `arch.py check` rejects it: only a proposed risk is accepted |
| observed | decline | (impossible) | `arch.py check` rejects it: only a proposed risk is declined |
| observed | mitigate | (impossible) | `arch.py check` rejects it: only an accepted risk is mitigated |
| observed | close | (impossible) | `arch.py check` rejects it: only a mitigating risk closes |
| observed | reopen | (impossible) | `arch.py check` rejects it: it is not declined or closed |
| open | observe | (impossible) | `arch.py check` rejects it: the id is taken |
| open | open | (impossible) | `arch.py check` rejects it: already open |
| open | rescore | open | records a human's answer; later rows use the new scores |
| open | propose | proposed | carries the id of the question put to the user |
| open | accept | (impossible) | `arch.py check` rejects it: only a proposed risk is accepted |
| open | decline | (impossible) | `arch.py check` rejects it: only a proposed risk is declined |
| open | mitigate | (impossible) | `arch.py check` rejects it: only an accepted risk is mitigated |
| open | close | (impossible) | `arch.py check` rejects it: only a mitigating risk closes |
| open | reopen | (impossible) | `arch.py check` rejects it: it is not declined or closed |
| proposed | observe | (impossible) | `arch.py check` rejects it: the id is taken |
| proposed | open | (impossible) | `arch.py check` rejects it: only an observed risk is opened |
| proposed | rescore | proposed | records a human's answer; later rows use the new scores |
| proposed | propose | (impossible) | `arch.py check` rejects it: already proposed |
| proposed | accept | accepted | evidence is the user's answer |
| proposed | decline | declined | evidence is the user's answer |
| proposed | mitigate | (impossible) | `arch.py check` rejects it: it must be accepted first |
| proposed | close | (impossible) | `arch.py check` rejects it: only a mitigating risk closes |
| proposed | reopen | (impossible) | `arch.py check` rejects it: it is not declined or closed |
| accepted | observe | (impossible) | `arch.py check` rejects it: the id is taken |
| accepted | open | (impossible) | `arch.py check` rejects it: only an observed risk is opened |
| accepted | rescore | accepted | records a human's answer; later rows use the new scores |
| accepted | propose | (impossible) | `arch.py check` rejects it: it is already decided |
| accepted | accept | (impossible) | `arch.py check` rejects it: already accepted |
| accepted | decline | (impossible) | `arch.py check` rejects it: already accepted |
| accepted | mitigate | mitigating | evidence is a roadmap id or a pull request |
| accepted | close | (impossible) | `arch.py check` rejects it: only a mitigating risk closes |
| accepted | reopen | (impossible) | `arch.py check` rejects it: it is not declined or closed |
| declined | observe | (impossible) | `arch.py check` rejects it: the id is taken |
| declined | open | (impossible) | `arch.py check` rejects it: only an observed risk is opened; `reopen` is the way back |
| declined | rescore | declined | records a human's answer; later rows use the new scores |
| declined | propose | (impossible) | `arch.py check` rejects it: `reopen` first |
| declined | accept | (impossible) | `arch.py check` rejects it: it is already decided |
| declined | decline | (impossible) | `arch.py check` rejects it: already declined |
| declined | mitigate | (impossible) | `arch.py check` rejects it: it is not accepted |
| declined | close | (impossible) | `arch.py check` rejects it: only a mitigating risk closes |
| declined | reopen | open | evidence says what changed |
| mitigating | observe | (impossible) | `arch.py check` rejects it: the id is taken |
| mitigating | open | (impossible) | `arch.py check` rejects it: only an observed risk is opened |
| mitigating | rescore | mitigating | records a human's answer; later rows use the new scores |
| mitigating | propose | (impossible) | `arch.py check` rejects it: it is already decided |
| mitigating | accept | (impossible) | `arch.py check` rejects it: already accepted |
| mitigating | decline | (impossible) | `arch.py check` rejects it: already accepted |
| mitigating | mitigate | (impossible) | `arch.py check` rejects it: already mitigating |
| mitigating | close | closed | evidence starts with `receipt:`; no other event reaches closed |
| mitigating | reopen | (impossible) | `arch.py check` rejects it: it is not declined or closed |
| closed | observe | (impossible) | `arch.py check` rejects it: the id is taken |
| closed | open | (impossible) | `arch.py check` rejects it: only an observed risk is opened; `reopen` is the way back |
| closed | rescore | (impossible) | `arch.py check` rejects it: a closed risk keeps the scores it closed with |
| closed | propose | (impossible) | `arch.py check` rejects it: `reopen` first |
| closed | accept | (impossible) | `arch.py check` rejects it: `reopen` first |
| closed | decline | (impossible) | `arch.py check` rejects it: `reopen` first |
| closed | mitigate | (impossible) | `arch.py check` rejects it: `reopen` first |
| closed | close | (impossible) | `arch.py check` rejects it: already closed |
| closed | reopen | open | evidence says what changed |

## What each event must carry

| event | scores | evidence | question |
|---|---|---|---|
| observe | none | required | none |
| open | all three, equal to the rubric row | optional | none |
| rescore | all three | required | none |
| propose | none | optional | required |
| accept | none | required | none |
| decline | none | required | none |
| mitigate | none | required | none |
| close | none | required, starts with `receipt:` | none |
| reopen | none | required | none |

`observe` also carries component and failure_mode. Every later row for the risk leaves both empty or repeats them.

## Invariants
- A risk is in exactly one state, the fold of its own rows; rows of other risks never change it.
- `closed` is reached only by `close`, and a `close` row's evidence starts with `receipt:`.
- Every state except `unseen` and `observed` has all three scores; the current ones are those of the latest `open` or `rescore` row.
- A risk's component and failure_mode never change after `observe`.
- A risk's rows never go back in date.
- A row that breaks any rule above is reported by `arch.py check`, and `arch.py summary` refuses to summarize books that have one.

## Interruptions
- A second writer appends `observe` for an id that exists: `observe` in every state but `unseen`.
- A survey or a person repeats a row after a crash: `open`, `propose`, `accept`, `decline`, `mitigate`, `close` in the state they already moved to.
- A late answer arrives after a risk was closed: `rescore`, `accept`, `decline` in `closed`.
- A fix is merged and its probe never run: `close` without `receipt:` evidence, or from any state but `mitigating`.
- The user changes their mind about a decision: `reopen` from `declined` or `closed`.
- A row for a risk nobody observed: every event but `observe` in `unseen`.

## Assumptions
- Scores come only from the rubric (at `open`) or from a human's recorded answer (`rescore`); the script never invents one.
- `rescore` is legal in `open`, `proposed`, `accepted`, `declined` and `mitigating`, and never moves the risk. The first draft of this table also allowed it in `observed`; it is removed, because `observed` carries no scores and `open` is what sets them.
- `reopen` is the only way out of `declined` and `closed`; a reopened risk goes to `open` and keeps its latest scores.
- Nothing leaves `accepted` or `mitigating` except forward. A mitigation that is abandoned stays `mitigating` until it is closed with a receipt; a way out is a decision for a later change.
- An `observed` risk that turns out to be noise stays `observed`; it has no score and no tier, so it ranks last.
- A row with an illegal move leaves the risk in the state it was in, so one bad row does not hide the rows after it.
