#!/bin/sh
set -eu

if [ "${STARTUP_BOOTSTRAP:-false}" = "true" ]; then
  python -m promotion_control_plane.cli.main bootstrap
fi

exec "$@"
