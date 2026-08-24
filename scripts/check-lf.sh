#!/usr/bin/env bash
set -euo pipefail

if ! command -v git >/dev/null 2>&1 || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Git and a valid worktree are required for tracked shell validation." >&2
  exit 1
fi

failure=0
while IFS= read -r -d '' file; do
  if LC_ALL=C grep -q $'\r' "$file"; then
    echo "$file contains a carriage return" >&2
    failure=1
  fi
  bash -n "$file"
done < <(git ls-files -z '*.sh')

if (( failure != 0 )); then
  exit 1
fi

echo "Shell scripts use LF and pass bash -n."
