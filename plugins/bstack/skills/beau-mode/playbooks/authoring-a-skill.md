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
7. A breaking change to a generated artifact ships with its sweep. The kit writes phase specs, `verify-<app>` skills and `REVIEW.md` into other repos, and CI there only meets a new rule when something carries it over. A change is breaking when an artifact the last release wrote now fails a check or is read differently. For each kind it breaks, run the **qualitydirector** skill's `quality.py sweep BOOKS_DIR KIND` (`phase-spec`, `verify-skill` or `review-guide`) on the quality books, paste the output under the PR's `## Blast radius`, and beside each repo it lists put the upgrade PR you opened or the one that already exists. The output leaves private repos out and says how many: run it again with `--with-private`, upgrade those too, and keep that second output out of the PR. With no books to read, say in the PR that the sweep did not run.
8. Run **Opening a PR**.

**Reply:** what the skill does, the key design decisions, and the validation result.
