#!/usr/bin/env python3
"""kitgen - generate every tool-specific manifest in agent-kit from kit.yaml.

Usage:
    python3 tools/kitgen.py            # write generated files
    python3 tools/kitgen.py --check    # exit 1 if generated files are stale (CI)
    python3 tools/kitgen.py --list     # print the files that would be generated

Inputs:  kit.yaml + the plugins/<name>/ directories (skills/, hooks/, ...).
Outputs (all committed, so plain `git clone` / marketplace installs work):

    plugins/<name>/plugin.json                Agent Plugins 1.0 manifest (Codex, Cursor, Copilot, ...)
    plugins/<name>/mcp.json                   Agent Plugins 1.0 MCP config (only if the plugin has MCP)
    plugins/<name>/.claude-plugin/plugin.json Claude Code manifest
    plugins/<name>/.mcp.json                  Claude Code MCP config (only if the plugin has MCP)
    plugins/<name>/.cursor-plugin/plugin.json Cursor-native manifest (only if the plugin has rules/)
    .claude-plugin/marketplace.json           Claude Code marketplace
    .agents/plugins/marketplace.json          Codex marketplace
    .cursor-plugin/marketplace.json           Cursor marketplace
    package.json                              pi package manifest
    docs/CATALOG.md                           human-readable catalog
    docs/PRINCIPLES.md                        human-readable principle index
    .generated                                list of generated files (used by --check)

It also fills GENERATED blocks inside authored Markdown files, so indexes and shared
text have one source and cannot drift:

    <!-- BEGIN GENERATED: <block> (...) -->  ...  <!-- END GENERATED: <block> -->

    principles-index     full principle table, from plugins/*/skills/principles/references/*.md
    principles-compact   grouped one-line principle list (for router skills)
    playbooks-index      the skill's own playbooks/*.md, from their frontmatter
    snippet:<name>       plugins/<this plugin>/snippets/<name>.md, verbatim
    upstream-files       table of files adapted from other projects (from their source/upstream
                         field or "Adapted from" header), for docs/UPSTREAM.md

Only depends on PyYAML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("kitgen needs PyYAML: pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
AP_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AP_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
CLAUDE_MARKETPLACE_SCHEMA = "https://json.schemastore.org/claude-code-marketplace.json"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CODEX_CATEGORIES = {
    "productivity": "Productivity",
    "development": "Developer Tools",
    "developer-tools": "Developer Tools",
    "design": "Design",
    "data": "Data",
}


class KitError(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def dump_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, [], {})}


def load_kit() -> dict:
    path = ROOT / "kit.yaml"
    if not path.exists():
        raise KitError("kit.yaml not found")
    kit = yaml.safe_load(path.read_text()) or {}
    for key in ("marketplace", "plugins"):
        if key not in kit:
            raise KitError(f"kit.yaml is missing '{key}'")
    return kit


def plugin_skills(pdir: Path) -> list[str]:
    sdir = pdir / "skills"
    if not sdir.is_dir():
        return []
    return sorted(p.parent.name for p in sdir.glob("*/SKILL.md"))


def skill_description(pdir: Path, skill: str) -> str:
    text = (pdir / "skills" / skill / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return ""
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise KitError(f"plugins/.../skills/{skill}/SKILL.md: frontmatter is not valid YAML "
                       f"(quote values that contain ': '): {e}") from e
    return str(fm.get("description", "")).strip()


# --------------------------------------------------------------------------- MCP translation

def neutral_mcp_to_agent_plugins(servers: dict) -> dict:
    out = {}
    for name, cfg in servers.items():
        t = cfg.get("type", "stdio")
        if t == "stdio":
            if "command" not in cfg:
                raise KitError(f"MCP server {name}: stdio servers need 'command'")
            out[name] = drop_none({
                "type": "stdio",
                "command": cfg["command"],
                "args": cfg.get("args"),
                "env": cfg.get("env"),
                "cwd": cfg.get("cwd"),
            })
        elif t in ("streamable-http", "sse"):
            if "url" not in cfg:
                raise KitError(f"MCP server {name}: {t} servers need 'url'")
            out[name] = drop_none({"type": t, "url": cfg["url"], "headers": cfg.get("headers")})
        else:
            raise KitError(f"MCP server {name}: unknown type {t!r}")
    return {"$schema": AP_MCP_SCHEMA, "mcpServers": out}


def _claude_vars(value):
    if isinstance(value, str):
        return value.replace("${PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}").replace(
            "${PLUGIN_DATA}", "${CLAUDE_PLUGIN_DATA}")
    if isinstance(value, list):
        return [_claude_vars(v) for v in value]
    if isinstance(value, dict):
        return {k: _claude_vars(v) for k, v in value.items()}
    return value


def neutral_mcp_to_claude(servers: dict) -> dict:
    out = {}
    for name, cfg in servers.items():
        t = cfg.get("type", "stdio")
        if t == "stdio":
            cmd = cfg["command"]
            if cmd.startswith("./"):
                cmd = "${CLAUDE_PLUGIN_ROOT}/" + cmd[2:]
            out[name] = drop_none({
                "command": cmd,
                "args": _claude_vars(cfg.get("args")),
                "env": _claude_vars(cfg.get("env")),
            })
        elif t == "streamable-http":
            out[name] = drop_none({"type": "http", "url": cfg["url"], "headers": cfg.get("headers")})
        elif t == "sse":
            out[name] = drop_none({"type": "sse", "url": cfg["url"], "headers": cfg.get("headers")})
    return {"mcpServers": out}


# --------------------------------------------------------------------------- generation

def generate(kit: dict) -> dict[str, str]:
    files: dict[str, str] = {}
    mk = kit["marketplace"]
    defaults = kit.get("defaults", {})
    repo_url = mk.get("repository")

    if not NAME_RE.match(mk["name"]):
        raise KitError(f"marketplace name {mk['name']!r} must be kebab-case")

    seen = set()
    resolved = []
    for p in kit["plugins"]:
        name = p["name"]
        if not NAME_RE.match(name) or len(name) > 64:
            raise KitError(f"plugin name {name!r} must be kebab-case, 1-64 chars")
        if name in seen:
            raise KitError(f"duplicate plugin {name!r}")
        seen.add(name)
        pdir = ROOT / "plugins" / name
        if not pdir.is_dir():
            raise KitError(f"plugins/{name}/ does not exist (declared in kit.yaml)")
        merged = {**defaults, **p}
        if not merged.get("description"):
            raise KitError(f"plugin {name}: description is required")
        resolved.append((merged, pdir))

    undeclared = sorted(
        d.name for d in (ROOT / "plugins").iterdir()
        if d.is_dir() and d.name not in seen
    )
    if undeclared:
        raise KitError(f"plugin directories not declared in kit.yaml: {', '.join(undeclared)}")

    for p, pdir in resolved:
        name = p["name"]
        rel = f"plugins/{name}"
        author = p.get("author")
        homepage = f"{repo_url}/tree/main/{rel}" if repo_url else None

        # Agent Plugins 1.0: closed schema - only these top-level keys are allowed.
        ap = drop_none({
            "$schema": AP_PLUGIN_SCHEMA,
            "name": name,
            "version": p.get("version"),
            "description": p["description"],
            "author": author,
            "homepage": homepage,
            "repository": repo_url,
            "license": p.get("license"),
            "keywords": p.get("keywords"),
            "extensions": p.get("extensions"),
        })
        files[f"{rel}/plugin.json"] = dump_json(ap)

        claude = drop_none({
            "name": name,
            "version": p.get("version"),
            "description": p["description"],
            "author": author,
            "homepage": homepage,
            "repository": repo_url,
            "license": p.get("license"),
            "keywords": p.get("keywords"),
        })
        files[f"{rel}/.claude-plugin/plugin.json"] = dump_json(claude)

        if p.get("mcp"):
            files[f"{rel}/mcp.json"] = dump_json(neutral_mcp_to_agent_plugins(p["mcp"]))
            files[f"{rel}/.mcp.json"] = dump_json(neutral_mcp_to_claude(p["mcp"]))

        if (pdir / "rules").is_dir() or p.get("cursor"):
            cursor = drop_none({
                "name": name,
                "version": p.get("version"),
                "description": p["description"],
                "author": author,
                "homepage": homepage,
                "repository": repo_url,
                "license": p.get("license"),
                "keywords": p.get("keywords"),
                **(p.get("cursor") or {}),
            })
            files[f"{rel}/.cursor-plugin/plugin.json"] = dump_json(cursor)

    # ---- marketplaces
    owner = mk.get("owner", {})
    files[".claude-plugin/marketplace.json"] = dump_json(drop_none({
        "$schema": CLAUDE_MARKETPLACE_SCHEMA,
        "name": mk["name"],
        "description": mk.get("description"),
        "owner": owner,
        "plugins": [drop_none({
            "name": p["name"],
            "description": p["description"],
            "version": p.get("version"),
            "source": f"./plugins/{p['name']}",
            "category": p.get("category"),
            "keywords": p.get("keywords"),
        }) for p, _ in resolved],
    }))

    files[".agents/plugins/marketplace.json"] = dump_json({
        "name": mk["name"],
        "interface": {"displayName": mk.get("display_name", mk["name"])},
        "plugins": [drop_none({
            "name": p["name"],
            "source": {"source": "local", "path": f"./plugins/{p['name']}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": CODEX_CATEGORIES.get(p.get("category", ""), "Productivity"),
        }) for p, _ in resolved],
    })

    files[".cursor-plugin/marketplace.json"] = dump_json(drop_none({
        "name": mk["name"],
        "owner": owner,
        "metadata": drop_none({"description": mk.get("description")}),
        "plugins": [{
            "name": p["name"],
            "source": f"plugins/{p['name']}",
            "description": p["description"],
        } for p, _ in resolved],
    }))

    # ---- pi package (pi install git:github.com/<owner>/agent-kit)
    files["package.json"] = dump_json(drop_none({
        "name": mk["name"],
        "version": kit.get("version", defaults.get("version", "0.1.0")),
        "private": True,
        "description": mk.get("description"),
        "license": mk.get("license"),
        "repository": repo_url,
        "keywords": ["pi-package", "agent-skills", "agent-plugins"],
        "pi": {"skills": [f"./plugins/{p['name']}/skills" for p, pdir in resolved
                          if plugin_skills(pdir)]},
    }))

    # ---- catalog
    lines = [
        "<!-- GENERATED by tools/kitgen.py from kit.yaml - do not edit by hand -->",
        "# Catalog",
        "",
        "Every plugin and skill in this repo. See [INSTALL.md](INSTALL.md) for how to install them.",
        "",
    ]
    for p, pdir in resolved:
        skills = plugin_skills(pdir)
        lines += [f"## `{p['name']}`", "", p["description"], ""]
        extras = []
        if p.get("mcp"):
            extras.append("MCP servers: " + ", ".join(f"`{s}`" for s in p["mcp"]))
        for comp in ("hooks", "agents", "commands", "rules"):
            if (pdir / comp).is_dir():
                extras.append(f"client-specific `{comp}/` (not portable)")
        if extras:
            lines += ["- " + e for e in extras] + [""]
        if skills:
            lines += ["| Skill | Description |", "|---|---|"]
            for s in skills:
                desc = skill_description(pdir, s).replace("|", "\\|")
                lines.append(f"| [`{s}`](../plugins/{p['name']}/skills/{s}/SKILL.md) | {desc} |")
            lines.append("")
    files["docs/CATALOG.md"] = "\n".join(lines)

    principles = load_principles()
    if principles:
        files["docs/PRINCIPLES.md"] = principles_doc(principles)

    files[".generated"] = "".join(f"{f}\n" for f in sorted(files) + [".generated"])
    return files


# --------------------------------------------------------------------------- generated blocks

BLOCK_RE = re.compile(
    r"(<!-- BEGIN GENERATED: (?P<name>[a-z0-9:_-]+)[^>]*-->\n)(?P<body>.*?)(<!-- END GENERATED: (?P=name) -->)",
    re.S)
PRINCIPLE_GROUPS = ("core", "architecture", "verification", "delegation", "meta")
PRINCIPLE_KEYS = {"id", "title", "group", "when", "rule", "source"}


def _frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise KitError(f"{path.relative_to(ROOT)}: invalid frontmatter: {e}") from e
    return fm, text[m.end():]


def load_principles() -> list[dict]:
    out, seen = [], {}
    for f in sorted(ROOT.glob("plugins/*/skills/principles/references/*.md")):
        fm, _ = _frontmatter(f)
        rel = f.relative_to(ROOT)
        missing = {k for k in ("id", "title", "group", "when", "rule") if not str(fm.get(k) or "").strip()}
        if missing:
            raise KitError(f"{rel}: principle frontmatter is missing or empty: {sorted(missing)}")
        unknown = set(fm) - PRINCIPLE_KEYS
        if unknown:
            raise KitError(f"{rel}: unknown principle keys {sorted(unknown)}")
        if fm["id"] != f.stem or not NAME_RE.match(fm["id"]):
            raise KitError(f"{rel}: id {fm['id']!r} must be kebab-case and match the file name")
        if fm["group"] not in PRINCIPLE_GROUPS:
            raise KitError(f"{rel}: group {fm['group']!r} not in {PRINCIPLE_GROUPS}")
        if fm["id"] in seen:
            raise KitError(f"{rel}: duplicate principle id (also {seen[fm['id']]})")
        seen[fm["id"]] = rel
        out.append({**fm, "path": f})
    order = {g: i for i, g in enumerate(PRINCIPLE_GROUPS)}
    return sorted(out, key=lambda p: (order[p["group"]], p["title"].lower()))


def _cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


def gen_principles_index(principles: list[dict]) -> str:
    lines = ["| Principle | Group | When | Rule |", "|---|---|---|---|"]
    for p in principles:
        lines.append(f"| [{p['title']}](references/{p['id']}.md) (`{p['id']}`) | {p['group']} | "
                     f"{_cell(p['when'])} | {_cell(p['rule'])} |")
    return "\n".join(lines) + "\n"


def gen_principles_compact(principles: list[dict]) -> str:
    lines = []
    for g in PRINCIPLE_GROUPS:
        group = [p for p in principles if p["group"] == g]
        if not group:
            continue
        lines += [f"**{g.capitalize()}**", ""]
        lines += [f"- **{p['title']}** (`{p['id']}`). {_cell(p['when'])}" for p in group]
        lines.append("")
    return "\n".join(lines)


def gen_playbooks_index(skill_dir: Path) -> str:
    lines = []
    for f in sorted((skill_dir / "playbooks").glob("*.md")):
        fm, _ = _frontmatter(f)
        rel = f.relative_to(ROOT)
        for key in ("id", "title", "when"):
            if not fm.get(key):
                raise KitError(f"{rel}: playbook frontmatter needs '{key}'")
        if fm["id"] != f.stem:
            raise KitError(f"{rel}: playbook id {fm['id']!r} must match the file name")
        lines.append(f"- **{fm['title']}** (`playbooks/{f.name}`). {_cell(fm['when'])}")
    if not lines:
        raise KitError(f"{skill_dir.relative_to(ROOT)}: playbooks-index block but no playbooks/*.md")
    return "\n".join(lines) + "\n"


UPSTREAM_RE = re.compile(r"(?:^source|^  upstream): \"?(?P<a>[^\"\n]+)|Adapted from (?P<b>\S+) @ (?P<c>[0-9a-f]{7})", re.M)


def gen_upstream_files() -> str:
    rows = []
    for f in sorted(ROOT.glob("plugins/**/*")):
        if not f.is_file() or f.suffix not in (".md", ".sh", ".py", ".tsv"):
            continue
        m = UPSTREAM_RE.search(f.read_text(errors="replace"))
        if not m:
            continue
        origin = m.group("a") or f"{m.group('b')} @ {m.group('c')}"
        origin = origin.replace(" (MIT, Lauren Tan)", "")
        rows.append(f"| `{f.relative_to(ROOT).as_posix()}` | `{origin}` |")
    if not rows:
        return "No adapted files.\n"
    return "\n".join(["| File | Adapted from |", "|---|---|", *rows]) + "\n"


def fill_blocks(principles: list[dict]) -> dict[str, str]:
    """Return {relative path: new content} for every authored file with GENERATED blocks."""
    out: dict[str, str] = {}
    for f in sorted([*ROOT.glob("plugins/**/*.md"), *ROOT.glob("docs/*.md")]):
        text = f.read_text()
        if "<!-- BEGIN GENERATED:" not in text:
            continue
        rel = f.relative_to(ROOT)
        plugin_root = ROOT / rel.parts[0] / rel.parts[1] if rel.parts[0] == "plugins" else None

        def render(m):
            name = m.group("name")
            if name == "principles-index":
                body = gen_principles_index(principles)
            elif name == "principles-compact":
                body = gen_principles_compact(principles)
            elif name == "playbooks-index":
                body = gen_playbooks_index(f.parent)
            elif name == "upstream-files":
                body = gen_upstream_files()
            elif name.startswith("snippet:"):
                if plugin_root is None:
                    raise KitError(f"{rel}: snippet blocks are only allowed inside plugins/")
                snip = plugin_root / "snippets" / f"{name.split(':', 1)[1]}.md"
                if not snip.is_file():
                    raise KitError(f"{rel}: snippet {snip.relative_to(ROOT)} not found")
                body = snip.read_text()
                if not body.endswith("\n"):
                    body += "\n"
            else:
                raise KitError(f"{rel}: unknown GENERATED block {name!r}")
            return m.group(1) + body + m.group(4)

        # Blocks inside fenced code (documentation examples) are left alone.
        parts = re.split(r"(^```.*?^```[^\n]*\n?)", text, flags=re.S | re.M)
        for i in range(0, len(parts), 2):
            seg = parts[i]
            if seg.count("<!-- BEGIN GENERATED:") != len(BLOCK_RE.findall(seg)):
                raise KitError(f"{rel}: a GENERATED block is missing its END marker")
            parts[i] = BLOCK_RE.sub(render, seg)
        new = "".join(parts)
        if new != text or BLOCK_RE.search("".join(parts[0::2])):
            out[str(rel)] = new
    return out


def principles_doc(principles: list[dict]) -> str:
    lines = [
        "<!-- GENERATED by tools/kitgen.py from plugins/principles/skills/principles/references - do not edit -->",
        "# Principles",
        "",
        "Named rules that steer how agents design, build and verify. Steer an agent by name "
        "(\"apply prove it works\"); the agent must say which decision each principle changed.",
        "Source files live in [`plugins/principles/skills/principles/references/`]"
        "(../plugins/principles/skills/principles/references/). Each has a stable `id` that other skills, "
        "profiles and (later) the knowledge base use to refer to it.",
        "",
    ]
    for g in PRINCIPLE_GROUPS:
        group = [p for p in principles if p["group"] == g]
        if not group:
            continue
        lines += [f"## {g.capitalize()}", "", "| Principle | When | Rule |", "|---|---|---|"]
        for p in group:
            rel = p["path"].relative_to(ROOT).as_posix()
            lines.append(f"| [{p['title']}](../{rel}) `{p['id']}` | {_cell(p['when'])} | {_cell(p['rule'])} |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if generated files are out of date")
    ap.add_argument("--list", action="store_true", help="list generated files")
    args = ap.parse_args(argv)

    try:
        files = generate(load_kit())
        blocks = fill_blocks(load_principles())
    except KitError as e:
        print(f"kitgen: error: {e}", file=sys.stderr)
        return 2

    previous = set()
    gen_list = ROOT / ".generated"
    if gen_list.exists():
        previous = {l.strip() for l in gen_list.read_text().splitlines() if l.strip()}
    stale_removed = sorted(previous - set(files))

    if args.list:
        print("\n".join(sorted(files)))
        print("\n".join(f"{r} (blocks)" for r in sorted(blocks)))
        return 0

    if args.check:
        bad = []
        for rel, content in files.items():
            path = ROOT / rel
            if not path.exists() or path.read_text() != content:
                bad.append(rel)
        bad += [f"{r} (should be deleted)" for r in stale_removed if (ROOT / r).exists()]
        bad += [f"{r} (GENERATED block)" for r, c in blocks.items() if (ROOT / r).read_text() != c]
        if bad:
            print("kitgen: generated files are stale. Run `make gen` and commit:", file=sys.stderr)
            for b in bad:
                print(f"  {b}", file=sys.stderr)
            return 1
        print(f"kitgen: {len(files)} generated files and {len(blocks)} files with GENERATED blocks up to date")
        return 0

    for rel in stale_removed:
        path = ROOT / rel
        if path.exists():
            path.unlink()
            print(f"removed  {rel}")
    for rel, content in sorted(files.items()):
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
            print(f"wrote    {rel}")
    for rel, content in sorted(blocks.items()):
        path = ROOT / rel
        if path.read_text() != content:
            path.write_text(content)
            print(f"filled   {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
