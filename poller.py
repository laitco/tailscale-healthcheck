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
from datetime import datetime, timedelta, timezone

import requests

import dbstore
import notifier

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
    "notification_sent", "notification_failed", "notification_suppressed",
    "poll_completed",
)

_ERROR_EVENT_TYPES = {"devices_error", "keys_error", "notification_failed"}


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


def _record_notification(event_type: str, target: str, sent: bool, reason: str):
    if sent:
        _record("notification_sent", f"Notified '{event_type}' for {target}.", {"event_type": event_type})
    elif reason not in ("not_configured", "event_not_enabled", "tag_filtered"):
        _record(
            "notification_failed", f"Failed to notify '{event_type}' for {target}: {reason}",
            {"event_type": event_type, "error": reason},
        )


def _cooldown_minutes(cfg: dict) -> int:
    try:
        return max(0, int(cfg.get("notification_cooldown_minutes") or 0))
    except (TypeError, ValueError):
        return 0


def _in_cooldown(last_notified_iso: str, cooldown_minutes: int) -> bool:
    """True if `last_notified_iso` is recent enough that another notification
    for the same (event, entity) should be suppressed."""
    if not cooldown_minutes or not last_notified_iso:
        return False
    try:
        last = datetime.fromisoformat(last_notified_iso)
    except (TypeError, ValueError):
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last) < timedelta(minutes=cooldown_minutes)


def _notify_entity(event_type, entity_id, target, title, body, cfg, cooldown_state, device_tags=None):
    """Send one entity-scoped notification, honouring notification_cooldown_minutes.

    Notifications already only fire on a state *transition*, but a device
    flapping across the healthy line still produces one alert per flap. The
    cooldown collapses those into at most one per window per (event, entity).
    Suppressions are recorded as their own poller_log event so /debug explains
    the silence rather than looking like the notifier simply stopped working.
    """
    cooldown_minutes = _cooldown_minutes(cfg)
    if _in_cooldown(cooldown_state.get(entity_id), cooldown_minutes):
        _record(
            "notification_suppressed",
            f"Suppressed '{event_type}' for {target} (within {cooldown_minutes}m cooldown).",
            {"event_type": event_type, "cooldown_minutes": cooldown_minutes},
        )
        return
    sent, reason = notifier.notify(event_type, title, body, cfg, device_tags=device_tags)
    _record_notification(event_type, target, sent, reason)
    if sent and cooldown_minutes:
        now_iso = datetime.now(timezone.utc).isoformat()
        dbstore.set_last_notified(event_type, entity_id, now_iso)
        cooldown_state[entity_id] = now_iso


def _process_device_notifications(cfg: dict, health_status: list):
    """Fire device_unhealthy/device_healthy_again on a healthy-state
    transition, comparing against the previous poll cycle's stored state -
    never on a device's first-ever appearance (that would spam every device
    at rollout/first run)."""
    old_state = dbstore.get_health_state("device")
    cooldowns = {
        "device_unhealthy": dbstore.get_last_notified("device_unhealthy"),
        "device_healthy_again": dbstore.get_last_notified("device_healthy_again"),
    }
    new_states = {}
    for d in health_status:
        device_id = d.get("id")
        if not device_id:
            continue
        name = d.get("machineName") or d.get("device") or device_id
        new_healthy = bool(d.get("healthy"))
        old_healthy = old_state.get(device_id)
        if old_healthy is not None and old_healthy != new_healthy:
            event = "device_healthy_again" if new_healthy else "device_unhealthy"
            title = f"{name} is {'healthy again' if new_healthy else 'unhealthy'}"
            body = f"Device {d.get('device', name)} transitioned to {'healthy' if new_healthy else 'unhealthy'}."
            _notify_entity(event, device_id, name, title, body, cfg, cooldowns[event], device_tags=d.get("tags"))
        new_states[device_id] = new_healthy
    dbstore.set_health_state_bulk("device", new_states)
    dbstore.prune_health_state("device", new_states.keys())


def _process_lock_notifications(cfg: dict, health_status: list):
    """Fire device_needs_signing/device_signed on a Tailnet Lock signature
    transition. Gated behind tailnet_lock_enabled like every other Tailnet
    Lock behavior - inert until an admin opts in."""
    if not cfg.get("tailnet_lock_enabled"):
        return
    old_state = dbstore.get_health_state("device_lock")
    cooldowns = {
        "device_needs_signing": dbstore.get_last_notified("device_needs_signing"),
        "device_signed": dbstore.get_last_notified("device_signed"),
    }
    new_states = {}
    for d in health_status:
        device_id = d.get("id")
        if not device_id:
            continue
        name = d.get("machineName") or d.get("device") or device_id
        signed = not d.get("tailnetLockError")
        old_signed = old_state.get(device_id)
        if old_signed is not None and old_signed != signed:
            event = "device_signed" if signed else "device_needs_signing"
            title = f"{name} {'is signed' if signed else 'needs a Tailnet Lock signature'}"
            body = (
                f"Device {d.get('device', name)} is now signed under Tailnet Lock."
                if signed
                else f"Device {d.get('device', name)} needs a Tailnet Lock signature: {d.get('tailnetLockError', '')}"
            )
            _notify_entity(event, device_id, name, title, body, cfg, cooldowns[event], device_tags=d.get("tags"))
        new_states[device_id] = signed
    dbstore.set_health_state_bulk("device_lock", new_states)
    dbstore.prune_health_state("device_lock", new_states.keys())


def _process_key_notifications(cfg: dict, key_status: list):
    """Fire key_expiring the moment a key crosses into unhealthy (expiring
    soon). There's no "key healthy again" event - a renewed/replaced key
    just stops being interesting."""
    old_state = dbstore.get_health_state("key")
    key_cooldown = dbstore.get_last_notified("key_expiring")
    new_states = {}
    for k in key_status:
        key_id = k.get("id")
        if not key_id:
            continue
        new_healthy = bool(k.get("key_healthy"))
        old_healthy = old_state.get(key_id)
        if old_healthy is True and new_healthy is False:
            title = f"Tailnet key '{k.get('description') or key_id}' is expiring soon"
            body = f"Key expires in {k.get('key_days_to_expire')} day(s)."
            _notify_entity(
                "key_expiring", key_id, k.get("description") or key_id, title, body, cfg, key_cooldown,
            )
        new_states[key_id] = new_healthy
    dbstore.set_health_state_bulk("key", new_states)
    dbstore.prune_health_state("key", new_states.keys())


def _process_global_notifications(cfg: dict, health_metrics: dict):
    old_state = dbstore.get_health_state("global")
    new_healthy = bool(health_metrics.get("global_healthy"))
    old_healthy = old_state.get("tailnet")
    if old_healthy is not None and old_healthy != new_healthy:
        event = "global_healthy_restored" if new_healthy else "global_unhealthy"
        title = "Tailnet is healthy again" if new_healthy else "Tailnet is unhealthy"
        body = f"{health_metrics.get('counter_healthy_false', 0)} device(s) currently unhealthy."
        _notify_entity(event, "tailnet", "tailnet", title, body, cfg, dbstore.get_last_notified(event))
    dbstore.set_health_state("global", "tailnet", new_healthy)


def _needs_oauth_refresh(healthcheck, current_client_id) -> bool:
    """Whether this process should fetch a fresh OAuth token before polling.

    ACCESS_TOKEN and its renewal timer are per-process globals, so there are
    three distinct staleness cases:

    1. No token at all - e.g. OAuth creds became configured via the settings
       UI while a still-working static token meant no 401 ever occurred to
       trigger the usual retry-driven fetch.
    2. A token for a DIFFERENT client id - creds were replaced (new client
       id/secret) while a cached token from the OLD client is still truthy.
       Without comparing the client id, that stale token for a possibly-now-
       wrong tailnet would keep being used until it happened to expire or get
       a 401, which a wrong-but-still-valid-elsewhere token might never do.
    3. A token with no live renewal timer. Threads do not survive fork, so a
       worker that inherited a valid ACCESS_TOKEN from the preloaded master
       (see the --preload flag in the Dockerfile) has no 50-minute renewal
       running of its own - only the master does, and the master serves no
       requests. Without this case the polling worker would coast on the
       inherited token until it expired and a 401 forced a refresh; correct,
       but reactive. Fetching once here re-establishes a live timer in the
       process that actually polls, so renewals stay ahead of expiry.

    Case 3 is self-limiting: fetch_oauth_token() starts a new timer on
    success, so the very next cycle sees a live one and skips. If the fetch
    fails it leaves no timer and no token, and the retry on the next cycle is
    exactly what's wanted.
    """
    if not current_client_id or not dbstore.get_setting("oauth_client_secret"):
        return False  # not an OAuth install; a static token needs no refresh
    if not getattr(healthcheck, "ACCESS_TOKEN", None):
        return True
    if getattr(healthcheck, "ACCESS_TOKEN_CLIENT_ID", None) != current_client_id:
        return True
    renewal_timer = getattr(healthcheck, "TOKEN_RENEWAL_TIMER", None)
    # is_alive() is False for a timer inherited across fork: CPython's
    # threading._after_fork() marks every thread but the current one stopped.
    return renewal_timer is None or not renewal_timer.is_alive()


def run_poll_cycle():
    """Fetch devices + tailnet keys from the Tailscale API and persist them.

    Safe to call directly (e.g. from an admin-triggered "poll now" action)
    regardless of whether this process holds the poller election lock.
    """
    cycle_start = time.monotonic()
    if not (dbstore.is_tailnet_configured() and dbstore.is_auth_configured()):
        # Silent, no API call and no log/poller_log noise: until setup is
        # actually complete, this would otherwise fire (and log) every
        # single POLL_INTERVAL_SECONDS forever on a fresh/unconfigured
        # instance - not actionable, not interesting, just repeats the same
        # "not configured" fact the setup wizard is already showing.
        return

    _record("poll_started", "Poll cycle starting.")
    import healthcheck  # deferred: avoids circular import at module load time

    current_client_id = dbstore.get_setting("oauth_client_id")
    if _needs_oauth_refresh(healthcheck, current_client_id):
        healthcheck.fetch_oauth_token()

    tailnet_domain = dbstore.get_setting("tailnet_domain")
    devices_url = f"https://api.tailscale.com/api/v2/tailnet/{tailnet_domain}/devices"
    keys_url = f"https://api.tailscale.com/api/v2/tailnet/{tailnet_domain}/keys?all=true"
    auth_header = healthcheck.build_auth_header()

    cycle_error = None
    cycle_auth_error = False
    previous_poll_status = dbstore.get_poll_status()

    devices_count = None
    try:
        devices_response = healthcheck.make_authenticated_request(devices_url, dict(auth_header))
        devices = devices_response.json().get("devices") or []
        dbstore.upsert_devices(devices)
        devices_count = len(devices)
        needs_signing_count = sum(1 for d in devices if d.get("tailnetLockError"))
        detail = {"devices_count": devices_count}
        if needs_signing_count:
            detail["needs_signing_count"] = needs_signing_count
        _record("devices_success", f"Fetched {devices_count} device(s).", detail)
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

    was_auth_error = bool(previous_poll_status.get("auth_error"))
    dbstore.set_poll_status(ok=cycle_error is None, error=cycle_error, auth_error=cycle_auth_error)

    notify_cfg = dbstore.get_settings_typed(notifier.NOTIFICATION_SETTINGS + ("tailnet_lock_enabled",))
    if cycle_auth_error and not was_auth_error:
        _notify_entity(
            "poll_auth_error", "poller", "poller", "Tailscale authentication failing",
            f"The last poll cycle failed with an authentication error: {cycle_error}",
            notify_cfg, dbstore.get_last_notified("poll_auth_error"),
        )

    try:
        health_status, health_metrics = healthcheck._compute_health_summary(dbstore.get_devices_snapshot())
        key_status, keys_metrics = healthcheck._compute_keys_summary(dbstore.get_keys_snapshot())
        dbstore.record_metrics_snapshot(health_metrics, keys_metrics)
        _process_device_notifications(notify_cfg, health_status)
        _process_lock_notifications(notify_cfg, health_status)
        _process_key_notifications(notify_cfg, key_status)
        _process_global_notifications(notify_cfg, health_metrics)
    except Exception as e:  # pragma: no cover - defensive, must never break the poll cycle
        logging.warning(f"Poll cycle: failed to record metrics snapshot / process notifications: {e}")
    dbstore.purge_metrics_history()

    now_iso = datetime.now(timezone.utc).isoformat()
    dbstore.set_poll_meta(now_iso)
    dbstore.purge_audit_log()
    dbstore.purge_poller_log()
    dbstore.purge_notification_state()
    dbstore.purge_login_rate_limit()
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
