#!/usr/bin/env python3
"""Docker HEALTHCHECK probe for /health.

A plain `curl` can't know HEALTH_ENDPOINT_TOKEN when it's only configured
through /admin/settings (a DB-only secret, not an env var) - this reads the
effective value (env-first, DB-fallback, same resolution as the app itself)
directly from SQLite before making the request, so the probe still works
regardless of where the token was configured.

The probe measures liveness - "is the app serving?" - and must not report a
healthy container as unhealthy just because *it* couldn't read the token.
Docker runs HEALTHCHECK as the image's user (root, since no USER is declared),
not as the uid the entrypoint resolved for the data directory, so the database
can legitimately be unreadable here while the app itself is running fine: on an
NFS export with root_squash, root maps to the anonymous uid and cannot open a
database owned by the share's uid. Both that read failure and the resulting
401 are therefore treated as "app is up", since a 401 is itself proof the HTTP
server responded.
"""
import os
import sys
import urllib.request

import dbstore

port = os.environ.get("PORT", "5000")

try:
    token = dbstore.get_setting("health_endpoint_token")
    token_known = True
except Exception:
    # Unreadable database (root_squash, permissions, mid-migration lock...).
    # Fall back to an unauthenticated probe rather than failing outright.
    token = None
    token_known = False

headers = {"X-Health-Token": token} if token else {}

try:
    with urllib.request.urlopen(
        urllib.request.Request(f"http://localhost:{port}/health", headers=headers), timeout=5
    ) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except urllib.error.HTTPError as e:
    # 401 with a token we couldn't look up means the app is serving and simply
    # rejected an under-credentialed probe - healthy. A 401 when we *did* read
    # the token is a real mismatch worth surfacing.
    sys.exit(0 if (e.code == 401 and not token_known) else 1)
except Exception:
    sys.exit(1)
