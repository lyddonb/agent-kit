#!/usr/bin/env bash
# replay.sh REPO EXEMPT_FILE CHECKER PR... : for each PR, merge its head into (its base + the exempt list)
# and run the enforced check there, the way CI will once the list is on main.
set -uo pipefail
repo=$1 exempt=$2 checker=$3; shift 3
dir=$(mktemp -d)/$repo
git clone -q "git@github.com:lyddonb/$repo.git" "$dir"
cd "$dir"
g() { git -c user.name=replay -c user.email=replay@example.com "$@"; }
for n in "$@"; do
  read -r base head state <<<"$(gh pr view "$n" -R "lyddonb/$repo" --json baseRefOid,headRefOid,state --jq '"\(.baseRefOid) \(.headRefOid) \(.state)"')"
  git fetch -q origin "pull/$n/head" 2>/dev/null
  git checkout -q --detach "$base"
  mkdir -p .changes && cp "$exempt" .changes/exempt && git add .changes/exempt && g commit -qm "replay: exempt list"
  B=$(git rev-parse HEAD)
  if ! g merge -q --no-ff --no-edit "$head" >/dev/null 2>&1; then
    echo "#$n ($state) MERGE-CONFLICT"; git merge --abort; continue
  fi
  out=$(python3 "$checker" check --base "$B" --root . 2>&1); rc=$?
  verdict=$([ $rc = 0 ] && echo PASS || echo "FAIL(rc=$rc)")
  echo "#$n ($state) $verdict :: $(echo "$out" | grep -v '^exempt on' | tr '\n' ' ' | cut -c1-230)"
done
