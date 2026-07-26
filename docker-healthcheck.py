#!/usr/bin/env python3
"""Docker HEALTHCHECK probe for /health.

A plain `curl` can't know HEALTH_ENDPOINT_TOKEN when it's only configured
through /admin/settings (a DB-only secret, not an env var) - this reads the
effective value (env-first, DB-fallback, same resolution as the app itself)
directly from SQLite before making the request, so the probe still works
regardless of where the token was configured.
"""
import os
import sys
import urllib.request

import dbstore

port = os.environ.get("PORT", "5000")
token = dbstore.get_setting("health_endpoint_token")
headers = {"X-Health-Token": token} if token else {}

try:
    with urllib.request.urlopen(
        urllib.request.Request(f"http://localhost:{port}/health", headers=headers), timeout=5
    ) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
