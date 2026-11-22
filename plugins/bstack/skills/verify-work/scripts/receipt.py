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

A reliability checklist item (`.agents/checklist.json`, see references/checklist.md) is recorded
the same way, with --item in place of --spec and --criterion:

    receipt.py --run RUN_ID --actor ACTOR_JSON --item gh-call [--checklist FILE] [--not-run TEXT] [-- CMD [ARG...]]

An item whose check is a command runs that command through `sh -c`, as the committed checklist
states it, and takes no CMD. An item whose check is a question needs the CMD that answers its
probe. The entry is an ordinary `verification` entry: `data.checklist` holds what `data.receipt`
would (the item's id, the file and its hash at HEAD, the probe, the commit, the exit code), so
the ledger's format is unchanged and `ledger receipts`, which lists spec criteria, does not show
it. `ledger show` does. Prints `checklist:gh-call VERIFIED (seq 5)`.

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
BOOKKEEPING = (".audit", ".changes", ".evidence", "docs/phases", "docs/plans", "docs/DECISIONS.md", "ROADMAP.md",
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


@dataclasses.dataclass(frozen=True)
class Target:
    """What one run of this script proves: a spec criterion or a checklist item, with the file that
    states it, the key its record goes under in the entry's data, and the command to run."""
    label: str            # `P2e-C8`, or `checklist:gh-call`
    file: str             # repo path of the spec or the checklist
    kind: str             # "receipt" or "checklist": the key under `data`
    evidence_name: str
    cmd: list


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


def repo_root(args: argparse.Namespace) -> Path:
    root = Path(args.root or ".").resolve()
    top = git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise Refusal(f"{root} is not inside a git repo")
    if Path(top.stdout.strip()).resolve() != root:
        raise Refusal(f"run it from the repo root ({top.stdout.strip()}), or pass --root")
    return root


def check_run(root: Path, args: argparse.Namespace) -> None:
    if args.not_run is not None and not args.not_run.strip():
        raise Refusal("--not-run needs text saying which part of the probe did not run")
    if not (root / ".audit/runs" / args.run / "ledger.jsonl").is_file():
        raise Refusal(f"no ledger for run {args.run} at .audit/runs/{args.run}/ledger.jsonl")


def locate_item(args: argparse.Namespace, cmd: list) -> tuple[Path, Target]:
    """The checklist item as HEAD has it, and the command that checks it."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import checklist  # the script beside this one: it owns the file format

    root = repo_root(args)
    file = (root / (args.checklist or checklist.DEFAULT_FILE)).resolve()
    try:
        rel = file.relative_to(root).as_posix()
    except ValueError:
        raise Refusal(f"checklist {args.checklist} is outside the repo {root}")
    committed = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{rel}"], capture_output=True)
    if committed.returncode != 0:
        raise Refusal(f"{rel} is not committed; commit the checklist first, so the entry can name the text it checked")
    try:
        items = checklist.parse_checklist(committed.stdout.decode("utf-8", "replace"), rel)
    except checklist.Unusable as e:
        raise Refusal(f"the checklist at HEAD is not usable: {e}")
    item = next((i for i in items if i.id == args.item), None)
    if item is None:
        raise Refusal(f"{args.item!r} is not an item in {rel} at HEAD (it has: {', '.join(i.id for i in items) or 'none'})")
    if isinstance(item.check, checklist.Command):
        if cmd:
            raise Refusal(f"{item.id}'s check is a command ({item.check.command}); it runs as the checklist "
                          f"states it, so give no command after `--`")
        cmd = ["sh", "-c", item.check.command]
    elif not cmd:
        raise Refusal(f"{item.id}'s check is a question; put the command that answers its probe after `--`")
    check_run(root, args)
    return root, Target(f"checklist:{item.id}", rel, "checklist", f"checklist-{item.id}.txt", cmd)


def locate(args: argparse.Namespace, cmd: list) -> tuple[Path, Target]:
    """Validate everything that can be refused before the probe runs."""
    if not cmd:
        raise Refusal("no probe command; put it after `--`")
    root = repo_root(args)
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
    check_run(root, args)
    criterion = f"{phase}-{local}"
    return root, Target(criterion, spec, "receipt", f"{criterion.lower()}.txt", cmd)


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
    p = argparse.ArgumentParser(prog="receipt.py", usage="%(prog)s --run RUN_ID --actor ACTOR_JSON "
                                "(--spec SPEC --criterion C8 | --item ID [--checklist FILE]) "
                                "[--not-run TEXT] [--root DIR] [-- CMD [ARG...]]",
                                description="Run one criterion's probe, or one checklist item's check, and write "
                                            "its ledger entry.")
    p.add_argument("--run", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--spec")
    p.add_argument("--criterion")
    p.add_argument("--item", help="a reliability checklist item's id, in place of --spec and --criterion")
    p.add_argument("--checklist", help="the checklist file for --item (default: .agents/checklist.json)")
    p.add_argument("--not-run", dest="not_run")
    p.add_argument("--root")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    try:
        if args.item is not None and (args.spec or args.criterion):
            raise Refusal("give either --item, or --spec with --criterion, not both")
        if args.item is None and not (args.spec and args.criterion):
            raise Refusal("give --spec with --criterion, or --item for a checklist item")
        if args.checklist and args.item is None:
            raise Refusal("--checklist goes with --item")
        ledger = check_ledger()
        root, target = locate_item(args, cmd) if args.item is not None else locate(args, cmd)
        cmd, spec, criterion = target.cmd, target.file, target.label
        head = git(root, "rev-parse", "HEAD")
        if head.returncode != 0:
            raise Refusal(f"no commit to run the probe on: {head.stderr.strip()}")
        commit = head.stdout.strip()
        at_head = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{spec}"], capture_output=True, check=True)
        spec_sha = hashlib.sha256(at_head.stdout).hexdigest()
        dirty_before = dirty_tree(root, untracked=True)
        evidence = root / ".evidence" / args.run / target.evidence_name
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
                      commit=commit, exit=code, dirty=dirty, not_run=args.not_run).to_dict()
    if target.kind == "checklist":
        receipt = {"item": args.item, "file": spec, "file_sha256": spec_sha,
                   **{k: v for k, v in receipt.items() if k not in ("criterion", "spec", "spec_sha256")}}
    why = f"probe exited {code}" + (f"; not run: {args.not_run}" if args.not_run else "") + ("; tree was dirty" if dirty else "")
    append = [ledger, "append", "--run", args.run, "--actor", args.actor, "--type", "verification",
              "--summary", f"{criterion} {verdict}", "--why", why,
              f"--evidence={evidence.relative_to(root).as_posix()} sha256:{out_sha}", f"--evidence={commit}",
              f"--data={json.dumps({'verdict': verdict, target.kind: receipt})}"]
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
