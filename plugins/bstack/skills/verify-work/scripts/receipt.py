#!/usr/bin/env python3
"""Run one criterion's probe and write its receipt to the run's ledger.

Usage:
    receipt.py --run RUN_ID --actor ACTOR_JSON --spec docs/phases/P2e-digest-actions.md \\
        --criterion C8 [--not-run TEXT] [--root DIR] -- CMD [ARG...]

Run it from the product repo root (or pass --root). It runs CMD there, copies its combined
stdout and stderr to the terminal and to `.evidence/<run-id>/<criterion>.txt`, and decides the
verdict from the exit code, not from anyone's prose:

    non-zero exit                      NOT VERIFIED
    exit 0 with --not-run, or a dirty  INCONCLUSIVE
      tree: a tracked file differs from HEAD before or after the probe, or an untracked file
      that git doesn't ignore exists before it (bookkeeping files don't count: see BOOKKEEPING)
    exit 0 otherwise                   VERIFIED

Then it appends a `verification` entry with a `receipt` (agent-ledger 1.1.0 or newer; see
"Receipt entries" in its S3 spec). Prints `P2e-C8 VERIFIED (seq 4)`.

The criterion and its spec must be committed: the receipt names HEAD and hashes the spec as HEAD
has it, so `check-product.py --receipts` can check both later. Ticking the box may wait or not.

Exit code: 0 when the receipt was written, whatever the verdict. 2 when it refused (nothing is
written, and the probe did not run). When `ledger append` fails, its exit code and stderr.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

VERIFIED, NOT_VERIFIED, INCONCLUSIVE = "VERIFIED", "NOT VERIFIED", "INCONCLUSIVE"
LIVE_ITEM = re.compile(r"^\s*- \[[ xX]\] \*\*([A-Z]\d+)\.\*\*")
LOCAL_ID = re.compile(r"^[A-Z](?:0|[1-9][0-9]*)$")
PHASE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
# What the Product phase playbook edits alongside a ticked box. These are records, not source, so a
# change to one neither dirties a probe nor makes its receipt stale. check-product.py has the same list.
BOOKKEEPING = (".audit", ".evidence", "docs/phases", "docs/plans", "docs/DECISIONS.md", "ROADMAP.md",
               "HUMAN_TASKS.md", "IDEAS.md")


@dataclasses.dataclass(frozen=True)
class Receipt:
    """The `receipt` object of a ledger `verification` entry (agent-ledger S3, Receipt entries)."""
    criterion: str
    spec: str
    spec_sha256: str
    probe: str
    commit: str
    exit: Optional[int]
    dirty: bool
    not_run: Optional[str] = None

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        if d["not_run"] is None:
            del d["not_run"]
        return d


def decide_verdict(exit_code: Optional[int], not_run: Optional[str], dirty: bool) -> str:
    """The three-way rule: a failed probe, an incomplete or off-commit one, or a clean pass."""
    if exit_code not in (0, None):
        return NOT_VERIFIED
    if not_run or dirty:
        return INCONCLUSIVE
    return VERIFIED


class Refusal(Exception):
    pass


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def check_ledger() -> str:
    ledger = shutil.which("ledger")
    need = "receipts need agent-ledger 1.1.0 or newer"
    if not ledger:
        raise Refusal(f"`ledger` is not on PATH; {need}")
    probe = subprocess.run([ledger, "receipts", "--help"], capture_output=True, text=True)
    if probe.returncode != 0:
        raise Refusal(f"this `ledger` has no `receipts` command; {need}")
    return ledger


def locate(args: argparse.Namespace) -> tuple[Path, str, str, str]:
    """Validate everything that can be refused before the probe runs. Returns root, spec path, phase, local id."""
    root = Path(args.root or ".").resolve()
    top = git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise Refusal(f"{root} is not inside a git repo")
    if Path(top.stdout.strip()).resolve() != root:
        raise Refusal(f"run it from the repo root ({top.stdout.strip()}), or pass --root")
    spec_file = (root / args.spec).resolve()
    if not spec_file.is_file():
        raise Refusal(f"spec file not found: {args.spec}")
    try:
        spec = spec_file.relative_to(root).as_posix()
    except ValueError:
        raise Refusal(f"spec {args.spec} is outside the repo {root}")
    phase = spec_file.name.split("-")[0]
    if not PHASE_ID.match(phase):
        raise Refusal(f"cannot read a phase id from the spec name {spec_file.name} (expected P2e-<slug>.md)")
    local = args.criterion
    if not LOCAL_ID.match(local):
        raise Refusal(f"criterion {local!r} is not an id like C8 (one capital letter, a number with no leading zero)")
    committed = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{spec}"], capture_output=True)
    if committed.returncode != 0:
        raise Refusal(f"{spec} is not committed; commit the spec first, so the receipt can name the text it checked")
    live = {m.group(1) for l in committed.stdout.decode("utf-8", "replace").splitlines() if (m := LIVE_ITEM.match(l))}
    if local not in live:
        raise Refusal(f"{local} is not a live item in {spec} at HEAD (items look like `- [ ] **{local}.**`; a struck "
                      f"item is not live, and a new criterion must be committed first)")
    if args.not_run is not None and not args.not_run.strip():
        raise Refusal("--not-run needs text saying which part of the probe did not run")
    if not (root / ".audit/runs" / args.run / "ledger.jsonl").is_file():
        raise Refusal(f"no ledger for run {args.run} at .audit/runs/{args.run}/ledger.jsonl")
    return root, spec, phase, local


def dirty_tree(root: Path, untracked: bool) -> bool:
    """Tracked files differ from HEAD outside the bookkeeping files. With `untracked`, a file git
    doesn't ignore counts too: a probe can pass because of a file that is in no commit."""
    out = git(root, "status", "--porcelain", f"--untracked-files={'normal' if untracked else 'no'}", "--", ".",
              *(f":(exclude){p}" for p in BOOKKEEPING))
    if out.returncode != 0:
        raise Refusal(f"git status failed: {out.stderr.strip()}")
    return bool(out.stdout.strip())


def run_probe(cmd: list[str], root: Path, evidence: Path) -> tuple[int, str]:
    """Run cmd at the repo root, tee its combined output to the terminal and the evidence file."""
    digest = hashlib.sha256()
    with evidence.open("wb") as f:
        try:
            proc = subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
        except OSError as e:
            msg = f"could not run {cmd[0]}: {e}\n".encode()
            f.write(msg)
            sys.stderr.write(msg.decode())
            return 127, hashlib.sha256(msg).hexdigest()
        while chunk := proc.stdout.read1(65536):
            f.write(chunk)
            digest.update(chunk)
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        code = proc.wait()
    return code, digest.hexdigest()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="receipt.py", usage="%(prog)s --run RUN_ID --actor ACTOR_JSON --spec SPEC "
                                "--criterion C8 [--not-run TEXT] [--root DIR] -- CMD [ARG...]",
                                description="Run one criterion's probe and write its ledger receipt.")
    p.add_argument("--run", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--criterion", required=True)
    p.add_argument("--not-run", dest="not_run")
    p.add_argument("--root")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    try:
        if not cmd:
            raise Refusal("no probe command; put it after `--`")
        ledger = check_ledger()
        root, spec, phase, local = locate(args)
        criterion = f"{phase}-{local}"
        head = git(root, "rev-parse", "HEAD")
        if head.returncode != 0:
            raise Refusal(f"no commit to run the probe on: {head.stderr.strip()}")
        commit = head.stdout.strip()
        at_head = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{spec}"], capture_output=True, check=True)
        spec_sha = hashlib.sha256(at_head.stdout).hexdigest()
        dirty_before = dirty_tree(root, untracked=True)
        evidence = root / ".evidence" / args.run / f"{criterion.lower()}.txt"
        try:
            evidence.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise Refusal(f"cannot write evidence under .evidence/{args.run}: {e}")
    except Refusal as e:
        print(f"receipt.py: refused: {e}", file=sys.stderr)
        return 2

    code, out_sha = run_probe(cmd, root, evidence)
    try:
        # files the probe itself leaves behind don't count; a tracked file it changed does
        dirty = dirty_before or dirty_tree(root, untracked=False)
    except Refusal:
        dirty = True  # the probe ran, so record it; a tree we can't read is not a clean one
    verdict = decide_verdict(code, args.not_run, dirty)
    receipt = Receipt(criterion=criterion, spec=spec, spec_sha256=spec_sha, probe=shlex.join(cmd),
                      commit=commit, exit=code, dirty=dirty, not_run=args.not_run)
    why = f"probe exited {code}" + (f"; not run: {args.not_run}" if args.not_run else "") + ("; tree was dirty" if dirty else "")
    append = [ledger, "append", "--run", args.run, "--actor", args.actor, "--type", "verification",
              "--summary", f"{criterion} {verdict}", "--why", why,
              f"--evidence={evidence.relative_to(root).as_posix()} sha256:{out_sha}", f"--evidence={commit}",
              f"--data={json.dumps({'verdict': verdict, 'receipt': receipt.to_dict()})}"]
    if args.root:
        append += ["--root", str(root)]
    done = subprocess.run(append, cwd=root, capture_output=True, text=True)
    if done.returncode != 0:
        sys.stderr.write(done.stderr)
        print(f"receipt.py: ledger append failed (exit {done.returncode}); no receipt written", file=sys.stderr)
        return done.returncode
    seq = re.search(r"\bseq (\d+)", done.stdout)
    print(f"{criterion} {verdict}" + (f" (seq {seq.group(1)})" if seq else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
