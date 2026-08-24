#!/usr/bin/env bash
set -euo pipefail

api_base="${API_BASE:-http://localhost:8000}"
curl --fail-with-body --silent --show-error \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-autonomous-cycle-v1' \
  -d '{}' \
  "$api_base/api/v1/demo/cycle"
echo
