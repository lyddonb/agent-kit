# P1. Add

**Outcome.** `python3 tally.py A B` prints the sum of A and B.
**Serves.** G1.
**Lever.** The add function.

## Ideal state

1. **Done.** Integers add correctly.
2. **Good.** Negative numbers work too.
3. **Surprising.** Floats print without trailing noise.

**Confirmed.** Beau, 2026-11-20, in chat.

## Criteria

- [ ] **C1.** `add(2, 3)` returns 5 and `add(-2, 3)` returns 1.
  Probe: `python3 -m unittest test_tally -v`

## Anti-criteria

- [ ] **A1.** The CLI never prints a traceback for two valid integers.
  Probe: `python3 tally.py 2 3` exits 0 and prints `5`.
