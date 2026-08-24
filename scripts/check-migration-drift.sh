#!/usr/bin/env bash
set -euo pipefail

uv run alembic upgrade head
uv run alembic current --check-heads
output="$(uv run alembic check 2>&1)"
echo "$output"
grep -F 'No new upgrade operations detected.' <<<"$output"
