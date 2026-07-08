#!/usr/bin/env bash
# Commit staged changes and push with rebase retries (avoids concurrent GHA races).
set -euo pipefail

MSG="${1:?commit message required}"
MAX_ATTEMPTS="${2:-8}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if git diff --staged --quiet; then
  echo "changed=false" >> "$GITHUB_OUTPUT"
  echo "No changes"
  exit 0
fi

git commit -m "$MSG"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  if git pull --rebase origin main && git push; then
    echo "changed=true" >> "$GITHUB_OUTPUT"
    echo "Pushed on attempt ${attempt}"
    exit 0
  fi
  echo "Push race on attempt ${attempt}/${MAX_ATTEMPTS}; retrying..."
  git rebase --abort 2>/dev/null || true
  git fetch origin main
  sleep $((attempt * 2))
done

echo "ERROR: failed to push after ${MAX_ATTEMPTS} attempts" >&2
exit 1
