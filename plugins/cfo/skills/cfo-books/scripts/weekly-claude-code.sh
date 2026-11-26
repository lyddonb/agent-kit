#!/usr/bin/env bash
# Weekly Mac job: price this Mac's Claude Code logs and import last week's Vercel billing into the
# books, and hand the rows to the weekly brief PR.
#
# The scheduled cloud run that writes the brief can't read ~/.claude/projects, and the Vercel CLI is
# logged in only here, so this job runs on the Mac (launchd, hourly from Sunday 06:00 until it
# succeeds once, before the cloud run). It pushes
# its ledger rows to the open brief PR's branch, or opens a brief PR on a new cfo/brief-YYYY-MM-DD
# branch. The cloud run already adds its commit to an open brief PR, so each week still ends in one
# PR. It never pushes to main, merges or force-pushes.
#
# With a quality books repo (--quality-repo), a second pass books one row per skill invocation in
# this Mac's Claude Code and Cursor transcripts (quality.py book-skills) onto a quality/brief-* branch
# of that repo, the same way. It runs after the cfo rows are pushed; a failure in it never holds back
# the cfo rows and fails the job at the end.
#
# Usage:
#   weekly-claude-code.sh --install | --uninstall | --status | --run-now   # manage the launchd agent
#   weekly-claude-code.sh [--repo OWNER/NAME] [--quality-repo OWNER/NAME] [--agentfiles-lock FILE] [--dry-run]   # one run
#   weekly-claude-code.sh --scheduled [same options]   # what the agent runs every hour
#   weekly-claude-code.sh [--repo OWNER/NAME] [--quality-repo OWNER/NAME] [--agentfiles-lock FILE] --print-plist
# --repo defaults to the GitHub remote of the books checkout in $CFO_BOOKS.
# --quality-repo defaults to the GitHub remote of the checkout in $QUALITY_BOOKS; with neither, the
# skill-use pass is skipped. --agentfiles-lock is the agentfiles.lock skill versions come from; it
# defaults to $AGENTFILES_LOCK, else $AGENTFILES_HOME/agentfiles.lock when that exists, and --install
# writes the path into the agent, whose environment has neither variable. Without a lock, versions
# are empty.
# The quality books need books/skill-uses.csv (header only is fine).
# --scheduled runs only from Sunday 06:00 to Monday 23:59 in $CFO_TZ, and only until one run of that
# window has finished without a failure (its Sunday's date is kept in a stamp file). It skips a dark
# wake, when the Mac is briefly awake with no display and the network may drop, and the next hour tries
# again. A failed run leaves no stamp, so the next hour retries it. Outside those cases it prints nothing.
#
# Needs git, gh (logged in) and uv; Vercel billing also needs the vercel CLI, logged in (without it,
# that part is skipped). Test hooks: CFO_CLONE_URL (clone from here instead of GitHub),
# CFO_LOGS (Claude Code logs dir), CFO_CLAUDE_SETTINGS (settings file --install edits), CFO_JOB_PATH (the agent's PATH), CFO_PYTHON (a Python 3.10+ instead of uv), CFO_TZ (default America/Denver),
# CFO_UTC_TODAY (the UTC date that picks the Vercel week and closes the skill-use weeks). --scheduled:
# CFO_NOW (the local date-time to use as now, like 2026-11-22T07:00), CFO_STATE_DIR (where the stamp
# cfo-claude-code.done lives; default ~/Library/Application Support/agent-kit), CFO_PMSET (the pmset
# to ask; default /usr/bin/pmset). Skill-use
# pass: QUALITY_BOOKS (checkout whose remote --quality-repo defaults to), QUALITY_CLONE_URL (clone
# the quality books from here), QUALITY_PY (quality.py; default: bstack's, next to this plugin),
# CFO_CURSOR_LOGS (Cursor logs dir).
set -Eeuo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SELF="$HERE/$(basename "$0")"
BOOKS_PY="$HERE/books.py"
LABEL=dev.agent-kit.cfo-claude-code
TZNAME=${CFO_TZ:-America/Denver}
REPO=""
QUALITY_REPO=""
LOCK=""
DRY_RUN=0
PRINT_PLIST=0
SCHEDULED=0

PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGFILE="$HOME/Library/Logs/cfo-claude-code.log"
JOB_PATH=${CFO_JOB_PATH:-/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin}
DOMAIN="gui/$(id -u)"
ACTION=run

usage() { sed -n '/^# Usage:/,/^# The quality books need/p' "$SELF" | sed 's/^# \{0,3\}//' >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO=${2:-}; shift 2 ;;
    --quality-repo) QUALITY_REPO=${2:-}; shift 2 ;;
    --agentfiles-lock) LOCK=${2:-}; [ -n "$LOCK" ] || usage; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --print-plist) PRINT_PLIST=1; shift ;;
    --scheduled) SCHEDULED=1; shift ;;
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
if [ -z "$QUALITY_REPO" ] && [ -n "${QUALITY_BOOKS:-}" ] && [ "$ACTION" != uninstall ] && [ "$ACTION" != status ] && [ "$ACTION" != run-now ]; then
  url=$(git -C "$QUALITY_BOOKS" remote get-url origin 2>/dev/null) \
    || { echo "QUALITY_BOOKS is set but $QUALITY_BOOKS has no git remote. Pass --quality-repo OWNER/NAME." >&2; exit 2; }
  QUALITY_REPO=$(printf '%s' "$url" | sed -E 's#^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)##; s#\.git$##')
fi
case "$ACTION" in uninstall|status|run-now) ;; *)
  [[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "Not a GitHub OWNER/NAME: $REPO" >&2; usage; }
  [ -z "$QUALITY_REPO" ] || [[ "$QUALITY_REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] \
    || { echo "Not a GitHub OWNER/NAME: $QUALITY_REPO" >&2; usage; } ;;
esac
# The lock for skill versions: the flag, else the environment. An installed agent has only the flag.
if [ -z "$LOCK" ]; then
  if [ -n "${AGENTFILES_LOCK:-}" ]; then LOCK=$AGENTFILES_LOCK
  elif [ -n "${AGENTFILES_HOME:-}" ] && [ -f "$AGENTFILES_HOME/agentfiles.lock" ]; then LOCK=$AGENTFILES_HOME/agentfiles.lock
  fi
fi
QUALITY_ARGS=()
if [ -n "$QUALITY_REPO" ]; then
  QUALITY_ARGS=(--quality-repo "$QUALITY_REPO")
  if [ -n "$LOCK" ]; then
    [ -f "$LOCK" ] || { echo "Not a file: $LOCK (--agentfiles-lock, AGENTFILES_LOCK or AGENTFILES_HOME)" >&2; exit 2; }
    LOCK=$(cd "$(dirname "$LOCK")" && pwd)/$(basename "$LOCK")
    QUALITY_ARGS+=(--agentfiles-lock "$LOCK")
  fi
fi

case "$ACTION" in
  install)
    for tool in git gh uv; do
      PATH=$JOB_PATH command -v "$tool" >/dev/null || { echo "$tool not found on the job's PATH ($JOB_PATH)" >&2; exit 1; }
    done
    gh auth status >/dev/null 2>&1 || { echo "gh is not logged in. Run: gh auth login" >&2; exit 1; }
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOGFILE")"
    bash "$SELF" --repo "$REPO" ${QUALITY_ARGS[@]+"${QUALITY_ARGS[@]}"} --print-plist > "$PLIST.tmp"
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
    [ -z "$QUALITY_REPO" ] || echo "Skill uses go to $QUALITY_REPO's brief PR; skill versions come from ${LOCK:-nowhere: no agentfiles.lock was given, so they stay empty}."
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
  <array><string>/bin/bash</string><string>$SELF</string><string>--repo</string><string>$REPO</string>$([ ${#QUALITY_ARGS[@]} = 0 ] || printf '<string>%s</string>' "${QUALITY_ARGS[@]}")<string>--scheduled</string></array>
  <!-- Every hour. The scheduled flag keeps the run to Sunday 06:00 to Monday 23:59 and to once a week. -->
  <key>StartCalendarInterval</key>
  <dict><key>Minute</key><integer>0</integer></dict>
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

STAMP="${CFO_STATE_DIR:-$HOME/Library/Application Support/agent-kit}/cfo-claude-code.done"
WINDOW=""
if [ "$SCHEDULED" = 1 ]; then
  WINDOW=$(py '
import datetime, os, sys
from zoneinfo import ZoneInfo
now = os.environ.get("CFO_NOW")
now = datetime.datetime.fromisoformat(now) if now else datetime.datetime.now(ZoneInfo(sys.argv[1]))
day = now.date()
if day.weekday() == 6 and now.hour >= 6:
    print(day)
elif day.weekday() == 0:
    print(day - datetime.timedelta(days=1))' "$TZNAME")
  [ -n "$WINDOW" ] || exit 0
  [ "$(cat "$STAMP" 2>/dev/null || true)" != "$WINDOW" ] || exit 0
  CAPS=$("${CFO_PMSET:-/usr/bin/pmset}" -g systemstate 2>/dev/null | sed -n 's/^.*Current System Capabilities are: *//p' | head -n 1) || CAPS=""
  case " $CAPS " in
    "  "|*" Graphics "*) ;;
    *) echo "cfo-claude-code: dark wake ($CAPS); trying again next hour"; exit 0 ;;
  esac
fi
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

# Vercel billing for the last closed Pacific week (finances AGENTS.md weekly-run step 2). Sets
# VERCEL_FILE ("" means nothing to import) and VERCEL_WEEK. A missing or logged-out CLI is a skip;
# anything else sets VERCEL_PROBLEM, which fails the job after the Claude Code rows are pushed.
# Team and project ids stay in $W: never echoed, logged or committed.
VERCEL_FILE=""; VERCEL_WEEK=""; VERCEL_PROBLEM=""
redact() { sed -E 's/(team|prj|acct|user)_[A-Za-z0-9]+/\1_<redacted>/g' "$1" | tail -n 5 >&2; }
fetch_vercel() {
  if ! command -v vercel >/dev/null; then
    echo "cfo-claude-code: vercel CLI not on PATH; skipping Vercel billing"; return
  fi
  if ! (cd "$W" && vercel whoami) >/dev/null 2>&1; then
    echo "cfo-claude-code: vercel CLI not logged in (run: vercel login); skipping Vercel billing"; return
  fi
  local code=0 from to
  (cd "$W" && vercel teams ls --json) >"$W/teams.json" 2>"$W/vercel.err" || code=$?
  if [ "$code" != 0 ]; then
    redact "$W/vercel.err"; VERCEL_PROBLEM="vercel teams ls exited $code"; return
  fi
  # One team, or the current one of several. The id goes only into the request.
  "${PY[@]}" -c '
import json, sys
teams = json.load(open(sys.argv[1])).get("teams") or []
pick = teams if len(teams) == 1 else [t for t in teams if t.get("current")]
if len(pick) != 1:
    sys.exit(f"{len(teams)} Vercel teams and {len(pick)} marked current; switch to one with: vercel switch")
print(pick[0]["id"])' "$W/teams.json" >"$W/team" 2>"$W/vercel.err" || code=$?
  if [ "$code" != 0 ]; then
    cat "$W/vercel.err" >&2; VERCEL_PROBLEM="couldn't pick the Vercel team"; return
  fi
  # The latest Monday-to-Monday week whose Sunday ended over a day ago in UTC (books.py vercel books
  # only closed weeks), with each Monday at midnight Pacific: 07:00Z in summer time, 08:00Z in winter.
  read -r from to VERCEL_WEEK < <(py '
import datetime, os
from zoneinfo import ZoneInfo
utc = datetime.timezone.utc
today = os.environ.get("CFO_UTC_TODAY")
today = datetime.date.fromisoformat(today) if today else datetime.datetime.now(utc).date()
end = today - datetime.timedelta(days=1)
end -= datetime.timedelta(days=end.weekday())
start = end - datetime.timedelta(days=7)
def midnight(d):
    t = datetime.datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("America/Los_Angeles"))
    return t.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
iso = start.isocalendar()
print(midnight(start), midnight(end), f"{iso[0]}-W{iso[1]:02d}")')
  [ -n "$VERCEL_WEEK" ] || fail "couldn't compute the Vercel week"
  echo "cfo-claude-code: fetching Vercel billing for $VERCEL_WEEK ($from to $to)"
  (cd "$W" && vercel api "/v1/billing/charges?from=$from&to=$to&teamId=$(cat "$W/team")" --method GET) \
    >"$W/focus.jsonl" 2>"$W/vercel.err" || code=$?
  if [ "$code" != 0 ]; then
    redact "$W/vercel.err"; VERCEL_PROBLEM="vercel api exited $code for $VERCEL_WEEK; nothing imported"; return
  fi
  VERCEL_FILE="$W/focus.jsonl"
}

# Import the fetched week onto the current branch (extra args go to books.py, e.g. --dry-run). Sets
# VC_WEEKS. A non-zero exit (1: an incomplete week or failing books, 2: unreadable input) books
# nothing and sets VERCEL_PROBLEM; a cut-off fetch is never booked or refetched silently.
import_vercel() {
  VC_WEEKS=""
  [ -n "$VERCEL_FILE" ] || return 0
  local code=0
  "${PY[@]}" "$BOOKS_PY" vercel . "$VERCEL_FILE" --json "$@" >"$W/vercel.out" 2>"$W/vercel.err" || code=$?
  if [ "$code" != 0 ]; then
    git checkout -q -- ledger/charges.csv
    "${PY[@]}" -c '
import json, sys
try:
    print("incomplete weeks: " + ", ".join(json.load(open(sys.argv[1]))["incomplete_weeks"]))
except (ValueError, KeyError):
    print(open(sys.argv[1]).read().strip())' "$W/vercel.out" >&2 || true
    redact "$W/vercel.err"
    VERCEL_PROBLEM="books.py vercel exited $code for $VERCEL_WEEK; nothing booked. Refetch; never book the week by hand"
    return 0
  fi
  read -r VC_WEEKS < <(py '
import json, sys
s = json.load(open(sys.argv[1]))
print(", ".join(sorted({r["evidence"].split(":")[1] for r in s["rows"]})))' "$W/vercel.out")
  echo "cfo-claude-code: Vercel $VERCEL_WEEK: $(py 'import json, sys; s = json.load(open(sys.argv[1])); print(("would add " if s["dry_run"] else "added ") + str(s["rows_added"]) + " rows, skipped " + str(s["rows_skipped"]))' "$W/vercel.out")"
}

fetch_vercel

if [ -n "${CFO_CLONE_URL:-}" ]; then git clone -q "$CFO_CLONE_URL" "$B"; else gh repo clone "$REPO" "$B" -- -q; fi
cd "$B"

# Pick the branch in the current checkout of REPO, whose brief branches start with PREFIX (and,
# for an open PR only, any extra prefix after it). Rule shared with the cloud run (finances
# AGENTS.md step 8): the oldest open brief PR takes every unmerged week, so the appends never
# conflict. Sets BRANCH and NEED_PR.
pick_branch() {
  local repo=$1 prefix=$2
  shift 2
  git fetch -q origin
  local pulls open sunday n
  pulls=$(gh api "repos/$repo/pulls?state=open&per_page=100")
  open=$(printf '%s' "$pulls" | py '
import json, sys
pulls = [p for p in json.load(sys.stdin)
         if p["head"]["ref"].startswith(tuple(sys.argv[2:]))
         and (p["head"].get("repo") or {}).get("full_name") == sys.argv[1]]
pulls.sort(key=lambda p: p["created_at"])
print(pulls[0]["head"]["ref"] if pulls else "")' "$repo" "$prefix" "$@")
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
  BRANCH="$prefix$sunday"; n=1
  while git rev-parse -q --verify "origin/$BRANCH" >/dev/null; do
    if ! git merge-base --is-ancestor "origin/$BRANCH" origin/main; then
      git checkout -q -B "$BRANCH" "origin/$BRANCH"
      echo "cfo-claude-code: no open brief PR; building on unmerged $BRANCH"
      return
    fi
    n=$((n + 1)); BRANCH="$prefix$sunday-$n"
  done
  git checkout -q -B "$BRANCH" origin/main
  echo "cfo-claude-code: no open brief PR; new branch $BRANCH"
}

# Import Vercel and price new Claude Code weeks onto the picked branch, and commit. Sets WEEKS, a
# description of what was added ("" when nothing is new).
price_and_commit() {
  local out
  import_vercel
  out=$("${PY[@]}" "$BOOKS_PY" claude-code . --since "$SINCE" "${LOG_ARGS[@]+"${LOG_ARGS[@]}"}" --json) \
    || fail "books.py claude-code failed on $BRANCH: $out"
  local cc_weeks
  cc_weeks=$(printf '%s' "$out" | py '
import json, sys
print(", ".join(sorted({r["evidence"].split(":")[1] for r in json.load(sys.stdin)["rows"]})))')
  WEEKS=""
  [ -z "$cc_weeks" ] || WEEKS="Claude Code API-equivalent for $cc_weeks"
  [ -z "$VC_WEEKS" ] || WEEKS="${WEEKS:+$WEEKS; }Vercel usage for $VC_WEEKS"
  if [ -z "$WEEKS" ]; then return; fi
  local changed
  changed=$(git status --porcelain | awk '{print $2}')
  [ "$changed" = "ledger/charges.csv" ] || fail "expected only ledger/charges.csv to change, got: $changed"
  "${PY[@]}" "$BOOKS_PY" check . --base origin/main || fail "books check failed; nothing pushed"
  git add ledger/charges.csv
  git commit -q -m "$WEEKS" -m "Added by the Mac job (agent-kit plugins/cfo weekly-claude-code.sh)."
}

# Book one row per skill invocation into the quality books (quality.py book-skills), on a
# quality/brief-* branch picked with the same rule as the cfo one. Takes --dry-run. Runs in a
# background subshell: errexit and the ERR trap stay live there (a `|| ...` context would switch them
# off), and a failure ends only the pass. Any non-zero exit sets SKILLS_PROBLEM, reported at the end.
# Logs hold counts and week names only, never a skill name, a project name or transcript text.
SKILLS_PROBLEM=""
skills_pass() {
  local qpy=${QUALITY_PY:-$HERE/../../../../bstack/skills/qualitydirector/scripts/quality.py}
  if [ ! -f "$qpy" ]; then
    echo "cfo-claude-code: quality.py not found (cfo can be installed without bstack); skipping skill uses"; return 0
  fi
  local Q="$W/quality" dry=0 attempt
  [ "${1:-}" != --dry-run ] || dry=1
  if [ -n "${QUALITY_CLONE_URL:-}" ]; then git clone -q "$QUALITY_CLONE_URL" "$Q"; else gh repo clone "$QUALITY_REPO" "$Q" -- -q; fi
  cd "$Q"
  pick_branch "$QUALITY_REPO" quality/brief-
  if [ ! -f books/skill-uses.csv ]; then
    echo "cfo-claude-code: skill-uses.csv is not in the quality books yet; skipping"; return 0
  fi
  local args=(. --since "$SINCE" --json)
  [ -z "${CFO_LOGS:-}" ] || args+=(--claude-logs "$CFO_LOGS")
  [ -z "${CFO_CURSOR_LOGS:-}" ] || args+=(--cursor-logs "$CFO_CURSOR_LOGS")
  [ -z "${CFO_UTC_TODAY:-}" ] || args+=(--today "$CFO_UTC_TODAY")
  if [ -n "$LOCK" ]; then
    args+=(--lock "$LOCK")
  else
    echo "cfo-claude-code: no agentfiles.lock given; skill versions will be empty"
  fi
  [ "$dry" = 0 ] || args+=(--dry-run)
  local out="$W/skills.out" err="$W/skills.err" code summary booked weeks
  for attempt in 1 2; do
    code=0
    "${PY[@]}" "$qpy" book-skills "${args[@]}" >"$out" 2>"$err" || code=$?
    if [ "$code" != 0 ]; then
      tail -n 1 "$out" >&2; tail -n 3 "$err" >&2
      fail "quality.py book-skills exited $code on $BRANCH; nothing pushed"
    fi
    summary=$(py '
import json, sys
s = json.load(open(sys.argv[1]))
t = s["totals"]
weeks = ", ".join(sorted(s["weeks"]))
print("%s|%s|%s %d skill uses%s; %d already booked, %d in the open week, %d not in the lock file" % (
    t["booked"], weeks, "would book" if s["dry_run"] else "booked", t["booked"], " for " + weeks if weeks else "",
    t["already_booked"], t["open_week"], t["not_in_lock"]))' "$out")
    booked=${summary%%|*}; weeks=${summary#*|}; weeks=${weeks%%|*}
    echo "cfo-claude-code: ${summary##*|}"
    if [ "$booked" = 0 ]; then echo "cfo-claude-code: no new skill uses"; return 0; fi
    if [ "$dry" = 1 ]; then
      echo "cfo-claude-code: dry run; would push skill uses to $BRANCH$([ "$NEED_PR" = 1 ] && echo ' and open a PR')"; return 0
    fi
    local changed
    changed=$(git status --porcelain | awk '{print $2}')
    [ "$changed" = "books/skill-uses.csv" ] || fail "expected only books/skill-uses.csv to change, got: $changed"
    "${PY[@]}" "$qpy" check . --base origin/main >/dev/null || fail "quality books check failed; nothing pushed"
    git add books/skill-uses.csv
    git commit -q -m "Skill uses for $weeks" -m "Added by the Mac job (agent-kit plugins/cfo weekly-claude-code.sh)."
    if git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -q origin "HEAD:refs/heads/$BRANCH"; then
      echo "cfo-claude-code: pushed $(git rev-parse --short HEAD) to $BRANCH (skill uses for $weeks)"
      break
    fi
    [ "$attempt" = 1 ] || fail "push to $BRANCH was rejected twice"
    echo "cfo-claude-code: push rejected; refetching and retrying once"
    pick_branch "$QUALITY_REPO" quality/brief-
  done
  if [ "$NEED_PR" = 1 ]; then
    git fetch -q origin
    if git rev-parse -q --verify "origin/$BRANCH" >/dev/null && [ "$(git rev-list --count "origin/main..origin/$BRANCH")" -gt 0 ]; then
      local url
      url=$(gh api "repos/$QUALITY_REPO/pulls" -f title="Quality brief ${BRANCH#quality/brief-}: skill uses (brief pending)" \
        -f head="$BRANCH" -f base=main \
        -f body="Skill-use rows from the Mac job. The weekly quality brief run adds its commit here and retitles this PR. Merge only after the brief lands, or merge now to record the skill uses alone." \
        --jq .html_url)
      echo "cfo-claude-code: opened $url"
    fi
  fi
}
run_skills_pass() {
  if [ -z "$QUALITY_REPO" ]; then
    echo "cfo-claude-code: no --quality-repo or QUALITY_BOOKS; skipping skill uses"; return 0
  fi
  local code=0
  skills_pass "$@" &
  wait $! || code=$?
  [ "$code" = 0 ] || SKILLS_PROBLEM="skill uses: the pass exited $code (output above); the cfo rows are unaffected"
  return 0
}
# Reported last, so a Vercel or skill-use problem never holds back the Claude Code rows.
report_problems() {
  if [ -n "$VERCEL_PROBLEM$SKILLS_PROBLEM" ]; then
    fail "${VERCEL_PROBLEM:+Vercel: $VERCEL_PROBLEM}${VERCEL_PROBLEM:+${SKILLS_PROBLEM:+; }}$SKILLS_PROBLEM"
  fi
}

pick_branch "$REPO" cfo/brief- claude/cfo-brief-
if [ "$DRY_RUN" = 1 ]; then
  import_vercel --dry-run
  [ -z "$VERCEL_FILE" ] || [ -n "$VERCEL_PROBLEM" ] || py '
import json, sys
s = json.load(open(sys.argv[1]))
print("Vercel weeks:", ", ".join(s["weeks"]) or "none", "| incomplete:", ", ".join(s["incomplete_weeks"]) or "none")
for r in s["rows"]:
    print(" ", r["evidence"].split(":")[1], r["project"], r["service"], r["billed_cost"])' "$W/vercel.out" < /dev/null
  "${PY[@]}" "$BOOKS_PY" claude-code . --since "$SINCE" "${LOG_ARGS[@]+"${LOG_ARGS[@]}"}" --dry-run \
    || fail "books.py claude-code failed"
  echo "cfo-claude-code: dry run; would push to $BRANCH$([ "$NEED_PR" = 1 ] && echo ' and open a PR')"
  run_skills_pass --dry-run
  report_problems
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
  pick_branch "$REPO" cfo/brief- claude/cfo-brief-
done

# Open the PR when this job's branch has commits but no PR, including a branch left by an earlier
# run whose PR call failed. NEED_PR=1 means no brief PR was open when the branch was picked.
if [ "$NEED_PR" = 1 ] && [ "$DRY_RUN" = 0 ]; then
  git fetch -q origin
  if git rev-parse -q --verify "origin/$BRANCH" >/dev/null && [ "$(git rev-list --count "origin/main..origin/$BRANCH")" -gt 0 ]; then
    URL=$(gh api "repos/$REPO/pulls" -f title="CFO brief ${BRANCH#cfo/brief-}: Claude Code and Vercel usage (brief pending)" \
      -f head="$BRANCH" -f base=main \
      -f body="Claude Code API-equivalent and Vercel usage rows from the Mac job. The Sunday brief run adds its commit here and retitles this PR. Merge only after the brief lands, or merge now to record the usage alone." \
      --jq .html_url)
    echo "cfo-claude-code: opened $URL"
  fi
fi

run_skills_pass
report_problems
if [ "$SCHEDULED" = 1 ]; then
  mkdir -p "$(dirname "$STAMP")"
  printf '%s\n' "$WINDOW" >"$STAMP"
fi
