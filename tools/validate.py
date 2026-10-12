#!/usr/bin/env python3
"""validate - portability lint for agent-kit skills and plugins.

Checks every plugins/*/skills/*/SKILL.md against the Agent Skills spec
(https://agentskills.io/specification) plus a few portability rules this repo
adopts so the same skill behaves the same in every client:

  errors   - break the spec, so some clients will refuse or skip the skill
  warnings - legal, but likely to behave differently across clients

Usage: python3 tools/validate.py [--strict]   (--strict turns warnings into errors)

For Claude Code specifics, CI additionally runs `claude plugin validate --strict`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
AP_PLUGIN_FIELDS = {"$schema", "name", "version", "description", "author", "homepage",
                    "repository", "license", "keywords", "extensions"}
# Tool-specific placeholders that only resolve in one client.
NON_PORTABLE = {
    "${CLAUDE_PLUGIN_ROOT}": "Claude Code only",
    "${CLAUDE_PLUGIN_DATA}": "Claude Code only",
    "{baseDir}": "pi only",
    "${PLUGIN_ROOT}": "only expanded in MCP config, not skill bodies",
}
RESERVED_PREFIXES = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 4:].lstrip("\n")
    return fm, body


def check_skill(skill_md: Path, r: Report):
    where = str(skill_md.relative_to(ROOT))
    text = skill_md.read_text()
    try:
        fm, body = parse_frontmatter(text)
    except yaml.YAMLError as e:
        r.err(where, f"frontmatter is not valid YAML: {e}")
        return
    if fm is None:
        r.err(where, "missing YAML frontmatter (--- ... ---)")
        return
    if not isinstance(fm, dict):
        r.err(where, "frontmatter must be a mapping")
        return

    name = fm.get("name")
    if not isinstance(name, str) or not name:
        r.err(where, "'name' is required")
    else:
        if len(name) > 64 or not NAME_RE.match(name):
            r.err(where, f"name {name!r} must be 1-64 chars of a-z, 0-9 and single hyphens")
        if name != skill_md.parent.name:
            r.err(where, f"name {name!r} must match its directory {skill_md.parent.name!r}")

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        r.err(where, "'description' is required")
    elif len(desc) > 1024:
        r.err(where, f"description is {len(desc)} chars (max 1024)")
    elif len(desc) < 40:
        r.warn(where, "description is very short; say what it does AND when to use it")

    comp = fm.get("compatibility")
    if comp is not None and (not isinstance(comp, str) or not 1 <= len(comp) <= 500):
        r.err(where, "compatibility must be a 1-500 char string")

    meta = fm.get("metadata")
    if meta is not None and (not isinstance(meta, dict) or
                             not all(isinstance(k, str) and isinstance(v, str) for k, v in meta.items())):
        r.err(where, "metadata must map strings to strings (quote numbers like version: \"1.0\")")

    for key in fm:
        if key not in SPEC_FIELDS:
            r.warn(where, f"frontmatter field {key!r} is not in the Agent Skills spec; most clients ignore it")
    if "allowed-tools" in fm:
        r.warn(where, "'allowed-tools' is experimental and tool names differ per client")

    lines = body.count("\n") + 1
    if lines > 500:
        r.warn(where, f"SKILL.md body is {lines} lines; keep under 500 and move detail to references/")

    for token, why in NON_PORTABLE.items():
        if token in body:
            r.warn(where, f"uses {token} ({why}); use paths relative to the skill directory instead")

    check_links(skill_md, body, where, r)


def check_links(md: Path, text: str, where: str, r: Report):
    """Relative links must resolve. Links in fenced code are examples, not links."""
    for target in LINK_RE.findall(FENCE_RE.sub("", text)):
        if "://" in target or target.startswith("mailto:"):
            continue
        if not (md.parent / target).exists():
            r.err(where, f"links to {target!r}, which does not exist")


def check_plugin(pdir: Path, r: Report):
    where = str(pdir.relative_to(ROOT))
    name = pdir.name
    low = name.lower()
    if low.startswith(RESERVED_PREFIXES) or low in {"claude", "anthropic", "claude-code"}:
        r.err(where, f"plugin name {name!r} is reserved by Claude Code")
    elif re.search(r"(^|-)(claude|anthropic|anthropics)(-|$)", low):
        r.warn(where, "plugin name contains 'claude'/'anthropic'; Claude Code warns on this")

    ap = pdir / "plugin.json"
    if ap.exists():
        data = json.loads(ap.read_text())
        extra = set(data) - AP_PLUGIN_FIELDS
        if extra:
            r.err(f"{where}/plugin.json", f"Agent Plugins manifest is closed; unknown keys {sorted(extra)}")
    if (pdir / "skills").is_dir():
        for child in sorted((pdir / "skills").iterdir()):
            if child.is_dir() and not (child / "SKILL.md").is_file():
                r.err(f"{where}/skills/{child.name}", "directory has no SKILL.md")
    if (pdir / "CLAUDE.md").exists():
        r.warn(where, "CLAUDE.md in a plugin is not loaded by Claude Code; put guidance in a skill")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    r = Report()
    plugins = sorted(d for d in (ROOT / "plugins").iterdir() if d.is_dir())
    names: dict[str, str] = {}
    for pdir in plugins:
        check_plugin(pdir, r)
        for skill_md in sorted(pdir.glob("skills/*/SKILL.md")):
            check_skill(skill_md, r)
            sname = skill_md.parent.name
            if sname in names:
                # Skills land in one shared ~/.agents/skills directory, so names must be unique repo-wide.
                r.err(str(skill_md.relative_to(ROOT)), f"skill name {sname!r} also used in {names[sname]}")
            names[sname] = pdir.name

    # Relative links in every Markdown file inside a skill (references, playbooks, ...) must resolve.
    for md in sorted(ROOT.glob("plugins/*/skills/**/*.md")):
        if md.name == "SKILL.md":
            continue  # checked in check_skill
        check_links(md, md.read_text(), str(md.relative_to(ROOT)), r)

    for w in r.warnings:
        print(f"warning: {w}")
    for e in r.errors:
        print(f"error:   {e}")
    failed = bool(r.errors) or (args.strict and bool(r.warnings))
    print(f"validate: {len(names)} skills in {len(plugins)} plugins, "
          f"{len(r.errors)} errors, {len(r.warnings)} warnings")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
