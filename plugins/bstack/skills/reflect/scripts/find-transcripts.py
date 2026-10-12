#!/usr/bin/env python3
"""List recent agent session transcripts for ONE project, across Claude Code, Codex, Cursor and pi.

Usage:
    python3 find-transcripts.py --project DIR [--limit N] [--days N] [--grep TEXT]
                                [--tool claude-code|codex|cursor|pi]

--days keeps sessions modified in the last N days. --grep keeps sessions whose text contains TEXT
(case-insensitive); the recall skill uses both to scope a window and a topic.

Prints newest first: tool, modified time, path, and the first user message (truncated).
Only the given project's sessions are listed: the git root of --project (default: the current
directory), including sessions started in its subdirectories. Each candidate is confirmed by the
working directory the transcript records, or, when it records none, by the project path appearing
in it. It never lists other projects' transcripts: those are private conversations unrelated to
the task.

Locations it knows (override the homes with CLAUDE_CONFIG_DIR, CODEX_HOME, PI_CODING_AGENT_DIR):
    Claude Code  ~/.claude/projects/<path with non-alphanumerics as ->/<session>.jsonl
    Codex        ~/.codex/sessions/<yyyy>/<mm>/<dd>/*.jsonl   (newest 500, matched by recorded cwd)
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
CWD_RE = re.compile(r'"cwd"\s*:\s*("(?:[^"\\]|\\.)*")')


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


def recorded_cwds(path: Path, max_lines: int = 400) -> list[str]:
    """Every working directory the transcript records in its first lines (decoded, so non-ASCII paths compare)."""
    cwds = []
    try:
        with path.open(errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                for m in CWD_RE.finditer(line):
                    try:
                        cwds.append(json.loads(m.group(1)))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return cwds


def inside(cwd: str, root: Path) -> bool:
    return cwd == str(root) or cwd.startswith(str(root) + os.sep)


def belongs(path: Path, root: Path, require_evidence: bool) -> bool:
    """Confirm a candidate transcript is this project's.

    Directory slugs are lossy (/a/agent-kit and /a/agent_kit share one), so a slug match only
    nominates a file. A recorded cwd decides it. Without one, the file must name the project path
    itself when require_evidence is set; otherwise the exact slug match is trusted.
    """
    cwds = recorded_cwds(path)
    if cwds:
        return any(inside(c, root) for c in cwds)
    if not require_evidence:
        return True
    try:
        with path.open(errors="replace") as fh:
            head = fh.read(256 * 1024)
    except OSError:
        return False
    return str(root) in head or json.dumps(str(root))[1:-1] in head


def slug_dirs(base: Path, root: Path, normalize) -> list[tuple[Path, bool]]:
    """Directories under base whose name is the project's slug, or a subdirectory's (slug + '-...').
    Returns (dir, exact) pairs."""
    want = normalize(str(root))
    out = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        name = normalize(d.name)
        if name == want or name.startswith(want + "-"):
            out.append((d, name == want))
    return out


def claude_code(root: Path) -> list[tuple[str, Path]]:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude") / "projects"
    if not base.is_dir():
        return []
    out = []
    for d, exact in slug_dirs(base, root, slug):
        # An exact slug match with no recorded cwd is trusted: Claude Code names the folder after the path.
        out += [("claude-code", p) for p in d.glob("*.jsonl") if belongs(p, root, require_evidence=not exact)]
    return out


def codex(root: Path) -> list[tuple[str, Path]]:
    base = Path(os.environ.get("CODEX_HOME") or HOME / ".codex") / "sessions"
    if not base.is_dir():
        return []
    files = sorted(((mtime(p), p) for p in base.glob("*/*/*/*.jsonl")), reverse=True)[:500]
    return [("codex", p) for t, p in files if t is not None and any(inside(c, root) for c in recorded_cwds(p, 20))]


def cursor(root: Path) -> list[tuple[str, Path]]:
    base = HOME / ".cursor" / "projects"
    if not base.is_dir():
        return []
    norm = lambda s: slug(Path(s)).strip("-").lower()
    out = []
    for d, _ in slug_dirs(base, root, norm):
        out += [("cursor", p) for p in (d / "agent-transcripts").rglob("*.jsonl")
                if belongs(p, root, require_evidence=True)]
    return out


def pi(root: Path) -> list[tuple[str, Path]]:
    base = Path(os.environ.get("PI_CODING_AGENT_DIR") or HOME / ".pi" / "agent") / "sessions"
    if not base.is_dir():
        return []
    norm = lambda s: slug(Path(s)).strip("-").lower()
    out = []
    for d, _ in slug_dirs(base, root, norm):
        out += [("pi", p) for p in d.glob("*.jsonl") if belongs(p, root, require_evidence=True)]
    return out


def mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:   # deleted or rotated since it was listed
        return None


def contains(path: Path, needle: str) -> bool:
    needle = needle.lower()
    try:
        with path.open(errors="replace") as fh:
            return any(needle in line.lower() for line in fh)
    except OSError:
        return False


FINDERS = {"claude-code": claude_code, "codex": codex, "cursor": cursor, "pi": pi}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="List one project's recent agent transcripts.")
    ap.add_argument("--project", default=".", help="project directory (default: current directory)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--tool", choices=sorted(FINDERS))
    ap.add_argument("--days", type=float, help="only sessions modified in the last N days")
    ap.add_argument("--grep", help="only sessions whose text contains this (case-insensitive)")
    args = ap.parse_args(argv)

    root = project_root(Path(args.project).expanduser().resolve())
    found = []
    for name, finder in FINDERS.items():
        if args.tool and name != args.tool:
            continue
        found += finder(root)
    found = sorted(((t, tool, p) for tool, p in found if (t := mtime(p)) is not None), reverse=True)
    total = len(found)
    if args.days is not None:
        cutoff = datetime.now().timestamp() - args.days * 86400
        found = [f for f in found if f[0] >= cutoff]
    if args.grep:
        found = [f for f in found if contains(f[2], args.grep)]
    if not found and total:
        print(f"{total} transcripts found for {root}, none matching --days/--grep", file=sys.stderr)
        return 1
    if not found:
        print(f"no transcripts found for {root}", file=sys.stderr)
        return 1
    print(f"# project: {root}")
    for t, tool, path in found[: args.limit]:
        ts = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
        print(f"{tool}\t{ts}\t{path}\t{first_user_text(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
