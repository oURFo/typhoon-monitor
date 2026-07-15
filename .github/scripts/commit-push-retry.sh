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

stash_dirty() {
  if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
    git stash push --include-untracked -m "gha-commit-push-retry" >/dev/null
    echo "stashed dirty worktree for rebase"
    return 0
  fi
  return 1
}

restore_stash() {
  if git stash list | head -n1 | grep -q "gha-commit-push-retry"; then
    git stash pop >/dev/null 2>&1 || true
  fi
}

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  STASHED=0
  if stash_dirty; then
    STASHED=1
  fi
  if git pull --rebase origin main && git push; then
    if [ "$STASHED" = 1 ]; then
      restore_stash
    fi
    echo "changed=true" >> "$GITHUB_OUTPUT"
    echo "Pushed on attempt ${attempt}"
    exit 0
  fi
  echo "Push race on attempt ${attempt}/${MAX_ATTEMPTS}; retrying..."
  git rebase --abort 2>/dev/null || true
  if [ "$STASHED" = 1 ]; then
    restore_stash
  fi
  git fetch origin main
  sleep $((attempt * 2))
done

echo "ERROR: failed to push after ${MAX_ATTEMPTS} attempts" >&2
exit 1
