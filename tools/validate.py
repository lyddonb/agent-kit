#!/usr/bin/env python3
"""validate - portability lint for agent-kit skills and plugins.

Checks every plugins/*/skills/*/SKILL.md against the Agent Skills spec
(https://agentskills.io/specification) plus a few portability rules this repo
adopts so the same skill behaves the same in every client:

  errors   - break the spec, so some clients will refuse or skip the skill
  warnings - legal, but likely to behave differently across clients

It also checks every command a skill doc names for one of the kit's own scripts: the script,
the subcommand and each flag must exist (see check_commands).

Usage: python3 tools/validate.py [--strict]   (--strict turns warnings into errors)

For Claude Code specifics, CI additionally runs `claude plugin validate --strict`.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
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
GENERATED_RE = re.compile(r"^[ \t]*<!-- BEGIN GENERATED.*?^[ \t]*<!-- END GENERATED[^\n]*", re.S | re.M)
FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")
SPAN_RE = re.compile(r"`([^`\n]+)`")
SCRIPT_RE = re.compile(r"(?<![\w.-])([\w.-]+\.(?:py|sh))(?![\w.-])")
ALIAS_RE = re.compile(r"`(\w+)` below is `([^`\n]+)`")
# A quoted argument, or a placeholder such as <run-id> or <project root>: one argument, never a flag.
QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"|<[^<>|]*>")
FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")
DOC_FLAG_RE = re.compile(r"--[A-Za-z][\w-]*")  # a flag as a doc writes it, whole, so --dryRun is not read as --dry
# Words that may stand before a script that is being run. Any other word (`cat`, `ruff check`)
# means the script is that program's argument, and the flags after it are not the script's.
RUNNERS = {"python", "python3", "bash", "sh", "uv", "run", "exec", "time"}
# A stand-in for an argument (BOOKS_DIR, ARG, SPEC.md, ./path), as opposed to a word meant literally.
PLACEHOLDER_RE = re.compile(r"[A-Z0-9_]+|.*[./].*")
SH_ARM_RE = re.compile(r"^\s*([-\w=*|\s]*--[a-z][-\w=*|\s]*)\)", re.M)  # `-h|--help)`, `--repo=*)`
# The end of one command's arguments: a pipe, a redirect, a list operator, a bare `--` or a
# comment, after which the words belong to another program or to nobody.
COMMAND_END_RE = re.compile(r"\s--\s|\s#|[|;>]|&&")
# Lines a doc may name that are not one of the kit's skill scripts. Keep it under six.
COMMAND_ALLOW: set[tuple[str, str]] = set()


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
    if isinstance(desc, str) and ("<" in desc or ">" in desc):
        # claude.ai's marketplace sync rejects XML-like tags and stores the text with them stripped.
        r.err(where, "description contains '<' or '>'; claude.ai strips them. Write verify-APP, not verify-<app>")

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


# --- Commands that skill docs name -------------------------------------------------------------
#
# A skill tells an agent to run `<skill dir>/scripts/books.py summary BOOKS_DIR --json`. When the
# script, the subcommand or the flag is gone, the agent runs a command that fails. This check reads
# what each script accepts from its source and never runs one: some of them install launchd jobs.

@dataclass
class ScriptSpec:
    """What one kit script accepts. `subcommands` is None when the script has none."""
    path: Path
    flags: set[str] = field(default_factory=set)
    subcommands: dict[str, set[str]] | None = None

    def allowed(self, sub: str | None) -> set[str]:
        if self.subcommands is None:
            return self.flags
        if sub is None:  # the doc used a placeholder for the subcommand, so any subcommand's flag fits
            return self.flags.union(*self.subcommands.values())
        return self.subcommands[sub]


@dataclass
class CommandRef:
    """One place a doc names a kit script, with the words that follow it."""
    where: str
    script: str
    in_scripts_dir: bool
    args: list[str]


def _flag_literals(node: ast.AST) -> set[str]:
    return {c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and FLAG_RE.fullmatch(c.value)}


def _argparse_spec(path: Path, tree: ast.AST) -> ScriptSpec:
    """Follow the parser variables in source order, since one name is often rebound per subcommand."""
    spec = ScriptSpec(path, flags={"--help"})
    owner: dict[str, str | None] = {}  # variable -> subcommand name, or None for the top parser
    holders: set[str] = set()          # variables bound to add_subparsers()
    calls = sorted((n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.Expr))
                    and isinstance(n.value, ast.Call) and isinstance(n.value.func, (ast.Attribute, ast.Name))),
                   key=lambda n: (n.lineno, n.col_offset))
    for stmt in calls:
        call, func = stmt.value, stmt.value.func
        method = func.attr if isinstance(func, ast.Attribute) else func.id
        recv = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else None
        bound = stmt.targets[0] if isinstance(stmt, ast.Assign) else getattr(stmt, "target", None)
        target = bound.id if isinstance(bound, ast.Name) else None
        if method == "ArgumentParser" and target:
            owner[target] = None
        elif method == "add_subparsers" and target and recv in owner:
            holders.add(target)
            spec.subcommands = spec.subcommands or {}
        elif method == "add_parser" and recv in holders:
            name = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None
            if not isinstance(name, str) or not target:
                raise ValueError(f"line {stmt.lineno}: add_parser needs a literal name and a variable")
            spec.subcommands[name] = {"--help"}
            owner[target] = name
            for kw in call.keywords:
                if kw.arg == "aliases":
                    for alias in ast.literal_eval(kw.value):
                        spec.subcommands[alias] = spec.subcommands[name]
        elif method in ("add_mutually_exclusive_group", "add_argument_group") and target and recv in owner:
            owner[target] = owner[recv]
        elif method == "add_argument":
            if recv not in owner:
                raise ValueError(f"line {stmt.lineno}: add_argument on {recv!r}, which this lint can't "
                                 "trace to a parser. Bind the parser to a variable in the same function")
            if not all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in call.args):
                raise ValueError(f"line {stmt.lineno}: add_argument with a name that is not a string literal")
            flags = {a.value for a in call.args if a.value.startswith("--")}
            if any(kw.arg == "action" and "BooleanOptionalAction" in ast.dump(kw.value) for kw in call.keywords):
                flags |= {"--no-" + f[2:] for f in flags}
            (spec.flags if owner[recv] is None else spec.subcommands[owner[recv]]).update(flags)
    return spec


def script_spec(path: Path) -> ScriptSpec:
    """Read a script's subcommands and flags from its source. Raises ValueError when it can't."""
    text = path.read_text()
    if path.suffix == ".sh":
        # The flags are the case arms. A script with none may test "$1" some other way, so every
        # flag on a line of code counts.
        arms = SH_ARM_RE.findall(text) or [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
        return ScriptSpec(path, flags={f for arm in arms for f in FLAG_RE.findall(arm)})
    tree = ast.parse(text)
    if any(isinstance(n, ast.Attribute) and n.attr == "add_argument" for n in ast.walk(tree)):  # argparse
        return _argparse_spec(path, tree)
    # A script that reads argv itself: its flags are the literals in the functions that take argv.
    flags: set[str] = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and any(a.arg == "argv" for a in fn.args.args):
            flags |= _flag_literals(fn)
    return ScriptSpec(path, flags=flags)


def _commands(text: str):
    """Yield (line number, command text): each inline code span, and each line of a fenced block
    with its backslash continuations joined."""
    fence, pending, start = None, "", 0
    for no, line in enumerate(text.split("\n"), 1):
        m = FENCE_LINE_RE.match(line)
        if m and fence in (None, m.group(1)):  # a ``` line inside a ~~~ block is text
            fence, pending = (None if fence else m.group(1)), ""
        elif fence:
            start = start if pending else no
            pending += line.rstrip()
            if pending.endswith("\\"):
                pending = pending[:-1] + " "
            else:
                yield start, pending
                pending = ""
        else:
            for m in SPAN_RE.finditer(line):
                yield no, m.group(1)


def command_refs(md: Path, where: str) -> list[CommandRef]:
    # Generated blocks repeat a snippet, which is checked where it is written.
    text = GENERATED_RE.sub(lambda m: "\n" * m.group().count("\n"), md.read_text())
    aliases = dict(ALIAS_RE.findall(text))  # "`Q` below is `uv run ... quality.py`"
    refs = []
    for no, command in _commands(text):
        first, _, rest = command.partition(" ")
        if first in aliases and rest:
            command = f"{aliases[first]} {rest}"
        found = list(SCRIPT_RE.finditer(command))
        for m, nxt in zip(found, found[1:] + [None]):
            # Only the words since the last separator can be running this script: `cd DIR && python3 x.py`.
            before = COMMAND_END_RE.split(QUOTED_RE.sub("ARG", command[:m.start()]))[-1].rpartition("$(")[2]
            # `./scripts/test.sh` is the project's own script, not one a skill ships.
            in_scripts_dir = before.endswith("scripts/") and not before.endswith("./scripts/")
            *runners, path = (before + "x").split()
            run = all(w in RUNNERS or not w.isalpha() for w in runners) and (in_scripts_dir or "/" not in path)
            tail = QUOTED_RE.sub(" ARG ", command[m.end():nxt.start() if nxt else len(command)])
            tail = COMMAND_END_RE.split(" " + tail + " ", maxsplit=1)[0]
            # A script that another program reads, or a file of the same name elsewhere, has no arguments to check.
            refs.append(CommandRef(f"{where}:{no}", m.group(1), in_scripts_dir, tail.split() if run else []))
    return refs


def check_ref(ref: CommandRef, specs: dict[str, ScriptSpec], r: Report):
    spec = specs.get(ref.script)
    if spec is None:
        if ref.in_scripts_dir:
            r.err(ref.where, f"names scripts/{ref.script}, which no skill ships")
        return
    args = [w.lstrip("[(") for w in ref.args]
    sub, at = None, len(args)
    if spec.subcommands is not None:
        # The subcommand is the first bare word. A word right after one of the script's own
        # top-level flags may be that flag's value.
        for i, word in enumerate(args):
            if word.startswith("-") or (i and args[i - 1] in spec.flags):
                continue
            if not PLACEHOLDER_RE.fullmatch(word.rstrip("]")):
                sub, at = word.rstrip("]"), i
                if sub not in spec.subcommands:
                    r.err(ref.where, f"runs `{ref.script} {sub}`, but {ref.script} has no {sub!r} subcommand "
                                     f"(it has {', '.join(sorted(spec.subcommands))})")
                    return
            break
    for i, word in enumerate(args):
        m = DOC_FLAG_RE.match(word)
        if not m:
            continue
        # argparse takes the script's own flags before the subcommand and the subcommand's after it.
        allowed = spec.flags if sub and i < at else spec.subcommands[sub] if sub else spec.allowed(None)
        if m.group() not in allowed:
            target = f"{ref.script} {sub}" if sub and i > at else ref.script
            place = " before the subcommand" if sub and i < at else ""
            r.err(ref.where, f"passes {m.group()} to `{target}`{place}, which does not accept it there "
                             f"(it accepts {', '.join(sorted(allowed)) or 'no flags'})")


def check_commands(root: Path, r: Report) -> int:
    """Every kit script, subcommand and flag a skill doc names must exist. Returns how many it checked."""
    specs: dict[str, ScriptSpec] = {}
    for path in sorted(root.glob("plugins/*/skills/*/scripts/*")):
        if path.suffix not in (".py", ".sh"):
            continue
        rel = str(path.relative_to(root))
        if path.name in specs:
            # A doc names a script by file name alone, so two skills can't ship the same one.
            r.err(rel, f"script name {path.name!r} is also used by {specs[path.name].path.relative_to(root)}")
            continue
        try:
            specs[path.name] = script_spec(path)
        except (ValueError, SyntaxError) as e:
            r.err(rel, f"can't read this script's arguments: {e}")
    unreadable = {p.name for p in root.glob("plugins/*/skills/*/scripts/*")} - set(specs)
    checked = 0
    docs = sorted({*root.glob("plugins/*/skills/**/*.md"), *root.glob("plugins/*/snippets/*.md")})
    for md in docs:
        for ref in command_refs(md, str(md.relative_to(root))):
            if (ref.where.rsplit(":", 1)[0], ref.script) in COMMAND_ALLOW or ref.script in unreadable:
                continue
            checked += ref.script in specs
            check_ref(ref, specs, r)
    return checked


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

    commands = check_commands(ROOT, r)

    for w in r.warnings:
        print(f"warning: {w}")
    for e in r.errors:
        print(f"error:   {e}")
    failed = bool(r.errors) or (args.strict and bool(r.warnings))
    print(f"validate: {len(names)} skills in {len(plugins)} plugins, {commands} script commands, "
          f"{len(r.errors)} errors, {len(r.warnings)} warnings")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
