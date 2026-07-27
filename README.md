# 🚀 Tailscale Healthcheck – A Dockerized Monitoring Helper Tool

<p align="center">
  <img src="https://img.shields.io/github/stars/laitco/tailscale-healthcheck?style=social" alt="GitHub Stars">
  <img src="https://img.shields.io/github/actions/workflow/status/laitco/tailscale-healthcheck/release.yaml?branch=main" alt="GitHub Workflow Status">
  <img src="https://img.shields.io/docker/pulls/laitco/tailscale-healthcheck" alt="Docker Pulls">
  <img src="https://img.shields.io/github/license/laitco/tailscale-healthcheck" alt="License">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python Version">
  <img src="https://img.shields.io/badge/code%20style-flake8-blue" alt="Code Style">
  <img src="https://img.shields.io/badge/coverage-90%25-brightgreen" alt="Test Coverage">
  <img src="https://img.shields.io/github/last-commit/laitco/tailscale-healthcheck" alt="Last Commit">
  <img src="https://img.shields.io/github/issues/laitco/tailscale-healthcheck" alt="Open Issues">
</p>

<p align="center">
  <img src=".github/images/tailscale_healthcheck_logo.png" alt="Tailscale Healthcheck Logo" width="630">
</p>

## 📖 Table of Contents
- [✨ Description](#-description)
- [🌟 Features](#-features)
- [📡 Endpoints](#-endpoints)
  - [`/health`](#health)
  - [`/keys`](#keys)
  - [`/health/<identifier>`](#healthidentifier)
  - [`/health/healthy`](#healthhealthy)
  - [`/health/unhealthy`](#healthunhealthy)
  - [`/health/cache/invalidate`](#healthcacheinvalidate)
  - [`/admin`](#admin)
- [⚙️ Configuration](#️-configuration)
  - [Process bootstrap (env-only)](#process-bootstrap-env-only)
  - [Security](#security)
  - [Logging](#logging)
  - [Rate Limiting](#rate-limiting)
  - [Notifications](#notifications)
  - [Background Polling](#background-polling)
  - [Read-Only Proxy](#read-only-proxy)
- [🔐 Admin UI](#-admin-ui)
  - [Response Metrics](#response-metrics)
  - [Using OAuth for Authentication](#using-oauth-for-authentication-recommended)
  - [Creating a Tailscale OAuth Client](#creating-a-tailscale-oauth-client)
  - [Generating the Tailscale API Key](#generating-the-tailscale-api-key)
  - [Filter Configuration Examples](#filter-configuration-examples)
- [🐳 Running with Docker](#-running-with-docker)
  - [Upgrading](#upgrading-recreate-the-container-dont-just-restart-it)
  - [Storage & permissions](#storage--permissions)
  - [Run with Docker Compose](#run-with-docker-compose)
  - [Build and Run Locally](#build-and-run-locally)
  - [Run from Docker Hub](#run-from-docker-hub)
- [📡 Integration with Gatus Monitoring System](#-integration-with-gatus-monitoring-system)
- [🔧 Development](#-development)
  - [Linting](#linting)
  - [Testing](#testing)
- [📜 License](#-license)
- [🤝 Contributing](#-contributing)

## ✨ Description

A Python-based Flask application to monitor the health of devices in a Tailscale network. The application provides endpoints to check the health status of all devices, specific devices, and lists of healthy or unhealthy devices.

> Release notes have moved to the [GitHub Releases page](https://github.com/laitco/tailscale-healthcheck/releases).

> This project's code is largely AI-written (Claude Code), with a human in the loop driving requirements, design decisions, review, and testing.

## 🌟 Features

- **Overall Health Status**: Combined health status based on:
  - Device online status (`online_healthy`)
  - Device key expiry status (`key_healthy`)
  - Device update status (`update_healthy`, optional)
- **Global Health Metrics**: 
  - Global device health status (`global_healthy`)
  - Global online status (`global_online_healthy`)
  - Global key health status (`global_key_healthy`)
  - Global update status (`global_update_healthy`)
- **Update Status**:
  - Update availability status
  - Client version tracking
  - Update health filtering with wildcards
  - Include/exclude update filter support by identifier and tags
- **Device Filtering**:
  - OS-based filtering with wildcards
  - Device identifier filtering (hostname, ID, name)
  - Tag-based filtering with wildcards
  - Include/exclude filter support
- **Key expiry**: Days until key expiry (`key_days_to_expire`)
- **Counter Metrics**: Detailed counters for healthy/unhealthy devices
- **Health Status**: Check the health of all devices in the Tailscale network.
- **Device Lookup**: Query the health of a specific device by hostname, ID, or name (case-insensitive).
- **Healthy Devices**: List all healthy devices.
- **Unhealthy Devices**: List all unhealthy devices.
- **Timezone Support**: Adjust `lastSeen` timestamps to a configurable timezone.
- **Background Polling + SQLite Persistence**:
  - Device and tailnet key data is refreshed from the Tailscale API by a background poller (`POLL_INTERVAL_SECONDS`, default 60s) and persisted to SQLite - `/health`, `/keys`, and the dashboard all read from that snapshot instead of calling the Tailscale API per request
  - Manual poll-now endpoint (`/health/cache/invalidate`, kept at this URL for backward compatibility)
  - Rolling 24h aggregate metrics history for the dashboard's trend tiles, purged after 48h
- **Web-based Admin UI** (`/admin`):
  - First-run setup wizard when no tailnet/auth is configured (env or database) and/or no admin user exists yet
  - Full settings editor covering every configurable behavior (connection, thresholds, filters, rate limiting, retry/backoff, polling, logging) grouped by category - env vars always take precedence; DB-backed values persist across container restarts and survive env var removal
  - User management (Flask-Login session auth)
  - Audit log of device/key/setting/user changes, rendered as a readable diff (field: old → new) with a raw-JSON toggle, filterable by entity type, entity id, action, actor, changed field, free-text search over the change contents, and date range (all combinable, and reflected in the URL so a filtered view is shareable), auto-purged after `AUDIT_RETENTION_DAYS` (default 14)
  - Interactive API docs page (`/admin/api-docs`) with "Try it" against the live API
  - Debug page (`/debug`) showing the background poller's recent activity log (persisted, not in-memory), filterable by event type
  - A visible banner on the dashboard and settings page when the poller can't reach the Tailscale API, calling out auth-credential problems specifically
  - User profile page (`/admin/profile`): change password, and enroll/disable TOTP-based two-factor authentication (with one-time recovery codes shown on enrollment); MFA-enabled accounts get a second login step
- **Tailnet Key Filters**: `INCLUDE_KEY_TYPE`/`EXCLUDE_KEY_TYPE`/`INCLUDE_KEY_DESCRIPTION`/`EXCLUDE_KEY_DESCRIPTION` narrow which tailnet API/auth keys are reported, mirroring the device filters below.

## 📡 Endpoints

### `/health`
Returns the health status of all devices.

**Example Response**:
```json
{
  "devices": [
    {
      "id": "1234567890",
      "device": "examplehostname.example.com",
      "machineName": "examplehostname",
      "hostname": "examplehostname",
      "os": "macOS",
      "clientVersion": "v1.36.0",
      "updateAvailable": false,
      "update_healthy": true,
      "lastSeen": "2025-04-09T22:03:57+02:00",
      "online_healthy": true,
      "keyExpiryDisabled": false,
      "keyExpiryTimestamp": "2025-05-09T22:03:57+02:00",
      "key_healthy": true,
      "key_days_to_expire": 25,
      "tailnetLockError": "",
      "lock_healthy": true,
      "tailnetLockEnabled": false,
      "isLockSigner": false,
      "healthy": true,
      "tags": ["user-device", "admin-device"]
    }
  ],
  "metrics": {
    "counter_healthy_true": 1,
    "counter_healthy_false": 0,
    "counter_healthy_online_true": 1,
    "counter_healthy_online_false": 0,
    "counter_key_healthy_true": 1,
    "counter_key_healthy_false": 0,
    "counter_update_healthy_true": 1,
    "counter_update_healthy_false": 0,
    "counter_lock_healthy_true": 1,
    "counter_lock_healthy_false": 0,
    "global_key_healthy": true,
    "global_online_healthy": true,
    "global_healthy": true,
    "global_update_healthy": true,
    "global_lock_healthy": true
  }
}
```
`tailnetLockError` reflects the Tailscale API's own device data regardless of app configuration: empty unless the tailnet actually has [Tailnet Lock](https://tailscale.com/kb/1226/tailnet-lock) enabled and that device's node-key signature is missing/invalid. `lock_healthy` (and therefore `healthy`), on the other hand, only reacts to a non-empty `tailnetLockError` once `TAILNET_LOCK_ENABLED=YES` is set - by default it's always `true`. There's no way to determine *which* devices are the tailnet's trusted signing nodes via the public API (that's only exposed by the `tailscale lock status` CLI, not this HTTP API) - this app can only report whether a given device still needs to be signed.

Full settings (including secrets, masked) are no longer embeddable in this response - view/edit them at `/admin/settings` (login required) or browse `GET /admin/api/settings` instead.

### `/keys`
Returns the health status of tailnet API and auth keys (from the Tailscale [`GET /tailnet/{tailnet}/keys?all=true`](https://tailscale.com/api#tag/keys/GET/tailnet/{tailnet}/keys) endpoint, listing all keys in the tailnet, not just the caller's own). Only `api` and `auth` key types are reported (`client`/OAuth-client keys are excluded). A key is `key_healthy: false` once its expiry is at or below `KEY_EXPIRY_WARNING_DAYS` days out; keys without an `expires` field never expire and are always healthy.

If `TAILNET_DOMAIN` is left at its default (`example.com`), or the tailnet simply has no API/auth keys, this returns an empty `keys` list rather than an error — check `metrics.tailnet_configured` and `metrics.has_keys` to distinguish the two cases.

**Required permissions**: the credential you configure (`AUTH_TOKEN` or OAuth client) needs read access to *Keys* in addition to *Devices*, or this endpoint returns a `403`:
- Personal API access token: when creating it at [Settings → Keys](https://login.tailscale.com/admin/settings/keys), grant it the **Keys** capability (read access is enough).
- OAuth client: when creating it at [Settings → OAuth clients](https://login.tailscale.com/admin/settings/oauth), in addition to `devices:core` read, grant `read` on **API Access Tokens** and `read` on **Auth Keys**.

**Example Response**:
```json
{
  "keys": [
    {
      "id": "k123456CNTRL",
      "description": "my-auth-key",
      "keyType": "auth",
      "created": "2025-04-01T10:00:00Z",
      "expires": "2025-07-01T10:00:00+02:00",
      "key_days_to_expire": 12,
      "key_healthy": false
    }
  ],
  "metrics": {
    "total_keys": 1,
    "counter_key_healthy_true": 0,
    "counter_key_healthy_false": 1,
    "global_keys_healthy": false,
    "has_keys": true,
    "key_expiry_warning_days": 30,
    "tailnet_configured": true
  }
}
```

**Upstream errors**: if the Tailscale API itself rejects a request (e.g. `403` for a missing scope/capability, as above), the app passes through the real upstream status code and message instead of masking it as a `500`:
```json
{
  "error": "requested scope is not granted for the given API access token",
  "upstream_status": 403
}
```
This passthrough applies to `/health`, `/keys`, and their variants (`/health/<identifier>`, `/health/healthy`, `/health/unhealthy`), as well as the dashboard and device detail pages (rendered as an error page with the same status code).

### `/health/<identifier>`
Returns the health status of a specific device by hostname, ID, name, or machine name (the part of the name before the first dot). Matching is case-insensitive. A device excluded by the device filters (`INCLUDE_OS`/`EXCLUDE_TAGS`/…) is not addressable here and returns `404`, the same as an unknown identifier. Its `metrics` block is scoped to the single returned device.

### `/health/healthy`
Returns the devices currently reported as healthy, plus the same tailnet-wide `metrics` block `/health` returns.

### `/health/unhealthy`
Returns the devices currently reported as unhealthy, plus the same tailnet-wide `metrics` block `/health` returns.

> **Note (behaviour change):** `/health/healthy`, `/health/unhealthy` and `/health/<identifier>` are
> now views over exactly the same computation as `/health`. Two things changed as a result:
> the device include/exclude filters now apply to all of them (previously only `/health` honoured
> them, so an excluded device could still fail a check against `/health/unhealthy`), and their
> `metrics` counters now describe the whole tailnet rather than just the returned subset. The
> latter is what makes `global_healthy` meaningful on `/health/healthy` - it was structurally
> always `true` before, because the false-counters could never be incremented there.

### `/health/cache/invalidate`
Triggers an immediate out-of-band poll of the Tailscale API instead of waiting for the next `POLL_INTERVAL_SECONDS` tick. Kept at this URL/method for backward compatibility with existing monitoring configs.

### `/admin`
Web UI for first-run setup, login, settings, user management, and the audit log. See [Admin UI](#-admin-ui) below.

## ⚙️ Configuration

The application is configured using environment variables:

| Variable             | Default Value      | Description                                                                 |
|----------------------|--------------------|-----------------------------------------------------------------------------|
| `TAILNET_DOMAIN`     | `example.com`     | The Tailscale tailnet domain. If unset (or left at the default), the setup wizard at `/admin/setup` prompts for it and saves it to the database. |
| `AUTH_TOKEN`         | None              | The Tailscale API token (required if OAuth is not configured and not set via the setup wizard/settings UI). |
| `OAUTH_CLIENT_ID`    | None              | The OAuth client ID (required if using OAuth and not set via the setup wizard/settings UI). |
| `OAUTH_CLIENT_SECRET`| None              | The OAuth client secret (required if using OAuth and not set via the setup wizard/settings UI). |
| `DATABASE_PATH`      | `/data/healthcheck.db` (Docker) | Path to the SQLite database (settings, users, device/key snapshots, audit log). Mount a volume at `/data` to persist it. |
| `SECRET_KEY`         | auto-generated    | Signs admin session cookies. If unset, a random key is generated on first boot and persisted to the database so all Gunicorn workers share it. |
| `API_BASE_URL`       | `""`              | Public base URL for this instance (e.g. behind a reverse proxy). Used for example commands and "Try it" calls on the API docs page (`/admin/api-docs`). Blank uses the current page's origin. |
| `POLL_INTERVAL_SECONDS` | `60`           | How often the background poller refreshes devices/tailnet keys from the Tailscale API into SQLite. |
| `AUDIT_RETENTION_DAYS` | `14`            | How long audit log entries are kept before being purged. Also editable via `/admin/settings`. |
| `POLLER_LOG_RETENTION_DAYS` | `7`         | How long the poller's operational activity log (shown on `/debug`) is kept before being purged. Also editable via `/admin/settings`. |
| `HEALTH_ENDPOINT_TOKEN` | `""` (disabled) | Optional shared secret guarding the public `/health` endpoint. When set, requests must include a matching `X-Health-Token` header or get `401`. Also editable via `/admin/settings`. |
| `TRUSTED_PROXY_COUNT` | `0`              | Number of reverse proxies in front of the app. `0` trusts nothing and uses the direct peer address; set it to your real proxy count (usually `1`) so per-IP rate limits and the failed-login lockout key off the actual client. Needs a restart. See [Security](#security). |
| `SESSION_COOKIE_SECURE` | `NO`           | Add the `Secure` flag to the admin session cookie. Set `YES` when serving over HTTPS. Needs a restart. |
| `SESSION_LIFETIME_MINUTES` | `43200`     | Admin session lifetime in minutes (default 30 days). Needs a restart.       |
| `LOG_LEVEL`          | `INFO`            | Root log level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Changes via `/admin/settings` persist but need a process restart to take effect. |
| `DEBUG_LOG_ENABLED`  | `YES`             | Whether the background poller records into its in-memory activity log, shown on the `/debug` page. Applies immediately (no restart needed). |
| `HTTP_TIMEOUT`       | `10`              | Timeout in seconds applied to all outbound HTTP requests.                  |
| `MAX_RETRIES`        | `3`               | Maximum total attempts for outbound authenticated requests (bounded).      |
| `BACKOFF_BASE_SECONDS` | `0.5`           | Initial backoff delay in seconds between retry attempts.                   |
| `BACKOFF_MAX_SECONDS`  | `8.0`           | Maximum backoff delay cap in seconds.                                      |
| `BACKOFF_JITTER_SECONDS` | `0.1`        | Random jitter (0..value) added to each backoff delay.                      |
| `ONLINE_THRESHOLD_MINUTES`  | `5`               | The threshold in minutes to determine online health.                       |
| `KEY_THRESHOLD_MINUTES`     | `1440`            | The threshold in minutes to determine key expiry health.                  |
| `KEY_EXPIRY_WARNING_DAYS`   | `30`              | The threshold in days at or below which a tailnet API/auth key (`/keys`) is considered unhealthy. |
| `GLOBAL_HEALTHY_THRESHOLD`  | `100`             | The threshold for total unhealthy.                               |
| `GLOBAL_ONLINE_HEALTHY_THRESHOLD`| `100`        | The threshold for total online health.                                       |
| `GLOBAL_KEY_HEALTHY_THRESHOLD`   | `100`        | The threshold for total key health.                             |
| `GLOBAL_UPDATE_HEALTHY_THRESHOLD`| `100`        | The threshold for total update health.                             |
| `UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH`| `NO` | Whether update health is included in overall health status. Example: `YES`                             |
| `TAILNET_LOCK_ENABLED`      | `NO`         | Explicit opt-in: set to `YES` if you use [Tailnet Lock](https://tailscale.com/kb/1226/tailnet-lock). Off by default, so a device needing a signature has no effect on health unless you confirm you use it. Also settable from the setup wizard or `/admin/settings`. |
| `GLOBAL_LOCK_HEALTHY_THRESHOLD`  | `100`        | The threshold for total Tailnet Lock health, only relevant when `TAILNET_LOCK_ENABLED=YES` (a device needing a signature is unhealthy). |
| `LOCK_SIGNER_TAGS`   | `""`              | Comma-separated, wildcard tag patterns labeling which devices are trusted Tailnet Lock signers (a "Signer" badge on the devices table/device detail page) - admin-provided, since the Tailscale API has no endpoint for this (only the `tailscale lock status` CLI does). |
| `APPRISE_API_URL`    | `""`              | Base URL of an already-running [Apprise API](https://github.com/caronc/apprise-api) instance to alert through, e.g. `http://apprise:8000`. Leave blank (with `APPRISE_NOTIFICATION_URLS`) to keep alerting off - this app doesn't bundle the `apprise` library itself, it just POSTs to that instance's stateless endpoint. |
| `APPRISE_NOTIFICATION_URLS` | `""`       | One or more Apprise service URLs (comma-separated), e.g. `tgram://bottoken/ChatID`, `mailto://user:pass@host`, `slack://...` - sent straight through on every notification, no server-side config needed. |
| `APPRISE_BEARER_TOKEN` | `""`            | Optional - only if the Apprise API instance itself requires bearer-token auth. Unrelated to the notification URLs above. |
| `NOTIFICATION_EVENTS`| `""`              | Comma-separated subset of: `device_unhealthy`, `device_healthy_again`, `key_expiring`, `device_needs_signing`, `device_signed`, `global_unhealthy`, `global_healthy_restored`, `poll_auth_error`. Only listed events actually notify; empty means none do. |
| `NOTIFY_INCLUDE_TAGS`| `""`              | Comma-separated, wildcard tag patterns scoping which devices' transitions notify (the four `device_*`/`key_expiring`... events above that are per-device; global/poll events aren't device-scoped, so this doesn't affect them). |
| `NOTIFY_EXCLUDE_TAGS`| `""`              | Same, but exclude. `NOTIFY_INCLUDE_TAGS` takes precedence if both are set. |
| `PORT`               | `5000`            | The port the application runs on. Process bootstrap only - not part of the settings registry, not editable via `/admin/settings`. |
| `TIMEZONE`           | `UTC`             | The timezone for `lastSeen` adjustments. Example: `Europe/Berlin`                                  |
| `INCLUDE_OS`         | `""`              | Filter to include only specific operating systems (comma-separated, wildcards allowed) |
| `EXCLUDE_OS`         | `""`              | Filter to exclude specific operating systems (comma-separated, wildcards allowed)      |
| `INCLUDE_IDENTIFIER` | `""`              | Filter to include only specific devices by identifier (comma-separated, wildcards allowed) |
| `EXCLUDE_IDENTIFIER` | `""`              | Filter to exclude specific devices by identifier (comma-separated, wildcards allowed)  |
| `INCLUDE_TAGS`       | `""`              | Filter to include only specific devices by tags (comma-separated, wildcards allowed) |
| `EXCLUDE_TAGS`       | `""`              | Filter to exclude specific devices by tags (comma-separated, wildcards allowed)  |
| `INCLUDE_IDENTIFIER_UPDATE_HEALTHY` | `""`              | Filter to include only specific devices by identifier for update health (comma-separated, wildcards allowed) |
| `EXCLUDE_IDENTIFIER_UPDATE_HEALTHY` | `""`              | Filter to exclude specific devices by identifier for update health (comma-separated, wildcards allowed)  |
| `INCLUDE_TAG_UPDATE_HEALTHY`       | `""`              | Filter to include only specific devices by tags for update health (comma-separated, wildcards allowed) |
| `EXCLUDE_TAG_UPDATE_HEALTHY`       | `""`              | Filter to exclude specific devices by tags for update health (comma-separated, wildcards allowed)  |
| `INCLUDE_KEY_TYPE`   | `""`              | Filter to include only specific tailnet key types (`api`/`auth`, comma-separated, wildcards allowed) |
| `EXCLUDE_KEY_TYPE`   | `""`              | Filter to exclude specific tailnet key types (comma-separated, wildcards allowed) |
| `INCLUDE_KEY_DESCRIPTION` | `""`         | Filter to include only tailnet keys whose description matches (comma-separated, wildcards allowed) |
| `EXCLUDE_KEY_DESCRIPTION` | `""`         | Filter to exclude tailnet keys whose description matches (comma-separated, wildcards allowed) |

All of the above (except `PORT` and the Gunicorn flags) are also viewable/editable at runtime via `/admin/settings`, grouped by category; fields sourced from an env var are shown as read-only there since the env var always wins.

### Process bootstrap (env-only)

These are read by the container entrypoint / Gunicorn itself rather than the settings registry, so
they are **not** editable from `/admin/settings` and always require a restart:

| Variable                    | Default | Description                                                                 |
|-----------------------------|---------|-----------------------------------------------------------------------------|
| `PORT`                      | `5000`  | Port the app binds to.                                                       |
| `DATABASE_PATH`             | `/data/healthcheck.db` | SQLite database location. Mount a volume here to persist config, users, and history. |
| `SECRET_KEY`                | *(generated)* | Flask session signing key. Generated and stored in the database on first run if unset. |
| `GUNICORN_TIMEOUT`          | `60`    | Worker timeout in seconds.                                                   |
| `GUNICORN_GRACEFUL_TIMEOUT` | `30`    | Grace period for workers to finish in-flight requests on shutdown.           |
| `GUNICORN_MASTER_PROCESS`   | *(unset)* | Internal marker used by the Gunicorn hooks; not normally set by hand.      |

### Security

- **`TRUSTED_PROXY_COUNT`** (default `0`): set this to the number of reverse proxies in front of the
  app (usually `1` behind nginx/Traefik/Caddy). It matters more than it looks: `remote_addr` drives
  both the rate limiters **and** the failed-login lockout, so if you run behind a proxy and leave
  this at `0`, every client appears to be the proxy - one attacker's failed logins lock out every
  user, and the per-IP request limit silently becomes a single global one. Don't set it higher than
  your real proxy count; the extra `X-Forwarded-For` hops are client-controlled and can be forged.
- **`SESSION_COOKIE_SECURE`** (default `NO`): set to `YES` when serving over HTTPS so the session
  cookie carries the `Secure` flag. It defaults off because a plain-HTTP LAN deployment would
  otherwise be unable to log in at all.
- **`SESSION_LIFETIME_MINUTES`** (default `43200`, i.e. 30 days): how long an admin session stays
  valid. Lower it if sessions should expire sooner.
- All responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, and a nonce-based `Content-Security-Policy`. Everything the UI
  loads is served from the app's own origin, so no external CDN/font/script hosts are permitted.
- All three security settings are read once at startup: saving them in `/admin/settings` persists
  the value immediately but takes effect only after a restart.

### Logging

- Default log level is `INFO` in both Flask and Gunicorn.
- Enable debug logging explicitly by setting `LOG_LEVEL=DEBUG`.
- Sensitive values are masked where logged; avoid enabling DEBUG in production.

### Rate Limiting

- Protects against abusive or accidental high-frequency requests.
- Returns JSON 429 with `{ "error": "Too Many Requests" }`.

Environment variables:
- `RATE_LIMIT_ENABLED`: Enable/disable rate limiting. Default `YES`.
- `RATE_LIMIT_PER_IP`: Integer requests per minute per client IP. Default `100`. `0` disables.
- `RATE_LIMIT_GLOBAL`: Optional integer requests per minute across all clients/endpoints. Empty/`0` disables.
- `RATE_LIMIT_STORAGE_URL`: Optional storage for shared enforcement across processes/instances.
  - Default: `file:///tmp/tailscale-healthcheck-ratelimit.json` (file-backed on single host)
  - Redis: `redis://host:6379/0` (Flask-Limiter)
  - Empty: in-memory per-process
- `RATE_LIMIT_HEADERS_ENABLED`: Include standard rate-limit headers when Flask-Limiter is active. Default `YES`.

Notes:
- Per-IP and global limits can be used together; exceeding either returns `429`.
- With multiple Gunicorn workers:
  - Without storage configured, limits apply per worker (in-memory).
  - With `redis://`, limits are shared across workers/instances (Flask-Limiter backend).
  - With `file://`, limits are shared on a single host via a JSON file with file locking.

### Notifications

- Alerts fire through an already-running [Apprise API](https://github.com/caronc/apprise-api) instance's *stateless* endpoint - this app POSTs `{urls, title, body}` to `<APPRISE_API_URL>/notify` after each poll cycle. It does not bundle the `apprise` Python library and needs no server-side config: `APPRISE_NOTIFICATION_URLS` carries the actual Apprise service URL(s) (e.g. `tgram://`, `mailto://`, `slack://`) directly.
- Off by default: leave `APPRISE_API_URL`/`APPRISE_NOTIFICATION_URLS` blank, or `NOTIFICATION_EVENTS` empty, and nothing fires.
- Fires once per *transition*, not on every poll cycle while a condition persists - e.g. a device staying unhealthy for an hour notifies once, not every `POLL_INTERVAL_SECONDS`. Nothing notifies on a device/key's first-ever appearance (avoids a notification storm on rollout).
- `NOTIFY_INCLUDE_TAGS`/`NOTIFY_EXCLUDE_TAGS` scope the four per-device event types (`device_unhealthy`, `device_healthy_again`, `device_needs_signing`, `device_signed`) to a subset of devices; `global_unhealthy`, `global_healthy_restored`, `key_expiring`, and `poll_auth_error` aren't device-scoped and always notify regardless of these filters.
- `device_needs_signing`/`device_signed` only fire when `TAILNET_LOCK_ENABLED=YES`, same as the rest of Tailnet Lock's behavior.
- A failed delivery (Apprise instance unreachable, etc.) is logged as a `notification_failed` event on the `/debug` page rather than retried - it won't block or slow down polling.
- `NOTIFICATION_COOLDOWN_MINUTES` (default `0`, off) sets a minimum gap between two notifications for the same event + device/key pair. Transitions already don't re-alert while a condition persists, but a device *flapping* across the healthy line alerts once per flap; a cooldown collapses those into one per window. Suppressed alerts appear on `/debug` as `notification_suppressed` events, so a quiet period is visibly a cooldown rather than a broken notifier.
- A "Send test notification" button on `/admin/settings` fires a one-off test through `POST /admin/api/notifications/test`, bypassing `NOTIFICATION_EVENTS`/tag filtering - it uses whatever's currently in the form (even unsaved), falling back to the saved value for any field left blank.

### Background Polling

- A background poller (one process/worker, elected via a file lock so it only runs once even with multiple Gunicorn workers) refreshes devices and tailnet keys from the Tailscale API into SQLite every `POLL_INTERVAL_SECONDS` (default 60s).
- `/health`, `/keys`, and the dashboard read from that SQLite snapshot - the Tailscale API is never called directly from a request.
- Manual refresh: call `GET /health/cache/invalidate` to trigger an immediate out-of-band poll.
- All 4 Gunicorn workers share the same SQLite database (WAL mode) for reads and writes.

### Read-Only Proxy

- Every route except `/admin/*` enforces read-only access: only `GET`, `HEAD`, and `OPTIONS` are allowed. Modifying methods (`POST`, `PUT`, `PATCH`, `DELETE`) are blocked with `403 Forbidden` and attempts are logged for auditing. This behavior is not user-configurable by design.
- `/admin/*` is the one exception: it's where the setup wizard, login, settings, user management, and audit log live, and it legitimately needs `POST`/`DELETE`. It's protected by login instead (see [Admin UI](#-admin-ui)).
- **The entire JSON API family stays public and unauthenticated by default**: `/health`, `/health/` (redirect), `/health/<identifier>`, `/health/healthy`, `/health/unhealthy`, `/health/cache/invalidate`, and `/keys` - that's the contract existing monitoring integrations (Gatus, etc.) depend on. Only the human dashboard (`/`, `/dashboard`, `/devices`, `/tailnet-keys`, `/debug`, `/device/<identifier>`) and `/admin/*` (except the setup/login endpoints themselves) require a logged-in session.
- The whole JSON API family can optionally be locked down with `HEALTH_ENDPOINT_TOKEN` (see Configuration) without requiring a login session - useful if you want to keep it out of a login flow (for monitoring tools) but still restrict who can query it. Leave it unset to keep it fully open, as it is by default.

## 🔐 Admin UI

`/admin` hosts the configuration wizard, login, settings, user management, and audit log - all backed by the SQLite database at `DATABASE_PATH`.

- **First run**: if no tailnet/auth is configured (via env var or a previous wizard run) and/or no admin user exists yet, visiting the dashboard redirects to `/admin/setup`. The wizard validates the tailnet domain and API token/OAuth credentials against the real Tailscale API before saving, then creates the first admin user.
- **Env vs. database**: whenever a setting is set as an environment variable, it always takes precedence and is synced into the database on every boot. If you later remove the env var, the last-synced value keeps being used - nothing reverts to "unconfigured". Settings sourced from an env var can't be edited in `/admin/settings` (the UI marks them read-only with the env var name); settings entered via the wizard/settings UI can be edited freely. This applies to every setting in `dbstore.py`'s `SETTINGS_REGISTRY` - connection info, health thresholds, device/key filters, rate limiting, retry/backoff, timezone, HTTP timeout, logging, and polling/audit config - not just the original tailnet connection fields.
- **Settings that need a restart**: rate-limiting (`RATE_LIMIT_*`) and `LOG_LEVEL` are wired up once at process startup, so saving a change persists it immediately but it only takes effect after the process restarts; `/admin/settings` flags these fields accordingly. Everything else (thresholds, filters, timezone, HTTP timeout, retry/backoff, poll interval, audit retention, health endpoint token, debug log capture) applies on the next request/poll cycle with no restart.
- **Users**: manage additional admin accounts at `/admin/users`. The last remaining user can't be deleted (to avoid a lockout); if the user table is ever emptied some other way, the setup wizard reappears to create a new one.
- **Audit log**: `/admin/audit` shows device/tailnet-key/setting/user changes as a readable diff (per-field "old → new" for updates, a compact summary for created/removed entries, a raw-JSON toggle for the exact data), filterable by entity type, entity id, action, actor (a specific username, or "poller" for automatic changes), changed field, free-text search over the change contents, and date range - all combinable.
  - **Changed field** narrows to entries that touched one specific field, e.g. only `os` changes or only `update_available` flips, across both the "old → new" update entries and the created/removed snapshots. Settings are excluded from this select, since a setting's "field" is its name - filter those by entity id instead.
  - **Changes contain** is a substring search over the change data itself, so it matches *values* as well as field names: a hostname, a client version, or the old/new value of a setting. It's case-insensitive, and `%`/`_` are treated literally rather than as wildcards.
  - Every filter (plus the current page) is stored in the query string, so a dug-out view is a shareable link and survives a reload or back/forward navigation. Only meaningful field changes are recorded (not noisy fields like `lastSeen`, and repeat pollings that produce no change never add a duplicate row); entries older than `AUDIT_RETENTION_DAYS` (default 14, editable in `/admin/settings`) are purged automatically as part of each poll cycle.
- **API docs**: `/admin/api-docs` documents every `/health*`/`/keys` endpoint (description + params on the left, an interactive "Try it" panel on the right) with example responses and a "Try it" button that calls the live API using the configured `API_BASE_URL` (or the current origin); when `HEALTH_ENDPOINT_TOKEN` is set, an `X-Health-Token` input appears for the `/health` "Try it" panel.
- **Debug page**: `/debug` shows the background poller's recent activity (persisted in the `poller_log` table, not just in-memory - so it survives worker restarts), filterable by event type (`poll_started`, `devices_success`, `devices_error`, `keys_success`, `keys_error`, `poll_completed`, `poll_skipped`); capture is controlled by `DEBUG_LOG_ENABLED`, retention by `POLLER_LOG_RETENTION_DAYS` (default 7).
- **Connectivity banner**: if the background poller's most recent cycle failed - especially with a 401/403 (bad/missing/revoked credentials) - the dashboard and `/admin/settings` show a banner pointing at the fix, driven by real poll outcomes (`GET /health`'s `poll_meta.last_poll_auth_error`) rather than a frontend guess.
- **Health endpoint token generator**: `/admin/settings` has a "Generate" button next to the `HEALTH_ENDPOINT_TOKEN` field that fills in a securely random value (server-generated via `POST /admin/api/settings/generate-token`) - it only takes effect once you save the form.

### Response Metrics

The API response includes the following health metrics:

**Counter Metrics:**
- `counter_healthy_true/false`: Number of healthy/unhealthy devices
- `counter_healthy_online_true/false`: Number of online/offline devices
- `counter_key_healthy_true/false`: Number of devices with valid/expiring keys
- `counter_update_healthy_true/false`: Number of devices considered up to date / needing an update. Devices exempted by the `*_UPDATE_HEALTHY` filters count as up to date here.
- `counter_lock_healthy_true/false`: Number of devices signed / awaiting a Tailnet Lock signature (always fully "true" unless `TAILNET_LOCK_ENABLED` is on)

**Global Health Metrics:**
- `global_healthy`: True if `counter_healthy_false` is at or below `GLOBAL_HEALTHY_THRESHOLD`
- `global_online_healthy`: True if `counter_healthy_online_false` is at or below `GLOBAL_ONLINE_HEALTHY_THRESHOLD`
- `global_key_healthy`: True if `counter_key_healthy_false` is at or below `GLOBAL_KEY_HEALTHY_THRESHOLD`
- `global_update_healthy`: True if `counter_update_healthy_false` is at or below `GLOBAL_UPDATE_HEALTHY_THRESHOLD`
- `global_lock_healthy`: True if `counter_lock_healthy_false` is at or below `GLOBAL_LOCK_HEALTHY_THRESHOLD`

Each global metric has its own threshold (all default to `100`) and flips to `false` once its
false-counter rises **above** that threshold. `/keys` reports a separate `global_keys_healthy`,
which is simply true when no monitored tailnet key is within `KEY_EXPIRY_WARNING_DAYS` of expiry.

`/health`, `/health/healthy` and `/health/unhealthy` all report the same tailnet-wide `metrics`
block; they differ only in which devices appear in `devices`. `/health/<identifier>` reports the
same fields scoped to the single device it returns (so its counters are 1 or 0).

### Using OAuth for Authentication (!RECOMMENDED!)

If you prefer to use OAuth instead of an API token (`AUTH_TOKEN`), configure the following environment variables:

1. **`OAUTH_CLIENT_ID`**: The client ID for your OAuth application.
2. **`OAUTH_CLIENT_SECRET`**: The client secret for your OAuth application.

When OAuth is configured, the application will automatically fetch an access token from the Tailscale API and use it for authentication. The access token is renewed every 50 minutes to ensure uninterrupted operation. Additionally, the application will immediately refresh the OAuth token upon receiving a 401 Unauthorized error during API requests.

**Note**: If both `AUTH_TOKEN` and OAuth credentials are configured, OAuth will take priority.

**Recommendation**: It is highly recommended to use OAuth for authentication instead of an API token (`AUTH_TOKEN`) for better security and token management.

### Creating a Tailscale OAuth Client

To use OAuth, you need to create a Tailscale OAuth client with the required permissions:

1. Visit the Tailscale Admin Console:  
   [https://login.tailscale.com/admin/settings/oauth](https://login.tailscale.com/admin/settings/oauth)

2. Click **Create OAuth Client** and configure the following:
   - **Name**: Provide a descriptive name for the client (e.g., `Tailscale Healthcheck`).
   - **Permissions**: Grant `read` permissions on `devices:core`. If you also want [tailnet key expiry monitoring](#keys) (`/keys`), additionally grant `read` on **API Access Tokens** and `read` on **Auth Keys**.

3. Copy the generated **Client ID** and **Client Secret**.

4. Set the `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` environment variables in your `.env` file or Docker configuration.

**Note**: Ensure the OAuth client credentials are stored securely and not shared publicly.

### Generating the Tailscale API Key

To use this application with an API token, you need to generate a Tailscale API key:

1. Visit the Tailscale Admin Console:  
   [https://login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys)

2. Click **Generate Key** and copy the generated API key. If you also want [tailnet key expiry monitoring](#keys) (`/keys`), grant it the **Keys** capability (read access is enough) in addition to device access.

3. Set the API key as the `AUTH_TOKEN` environment variable.

**Note**: Ensure the API key is stored securely and not shared publicly.

### Filter Configuration Examples

The application supports filtering devices by OS, identifier (hostname, ID, or name), and tags using wildcards:

**Operating System Filters:**
```bash
# Include only Windows and macOS devices
INCLUDE_OS="linux*,freebsd*"

# Exclude Linux devices
EXCLUDE_OS="iOS*"
```

**Device Identifier Filters:**
```bash
# Include only devices with specific names
INCLUDE_IDENTIFIER="firewall*,server*"

# Exclude specific devices
EXCLUDE_IDENTIFIER="test*,dev*,iphone*,ipad*"
```

**Tag Filters:**
```bash
# Include only devices with specific tags
INCLUDE_TAGS="admin*,infra*"

# Exclude specific devices by tags
EXCLUDE_TAGS="test*,dev*"
```

**Update Health Filters:**
```bash
# Include only devices with specific identifiers for update health
INCLUDE_IDENTIFIER_UPDATE_HEALTHY="firewall*,server*"

# Exclude specific devices by identifiers for update health
EXCLUDE_IDENTIFIER_UPDATE_HEALTHY="test*,dev*,iphone*,ipad*"

# Include only devices with specific tags for update health
INCLUDE_TAG_UPDATE_HEALTHY="admin*,infra*"

# Exclude specific devices by tags for update health
EXCLUDE_TAG_UPDATE_HEALTHY="test*,dev*"
```

**Note**: When `INCLUDE` filters are set, `EXCLUDE` filters are ignored for that category. Empty filter values mean no filtering is applied.

## 🐳 Running with Docker

Note: The container runs as a non-root user (`appuser`, UID 10001) following least-privilege best practices. It binds to the non-privileged port `5000`. If you need to expose a different external port, use Docker's port mapping (e.g., `-p 8080:5000`).

### Upgrading: recreate the container, don't just restart it

Pulling a new image is not enough — **recreate the container** so it picks up the image's current
`ENTRYPOINT`, `CMD`, `USER` and healthcheck:

```bash
docker compose pull && docker compose up -d      # compose recreates automatically
# or, for plain docker run:
docker pull laitco/tailscale-healthcheck:latest
docker rm -f tailscale-healthcheck
docker run -d --name tailscale-healthcheck ...   # same flags as before
```

Your data lives in the `/data` volume, not the container — so recreating it loses nothing **as long as
that volume is a named volume or a bind mount** (`-v tailscale-healthcheck-data:/data` or
`-v /host/path:/data`), which is how both the Compose file and the documented `docker run` commands
set it up.

> ⚠️ **If you started the container with no `-v` at all**, the image's `VOLUME ["/data"]` gave it an
> *anonymous* volume. `docker rm` + `docker run` attaches a **brand-new** anonymous volume, and your
> settings, users and history are left behind in the old one. Check before removing the container:
>
> ```bash
> docker inspect tailscale-healthcheck --format '{{range .Mounts}}{{.Type}} {{.Name}}{{.Source}} -> {{.Destination}}{{end}}'
> ```
>
> An empty `Name`/`Source` with type `volume` and a long hex id means it's anonymous. Either reattach
> it explicitly (`-v <that-volume-id>:/data`) or, better, migrate to a named volume first:
>
> ```bash
> docker run --rm -v <old-anonymous-volume-id>:/from -v tailscale-healthcheck-data:/to \
>   alpine sh -c 'cp -a /from/. /to/'
> ```

> **If you manage containers through a UI** (Portainer, Komodo, Dockge, …), check that it hasn't
> carried an **Entrypoint**, **Command** or **User** override forward from the previous container.
> Several of them copy the whole old configuration onto the new image when you redeploy, which
> pins settings that were only ever meant to be the image's own defaults.
>
> Symptom: the container crash-loops with
> `sqlite3.OperationalError: unable to open database file`, raised from inside
> `gunicorn_config.py`.
>
> Why: a `User` override starts the container as a non-root user, so the entrypoint can neither take
> ownership of `/data` nor drop privileges — and an `Entrypoint` override bypasses
> `docker-entrypoint.sh` entirely, so you get the raw SQLite error instead of a message explaining
> the problem. Clearing an `Entrypoint` override *alone* is not enough either: the container will
> then start and run **as root**, silently giving up its privilege dropping.
>
> Fix: leave **Entrypoint, Command and User empty** so the image supplies them. Recreating the
> container from scratch and re-adding only your own settings (tailnet domain, credentials,
> timezone, port, volume) is the most reliable way to clear a stale definition.

### Storage & permissions

The app keeps everything (settings, users, device/key snapshots, audit log) in a SQLite database
under `/data`, so that directory has to be writable by the container. This is handled automatically
— **you should not normally need to configure anything**:

| How you mount `/data` | What happens |
|---|---|
| Docker **named volume** (recommended) | Docker seeds it from the image; works as-is. |
| **Bind mount** on a normal Linux filesystem | The container starts as root, takes ownership, then drops to the unprivileged `appuser` (uid `10001`). |
| **Bind mount** on **CIFS/SMB or NFS** (typical NAS setup) | `chown` is refused there — ownership comes from the mount options — so the container instead runs *as the uid the share is mounted as*, and logs a `NOTE` saying so. |
| Hardened runtime (Kubernetes `runAsUser`, `docker run --user`) | Runs as the uid you specified, unchanged. |

If none of those can write, the container **fails immediately with an explanation** instead of
crash-looping on an opaque `sqlite3.OperationalError: unable to open database file`.

**`PUID` / `PGID`** (default `10001` / `999`) override the whole thing when you want a specific uid —
for example to make the database files owned by your own user on a NAS:

```bash
docker run -e PUID=1000 -e PGID=1000 -v /volume1/docker/tailscale-healthcheck:/data ...
```

Set explicitly, they are honoured exactly: the container will fail with a clear error rather than
quietly running as some other user.

> The image's own user is uid `10001` rather than the more familiar `1000` deliberately — it's a
> reserved system-range id, so it can't collide with a real account on the host. You do not need to
> match it; the table above means the container adapts to your storage, not the other way round.

### Run with Docker Compose

The quickest way to get started. A ready-to-edit [`docker-compose.yml`](docker-compose.yml) ships in
the repository:

```bash
docker compose up -d
```

Then open `http://localhost:5000` and complete the first-run setup wizard - you don't need to set
any environment variables up front, since the wizard writes the tailnet domain and credentials into
the database. The named `tailscale-healthcheck-data` volume is what makes that configuration (plus
your admin users and audit log) survive a restart or image upgrade.

To upgrade:

```bash
docker compose pull && docker compose up -d
```

### Build and Run Locally

### 1. **Build the Docker Image**:
   ```bash
   docker build -t laitco/tailscale-healthcheck .
   ```

### 2. **Run the Docker Container**:

A `/data` volume is the only thing that's actually required - it's where the SQLite database (settings, users, device/key snapshots, audit log) lives, and without it you'd lose your configuration and admin account on every container recreation.

```bash
docker run -d -p 5000:5000 \
  -v tailscale-healthcheck-data:/data \
  --name tailscale-healthcheck laitco/tailscale-healthcheck
```

That's it - open `http://IP-ADDRESS_OR_HOSTNAME:5000/` and the setup wizard walks you through connecting to your tailnet (API token or OAuth) and creating the first admin account. No environment variables are required for a first run.

Prefer to skip the wizard (e.g. for automated/scripted deployments)? Any setting can still be pre-configured via environment variables - see [Configuration](#️-configuration) for the full list. For example:

```bash
docker run -d -p 5000:5000 \
  -v tailscale-healthcheck-data:/data \
  -e TAILNET_DOMAIN="your-tailnet.ts.net" \
  -e AUTH_TOKEN="your-api-key" \
  --name tailscale-healthcheck laitco/tailscale-healthcheck
```

Env vars always take precedence over whatever's saved in the database, and are synced into it on every boot - if you remove one later, the last-known value keeps being used and becomes editable in `/admin/settings` again instead of reverting to "unconfigured".

### 3. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/
   ```
   First visit (or once no admin account exists) redirects to the setup wizard; afterwards this is the web dashboard with global metrics, search/filter controls, export (CSV/JSON), and device details - behind login. The raw JSON API remains available, unauthenticated by default, at:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/health
   ```

#### Error Handling
- Invalid routes return consistent errors:
  - JSON API (Accept `application/json` or under `/health*`): `{ "error": "Not Found", "status": 404 }`
  - Web UI: a clean 404 page with navigation back to the dashboard

### Run from Docker Hub

### 1. **Pull the Docker Image**:
   ```bash
   docker pull laitco/tailscale-healthcheck:latest
   ```

### 2. **Run the Docker Container**:

Same as above - only the `/data` volume is required, everything else is configured via the setup wizard on first visit:

```bash
docker run -d -p 5000:5000 \
  -v tailscale-healthcheck-data:/data \
  --name tailscale-healthcheck laitco/tailscale-healthcheck:latest
```

### 3. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/
   ```

## 📡 Integration with Gatus Monitoring System

You can integrate this healthcheck application with the [Gatus](https://github.com/TwiN/gatus) monitoring system to monitor the health of specific devices.

### Example Configuration

```yaml
endpoints:
  - name: tailscale-examplehostname.example.com
    group: tailscale
    url: "http://IP-ADDRESS_OR_HOSTNAME:5000/health/examplehostname"
    interval: 5m
    conditions:
      - "[STATUS] == 200"
      - "[BODY].device.healthy == pat(*true*)"
    alerts:
      - type: email
        failure-threshold: 2
        success-threshold: 3
        description: "healthcheck failed"
        send-on-resolved: true
```

### Explanation

- **`name`**: A descriptive name for the endpoint being monitored.
- **`group`**: A logical grouping for endpoints (e.g., `tailscale`).
- **`url`**: The URL of the healthcheck endpoint for a specific device.
- **`interval`**: The frequency of the healthcheck (e.g., every 5 minutes).
- **`conditions`**:
  - `[STATUS] == 200`: Ensures the HTTP status code is `200`.
  - `[BODY].device.healthy == pat(*true*)`: Checks if the `healthy` field in the response body is `true`.
- **`alerts`**:
  - **`type`**: The type of alert (e.g., `email`).
  - **`failure-threshold`**: The number of consecutive failures before triggering an alert.
  - **`success-threshold`**: The number of consecutive successes before resolving an alert.
  - **`description`**: A description of the alert.
  - **`send-on-resolved`**: Whether to send a notification when the issue is resolved.

For more details on configuring Gatus, refer to the [Gatus documentation](https://github.com/TwiN/gatus).

## 🔧 Development

### Linting
Run `flake8` to lint the code:
```bash
pip install flake8
flake8 healthcheck.py
```

### Testing
Use `pytest` for testing:
```bash
pip install pytest
pytest
```

## 📜 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request.
