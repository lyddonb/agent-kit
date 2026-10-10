---
name: library-docs
description: Look up current, version-specific documentation and code examples for a library, framework, SDK, or API before writing or fixing code that uses it. Use when working with a third-party package, when an API may have changed, when unsure of a function signature, or when the user asks for up-to-date docs.
license: MIT
compatibility: Works best with the Context7 MCP server bundled in the research-tools plugin; falls back to web search or fetch when MCP is unavailable.
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Library docs

Ground code in the documentation for the version the project actually uses, instead of memory.

## Steps

1. **Find the version in use.** Check the project's manifest and lockfile (`package.json` / lockfile, `pyproject.toml` / `uv.lock`, `go.mod`, `Cargo.toml`, `Gemfile.lock`, etc.). If none, ask or assume latest stable and say so.
2. **Fetch docs**, in this order of preference:
   - **Context7 MCP** (if its tools are available): resolve the library id first, then request docs for the specific topic (e.g. "middleware", "auth", "streaming"), passing the version when supported.
   - **Official docs on the web**, if the agent has web search or fetch: prefer the project's own docs site, changelog, and migration guides over blog posts.
   - **Installed source**: read the package's types, docstrings, or source in `node_modules/`, site-packages, or the module cache.
3. **Answer or write code** using what you fetched. Cite the doc page or file you relied on.
4. **Flag drift.** If the code base uses an API that is deprecated or removed in the version in use, say so and show the current equivalent.

## Rules

- Never present memory as documentation. If you could not fetch docs, say the answer is unverified.
- Keep fetched context small: request the specific topic, not the whole manual.
- Prefer the changelog or migration guide when the question is "what changed between X and Y".
