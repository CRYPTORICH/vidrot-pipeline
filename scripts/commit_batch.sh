#!/usr/bin/env bash
# Commit the daily prompt batch and push it to the current branch.
# Video files are never included. A no-op when nothing changed.
# Set PUSH=0 to commit locally without pushing (used by tests).
set -euo pipefail

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add -- prompts config/trending_cache.json

shopt -s nullglob
text_files=(output/*.json output/*.txt output/*.md)
if (( ${#text_files[@]} )); then
  git add -- "${text_files[@]}"
fi

if git diff --staged --quiet; then
  echo "No changes to commit."
  exit 0
fi

echo "Committing:"
git diff --staged --stat

git commit -m "Daily prompt batch $(date -u +%Y-%m-%d) [skip ci]"

if [[ "${PUSH:-1}" == "1" ]]; then
  branch="$(git rev-parse --abbrev-ref HEAD)"
  git push origin "HEAD:${branch}"
fi
