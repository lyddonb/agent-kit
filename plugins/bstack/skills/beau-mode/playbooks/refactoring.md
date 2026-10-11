---
id: refactoring
title: Refactoring
when: "A behavior-preserving change to structure: rename, extract, inline, dedupe, move, reshape an API."
source: pstack/skills/poteto-mode/playbooks/refactoring.md @ ccb5507
---

# Refactoring

**You own the contract. The structure changes. The behavior does not.** If the cleanup reveals a bug or a missing feature, split it out and ship the structural change first. Large or cross-cutting structural work goes to **figure-it-out**.

1. Pin the behavior first. Run **how** to learn the contract, then write a characterization test, snapshot, or equivalence harness that captures current behavior. Type checks and lint are not a pin.
2. Name the target shape: the module layout, types and call graph you would build today (`foundational-thinking`, `redesign-from-first-principles`). The reshape must delete branches or invalid states, not add indirection.
3. Subtract before you add: delete dead code, one-caller wrappers and redundant validators first (`subtract-before-you-add`, `laziness-protocol`).
4. Move in small steps that keep the pin green. For an API reshape, migrate every caller and delete the old API in the same change (`migrate-callers-then-delete-legacy-apis`). Check renames against strings, docs and back-references, which tools often miss. Delegate mechanical edits to a `code` subagent.
5. Prove behavior is unchanged on the real artifact with **verify-work**: run the pin, and for larger reshapes an old-versus-new equivalence check.
6. Keep the change only if it lowers reader load somewhere (`minimize-reader-load`). Otherwise revert it.
7. Commit in order: subtraction, then reshape, then follow-on cleanup. Run **Opening a PR**.

**Reply:** what structure changed, the pin you held it against, the equivalence proof, the reader-load improvement, and anything reverted. No new behavior.
