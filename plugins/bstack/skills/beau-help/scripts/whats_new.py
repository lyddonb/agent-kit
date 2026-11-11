#!/usr/bin/env python3
"""Show agent-kit changes you have not seen yet.

    whats_new.py            unseen entries, then mark every entry seen (first run: the last 14 days)
    whats_new.py --peek     unseen entries, without marking them seen
    whats_new.py --days N   entries from the last N days
    whats_new.py --all      every entry
    whats_new.py --hook     Claude Code SessionStart hook: JSON, silent when nothing is new

What you have seen lives in $AGENT_KIT_STATE (default ~/.agents/state/agent-kit-seen.json),
so every tool shares it. Standard library only, Python 3.9+.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

CHANGES = Path(__file__).resolve().parent.parent / "references" / "changes.json"
FIRST_RUN_DAYS = 14


def state_path() -> Path:
    return Path(os.environ.get("AGENT_KIT_STATE") or Path.home() / ".agents" / "state" / "agent-kit-seen.json")


def load_entries() -> list:
    return json.loads(CHANGES.read_text())["entries"]


def load_seen():
    """The set of seen entry ids, or None when nothing was ever recorded."""
    try:
        return set(json.loads(state_path().read_text())["seen"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def mark_seen(entries: list) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"seen": sorted(e["id"] for e in entries)}, indent=2) + "\n")
    tmp.replace(path)


def within_days(entries: list, days: int, today: datetime.date) -> list:
    cutoff = (today - datetime.timedelta(days=days)).isoformat()
    return [e for e in entries if e["date"] >= cutoff]


def unseen(entries: list, seen, today: datetime.date) -> list:
    if seen is None:
        return within_days(entries, FIRST_RUN_DAYS, today)
    return [e for e in entries if e["id"] not in seen]


def render(entries: list) -> str:
    out = []
    for e in entries:
        out.append(f"## {e['plugin']} {e['version']} ({e['date']})")
        out += [f"- {s}" for s in e["changes"]]
        if e.get("try"):
            out.append(f"- Try: `{e['try']}`")
        out.append("")
    return "\n".join(out)


def hook_output(entries: list) -> dict:
    newest = {}
    for e in entries:  # newest first, so the first entry per plugin is its latest version
        newest.setdefault(e["plugin"], e["version"])
    names = ", ".join(f"{p} {v}" for p, v in newest.items())
    return {
        "systemMessage": f"agent-kit updated: {names}. Ask \"what's new\" for details.",
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "agent-kit changes the user has not seen yet. If the user asks what's new, "
                                 "or a change bears on their first request, summarize the relevant lines "
                                 "in plain words.\n\n" + render(entries),
        },
    }


def main(argv=None, today=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--peek", action="store_true", help="show unseen entries without marking them seen")
    mode.add_argument("--days", type=int, help="show entries from the last N days")
    mode.add_argument("--all", action="store_true", help="show every entry")
    mode.add_argument("--hook", action="store_true", help="Claude Code SessionStart hook output")
    args = ap.parse_args(argv)
    today = today or datetime.date.today()

    if args.hook:
        # A broken hook must never break session start.
        try:
            entries = load_entries()
            new = unseen(entries, load_seen(), today)
            mark_seen(entries)
        except Exception as e:  # noqa: BLE001
            print(f"whats_new: {e}", file=sys.stderr)
            return 0
        if new:
            print(json.dumps(hook_output(new)))
        return 0

    entries = load_entries()
    if args.all:
        shown = entries
    elif args.days is not None:
        shown = within_days(entries, args.days, today)
    else:
        shown = unseen(entries, load_seen(), today)
        if not args.peek:
            mark_seen(entries)
    if shown:
        print(render(shown))
        return 0
    # In Claude Code the session-start hook has usually just marked everything seen, so
    # "nothing new" alone would hide the release the user is asking about.
    recent = within_days(entries, FIRST_RUN_DAYS, today)
    print(f"Nothing new since you last looked. The last {FIRST_RUN_DAYS} days:\n" if recent else
          "Nothing new since you last looked. `--days 30` shows the last month; `--all` shows everything.")
    if recent:
        print(render(recent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
