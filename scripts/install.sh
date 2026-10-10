#!/usr/bin/env bash
# install.sh - link agent-kit skills into the shared Agent Skills directory.
#
# This is the zero-dependency path for tools without a plugin marketplace
# (OpenCode, pi without packages, Amp, Gemini CLI, ...). It symlinks every
# plugins/*/skills/<skill> directory into one skills directory.
#
#   ~/.agents/skills   is read by Codex, Cursor, OpenCode, pi, and others.
#   ~/.claude/skills   is read by Claude Code (but Cursor and OpenCode ALSO read
#                      it, so linking to both directories shows duplicates there).
#
# For Claude Code we recommend the marketplace instead:
#   /plugin marketplace add lyddonb/agent-kit
#
# Usage:
#   scripts/install.sh                 # link into ~/.agents/skills
#   scripts/install.sh --claude        # also link into ~/.claude/skills
#   scripts/install.sh --project DIR   # link into DIR/.agents/skills instead
#   scripts/install.sh --uninstall     # remove links this script created
#   scripts/install.sh --dry-run       # show what would happen
#
# Want third-party skills, profiles, or pinning? Use agentfiles instead.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
targets=("$HOME/.agents/skills")
uninstall=false
dry=false

while [ $# -gt 0 ]; do
  case "$1" in
    --claude) targets+=("$HOME/.claude/skills") ;;
    --project)
      [ $# -ge 2 ] || { echo "--project needs a directory" >&2; exit 2; }
      targets=("$(cd "$2" && pwd)/.agents/skills"); shift ;;
    --uninstall) uninstall=true ;;
    --dry-run) dry=true ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

run() { if $dry; then echo "[dry-run] $*"; else "$@"; fi; }

shopt -s nullglob
skills=("$REPO_ROOT"/plugins/*/skills/*/)
if [ ${#skills[@]} -eq 0 ]; then echo "no skills found under $REPO_ROOT/plugins" >&2; exit 1; fi

for dest in "${targets[@]}"; do
  echo "==> $dest"
  run mkdir -p "$dest"
  for src in "${skills[@]}"; do
    src="${src%/}"
    name="$(basename "$src")"
    link="$dest/$name"
    if $uninstall; then
      if [ -L "$link" ] && [ "$(readlink "$link")" = "$src" ]; then
        run rm "$link"; echo "  removed $name"
      fi
      continue
    fi
    if [ -L "$link" ]; then
      if [ "$(readlink "$link")" = "$src" ]; then echo "  ok      $name"; continue; fi
      echo "  skip    $name (already linked to $(readlink "$link"))"; continue
    fi
    if [ -e "$link" ]; then echo "  skip    $name (a real directory exists; not touching it)"; continue; fi
    run ln -s "$src" "$link"; echo "  linked  $name"
  done
done

$uninstall || cat <<'EOF'

Done. Restart your agent to pick up new skills.
Claude Code users: prefer `/plugin marketplace add lyddonb/agent-kit` over --claude.
EOF
