#!/usr/bin/env bash
# Rank files by how many kinds of implicit-state-machine signal they contain.
# Leads only: read each file before calling anything a machine. Files with one kind rank last but
# still show: a hook with data/loading/error state can look like a single effect-chain hit.
#
# Usage: find-candidates.sh [DIR] [TOP]     (defaults: . and 30)
# Output: one line per file, "kinds total  path  [kind:count ...]", most kinds first.
# Skips tests, docs, lockfiles and binaries. Uses ripgrep when installed, else git grep (both respect
# .gitignore), else grep -rE. Counts are matches with rg and matching lines otherwise.
set -euo pipefail

dir="${1:-.}"
top="${2:-30}"

words='Loading|Error|Errored|Open|Opened|Closed|Closing|Submitting|Submitted|Pending|Fetching|Fetched|Saving|Saved|Done|Complete|Completed|Ready|Visible|Active|Running|Busy|Dirty|Failed|Success|Succeeded|Started|Finished|Cancelled|Canceled|Locked|Connected|Initialized|Processing|Retrying|Paused|Expanded|Editing'
snake=$(printf '%s' "$words" | tr 'A-Z' 'a-z')

# signal-patterns.tsv: kind<TAB>POSIX ERE (so the grep fallback understands it); @W@/@S@ expand to the flag words.
patterns=$(sed -e "s/@W@/${words}/g" -e "s/@S@/${snake}/g" "$(dirname "$0")/signal-patterns.tsv")

search() { # regex -> "path:count" lines
  # BSD/macOS ERE has no \b, so the non-rg paths spell the boundary out.
  local ere; ere=$(printf '%s' "$1" | sed 's/\\b/([^A-Za-z0-9_]|^|$)/g')
  if command -v rg >/dev/null 2>&1; then
    rg --count-matches --no-messages -e "$1" \
       -g '!*.lock' -g '!*-lock.*' -g '!*.lockb' -g '!*.min.*' -g '!*.map' -g '!*.svg' -g '!*.md' \
       -g '!*.test.*' -g '!*.spec.*' -g '!*_test.*' -g '!test_*' -g '!**/tests/**' -g '!**/__tests__/**' "$dir" || true
  elif git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$dir" grep -I -c -E -e "$ere" -- . ':!*.lock' ':!*-lock.*' ':!*.lockb' ':!*.min.*' ':!*.map' ':!*.svg' ':!*.md' \
        ':!*.test.*' ':!*.spec.*' ':!*_test.*' ':!**/test_*' ':!**/tests/**' ':!**/__tests__/**' \
      | sed "s|^|${dir%/}/|" || true
  else
    grep -rEIc --exclude-dir={node_modules,.git,dist,build,vendor,target,.next,tests,__tests__,.venv,venv,__pycache__,coverage} \
         --exclude='*.lock' --exclude='*-lock.*' --exclude='*.md' --exclude='*.test.*' --exclude='*.spec.*' --exclude='*_test.*' --exclude='test_*' \
         -e "$ere" "$dir" 2>/dev/null | grep -v ':0$' || true
  fi
}

printf '%s\n' "$patterns" | while IFS=$'\t' read -r kind regex; do
  search "$regex" | awk -v k="$kind" -F: '{c=$NF; sub(/:[0-9]+$/, ""); print k "\t" $0 "\t" c}'
done | awk -F'\t' '
  { key=$2; n[key]+=$3; if (!((key, $1) in seen)) { seen[key, $1]=1; kinds[key]++ }
    detail[key]=detail[key] " " $1 ":" $3 }
  END { for (f in n) if (kinds[f] >= 1) printf "%d %d  %s  [%s ]\n", kinds[f], n[f], f, detail[f] }
' | sort -k1,1nr -k2,2nr | head -n "$top"
