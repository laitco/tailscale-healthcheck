#!/bin/sh
# Runs as root so it can fix ownership of a bind-mounted /data volume (which may
# come from the host owned by an arbitrary user/root), then drops privileges to
# the unprivileged appuser before executing the real command.
set -e

if [ -d /data ]; then
    chown -R appuser:app /data || true
fi

exec gosu appuser "$@"
