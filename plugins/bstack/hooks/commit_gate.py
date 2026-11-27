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
COMMIT = re.compile(r"(?:^|[;&|(`]|\$\()\s*(?:\w+=\S*\s+)*git(?:\s+-[Cc]\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+commit(?![\w-])")
VERIFY_SKILLS = ("verify-work", "interrogate", "code-review", "review-pr", "review")
VERIFY_BASH = re.compile(r"second_opinion\.py|test_guard\.py|checklist\.py")
REASON = "no verify-work, verify-<app>, interrogate or review ran in this session since its last commit"


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
    """Whether a verification ran after the last commit that went through, and that commit's id."""
    results, uses = {}, []
    for e in entries:
        content = (e.get("message") or {}).get("content") if isinstance(e, dict) else None
        if isinstance(content, str):
            uses.append(("text", content))
            continue
        for block in content or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses.append(("use", block))
            elif block.get("type") == "tool_result":
                results[block.get("tool_use_id")] = bool(block.get("is_error"))
            elif block.get("type") == "text" and e.get("type") == "user":
                uses.append(("text", block.get("text", "")))
    last, verified = "start", False
    for kind, item in uses:
        if kind == "text":
            verified = verified or _typed_command(item)
        elif item.get("name") == "Bash" and COMMIT.search(str((item.get("input") or {}).get("command", ""))):
            if results.get(item.get("id")) is False:
                last, verified = item.get("id") or last, False
        elif _verifies(item):
            verified = True
    return verified, last


def decide(event: dict) -> dict | None:
    command = str((event.get("tool_input") or {}).get("command", ""))
    if event.get("tool_name") != "Bash" or not COMMIT.search(command):
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
