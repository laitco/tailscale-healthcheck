"""Background poller: refreshes devices/tailnet_keys from the Tailscale API into SQLite.

Only one process (of the 4 gunicorn workers) actually polls, elected via a
non-blocking fcntl lock on a file in the same directory as the SQLite DB -
the same primitive already used by healthcheck.py's file-based rate limiter.
Everything that talks to the Tailscale API (auth headers, retries, OAuth
token refresh) is reused from healthcheck.py to avoid duplicating that logic;
imports of healthcheck are deferred to call time to dodge a circular import
(healthcheck.py imports this module to kick off the poller after app setup).
"""
import os
import fcntl
import logging
import threading
import time
from datetime import datetime, timezone

import requests

import dbstore

_lock_fh = None
_timer = None
_have_lock = False

# Event types this module emits, in the order a poll cycle produces them.
# The /debug page filters on these (not log severity) - see
# dbstore.list_poller_log_event_types() for what's actually present.
EVENT_TYPES = (
    "poll_skipped", "poll_started",
    "devices_success", "devices_error",
    "keys_success", "keys_error",
    "poll_completed",
)

_ERROR_EVENT_TYPES = {"devices_error", "keys_error"}


def _record(event_type: str, message: str, detail: dict = None):
    """Log to the standard `logging` module always, and to the persistent
    poller_log table (gated by the debug_log_enabled setting) for the
    /debug page. Persisted, not an in-memory buffer, so it survives worker
    restarts and is visible across all Gunicorn workers."""
    py_level = logging.ERROR if event_type in _ERROR_EVENT_TYPES else logging.INFO
    logging.log(py_level, message)
    if not dbstore.get_setting_typed("debug_log_enabled"):
        return
    dbstore.record_poller_log(event_type, message, detail)


def get_poll_log(event_type: str = None, limit: int = 200):
    """Return recent poller_log entries (newest first), optionally filtered
    to a single event_type."""
    return dbstore.list_poller_log(event_type=event_type, limit=limit)


def get_poll_log_event_types():
    return list(EVENT_TYPES)


def _is_auth_error(exc: Exception) -> bool:
    """True if `exc` looks like a 401/403 from the Tailscale API - i.e. the
    configured AUTH_TOKEN/OAuth credentials are missing, wrong, or revoked,
    as opposed to a network blip or an unrelated API error."""
    response = getattr(exc, "response", None)
    if isinstance(exc, requests.exceptions.HTTPError) and response is not None:
        return response.status_code in (401, 403)
    return False


def _lock_path() -> str:
    directory = os.path.dirname(dbstore.DATABASE_PATH) or "."
    return os.path.join(directory, "poller.lock")


def _acquire_poller_lock() -> bool:
    """Non-blocking exclusive lock; returns True if this process won the election."""
    global _lock_fh, _have_lock
    if _have_lock:
        return True
    try:
        fh = open(_lock_path(), "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fh = fh  # keep open for process lifetime; released on process exit
        _have_lock = True
        return True
    except (BlockingIOError, OSError):
        return False


def poll_interval_seconds() -> int:
    try:
        return max(5, int(dbstore.get_setting_typed("poll_interval_seconds")))
    except (TypeError, ValueError):
        return 60


def run_poll_cycle():
    """Fetch devices + tailnet keys from the Tailscale API and persist them.

    Safe to call directly (e.g. from an admin-triggered "poll now" action)
    regardless of whether this process holds the poller election lock.
    """
    cycle_start = time.monotonic()
    if not dbstore.is_tailnet_configured():
        _record("poll_skipped", "Poll cycle skipped: tailnet not configured.")
        return
    if not dbstore.is_auth_configured():
        # Without this, a fresh/unconfigured instance (or one where auth was
        # only just removed) would still hit the Tailscale API every cycle
        # with the placeholder token and get a 401 every time - noisy and
        # pointless. Skip entirely until a usable token/OAuth pair exists.
        _record("poll_skipped", "Poll cycle skipped: no auth token or OAuth credentials configured.")
        return

    _record("poll_started", "Poll cycle starting.")
    import healthcheck  # deferred: avoids circular import at module load time

    have_access_token = getattr(healthcheck, "ACCESS_TOKEN", None)
    oauth_configured = dbstore.get_setting("oauth_client_id") and dbstore.get_setting("oauth_client_secret")
    if not have_access_token and oauth_configured:
        # ACCESS_TOKEN is per-process; if OAuth creds became configured via
        # the settings UI (handled by a different worker process than this
        # one) while a still-working static token meant no 401 ever occurred
        # to trigger the usual retry-driven fetch, self-heal here instead -
        # this runs in the one process that actually owns polling, so it's
        # process-correct regardless of which worker persisted the setting.
        healthcheck.fetch_oauth_token()

    tailnet_domain = dbstore.get_setting("tailnet_domain")
    devices_url = f"https://api.tailscale.com/api/v2/tailnet/{tailnet_domain}/devices"
    keys_url = f"https://api.tailscale.com/api/v2/tailnet/{tailnet_domain}/keys?all=true"
    auth_header = healthcheck.build_auth_header()

    cycle_error = None
    cycle_auth_error = False

    devices_count = None
    try:
        devices_response = healthcheck.make_authenticated_request(devices_url, dict(auth_header))
        devices = devices_response.json().get("devices") or []
        dbstore.upsert_devices(devices)
        devices_count = len(devices)
        _record("devices_success", f"Fetched {devices_count} device(s).", {"devices_count": devices_count})
    except Exception as e:
        cycle_error = str(e)
        cycle_auth_error = _is_auth_error(e)
        _record("devices_error", f"Failed to fetch/store devices: {e}", {"error": str(e), "auth_error": cycle_auth_error})

    keys_count = None
    try:
        keys_response = healthcheck.make_authenticated_request(keys_url, dict(auth_header))
        keys = keys_response.json().get("keys") or []
        dbstore.upsert_keys(keys, healthcheck._infer_key_type)
        keys_count = len(keys)
        _record("keys_success", f"Fetched {keys_count} tailnet key(s).", {"keys_count": keys_count})
    except Exception as e:
        cycle_error = cycle_error or str(e)
        cycle_auth_error = cycle_auth_error or _is_auth_error(e)
        _record("keys_error", f"Failed to fetch/store tailnet keys: {e}", {"error": str(e), "auth_error": _is_auth_error(e)})

    dbstore.set_poll_status(ok=cycle_error is None, error=cycle_error, auth_error=cycle_auth_error)

    try:
        health_metrics = healthcheck._compute_health_summary(dbstore.get_devices_snapshot())[1]
        keys_metrics = healthcheck._compute_keys_summary(dbstore.get_keys_snapshot())[1]
        dbstore.record_metrics_snapshot(health_metrics, keys_metrics)
    except Exception as e:  # pragma: no cover - defensive, must never break the poll cycle
        logging.warning(f"Poll cycle: failed to record metrics snapshot: {e}")
    dbstore.purge_metrics_history()

    now_iso = datetime.now(timezone.utc).isoformat()
    dbstore.set_poll_meta(now_iso)
    dbstore.purge_audit_log()
    dbstore.purge_poller_log()
    duration_ms = round((time.monotonic() - cycle_start) * 1000, 1)
    _record(
        "poll_completed", f"Poll cycle complete in {duration_ms}ms.",
        {"duration_ms": duration_ms, "devices_count": devices_count, "keys_count": keys_count},
    )


def _scheduled_cycle():
    global _timer
    try:
        run_poll_cycle()
    except Exception as e:  # pragma: no cover - defensive
        logging.error(f"Unhandled error in scheduled poll cycle: {e}")
    finally:
        _timer = threading.Timer(poll_interval_seconds(), _scheduled_cycle)
        _timer.daemon = True
        _timer.start()


def start():
    """Start the background poller in this process, if it wins the election."""
    if not _acquire_poller_lock():
        logging.info("Poller lock held by another worker process; not starting poller here.")
        return False
    logging.info("Poller lock acquired; starting background poll loop.")
    _scheduled_cycle()
    return True
