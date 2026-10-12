---
id: subtract-before-you-add
title: Subtract Before You Add
group: core
when: "Sequencing an addition, refactor, or rewrite."
rule: "Remove dead weight first, then build on the simpler base."
source: pstack/skills/principle-subtract-before-you-add @ ccb5507 (MIT, Lauren Tan)
---
# Subtract Before You Add

When evolving a system, remove complexity first, then build.

**Why:** Adding to a complex system compounds complexity. Removing first leaves less code, reveals the essential structure, and usually makes the next design obvious. Default to subtraction.

Make simplification a continual investment. Leave the design slightly simpler and more capable behind the same or smaller surface than you found it.

**The pattern:**
- Sequence removal before construction
- Cut before you polish (get to the minimum before investing in quality)
- Design for observed usage, not speculative edge cases
- No speculative validators, parsers, or guards beyond what the spec demands
- Simplify prompts (remove redundant instructions, excessive templates)
- When a reference has no novel content, delete it rather than leaving a stub
