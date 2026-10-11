#!/usr/bin/env python3
"""List recent agent session transcripts for ONE project, across Claude Code, Codex, Cursor and pi.

Usage:
    python3 find-transcripts.py [--project DIR] [--limit N] [--tool claude-code|codex|cursor|pi]

Prints newest first: tool, modified time, path, and the first user message (truncated).
Only the given project's sessions are listed (default: the current directory's git root).
It never lists other projects' transcripts: those are private conversations unrelated to
the task.

Locations it knows (override the homes with CLAUDE_CONFIG_DIR, CODEX_HOME, PI_CODING_AGENT_DIR):
    Claude Code  ~/.claude/projects/<path with non-alphanumerics as ->/<session>.jsonl
    Codex        ~/.codex/sessions/<yyyy>/<mm>/<dd>/*.jsonl   (matched by the cwd in its first lines)
    Cursor       ~/.cursor/projects/<workspace>/agent-transcripts/**.jsonl
    pi           ~/.pi/agent/sessions/--<path>--/*.jsonl
Exit code 1 when nothing is found.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()


def project_root(start: Path) -> Path:
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start


def slug(path: Path, sep: str = "-") -> str:
    return re.sub(r"[^A-Za-z0-9]", sep, str(path))


def first_user_text(path: Path) -> str:
    """Best effort: the first user-authored text in a JSONL transcript."""
    try:
        with path.open(errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 400:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = _user_text(rec).strip()
                if text and not text.startswith("<"):   # skip injected system/context blocks
                    return " ".join(text.split())[:100]
    except OSError:
        pass
    return ""


def _user_text(rec) -> str:
    if not isinstance(rec, dict):
        return ""
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else None
    for cand in (msg, payload):
        if not isinstance(cand, dict):
            continue
        if cand.get("role") != "user" and rec.get("type") != "user":
            continue
        content = cand.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    return part["text"]
    return ""


def claude_code(root: Path) -> list[tuple[str, Path]]:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude") / "projects" / slug(root)
    return [("claude-code", p) for p in base.glob("*.jsonl")] if base.is_dir() else []


def codex(root: Path) -> list[tuple[str, Path]]:
    base = Path(os.environ.get("CODEX_HOME") or HOME / ".codex") / "sessions"
    out = []
    if not base.is_dir():
        return out
    needle = json.dumps(str(root))[1:-1]
    for p in sorted(base.glob("*/*/*/*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)[:500]:
        try:
            head = p.open(errors="replace").read(8192)
        except OSError:
            continue
        if needle in head:
            out.append(("codex", p))
    return out


def cursor(root: Path) -> list[tuple[str, Path]]:
    base = HOME / ".cursor" / "projects"
    if not base.is_dir():
        return []
    want = slug(root).strip("-").lower()
    out = []
    for proj in base.iterdir():
        if proj.is_dir() and slug(proj.name).strip("-").lower() == want:
            out += [("cursor", p) for p in (proj / "agent-transcripts").rglob("*.jsonl")]
    return out


def pi(root: Path) -> list[tuple[str, Path]]:
    base = Path(os.environ.get("PI_CODING_AGENT_DIR") or HOME / ".pi" / "agent") / "sessions"
    if not base.is_dir():
        return []
    want = slug(root).strip("-").lower()
    out = []
    for d in base.iterdir():
        if d.is_dir() and slug(d.name).strip("-").lower() == want:
            out += [("pi", p) for p in d.glob("*.jsonl")]
    return out


FINDERS = {"claude-code": claude_code, "codex": codex, "cursor": cursor, "pi": pi}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="List one project's recent agent transcripts.")
    ap.add_argument("--project", default=".", help="project directory (default: current directory)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--tool", choices=sorted(FINDERS))
    args = ap.parse_args(argv)

    root = project_root(Path(args.project).expanduser().resolve())
    found = []
    for name, finder in FINDERS.items():
        if args.tool and name != args.tool:
            continue
        found += finder(root)
    found.sort(key=lambda t: t[1].stat().st_mtime, reverse=True)
    if not found:
        print(f"no transcripts found for {root}", file=sys.stderr)
        return 1
    print(f"# project: {root}")
    for tool, path in found[: args.limit]:
        ts = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"{tool}\t{ts}\t{path}\t{first_user_text(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
