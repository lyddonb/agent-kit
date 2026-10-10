#!/usr/bin/env bash
# Print a compact snapshot of git state for a handoff note.
# Read-only: never modifies the repository.
set -u

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not inside a git repository: $(pwd)"
  exit 0
fi

echo "## Repository"
echo "root:     $(git rev-parse --show-toplevel)"
echo "branch:   $(git branch --show-current 2>/dev/null || echo '(detached)')"
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
if [ -n "$upstream" ]; then
  read -r behind ahead < <(git rev-list --left-right --count "$upstream"...HEAD 2>/dev/null || echo "0 0")
  echo "upstream: $upstream (ahead $ahead, behind $behind)"
else
  echo "upstream: none"
fi

echo
echo "## Uncommitted changes"
status=$(git status --short)
if [ -n "$status" ]; then echo "$status" | head -50; else echo "(clean)"; fi

echo
echo "## Recent commits"
git log --oneline --decorate -10 2>/dev/null || echo "(no commits)"

stashes=$(git stash list 2>/dev/null | head -5)
if [ -n "$stashes" ]; then
  echo
  echo "## Stashes"
  echo "$stashes"
fi
