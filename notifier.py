"""Alerting via an externally-hosted Apprise API instance.

This does NOT bundle the `apprise` Python library - it just POSTs to an
already-running Apprise API server (https://github.com/caronc/apprise-api)
at `{APPRISE_API_URL}/notify/{APPRISE_CONFIG_KEY}`, so channel configuration
(Slack, Discord, email, ...) lives entirely on that server, not here.

notify() is the single entry point poller.py calls after each poll cycle's
health computation; it's a no-op (returns skipped) unless both Apprise is
configured and the event type is one of the admin-selected
notification_events, keeping this fully inert by default.
"""
import fnmatch

import requests

# Event types selectable in notification_events (comma-separated setting).
# device_* events are scoped by notify_include_tags/notify_exclude_tags;
# the rest aren't per-device so tag filtering doesn't apply to them.
EVENT_TYPES = (
    "device_unhealthy",
    "device_healthy_again",
    "key_expiring",
    "device_needs_signing",
    "device_signed",
    "global_unhealthy",
    "global_healthy_restored",
    "poll_auth_error",
)

NOTIFICATION_SETTINGS = (
    "apprise_api_url", "apprise_config_key", "notification_events",
    "notify_include_tags", "notify_exclude_tags",
)


def get_enabled_events(raw: str) -> set:
    selected = {e.strip() for e in (raw or "").split(",") if e.strip()}
    return selected & set(EVENT_TYPES)


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("apprise_api_url", "").strip() and cfg.get("apprise_config_key", "").strip())


def tag_matches(device_tags, include_csv: str, exclude_csv: str) -> bool:
    """Mirrors should_include_device()'s tag matching in healthcheck.py:
    INCLUDE takes precedence over EXCLUDE, globbed against tags with the
    'tag:' prefix stripped."""
    stripped_tags = [t.replace("tag:", "") for t in (device_tags or [])]
    include_csv = (include_csv or "").strip()
    exclude_csv = (exclude_csv or "").strip()

    if include_csv:
        patterns = [p.strip() for p in include_csv.split(",") if p.strip()]
        return bool(patterns) and any(
            any(fnmatch.fnmatch(tag, pattern) for pattern in patterns) for tag in stripped_tags
        )
    if exclude_csv:
        patterns = [p.strip() for p in exclude_csv.split(",") if p.strip()]
        if patterns and any(any(fnmatch.fnmatch(tag, pattern) for pattern in patterns) for tag in stripped_tags):
            return False
    return True


def is_lock_signer(device_tags, lock_signer_tags_csv: str) -> bool:
    """True if any of the device's tags match one of the configured
    LOCK_SIGNER_TAGS patterns. Purely a display label."""
    patterns = [p.strip() for p in (lock_signer_tags_csv or "").split(",") if p.strip()]
    if not patterns:
        return False
    stripped_tags = [t.replace("tag:", "") for t in (device_tags or [])]
    return any(any(fnmatch.fnmatch(tag, pattern) for pattern in patterns) for tag in stripped_tags)


def _send(cfg: dict, title: str, body: str):
    url = f"{cfg['apprise_api_url'].rstrip('/')}/notify/{cfg['apprise_config_key']}"
    response = requests.post(url, json={"title": title, "body": body}, timeout=10)
    response.raise_for_status()


def notify(event_type: str, title: str, body: str, cfg: dict, device_tags=None):
    """Send a notification for `event_type` if configured, enabled, and (for
    device-scoped events) tag-filter-matched. Returns (sent, reason) where
    `reason` explains a skip, or the exception message on a send failure -
    never raises, so a bad Apprise endpoint can't break polling."""
    if not is_configured(cfg):
        return False, "not_configured"
    if event_type not in get_enabled_events(cfg.get("notification_events", "")):
        return False, "event_not_enabled"
    if device_tags is not None and not tag_matches(device_tags, cfg.get("notify_include_tags", ""), cfg.get("notify_exclude_tags", "")):
        return False, "tag_filtered"
    try:
        _send(cfg, title, body)
        return True, None
    except Exception as e:
        return False, str(e)
