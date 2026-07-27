"""Alerting via an externally-hosted Apprise API instance's *stateless*
endpoint (https://github.com/caronc/apprise-api).

This does NOT bundle the `apprise` Python library, and does NOT rely on any
server-side persistent config - each request carries the actual Apprise
service URLs (e.g. tgram://bottoken/ChatID, mailto://user:pass@host) in
`apprise_notification_urls`, POSTed straight to `{APPRISE_API_URL}/notify`.
An optional `apprise_bearer_token` is only for authenticating to the Apprise
API instance itself, if it requires that.

notify() is the single entry point poller.py calls after each poll cycle's
health computation; it's a no-op (returns skipped) unless both Apprise is
configured and the event type is one of the admin-selected
notification_events, keeping this fully inert by default. test() bypasses
the event/tag gating for the settings page's "Send test notification" button.
"""
import fnmatch
import re

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
    "apprise_api_url", "apprise_notification_urls", "apprise_bearer_token", "notification_events",
    "notify_include_tags", "notify_exclude_tags", "notification_cooldown_minutes",
)


def get_enabled_events(raw: str) -> set:
    selected = {e.strip() for e in (raw or "").split(",") if e.strip()}
    return selected & set(EVENT_TYPES)


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("apprise_api_url", "").strip() and cfg.get("apprise_notification_urls", "").strip())


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


# scheme://user:pass@host - the userinfo half of any URL in an error message.
_URL_USERINFO_RE = re.compile(r"(\w+://)[^/\s:@]+:[^/\s@]+@")


def sanitize_error(exc: Exception, cfg: dict) -> str:
    """Render `exc` as a log-safe string.

    Failure reasons from here are persisted to dbstore.poller_log and shown on
    the /debug page and the settings page, so they must not carry credentials.
    `requests` embeds the request URL in its exception messages, and both
    apprise_api_url and the configured service URLs can contain inline
    credentials (mailto://user:pass@host). Host/status detail is kept - it's
    what makes the log actionable - but userinfo and any configured secret
    value are replaced with ***.
    """
    text = f"{type(exc).__name__}: {exc}"
    response = getattr(exc, "response", None)
    if response is not None:
        text = f"{type(exc).__name__}: HTTP {response.status_code}"
    text = _URL_USERINFO_RE.sub(r"\1***@", text)
    secrets_to_mask = [cfg.get("apprise_bearer_token", "")]
    secrets_to_mask += (cfg.get("apprise_notification_urls", "") or "").split(",")
    for secret in secrets_to_mask:
        secret = (secret or "").strip()
        if len(secret) > 3:
            text = text.replace(secret, "***")
    return text


def _send(cfg: dict, title: str, body: str):
    url = f"{cfg['apprise_api_url'].rstrip('/')}/notify"
    headers = {}
    bearer_token = (cfg.get("apprise_bearer_token") or "").strip()
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    payload = {"urls": cfg["apprise_notification_urls"], "title": title, "body": body}
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    response.raise_for_status()


def notify(event_type: str, title: str, body: str, cfg: dict, device_tags=None):
    """Send a notification for `event_type` if configured, enabled, and (for
    device-scoped events) tag-filter-matched. Returns (sent, reason) where
    `reason` explains a skip, or a sanitize_error()'d failure reason on a send
    failure - never raises, so a bad Apprise endpoint can't break polling."""
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
        return False, sanitize_error(e, cfg)


def test(cfg: dict):
    """Send a one-off test notification, bypassing notification_events/tag
    gating (used by the settings page's "Send test notification" button) -
    still requires apprise_api_url + apprise_notification_urls to be set."""
    if not is_configured(cfg):
        return False, "not_configured"
    try:
        _send(cfg, "Tailscale Healthcheck test notification", "If you can see this, your Apprise setup works.")
        return True, None
    except Exception as e:
        return False, sanitize_error(e, cfg)
