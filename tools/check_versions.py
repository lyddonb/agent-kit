#!/usr/bin/env python3
"""Fail when a plugin's files changed since BASE but its version in kit.yaml did not.

Claude Code re-fetches an installed plugin only when its version changes, so an
unbumped change never reaches people who installed from the marketplace.

    python3 tools/check_versions.py --base origin/main
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def versions(kit_text: str) -> dict[str, str]:
    kit = yaml.safe_load(kit_text) or {}
    defaults = kit.get("defaults") or {}
    return {p["name"]: str({**defaults, **p}.get("version")) for p in kit.get("plugins") or []}


def problems(base: str, root: Path = ROOT) -> list[str]:
    merge_base = git(root, "merge-base", base, "HEAD").strip()
    old = versions(git(root, "show", f"{merge_base}:kit.yaml"))
    new = versions((root / "kit.yaml").read_text())
    changed = git(root, "diff", "--name-only", merge_base, "--", "plugins/").split()
    touched = sorted({path.split("/")[1] for path in changed if path.count("/") >= 2})
    out = []
    for name in touched:
        if name in old and name in new and old[name] == new[name]:
            files = [p for p in changed if p.startswith(f"plugins/{name}/")]
            out.append(f"plugin '{name}' changed ({len(files)} file(s), e.g. {files[0]}) but its version "
                       f"is still {new[name]}. Bump `version` for {name} in kit.yaml, then run make gen.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main", help="ref to compare against (default: origin/main)")
    found = problems(ap.parse_args().base)
    for p in found:
        print(f"error: {p}", file=sys.stderr)
    print(f"versions: {len(found)} plugin(s) changed without a version bump")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
