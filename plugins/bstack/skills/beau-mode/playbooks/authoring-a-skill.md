---
id: authoring-a-skill
title: Authoring a skill
when: "Writing or editing a SKILL.md, a playbook, or a principle."
source: pstack/skills/poteto-mode/playbooks/authoring-a-skill.md @ ccb5507
---

# Authoring a skill

**You own the skill's voice.** Agent-facing prose has a higher bar than human prose: every sentence becomes an instruction some future agent follows.

1. Decide where it lives. Generic and public-safe goes in agent-kit (`plugins/<plugin>/skills/<name>/`). Anything employer- or project-specific goes in that project's own skills repo or the project's `.agents/skills/`.
2. Follow the Agent Skills format: `name` equals the folder name; `description` says what it does and when to use it, in the words a user would type. Use only `name`, `description`, `license`, `compatibility` and `metadata` in frontmatter so every tool reads it the same way.
3. Keep `SKILL.md` short. Move detail to `references/` and repeatable steps to `scripts/`. Reference other skills by name, never by pasting their content. Shared text belongs in a snippet that the generator inlines.
4. Cut every sentence that doesn't change a decision. Say what to do; explain why only when the rule is confusing without it. Prefer structure over prose (`encode-lessons-in-structure`): if a rule can be a script or a check, make it one.
5. Validate: in agent-kit run `make gen validate claude-validate`. Elsewhere, check the frontmatter and that every referenced file exists.
6. If the change alters behavior, test it with the Eval playbook before relying on it.
7. Run **Opening a PR**.

**Reply:** what the skill does, the key design decisions, and the validation result.
