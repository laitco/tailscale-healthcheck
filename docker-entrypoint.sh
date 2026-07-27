#!/bin/sh
# When started as root (the plain `docker run` default for this image, since
# no USER is declared), fixes ownership of a bind-mounted /data volume (which
# may come from the host owned by an arbitrary user/root) then drops
# privileges to the unprivileged appuser before executing the real command.
#
# When a hardened runtime already starts the container as non-root (e.g.
# Kubernetes runAsUser/runAsNonRoot), skips both steps entirely instead of
# failing: it has no permission to chown someone else's files anyway, and
# gosu itself requires root to change user, so calling it while already
# non-root would just crash the container instead of running it.
set -e

if [ "$(id -u)" = "0" ]; then
    if [ -d /data ]; then
        chown -R appuser:app /data || true
    fi
    exec gosu appuser "$@"
else
    exec "$@"
fi
