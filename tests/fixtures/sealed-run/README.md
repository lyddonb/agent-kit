# A sealed agent-ledger run

`.audit/` here is a real run folder made by `ledger` 1.0.0 (agent-ledger), with synthetic
content: 31 decision entries, one archived session transcript (`sessions/*.jsonl.gz`), a seal
and `INDEX.jsonl`. Every scanner in this repo that reads a books repo must pass it, because
governed runs commit exactly this to the repos they work in. Its sha256 hashes contain 12-digit
runs, which look like cloud account IDs to a naive scan; `tests/test_books.py` asserts that,
so the fixture keeps testing what it is for.

To regenerate it: in an empty git repo, `ledger init demo --date 2026-01-05`, append 30
`decision` entries, `ledger session add` a two-line synthetic transcript, commit, `ledger seal`,
commit, and copy `.audit/` here. Use made-up actors; this repo is public.
