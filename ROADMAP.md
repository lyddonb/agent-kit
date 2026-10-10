# Roadmap

Work that is planned but intentionally **not** done in the initial scaffold. Each item
says why it was deferred and what would trigger doing it.

**Priority key:** **P0** do before relying on the repo daily · **P1** next, high value ·
**P2** worthwhile once there is real usage · **P3** only if a need appears.

Items needing a person (accounts, publishing, decisions) live in
[HUMAN_TASKS.md](HUMAN_TASKS.md), not here.

---

## P0

### R1. Verify installs end-to-end in each real client
**What:** Install from the published GitHub repo in Codex (CLI + app), Cursor, Copilot
in VS Code, and pi; confirm each skill appears and `research-tools`' MCP server connects.
Record results in a table in `docs/INSTALL.md`.
**Why not done:** The scaffold was built and tested in a sandbox with only the Claude
Code CLI available. Claude Code installs (marketplace, all three plugins, MCP) were
verified there; the others are written from current vendor docs but not exercised.
**Blocked by:** H1 (publish the repo) in HUMAN_TASKS.
**Effort:** ~1 hour.

## P1

### R2. Release automation
**What:** A `release` workflow that, on tag `vX.Y.Z`, checks every plugin version in
`kit.yaml` was bumped since the last tag when its files changed, and creates a GitHub
release with a changelog generated from Conventional Commits.
**Why not done:** No release has happened yet; the convention should be proven
manually once first (see AUTHORING.md "Versioning").
**Prioritize when:** a second person contributes, or after the third manual release.

### R3. Skill evals
**What:** Add `evals/` per plugin and run `claude plugin eval` in CI on changed
plugins (prompt cases + graders), so description changes that break triggering are caught.
**Why not done:** Evals need real prompts drawn from use; inventing them up front
produces tests of the wrong things. They also cost API tokens in CI (needs a secret).
**Prioritize when:** a skill misfires (does not trigger, or triggers wrongly) twice.

### R4. `skills-ref validate` in CI
**What:** Run the reference validator from the Agent Skills project alongside
`tools/validate.py`.
**Why not done:** Its install method and CLI were not verified in the sandbox; our
validator already covers the spec's frontmatter rules.
**Prioritize when:** the spec changes (new required fields or constraints).

## P2

### R5. Codex and Cursor overlays
**What:** Let `kit.yaml` carry Codex `interface` metadata (display name, icon, default
prompt) under `extensions.com.openai`, and Cursor-specific metadata, so plugins look
polished in those directories.
**Why not done:** Cosmetic. Codex and Cursor load the plugins fine without it, and the
exact overlay shape should be copied from a working example rather than guessed.
**Prioritize when:** publishing to a public or team directory.

### R6. Client-specific hooks across tools
**What:** A neutral hook definition in `kit.yaml` emitted as Claude `hooks/hooks.json`,
Codex `hooks.json`, and Cursor `hooks/hooks.json`.
**Why not done:** No plugin here needs hooks yet, hooks are the least portable component
(different events and payloads per tool), and they carry the most risk (they run code
on every matching event).
**Prioritize when:** there is a concrete hook worth having in at least two tools.

### R7. Bundled stdio MCP server example
**What:** A plugin that ships its own small MCP server (e.g. a Join-internal API
reader) to exercise the `./bin/...` + `${PLUGIN_DATA}` path translation.
**Why not done:** The only MCP need so far is remote (Context7). The translation code
exists and is unit-testable, but there is no real server to ship.
**Prioritize when:** a skill needs API access that a CLI script cannot provide.

## P3

### R8. Submit to public directories
**What:** Submit selected plugins to Anthropic's plugin directory, the Codex plugin
directory, and Cursor's marketplace.
**Why not done:** Requires public-facing polish, support commitments, and listing
fields (privacy policy, support URL). Only worth it for plugins others will use.
**Prioritize when:** a plugin is useful beyond you (and see H5).

### R9. Split heavy plugins into their own repos
**What:** Move a plugin with its own build (e.g. a compiled MCP server) to a separate
repo and reference it from the marketplace with a git source.
**Why not done:** No plugin has its own build. Splitting early multiplies release work.
**Prioritize when:** a plugin needs its own CI, dependencies, or release cadence.
