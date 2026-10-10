# Human tasks

Things an agent cannot or should not do: creating accounts, publishing, spending money,
legal choices, and judgment calls. **🚧 BLOCKER** items block other work (listed under
"Unblocks"). Check items off as you go.

| # | Task | Status |
|---|---|---|
| H1 | Create and publish the GitHub repo | 🚧 **BLOCKER** |
| H2 | Confirm the license | 🚧 **BLOCKER** (before making it public) |
| H3 | Turn on GitHub Actions and branch protection | To do |
| H4 | Verify installs in each tool you use | To do |
| H5 | Decide public vs. private, and personal vs. Join content | To do |
| H6 | Review the example skills | To do |

---

### H1. Create and publish the GitHub repo — 🚧 BLOCKER
**Why a human:** Needs your GitHub account and a choice of owner/visibility.
**Steps:**
1. Create `github.com/lyddonb/agent-kit` (or rename: then update `marketplace.repository`
   and `owner` in `kit.yaml`, run `make gen`, and search-replace `lyddonb/agent-kit` in docs).
2. From the unpacked scaffold:
   ```bash
   cd agent-kit
   git init -b main && git add -A && git commit -m "feat: initial agent-kit scaffold"
   git remote add origin git@github.com:lyddonb/agent-kit.git
   git push -u origin main
   ```
3. Tag the first release: `git tag v0.1.0 && git push --tags`.
**Unblocks:** H3, H4, R1 (ROADMAP), and every install command in the docs. agentfiles'
`mine` source also points at this repo.

### H2. Confirm the license — 🚧 BLOCKER before going public
**Why a human:** A legal choice. The scaffold assumes **MIT** (`LICENSE`, `kit.yaml`,
every `SKILL.md`). If skills include anything derived from Join material, they may need
to stay private or use a different license.
**Steps:** Keep MIT, or change `LICENSE` + `kit.yaml` `license` fields + skill
frontmatter, then `make gen`.

### H3. Turn on Actions and protect `main`
**Why a human:** Repository settings.
**Steps:** Ensure Actions are enabled; add a branch protection rule requiring the
`validate` check to pass.

### H4. Verify installs in each tool you use
**Why a human:** Needs your machines, logged-in apps, and judgment on what "works".
**Steps:** Follow [docs/INSTALL.md](docs/INSTALL.md) for Codex, Cursor, pi, and any
others; note anything wrong in an issue. This is ROADMAP R1.
**Note:** Codex plugin enabling happens in the ChatGPT/Codex app UI; Cursor's flow for
adding a third-party plugin repo should be checked against its current docs.

### H5. Decide what is public, and keep Join content separate
**Why a human:** Company confidentiality and IP.
**Recommendation:** Keep this repo personal and public-safe. Put Join-specific skills
(internal systems, process docs, customer details) in a separate private repo under the
company org built from this same template (`kit.yaml` + `tools/`), and confirm with
Join leadership that publishing generic engineering-leadership skills is fine.

### H6. Review the example skills
**Why a human:** They were written by Claude as useful starting points. Read
`design-review`, `interview-kit`, `commit-message`, `handoff-notes`, and `library-docs`
and adjust them to how you actually work (for example, your real interview loop and
competencies, and your team's RFC template).
