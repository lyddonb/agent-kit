#!/usr/bin/env bash
# Weekly Mac job: price this Mac's Claude Code logs into the books and hand them to the weekly brief PR.
#
# The scheduled cloud run that writes the brief can't read ~/.claude/projects, so this job runs on
# the Mac (launchd, Sundays before the cloud run). It pushes its ledger rows to the open brief PR's
# branch, or opens a brief PR on a new cfo/brief-YYYY-MM-DD branch. The cloud run already adds its
# commit to an open brief PR, so each week still ends in one PR. It never pushes to main, merges or
# force-pushes.
#
# Usage:
#   weekly-claude-code.sh --install | --uninstall | --status | --run-now   # manage the launchd agent
#   weekly-claude-code.sh [--repo OWNER/NAME] [--dry-run]                  # what the agent runs
#   weekly-claude-code.sh [--repo OWNER/NAME] --print-plist
# --repo defaults to the GitHub remote of the books checkout in $CFO_BOOKS.
#
# Needs git, gh (logged in) and uv. Test hooks: CFO_CLONE_URL (clone from here instead of GitHub),
# CFO_LOGS (Claude Code logs dir), CFO_CLAUDE_SETTINGS (settings file --install edits), CFO_JOB_PATH (the agent's PATH), CFO_PYTHON (a Python 3.10+ instead of uv), CFO_TZ (default America/Denver).
set -Eeuo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SELF="$HERE/$(basename "$0")"
BOOKS_PY="$HERE/books.py"
LABEL=dev.agent-kit.cfo-claude-code
TZNAME=${CFO_TZ:-America/Denver}
REPO=""
DRY_RUN=0
PRINT_PLIST=0

PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGFILE="$HOME/Library/Logs/cfo-claude-code.log"
JOB_PATH=${CFO_JOB_PATH:-/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin}
DOMAIN="gui/$(id -u)"
ACTION=run

usage() { sed -n '/^# Usage:/,/^# --repo/p' "$SELF" | sed 's/^# \{0,3\}//' >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO=${2:-}; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --print-plist) PRINT_PLIST=1; shift ;;
    --install) ACTION=install; shift ;;
    --uninstall) ACTION=uninstall; shift ;;
    --status) ACTION=status; shift ;;
    --run-now) ACTION=run-now; shift ;;
    *) usage ;;
  esac
done
if [ -z "$REPO" ] && [ "$ACTION" != uninstall ] && [ "$ACTION" != status ] && [ "$ACTION" != run-now ]; then
  [ -n "${CFO_BOOKS:-}" ] || { echo "No --repo given and CFO_BOOKS isn't set. Pass --repo OWNER/NAME, or set CFO_BOOKS to the books checkout." >&2; exit 2; }
  BOOKS_DIR=$CFO_BOOKS
  url=$(git -C "$BOOKS_DIR" remote get-url origin 2>/dev/null) \
    || { echo "No --repo given and no git remote in $BOOKS_DIR. Pass --repo OWNER/NAME." >&2; exit 2; }
  REPO=$(printf '%s' "$url" | sed -E 's#^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)##; s#\.git$##')
fi
case "$ACTION" in uninstall|status|run-now) ;; *)
  [[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "Not a GitHub OWNER/NAME: $REPO" >&2; usage; } ;;
esac

case "$ACTION" in
  install)
    for tool in git gh uv; do
      PATH=$JOB_PATH command -v "$tool" >/dev/null || { echo "$tool not found on the job's PATH ($JOB_PATH)" >&2; exit 1; }
    done
    gh auth status >/dev/null 2>&1 || { echo "gh is not logged in. Run: gh auth login" >&2; exit 1; }
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOGFILE")"
    bash "$SELF" --repo "$REPO" --print-plist > "$PLIST.tmp"
    plutil -lint -s "$PLIST.tmp" && mv "$PLIST.tmp" "$PLIST"
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    # Weeks older than Claude Code's log retention can't be priced, so keep logs four months.
    if [ -n "${CFO_PYTHON:-}" ]; then IPY=("$CFO_PYTHON"); else IPY=(uv run --no-project -q --python 3.12 python); fi
    "${IPY[@]}" -I - "${CFO_CLAUDE_SETTINGS:-$HOME/.claude/settings.json}" <<'PYEOF'
import json, os, shutil, sys
path = sys.argv[1]
settings = json.load(open(path)) if os.path.exists(path) else {}
current = settings.get("cleanupPeriodDays", 30)
if isinstance(current, int) and current >= 120:
    print(f"Claude Code keeps logs {current} days; left as is.")
else:
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    settings["cleanupPeriodDays"] = 120
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print(f"Claude Code now keeps logs 120 days (was {current}); backup at {path}.bak" if os.path.exists(path + ".bak")
          else "Claude Code now keeps logs 120 days.")
PYEOF
    echo "Installed: Claude Code usage goes to $REPO's brief PR every Sunday at 06:00."
    echo "Log: $LOGFILE   Check it: --status   Run it now: --run-now   Remove it: --uninstall"
    exit 0 ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed the launch agent. Claude Code log retention is left as it is."
    exit 0 ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      echo "Installed ($PLIST)."
      launchctl print "$DOMAIN/$LABEL" | grep -E '^\s*(state|last exit code|runs) =' | sed 's/^[[:space:]]*/  /'
    else
      echo "Not installed. Install it with --install (or make install in the books)."
    fi
    if [ -f "$LOGFILE" ]; then echo "Last log lines ($LOGFILE):"; tail -n 8 "$LOGFILE" | sed 's/^/  /'; fi
    exit 0 ;;
  run-now)
    launchctl kickstart "$DOMAIN/$LABEL" || { echo "Not installed. Install it with --install (or make install in the books)." >&2; exit 1; }
    echo "Started. Follow it with: tail -f $LOGFILE"
    exit 0 ;;
esac

if [ "$PRINT_PLIST" = 1 ]; then
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SELF</string><string>--repo</string><string>$REPO</string></array>
  <!-- Sundays 06:00 local time, before the cloud brief. A Mac asleep at 06:00 runs it on wake. -->
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$JOB_PATH</string></dict>
  <key>StandardOutPath</key><string>$LOGFILE</string>
  <key>StandardErrorPath</key><string>$LOGFILE</string>
</dict>
</plist>
EOF
  exit 0
fi

# Dates are Denver dates throughout, so the branch name and the cloud run agree.
export TZ=$TZNAME
if [ -n "${CFO_PYTHON:-}" ]; then PY=("$CFO_PYTHON" -I); else PY=(uv run --no-project -q --python 3.12 python -I); fi

W=$(mktemp -d)
B="$W/books"
trap 'rm -rf "$W"' EXIT
FAILED=0
# With -E the ERR trap also runs in functions and $(...) subshells. A subshell only reports and exits;
# its caller's failure then notifies once.
fail() {
  echo "cfo-claude-code: FAILED: $*" >&2
  [ "$BASH_SUBSHELL" = 0 ] && [ "$FAILED" = 0 ] || exit 1
  FAILED=1
  if command -v osascript >/dev/null; then
    osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "CFO Claude Code job failed"' \
      -e 'end run' "$*" >/dev/null 2>&1 || true
  fi
  exit 1
}
trap 'fail "line $LINENO exited $?"' ERR
py() { "${PY[@]}" -c "$@"; }
echo "cfo-claude-code: $(date -u +%FT%TZ) repo $REPO dry_run $DRY_RUN"

# Older logs may already be partly deleted by Claude Code's cleanup, and a partial week would be
# written as a verified total. Start at the first Monday two days inside the retention window.
KEEP_DAYS=$(py '
import json, os
try:
    s = json.load(open(os.path.expanduser("~/.claude/settings.json")))
    print(int(s.get("cleanupPeriodDays", 30)) if isinstance(s, dict) else 30)
except (OSError, ValueError, TypeError):
    print(30)')
[ "$KEEP_DAYS" -ge 9 ] || fail "cleanupPeriodDays is $KEEP_DAYS; a whole week can't fit inside it"
SINCE=$(py '
import datetime, sys
d = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=int(sys.argv[1]) - 2)
print(d + datetime.timedelta(days=(7 - d.weekday()) % 7))' "$KEEP_DAYS")
LOG_ARGS=(); [ -n "${CFO_LOGS:-}" ] && LOG_ARGS=(--logs "$CFO_LOGS")
echo "cfo-claude-code: cleanupPeriodDays $KEEP_DAYS, pricing whole weeks from $SINCE"

if [ -n "${CFO_CLONE_URL:-}" ]; then git clone -q "$CFO_CLONE_URL" "$B"; else gh repo clone "$REPO" "$B" -- -q; fi
cd "$B"

# Pick the branch. Rule shared with the cloud run (finances AGENTS.md step 8): the oldest open brief
# PR takes every unmerged week, so the ledger appends never conflict. Sets BRANCH and NEED_PR.
pick_branch() {
  git fetch -q origin
  local pulls open sunday n
  pulls=$(gh api "repos/$REPO/pulls?state=open&per_page=100")
  open=$(printf '%s' "$pulls" | py '
import json, sys
pulls = [p for p in json.load(sys.stdin)
         if p["head"]["ref"].startswith(("cfo/brief-", "claude/cfo-brief-"))
         and (p["head"].get("repo") or {}).get("full_name") == sys.argv[1]]
pulls.sort(key=lambda p: p["created_at"])
print(pulls[0]["head"]["ref"] if pulls else "")' "$REPO")
  if [ -n "$open" ]; then
    BRANCH=$open; NEED_PR=0
    git checkout -q -B "$BRANCH" "origin/$BRANCH"
    echo "cfo-claude-code: adding to the open brief PR on $BRANCH"
    return
  fi
  NEED_PR=1
  sunday=$(py '
import datetime
today = datetime.date.today()
print(today + datetime.timedelta(days=(6 - today.weekday()) % 7))')
  # Run late on a Sunday whose brief already merged, the rows wait for next Sunday's brief.
  if git cat-file -e "origin/main:briefs/$sunday.md" 2>/dev/null; then
    sunday=$(py 'import datetime, sys; print(datetime.date.fromisoformat(sys.argv[1]) + datetime.timedelta(days=7))' "$sunday")
  fi
  # A branch of that name not yet merged is this week's (the cloud run before it opens its PR, or
  # an earlier run of this job whose PR call failed): build on it. A merged one gets a suffix.
  BRANCH="cfo/brief-$sunday"; n=1
  while git rev-parse -q --verify "origin/$BRANCH" >/dev/null; do
    if ! git merge-base --is-ancestor "origin/$BRANCH" origin/main; then
      git checkout -q -B "$BRANCH" "origin/$BRANCH"
      echo "cfo-claude-code: no open brief PR; building on unmerged $BRANCH"
      return
    fi
    n=$((n + 1)); BRANCH="cfo/brief-$sunday-$n"
  done
  git checkout -q -B "$BRANCH" origin/main
  echo "cfo-claude-code: no open brief PR; new branch $BRANCH"
}

# Price new weeks onto the picked branch and commit. Sets WEEKS ("" when nothing is new).
price_and_commit() {
  local out
  out=$("${PY[@]}" "$BOOKS_PY" claude-code . --since "$SINCE" "${LOG_ARGS[@]+"${LOG_ARGS[@]}"}" --json) \
    || fail "books.py claude-code failed on $BRANCH: $out"
  WEEKS=$(printf '%s' "$out" | py '
import json, sys
print(", ".join(sorted({r["evidence"].split(":")[1] for r in json.load(sys.stdin)["rows"]})))')
  if [ -z "$WEEKS" ]; then return; fi
  local changed
  changed=$(git status --porcelain | awk '{print $2}')
  [ "$changed" = "ledger/charges.csv" ] || fail "expected only ledger/charges.csv to change, got: $changed"
  "${PY[@]}" "$BOOKS_PY" check . --base origin/main || fail "books check failed; nothing pushed"
  git add ledger/charges.csv
  git commit -q -m "Claude Code API-equivalent for $WEEKS" -m "Added by the Mac job (agent-kit plugins/cfo weekly-claude-code.sh)."
}

pick_branch
if [ "$DRY_RUN" = 1 ]; then
  "${PY[@]}" "$BOOKS_PY" claude-code . --since "$SINCE" "${LOG_ARGS[@]+"${LOG_ARGS[@]}"}" --dry-run \
    || fail "books.py claude-code failed"
  echo "cfo-claude-code: dry run; would push to $BRANCH$([ "$NEED_PR" = 1 ] && echo ' and open a PR')"
  exit 0
fi

# The push is a plain fast-forward. If the cloud run pushed to the same branch meanwhile, start over
# from the new tip once; claude-code skips recorded weeks, so the rerun adds only what's missing.
for attempt in 1 2; do
  price_and_commit
  if [ -z "$WEEKS" ]; then
    echo "cfo-claude-code: no new weeks; nothing to push"
    break
  fi
  if git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -q origin "HEAD:refs/heads/$BRANCH"; then
    echo "cfo-claude-code: pushed $(git rev-parse --short HEAD) to $BRANCH ($WEEKS)"
    break
  fi
  [ "$attempt" = 1 ] || fail "push to $BRANCH was rejected twice"
  echo "cfo-claude-code: push rejected; refetching and retrying once"
  pick_branch
done

# Open the PR when this job's branch has commits but no PR, including a branch left by an earlier
# run whose PR call failed. NEED_PR=1 means no brief PR was open when the branch was picked.
if [ "$NEED_PR" = 1 ] && [ "$DRY_RUN" = 0 ]; then
  git fetch -q origin
  if git rev-parse -q --verify "origin/$BRANCH" >/dev/null && [ "$(git rev-list --count "origin/main..origin/$BRANCH")" -gt 0 ]; then
    URL=$(gh api "repos/$REPO/pulls" -f title="CFO brief ${BRANCH#cfo/brief-}: Claude Code usage (brief pending)" \
      -f head="$BRANCH" -f base=main \
      -f body="Claude Code API-equivalent rows from the Mac job. The Sunday brief run adds its commit here and retitles this PR. Merge only after the brief lands, or merge now to record the usage alone." \
      --jq .html_url)
    echo "cfo-claude-code: opened $URL"
  fi
fi
