# dedupe-rows-by-id (2026-11-21)

**Goal.** Customer exports sometimes contain the same row twice; make the importer drop the repeats.

## What changed

- Added dedupe.py: a CSV filter that keeps the first row for each id and drops later rows with the same id.
- Added test_dedupe.py and sample.csv. Nothing calls dedupe.py yet: the repo has no importer, so this is a standalone script.

## What is proven

- **VERIFIED**: dedupe() keeps the first row for each id and drops later ones.
  - Check: python3 -m unittest -v test_dedupe, run in the repo root with Python 3 on macOS: 1 test, OK. (on f85541b)
  - Record: .changes/2026-11-21-dedupe-rows-by-id/unittest.txt
  - Still unchecked: One test with 3 rows. Not checked: large files, quoted fields, a missing id column.
- **VERIFIED**: Running python3 dedupe.py sample.csv prints the file with the repeat of id 1 removed.
  - Check: python3 dedupe.py sample.csv: output is the header, 1,a and 2,c. (on f85541b)
  - Record: .changes/2026-11-21-dedupe-rows-by-id/cli-sample.txt
  - Still unchecked: Only the 3-row sample. Rows that share an id but differ in other columns (1,a and 1,b) are collapsed to the first, so the second value is dropped silently.
- **UNCHECKED**: The real importer now drops repeated rows.
  - Still unchecked: No importer exists in this repo and nothing calls dedupe.py. Hook it into the import path and test there.
- **NOT VERIFIED**: A file with only a header row is handled.
  - Check: python3 dedupe.py on a file containing just 'id,v': crashes with IndexError at rows[0].keys(). (on f85541b)
  - Record: .changes/2026-11-21-dedupe-rows-by-id/empty.txt
  - Still unchecked: Fix the crash on an empty export (read the header from the reader, not from rows[0]) and add a test.

## Next

- **Wire dedupe into the importer.**
  - From: inferred
  - Why now: The goal was that the importer drops repeats. Until it is called there, exports still import duplicates.
  - Impact: Whoever imports customer exports sees no change from this commit until it is wired in; after, repeated rows stop appearing.
- **Fix the crash on a header-only (empty) CSV.**
  - From: inferred
  - Why now: Found while verifying this change; an empty export would stop the run with a traceback.
  - Impact: Anyone importing an empty export gets a stack trace instead of an empty result.
- **Make ids case-insensitive (A1 and a1 are the same customer).**
  - From: ROADMAP.md R3
  - Why now: Billing exports repeat customers under different case, and dedupe.py treats A1 and a1 as different (confirmed: both rows kept).
  - Impact: Billing users keep duplicate customers until this is done.
- **Stream large files instead of reading them into a list.**
  - From: ROADMAP.md R2
  - Why now: Exports run to 4 GB and dedupe.py loads the whole file into memory; the seen-set of ids still needs memory after streaming.
  - Impact: Large exports can run out of memory.

## Release note

none: dedupe.py is not yet connected to the importer, so users see no change.
