"""Claude Code Stop hook: when the agent finishes, run the cheap checks each trusted repo it
changed lists in .agents/checks.yaml, as its base branch has the file, so the change being judged
can't rewrite them. Observe logs a failure; enforce sends the failing output back to the agent
twice, then lets the stop through and logs why."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402

CHECK = "stop-checks"
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
DEFAULT_TIMEOUT = 120
BUDGET_S = 540
TAIL_LINES = 40
_QUOTED = re.compile(r"""'((?:[^']|'')*)'|"((?:[^"\\]|\\.)*)\"""")


def _strings(text: str) -> list:
    return [s.replace("''", "'") if s or not d else json.loads(f'"{d}"') for s, d in _QUOTED.findall(text)]


def _item(text: str) -> list:
    text = text.strip()
    return _strings(text) if text[:1] in ("'", '"') else [text]


def base_commit(root: Path) -> tuple[str, str] | None:
    """Origin's default branch as last fetched, as (name, commit): origin/HEAD, else origin/main or
    origin/master."""
    for ref in ("origin/HEAD", "origin/main", "origin/master"):
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", f"refs/remotes/{ref}"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return ref, out.stdout.strip()
    return None


def read_config(root: Path) -> tuple[list, int, tuple[str, str]] | None:
    """The base branch's `.agents/checks.yaml` and the base it came from, or None when the repo has
    no base to read it from."""
    base = base_commit(root)
    if not base:
        return None
    out = subprocess.run(["git", "-C", str(root), "show", f"{base[1]}:.agents/checks.yaml"],
                         capture_output=True, timeout=10)
    try:
        commands, timeout = parse_config(out.stdout.decode("utf-8")) if out.returncode == 0 else ([], DEFAULT_TIMEOUT)
    except UnicodeDecodeError:
        commands, timeout = [], DEFAULT_TIMEOUT
    return commands, timeout, base


def parse_config(text: str) -> tuple[list, int]:
    """`stop:` (a flow list, or a block list of quoted or bare commands) and `timeout_s`."""
    commands, timeout, in_stop = [], DEFAULT_TIMEOUT, False
    for line in text.splitlines():
        bare = line.split(" #", 1)[0].rstrip()
        if not bare.strip() or bare.lstrip().startswith("#"):
            continue
        if re.match(r"^stop:", bare):
            rest = bare[5:].strip()
            commands += _strings(rest) if rest.startswith("[") else []
            in_stop = not rest
        elif re.match(r"^timeout_s:\s*\d+$", bare):
            timeout, in_stop = int(bare.split(":")[1]), False
        elif in_stop and re.match(r"^\s+-\s", bare):
            commands += _item(bare.lstrip()[1:])
        else:
            in_stop = False
    return [c for c in commands if c.strip()], timeout


def fingerprint(root: Path) -> str:
    """HEAD, the status, the diff and every untracked file's content."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10).stdout
    digest = hashlib.sha256()
    for part in (git("rev-parse", "HEAD"), git("status", "--porcelain=v1", "-z"), git("diff", "HEAD")[:2_000_000]):
        digest.update(part + b"\0")
    for name in git("ls-files", "-o", "--exclude-standard", "-z").split(b"\0")[:500]:
        try:
            digest.update(name + b"\0" + (root / name.decode()).read_bytes()[:1_000_000])
        except (OSError, UnicodeDecodeError):
            continue
    return digest.hexdigest()


def touched_roots(entries: list, cwd: str) -> dict:
    """Each repo the session changed: one holding a file it edited, or cwd's repo when it ran a
    command there (a Bash command can change files without saying so)."""
    roots, home = {}, checks.repo_root(cwd)
    for e in entries:
        content = (e.get("message") or {}).get("content") if isinstance(e, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            args = block.get("input") or {}
            if block.get("name") in EDITS and (args.get("file_path") or args.get("notebook_path")):
                path = Path(str(args.get("file_path") or args.get("notebook_path")))
                path = path if path.is_absolute() else Path(cwd) / path
                root = checks.repo_root(str(path.parent if path.parent.exists() else cwd))
                if root:
                    roots[str(root)] = root
            elif block.get("name") == "Bash" and home:
                roots[str(home)] = home
    return roots


def run_checks(root: Path, commands: list, timeout: int, deadline: float) -> tuple[str, str] | None:
    """The first command that fails and the tail of its output, or None when all pass."""
    for command in commands:
        left = int(deadline - time.monotonic())
        if left <= 0:
            return command, "not run: the hook's time budget ran out"
        limit = min(timeout, left)
        try:
            out = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True,
                                 timeout=limit, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return command, f"timed out after {limit}s"
        if out.returncode != 0:
            text = (out.stdout + out.stderr).rstrip().splitlines()
            return command, "\n".join(text[-TAIL_LINES:])
    return None


def judge(root: Path, mode: str, session: str, entries: list, cwd: str, deadline: float) -> str | None:
    """The send-back text for one repo, or None."""
    if not checks.trusted(root):
        return None
    config = read_config(root)
    if config is None:
        if (root / ".agents" / "checks.yaml").exists():
            checks.warn(CHECK, f"{root}: no base branch (origin/HEAD, origin/main or origin/master), so its checks didn't run")
        return None
    commands, timeout, (base_name, base_sha) = config
    if not commands:
        return None
    key = f"{session}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}"
    state = checks.load_state(CHECK, key)
    now = f"{fingerprint(root)}:{base_sha}"
    blocks = state.get("blocks", 0)
    if blocks == 0 and state.get("tree") == now:
        return None
    failed = run_checks(root, commands, timeout, deadline)
    if failed is None:
        checks.save_state(CHECK, key, {"tree": now, "blocks": 0})
        return None
    command, tail = failed
    reason = f"`{command}` (from {base_name} {base_sha[:7]}) failed in {root.name}"
    model = checks.session_model(entries)
    if mode == "observe" or blocks >= checks.MAX_BLOCKS:
        outcome = "observe" if mode == "observe" else "let-through"
        note = reason if outcome == "observe" else f"{reason}; let through after {blocks} send-backs"
        checks.save_state(CHECK, key, {"tree": now, "blocks": 0})
        checks.log(CHECK, CHECK, outcome, note, command, session, str(root), model)
        return None
    checks.save_state(CHECK, key, {"tree": now, "blocks": blocks + 1})
    checks.log(CHECK, CHECK, "deny", reason, command, session, str(root), model)
    return (f"{reason} (send-back {blocks + 1} of {checks.MAX_BLOCKS}). Last lines of its output:\n{tail}")


def decide(event: dict) -> dict | None:
    deadline = time.monotonic() + BUDGET_S
    cwd = event.get("cwd") or "."
    session = str(event.get("session_id") or "unknown")
    entries = checks.transcript_entries(event.get("transcript_path") or "")
    backs = []
    for root in touched_roots(entries, cwd).values():
        mode = checks.mode(CHECK, str(root))
        if mode != "off":
            text = judge(root, mode, session, entries, cwd, deadline)
            if text:
                backs.append(text)
    if not backs:
        return None
    return {"decision": "block", "reason": "bstack stop checks: fix this before you finish.\n" + "\n\n".join(backs)}


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
