"""Shared parts of bstack's verification hooks: the check's mode, per-session state, and the
would-block log. Every hook fails open: an error allows the action and prints one line."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MODES = ("off", "observe", "enforce")
DEFAULT_MODE = "observe"
MAX_BLOCKS = 2

_TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*:")
_MODE_LINE = re.compile(r"^\s+([a-z][a-z0-9-]*):\s*'?([a-z]+)'?\s*(#.*)?$")
_FLAGS_LINE = re.compile(r"^(root|machine):\s*'(.*)'\s*$")


def warn(hook: str, msg: str) -> None:
    print(f"bstack {hook}: {msg}", file=sys.stderr)


def user_policy() -> Path:
    return Path(os.environ.get("BSTACK_POLICY") or Path.home() / ".agents" / "policy.yaml")


def repo_root(cwd: str) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def read_modes(path: Path) -> dict:
    """`checks:` from one policy file: the block map of `id: mode` lines agentfiles writes."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    modes, inside = {}, False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _TOP_KEY.match(line):
            inside = line.split("#", 1)[0].strip() == "checks:"
            continue
        m = _MODE_LINE.match(line) if inside else None
        if m and m.group(2) in MODES:
            modes[m.group(1)] = m.group(2)
        elif m and m.group(2) == "false":
            modes[m.group(1)] = "off"
    return modes


def mode(check: str, cwd: str) -> str:
    """The strictest mode the user's policy and the repo's .agents/policy.yaml set (S2)."""
    found = [read_modes(user_policy()).get(check)]
    root = repo_root(cwd)
    if root:
        found.append(read_modes(root / ".agents" / "policy.yaml").get(check))
    found = [m for m in found if m]
    return max(found, key=MODES.index) if found else DEFAULT_MODE


def identity_human() -> str | None:
    try:
        text = user_policy().read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    m = re.search(r"^\s+human:\s*'?([A-Za-z0-9][A-Za-z0-9._-]*@[a-z]+)'?\s*$", text, re.M)
    return m.group(1) if m else None


def state_path(check: str, session: str) -> Path:
    base = Path(os.environ.get("BSTACK_CHECKS_STATE") or Path.home() / ".agents" / "state" / "checks")
    return base / f"{check}-{re.sub(r'[^A-Za-z0-9-]', '_', session)}.json"


def load_state(check: str, session: str) -> dict:
    try:
        return json.loads(state_path(check, session).read_text())
    except (OSError, ValueError):
        return {}


def save_state(check: str, session: str, state: dict) -> None:
    path = state_path(check, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def transcript_entries(path: str) -> list:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def session_model(entries: list) -> str:
    for e in reversed(entries):
        model = (e.get("message") or {}).get("model") if isinstance(e, dict) else None
        if isinstance(model, str) and model:
            return model
    return "unknown"


def _flags_config() -> dict:
    path = Path(os.environ.get("BSTACK_FLAGS") or Path.home() / ".agents" / "flags.yaml")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    return {m.group(1): m.group(2) for m in map(_FLAGS_LINE.match, lines) if m}


def log(hook: str, check: str, outcome: str, reason: str, command: str, session: str,
        cwd: str, model: str) -> None:
    """One would-block lesson in this machine's weekly flags run (references/flags.md, S2)."""
    cfg, human = _flags_config(), identity_human()
    if not cfg.get("root") or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", cfg.get("machine", "")) or not human:
        warn(hook, f"{outcome} not logged: ~/.agents/flags.yaml or identity.human is missing")
        return
    root, machine = cfg["root"], cfg["machine"]
    actor = json.dumps({"kind": "agent", "id": f"bstack-{check}@claude-code#{session[:8]}",
                        "on_behalf_of": human, "tool": "claude-code", "model": model, "session": session})
    today = dt.datetime.now(dt.timezone.utc).date()
    monday = today - dt.timedelta(days=today.weekday())
    runs = sorted(p.name for p in (Path(root) / ".audit" / "runs").glob(f"*-flags-{machine}")
                  if re.fullmatch(rf"\d{{4}}-\d{{2}}-\d{{2}}-flags-{machine}", p.name) and p.name >= str(monday))
    try:
        if runs:
            run = runs[-1]
        else:
            run = f"{today}-flags-{machine}"
            subprocess.run(["ledger", "init", f"flags-{machine}", "--root", root, "--date", str(today),
                            "--actor", actor, "--why", "the first flag this week"],
                           capture_output=True, text=True, timeout=20, check=True)
        repo = repo_root(cwd)
        data = {"kind": "would-block", "check": check, "outcome": outcome, "reason": reason,
                "repo": repo.name if repo else "", "session": session}
        subprocess.run(["ledger", "append", "--root", root, "--run", run, "--actor", actor, "--type", "lesson",
                        "--summary", f"{check} {outcome}: {reason}",
                        "--why", f"bstack's {check} hook in {data['repo'] or 'a folder outside git'}",
                        "--evidence", command[:500], "--data", json.dumps(data)],
                       capture_output=True, text=True, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        detail = getattr(e, "stderr", "") or e
        warn(hook, f"{outcome} not logged: {str(detail).strip()[:200]}")
