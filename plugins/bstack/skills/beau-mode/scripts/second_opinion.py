#!/usr/bin/env python3
"""Send one prompt to another agent CLI and return its answer. See references/second-opinion.md.

Usage:
    python3 second_opinion.py --reviewer cli:AGENT:MODEL --prompt-file FILE|- [--cwd DIR] [--timeout SECONDS] [--json]
    python3 second_opinion.py --list

Exit code 0 on an answer, 1 on any other status, 2 on bad usage.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

STDERR_LINES = 20
KILL_GRACE = 2.0


class Status(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    TIMEOUT = "timeout"
    MISSING = "missing"


@dataclass(frozen=True)
class Spec:
    agent: str
    model: str

    @classmethod
    def parse(cls, text: str) -> "Spec":
        parts = text.split(":", 2)
        if len(parts) != 3 or parts[0] != "cli" or not parts[1] or not parts[2]:
            raise ValueError(f"bad reviewer {text!r}: want cli:<agent>:<model>")
        return cls(parts[1], parts[2])

    def __str__(self) -> str:
        return f"cli:{self.agent}:{self.model}"


@dataclass(frozen=True)
class Result:
    reviewer: str
    agent: str
    model: str
    status: str
    answer: str
    seconds: float
    cost_usd: Optional[float]
    detail: str


Parsed = Tuple[Status, str, Optional[float], str]


def _load(stdout: str) -> Tuple[Optional[dict], str]:
    try:
        data = json.loads(stdout)
    except ValueError:
        return None, "output is not JSON: " + stdout.strip()[:200]
    if not isinstance(data, dict):
        return None, "output is not a JSON object"
    return data, ""


def _finish(data: dict, cost: Optional[float]) -> Parsed:
    result = data.get("result")
    if data.get("is_error") is not False:
        return Status.ERROR, "", cost, "CLI reported an error: " + str(result)[:500]
    if not isinstance(result, str):
        return Status.ERROR, "", cost, "result is not a string"
    if not result.strip():
        return Status.EMPTY, "", cost, "CLI reported success with a blank answer"
    return Status.OK, result, cost, ""


def parse_claude(returncode: int, stdout: str) -> Parsed:
    data, why = _load(stdout)
    if data is None:
        return Status.ERROR, "", None, why
    cost = data.get("total_cost_usd")
    return _finish(data, float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None)


def parse_cursor(returncode: int, stdout: str) -> Parsed:
    data, why = _load(stdout)
    if data is None:
        return Status.ERROR, "", None, why
    if data.get("type") != "result":
        return Status.ERROR, "", None, f"unexpected type {data.get('type')!r}"
    if data.get("subtype") not in (None, "success"):
        return Status.ERROR, "", None, f"unexpected subtype {data.get('subtype')!r}"
    return _finish(data, None)


def claude_argv(model: str) -> List[str]:
    return ["claude", "-p", "--model", model, "--output-format", "json", "--permission-mode", "plan",
            "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]


def cursor_argv(model: str) -> List[str]:
    return ["cursor-agent", "-p", "--model", model, "--output-format", "json", "--mode", "ask", "--trust"]


@dataclass(frozen=True)
class Adapter:
    binary: str
    argv: Callable[[str], List[str]]
    parse: Callable[[int, str], Parsed]


ADAPTERS: Dict[str, Adapter] = {
    "claude": Adapter("claude", claude_argv, parse_claude),
    "cursor-agent": Adapter("cursor-agent", cursor_argv, parse_cursor),
}


def tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-STDERR_LINES:])


def kill_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def run_cli(argv: List[str], prompt: str, cwd: str, timeout: float) -> Tuple[Optional[int], str, str]:
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                            text=True, errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(prompt, timeout=timeout)
        code: Optional[int] = proc.returncode
    except subprocess.TimeoutExpired:
        kill_group(proc.pid, signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
        code = None
    kill_group(proc.pid, signal.SIGKILL)
    return code, out, err


def second_opinion(spec: Spec, prompt: str, cwd: Optional[str], timeout: float) -> Result:
    adapter = ADAPTERS[spec.agent]
    started = time.monotonic()

    def result(status: Status, answer: str = "", cost: Optional[float] = None, detail: str = "") -> Result:
        return Result(str(spec), spec.agent, spec.model, status.value, answer,
                      round(time.monotonic() - started, 1), cost, detail)

    binary = shutil.which(adapter.binary)
    if binary is None:
        return result(Status.MISSING, detail=f"{adapter.binary} is not on PATH")
    scratch = None if cwd else tempfile.mkdtemp(prefix="second-opinion-")
    try:
        code, out, err = run_cli([binary] + adapter.argv(spec.model)[1:], prompt, cwd or scratch, timeout)
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    if code is None:
        return result(Status.TIMEOUT, detail=f"killed after {timeout:g}s\n{tail(err)}".strip())
    if code != 0:
        return result(Status.ERROR, detail=f"exit {code}\n{tail(err)}".strip())
    status, answer, cost, why = adapter.parse(code, out)
    return result(status, answer, cost, why or (tail(err) if status is not Status.OK else ""))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Send one prompt to another agent CLI and return its answer.")
    parser.add_argument("--reviewer", help="cli:<agent>:<model>")
    parser.add_argument("--prompt-file", help="file holding the prompt, or - for stdin")
    parser.add_argument("--cwd", help="directory the CLI runs in (default: a new empty folder)")
    parser.add_argument("--timeout", type=float, default=600, help="seconds before the CLI and its children are killed")
    parser.add_argument("--json", action="store_true", help="print the result object")
    parser.add_argument("--list", action="store_true", help="list supported agents and whether each is on PATH")
    args = parser.parse_args(argv)
    if args.list:
        for name, adapter in ADAPTERS.items():
            print(f"{name}: {'found' if shutil.which(adapter.binary) else 'missing'}")
        return 0
    if not args.reviewer or not args.prompt_file:
        parser.error("--reviewer and --prompt-file are required")
    try:
        spec = Spec.parse(args.reviewer)
    except ValueError as exc:
        parser.error(str(exc))
    if spec.agent not in ADAPTERS:
        parser.error(f"unknown agent {spec.agent!r}: want one of {', '.join(ADAPTERS)}")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.cwd and not os.path.isdir(args.cwd):
        parser.error(f"--cwd {args.cwd!r} is not a directory")
    try:
        if args.prompt_file == "-":
            prompt = sys.stdin.read()
        else:
            with open(args.prompt_file, encoding="utf-8") as handle:
                prompt = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        parser.error(f"cannot read the prompt: {exc}")
    res = second_opinion(spec, prompt, args.cwd, args.timeout)
    if args.json:
        print(json.dumps(asdict(res)))
    elif res.status == Status.OK.value:
        print(res.answer)
    else:
        print(f"second_opinion: {res.status}: {res.detail}", file=sys.stderr)
    return 0 if res.status == Status.OK.value else 1


if __name__ == "__main__":
    sys.exit(main())
