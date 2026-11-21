"""Shared fixtures for the receipt tests: a real temp git repo and `ledger` wrappers on PATH."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECEIPT_PY = ROOT / "plugins/bstack/skills/verify-work/scripts/receipt.py"
CHECK_PRODUCT_PY = ROOT / "plugins/bstack/skills/scaffold-product/scripts/check-product.py"
DEBRIEF_PY = ROOT / "plugins/bstack/skills/debrief/scripts/debrief.py"

# The real-ledger tests need agent-ledger 1.1.0 or newer (it has `receipts`). Point AGENT_LEDGER_SRC at
# its `src` folder; without it those tests skip, and the stub-ledger tests still run.
LEDGER_SRC = Path(os.environ["AGENT_LEDGER_SRC"]) if os.environ.get("AGENT_LEDGER_SRC") else None
ACTOR = json.dumps({"kind": "agent", "id": "tester@test#1", "on_behalf_of": "tester@github",
                    "tool": "test", "model": "none", "session": "s1"})
SPEC = "docs/phases/P2e-digest-actions.md"
SPEC_TEXT = """# P2e. Digest actions

## Criteria

- [ ] **C8.** Digest actions work. Probe: `./probe.sh`.
- [ ] **C9.** Another one. Probe: `./probe.sh`.
- ~~**C4.**~~ struck, no longer a criterion.
- [ ] **C08.** Leading zero. Probe: none.

## Anti-criteria

- [x] **A2.** Never twice. Probe: `./probe.sh`. Evidence: old.
"""


def real_ledger_available() -> bool:
    if LEDGER_SRC is None or not LEDGER_SRC.is_dir():
        return False
    env = dict(os.environ, PYTHONPATH=str(LEDGER_SRC))
    done = subprocess.run([sys.executable, "-m", "agent_ledger.cli", "receipts", "--help"], env=env,
                          capture_output=True)
    return done.returncode == 0


def _wrapper(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ledger"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return directory


def real_ledger_bin(base: Path) -> Path:
    return _wrapper(base / "real", f'PYTHONPATH="{LEDGER_SRC}" exec "{sys.executable}" -m agent_ledger.cli "$@"\n')


def stub_ledger_bin(base: Path, receipts_rc: int = 0, append_rc: int = 0, verify_rc: int = 0) -> Path:
    """A `ledger` that only answers the way a test tells it to."""
    return _wrapper(base / f"stub-{receipts_rc}-{append_rc}-{verify_rc}", f"""case "$1" in
  receipts) exit {receipts_rc} ;;
  verify) exit {verify_rc} ;;
  append) echo "stub: append refused" >&2; exit {append_rc} ;;
esac
exit 0
""")


def bare_bin(base: Path) -> Path:
    """A PATH with git and nothing else, so `ledger` is not found."""
    d = base / "bare"
    d.mkdir(parents=True, exist_ok=True)
    for tool in ("git", "sh"):
        if not (d / tool).exists():
            (d / tool).symlink_to(shutil.which(tool))
    return d


def run(cmd, cwd, path_dir: Path) -> subprocess.CompletedProcess:
    """Run with PATH = path_dir plus the system tools, so a `ledger` installed on this machine never leaks in."""
    path = str(path_dir) if path_dir.name == "bare" else os.pathsep.join([str(path_dir), "/usr/bin", "/bin"])
    env = dict(os.environ, PATH=path)
    env.pop("PYTHONPATH", None)
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert done.returncode == 0, f"git {args}: {done.stderr}"
    return done.stdout.strip()


def new_repo(base: Path, files: dict) -> Path:
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    commit(repo, "base")
    return repo


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tmpdir(test) -> Path:
    d = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, d, True)
    return d.resolve()
