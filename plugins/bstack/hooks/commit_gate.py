"""Claude Code PreToolUse hook: a `git commit` in a session that ran no verification or review
since its last commit. Observe logs it; enforce denies it twice, then lets it through and logs why."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402

CHECK = "commit-gate"
COMMIT = re.compile(r"(?:^|[;&|(`]|\$\()[ \t]*(?:(?:sudo|env|command|exec)[ \t]+)*(?:\w+=\S*[ \t]+)*"
                    r"(?:\S*/)?git(?:[ \t]+-[Cc][ \t]+\S+|[ \t]+--[\w-]+(?:=\S+)?)*[ \t]+commit(?![\w-])", re.M)
VERIFY_SKILLS = ("verify-work", "interrogate", "code-review", "review-pr", "review")
VERIFY_BASH = re.compile(r"second_opinion\.py|test_guard\.py|checklist\.py")
_QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
REASON = "no verify-work, verify-<app>, interrogate or review ran in this session since its last commit"


def is_commit(command: str) -> bool:
    """A git commit in the command's own words: quoted text and heredoc bodies are data."""
    lines, kept = command.splitlines(), []
    for line in lines:
        kept.append(line)
        if "<<" in line:
            break
    masked = _QUOTED.sub("''", "\n".join(kept))
    return bool(COMMIT.search(masked)) and "--dry-run" not in masked


def _short(name: str) -> str:
    return name.rsplit(":", 1)[-1].lstrip("/")


def _verifies(block: dict) -> bool:
    name, args = block.get("name"), block.get("input") or {}
    if name == "Skill":
        skill = _short(str(args.get("skill", "")))
        return skill in VERIFY_SKILLS or skill.startswith("verify-")
    if name in ("Agent", "Task"):
        return "review" in str(args.get("subagent_type", ""))
    if name == "Bash":
        return bool(VERIFY_BASH.search(str(args.get("command", ""))))
    return False


def _typed_command(text: str) -> bool:
    for m in re.finditer(r"<command-name>([^<]+)</command-name>", text):
        skill = _short(m.group(1).strip())
        if skill in VERIFY_SKILLS or skill.startswith("verify-"):
            return True
    return False


def verified_since_last_commit(entries: list) -> tuple[bool, str]:
    """Whether a verification finished without error after the last commit that went through,
    and that commit's id. A verification still running, or one that failed, doesn't count."""
    last, verified, commits, checks_running = "start", False, set(), set()
    for e in entries:
        content = (e.get("message") or {}).get("content") if isinstance(e, dict) else None
        if isinstance(content, str):
            verified = verified or _typed_command(content)
            continue
        for block in content or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and e.get("type") == "user":
                verified = verified or _typed_command(block.get("text", ""))
            elif kind == "tool_use" and block.get("name") == "Bash" and \
                    is_commit(str((block.get("input") or {}).get("command", ""))):
                commits.add(block.get("id"))
            elif kind == "tool_use" and _verifies(block):
                checks_running.add(block.get("id"))
            elif kind == "tool_result" and not block.get("is_error"):
                uid = block.get("tool_use_id")
                if uid in commits:
                    last, verified = uid, False
                elif uid in checks_running:
                    verified = True
    return verified, last


def decide(event: dict) -> dict | None:
    command = str((event.get("tool_input") or {}).get("command", ""))
    if event.get("tool_name") != "Bash" or not is_commit(command):
        return None
    cwd = event.get("cwd") or "."
    mode = checks.mode(CHECK, cwd)
    if mode == "off":
        return None
    entries = checks.transcript_entries(event.get("transcript_path") or "")
    verified, last = verified_since_last_commit(entries)
    if verified:
        return None
    session = str(event.get("session_id") or "unknown")
    model = checks.session_model(entries)
    if mode == "observe":
        checks.log(CHECK, CHECK, "observe", REASON, command, session, cwd, model)
        return None
    state = checks.load_state(CHECK, session)
    blocks = state.get("blocks", 0) if state.get("after") == last else 0
    if blocks >= checks.MAX_BLOCKS:
        checks.save_state(CHECK, session, {"after": last, "blocks": 0})
        checks.log(CHECK, CHECK, "let-through", f"{REASON}; let through after {blocks} stops", command,
                   session, cwd, model)
        return None
    checks.save_state(CHECK, session, {"after": last, "blocks": blocks + 1})
    checks.log(CHECK, CHECK, "deny", REASON, command, session, cwd, model)
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"bstack commit gate: {REASON}. Prove the change works first (the verify-work skill, the "
            f"repo's verify-<app> skill, or a review), then commit. This is stop {blocks + 1} of "
            f"{checks.MAX_BLOCKS}; after that the gate lets the commit through and records why."),
    }}


def main() -> int:
    try:
        out = decide(json.load(sys.stdin))
    except Exception as e:  # noqa: BLE001
        checks.warn(CHECK, f"skipped: {e}")
        return 0
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
