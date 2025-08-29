# 🚀 Tailscale Healthcheck – A Dockerized Monitoring Helper Tool

<p align="center">
  <img src="https://img.shields.io/github/stars/laitco/tailscale-healthcheck?style=social" alt="GitHub Stars">
  <img src="https://img.shields.io/github/actions/workflow/status/laitco/tailscale-healthcheck/publish-image.yaml?branch=main" alt="GitHub Workflow Status">
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
- [📝 Release Notes](#-release-notes)
- [📡 Endpoints](#-endpoints)
  - [`/health`](#health)
  - [`/health/<identifier>`](#healthidentifier)
  - [`/health/healthy`](#healthhealthy)
  - [`/health/unhealthy`](#healthunhealthy)
- [⚙️ Configuration](#️-configuration)
  - [Using OAuth for Authentication](#using-oauth-for-authentication-recommended)
  - [Creating a Tailscale OAuth Client](#creating-a-tailscale-oauth-client)
  - [Generating the Tailscale API Key](#generating-the-tailscale-api-key)
  - [Logging](#logging)
  - [Rate Limiting](#rate-limiting)
- [🐳 Running with Docker](#-running-with-docker)
  - [Build and Run Locally](#build-and-run-locally)
  - [Run from Docker Hub](#run-from-docker-hub)
- [📡 Integration with Gatus Monitoring System](#-integration-with-gatus-monitoring-system)
- [🔧 Development](#-development)
  - [Linting](#linting)
  - [Testing](#testing)
- [📜 License](#-license)
- [🤝 Contributing](#-contributing)
- [⭐ Star History](#-star-history)

## ✨ Description

A Python-based Flask application to monitor the health of devices in a Tailscale network. The application provides endpoints to check the health status of all devices, specific devices, and lists of healthy or unhealthy devices.

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
- **Display Settings**:
  - Optional settings display in API output
  - Configurable via DISPLAY_SETTINGS_IN_OUTPUT
  - Secure masking of sensitive data
  - Comprehensive configuration overview
- **Configurable Caching**:
  - Optional in-memory cache for Tailscale API responses
  - Tunable TTL to balance freshness vs. API usage
  - Manual cache invalidation endpoint
  - Optional shared cache backends: File (local) or Redis

## 📝 Release Notes

### 1.3.0
- Add web UI dashboard and 404 handling (Resolves #21).
- Configurable rate limiting with default file backend; docs and tests updated (Resolves #30).
- Iterative retry logic with exponential backoff and jitter for authenticated requests; env config and tests (Resolves #29).
- Enforce read-only proxy; restrict cache invalidation to GET; tests and docs (Resolves #32).
- Configurable caching with shared file backend; add cache invalidate endpoint; docs and tests (Resolves #18).
- Enforce HTTP timeouts for outbound requests (Resolves #28).
- Pin dependencies and add Dependabot configuration (Resolves #26).
- Run container as non-root user `appuser` (Resolves #27).
- Upgrade to Python 3.12 in Docker and CI; refresh docs (Resolves #24).
- Default logging to INFO; add `.env.example`, `.gitignore`; update tests (Resolves #25).
- CI: Tag-driven release to Docker Hub and GHCR; dev publish on main (Resolves #33, #22).
- Add `.flake8` and fix lint issues in codebase (Resolves #34).
- Add manual GitHub Actions workflows for PR validation (Resolves #23).
- Various workflow updates to stabilize the release pipeline.

### 1.2.6.1
- Fixed: Support for ISO 8601 timestamps with fractional seconds from Tailscale API using `dateutil.parser`.
- Added: `python-dateutil` to requirements for robust timestamp parsing.

### 1.2.6
- Added capability to display settings:
  - New DISPLAY_SETTINGS_IN_OUTPUT environment variable (default: NO)
  - Optional display of all configuration settings in API output
  - Secure masking of sensitive credentials (AUTH_TOKEN, OAUTH_CLIENT_SECRET)
  - Default configuration values shown when settings are empty

### 1.2.5
- Added update status capabilities:
  - Update health status with `update_healthy` field
  - Client version tracking with `clientVersion` field
  - Update availability status with `updateAvailable` field
  - New global update health metric `global_update_healthy`
  - Configurable update health threshold with `GLOBAL_UPDATE_HEALTHY_THRESHOLD`
  - Optional inclusion of update health in overall health status via `UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH`
  - Update health filtering by identifier (INCLUDE_IDENTIFIER_UPDATE_HEALTHY, EXCLUDE_IDENTIFIER_UPDATE_HEALTHY)
  - Update health filtering by tags (INCLUDE_TAG_UPDATE_HEALTHY, EXCLUDE_TAG_UPDATE_HEALTHY)

### 1.2.4
- Added tag filtering capabilities:
  - Tag filters (INCLUDE_TAGS, EXCLUDE_TAGS)
  - Support for wildcard patterns in filter strings
  - Include filters take precedence over exclude filters
  - Multiple tag matching support per device

### 1.2.3
- Added device filtering capabilities:
  - Operating system filters (INCLUDE_OS, EXCLUDE_OS)
  - Device identifier filters (INCLUDE_IDENTIFIER, EXCLUDE_IDENTIFIER)
  - Support for wildcard patterns in filter strings
  - Include filters take precedence over exclude filters

### 1.2.2
- Added `key_days_to_expire` field showing the number of days until a device's key expires
- Set to `null` when key expiry is disabled

### 1.2.1
- Added global health metrics with configurable thresholds
  - GLOBAL_HEALTHY_THRESHOLD (default: 100)
  - GLOBAL_ONLINE_HEALTHY_THRESHOLD (default: 100)
  - GLOBAL_KEY_HEALTHY_THRESHOLD (default: 100)
- Added detailed counter metrics for monitoring device states
  - Healthy/unhealthy device counters
  - Online/offline device counters
  - Valid/expired key counters

### 1.2.0
- Added key expiry monitoring with configurable threshold (KEY_THRESHOLD_MINUTES, default: 1440)
- Introduced combined health status based on online status and key expiry
- Added new health indicators in API response:
  - online_healthy: Device online status
  - key_healthy: Key expiry status
  - healthy: Combined status (true only if both checks pass)
- Added keyExpiryDisabled and keyExpiryTimestamp fields in API response
- Improved timezone handling for all timestamp fields

### 1.1.3
- Added `worker_exit` hook in Gunicorn to log worker exits and confirm restarts.
- Enhanced error handling for `RemoteDisconnected` and `ProtocolError` in `make_authenticated_request` to retry requests instead of crashing workers.
- Improved logging for better debugging of worker lifecycle and connection issues.

### 1.1.2
- Updated GitHub Actions workflow to include validation on publishing of Docker containers

### 1.1.1
- Improved OAuth token renewal logic to handle retries and logging for better reliability.
- Added a global timer to automatically refresh the OAuth token every 50 minutes.
- Enhanced error handling for unknown timezones and invalid API responses.
- Improved logging for debugging, including token renewal times and device health checks.
- Fixed an issue where trailing slashes in URLs caused unnecessary redirects.
- Added logic to immediately refresh the OAuth token upon receiving a 401 Unauthorized error during API requests.
- Introduced a helper function to handle authenticated requests with automatic token refresh.
- Improved error handling and retry logic for token renewal failures.
- Enhanced logging for better debugging and monitoring of token usage and renewal.

### 1.1
- Added support for Tailscale OAuth Client authentication.
- OAuth tokens are automatically renewed every 50 minutes.
- Improved logging to include token renewal times in the configured timezone.

### 1.0
- Initial release of the Tailscale Healthcheck application.
- Supports health checks for all devices, specific devices, healthy devices, and unhealthy devices.
- Includes timezone support for `lastSeen` timestamps.
- Dockerized for easy deployment.

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
    "global_key_healthy": true,
    "global_online_healthy": true,
    "global_healthy": true,
    "global_update_healthy": true
  }
}
```

**Example with settings output (`DISPLAY_SETTINGS_IN_OUTPUT=YES`):**
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
    "global_healthy": true,
    "global_key_healthy": true,
    "global_online_healthy": true,
    "global_update_healthy": true
  },
  "settings": {
    "TAILNET_DOMAIN": "example.com",
    "OAUTH_CLIENT_ID": "123456789abcdefg",
    "OAUTH_CLIENT_SECRET": "********",
    "AUTH_TOKEN": "********",
    "ONLINE_THRESHOLD_MINUTES": 5,
    "KEY_THRESHOLD_MINUTES": 1440,
    "GLOBAL_HEALTHY_THRESHOLD": 100,
    "GLOBAL_ONLINE_HEALTHY_THRESHOLD": 100,
    "GLOBAL_KEY_HEALTHY_THRESHOLD": 100,
    "GLOBAL_UPDATE_HEALTHY_THRESHOLD": 100,
    "UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH": true,
    "DISPLAY_SETTINGS_IN_OUTPUT": true,
    "TIMEZONE": "Europe/Berlin",
    "INCLUDE_OS": "",
    "EXCLUDE_OS": "",
    "INCLUDE_IDENTIFIER": "",
    "EXCLUDE_IDENTIFIER": "",
    "INCLUDE_TAGS": "",
    "EXCLUDE_TAGS": "",
    "INCLUDE_IDENTIFIER_UPDATE_HEALTHY": "",
    "EXCLUDE_IDENTIFIER_UPDATE_HEALTHY": "",
    "INCLUDE_TAG_UPDATE_HEALTHY": "",
    "EXCLUDE_TAG_UPDATE_HEALTHY": ""
  }
}
```

### `/health/<identifier>`
Returns the health status of a specific device by hostname, ID, or name.

### `/health/healthy`
Returns a list of all healthy devices.

### `/health/unhealthy`
Returns a list of all unhealthy devices.

### `/health/cache/invalidate`
Clears the in-memory cache. Safe to call anytime. Useful when caching is enabled and you want to force a refresh before TTL expiry.

## ⚙️ Configuration

The application is configured using environment variables:

| Variable             | Default Value      | Description                                                                 |
|----------------------|--------------------|-----------------------------------------------------------------------------|
| `TAILNET_DOMAIN`     | `example.com`     | The Tailscale tailnet domain.                                              |
| `AUTH_TOKEN`         | None              | The Tailscale API token (required if OAuth is not configured).             |
| `OAUTH_CLIENT_ID`    | None              | The OAuth client ID (required if using OAuth).                             |
| `OAUTH_CLIENT_SECRET`| None              | The OAuth client secret (required if using OAuth).                         |
| `LOG_LEVEL`          | `INFO`            | Root log level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.    |
| `HTTP_TIMEOUT`       | `10`              | Timeout in seconds applied to all outbound HTTP requests.                  |
| `MAX_RETRIES`        | `3`               | Maximum total attempts for outbound authenticated requests (bounded).      |
| `BACKOFF_BASE_SECONDS` | `0.5`           | Initial backoff delay in seconds between retry attempts.                   |
| `BACKOFF_MAX_SECONDS`  | `8.0`           | Maximum backoff delay cap in seconds.                                      |
| `BACKOFF_JITTER_SECONDS` | `0.1`        | Random jitter (0..value) added to each backoff delay.                      |
| `ONLINE_THRESHOLD_MINUTES`  | `5`               | The threshold in minutes to determine online health.                       |
| `KEY_THRESHOLD_MINUTES`     | `1440`            | The threshold in minutes to determine key expiry health.                  |
| `GLOBAL_HEALTHY_THRESHOLD`  | `100`             | The threshold for total unhealthy.                               |
| `GLOBAL_ONLINE_HEALTHY_THRESHOLD`| `100`        | The threshold for total online health.                                       |
| `GLOBAL_KEY_HEALTHY_THRESHOLD`   | `100`        | The threshold for total key health.                             |
| `GLOBAL_UPDATE_HEALTHY_THRESHOLD`| `100`        | The threshold for total update health.                             |
| `UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH`| `NO` | Whether update health is included in overall health status. Example: `YES`                             |
| `DISPLAY_SETTINGS_IN_OUTPUT`| `NO` | Whether to include configuration settings in API output. Example: `YES`                             |
| `PORT`               | `5000`            | The port the application runs on.                                          |
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
| `CACHE_ENABLED`      | `YES`             | Enable in-memory caching of the Tailscale devices API response. Set to `NO` to disable. |
| `CACHE_TTL_SECONDS`  | `60`              | Cache time-to-live in seconds. |
| `CACHE_BACKEND`      | `FILE`            | Cache backend: `FILE` (shared on host), `MEMORY` (per-process), or `REDIS` (shared across instances). |
| `REDIS_URL`          | `""`              | Redis connection URL when `CACHE_BACKEND=REDIS`, e.g., `redis://host:6379/0`. |
| `CACHE_PREFIX`       | `ts_hc`           | Key prefix used for Redis cache keys. |
| `CACHE_FILE_PATH`    | `/tmp/tailscale-healthcheck-cache.json` | File path when `CACHE_BACKEND=FILE` (default). |

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

### Caching

- Enabled by default with `CACHE_TTL_SECONDS=60`.
- Disable by setting `CACHE_ENABLED=NO`.
- The app caches the JSON from the Tailscale `devices` API and reuses it across requests for the configured TTL.
- Invalidation: call `GET /health/cache/invalidate` to clear the cache immediately.
- Security: cached data contains only device info from the API; secrets remain masked elsewhere.

#### Shared Cache Across Gunicorn Workers

- By default (`CACHE_BACKEND=MEMORY`), each Gunicorn worker has its own in-memory cache.
- File-based shared cache on a single host: set `CACHE_BACKEND=FILE` and optionally `CACHE_FILE_PATH` to a writable path (e.g., `/tmp/tailscale-healthcheck-cache.json`). The app performs atomic writes and uses file locking for safe concurrent access.
- Distributed shared cache across instances: set `CACHE_BACKEND=REDIS` and provide `REDIS_URL`.

### Read-Only Proxy

- The proxy enforces read-only access: only `GET`, `HEAD`, and `OPTIONS` are allowed.
- Modifying methods (`POST`, `PUT`, `PATCH`, `DELETE`) are blocked with `403 Forbidden` and attempts are logged for auditing.
- This behavior is not user-configurable by design.

### Response Metrics

The API response includes the following health metrics:

**Counter Metrics:**
- `counter_healthy_true/false`: Number of healthy/unhealthy devices
- `counter_healthy_online_true/false`: Number of online/offline devices
- `counter_key_healthy_true/false`: Number of devices with valid/expired keys

**Global Health Metrics:**
- `global_key_healthy`: True if key_healthy_false count is below threshold
- `global_online_healthy`: True if healthy_online_false count is below threshold
- `global_healthy`: True if healthy_false count is below threshold
- `global_update_healthy`: True if update_healthy_false count is below threshold

These global metrics become false when their respective false counters exceed the GLOBAL_UNHEALTHY_THRESHOLD.

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
   - **Permissions**: Grant `read` permissions on `devices:core`.

3. Copy the generated **Client ID** and **Client Secret**.

4. Set the `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` environment variables in your `.env` file or Docker configuration.

**Note**: Ensure the OAuth client credentials are stored securely and not shared publicly.

### Generating the Tailscale API Key

To use this application with an API token, you need to generate a Tailscale API key:

1. Visit the Tailscale Admin Console:  
   [https://login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys)

2. Click **Generate Key** and copy the generated API key.

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

### Build and Run Locally

### 1. **Build the Docker Image**:
   ```bash
   docker build -t laitco/tailscale-healthcheck .
   ```

### 2. **Run the Docker Container**:

#### Using an API Key
```bash
docker run -d -p 5000:5000 \
    -e TAILNET_DOMAIN="example.com" \
    -e AUTH_TOKEN="your-api-key" \
    -e ONLINE_THRESHOLD_MINUTES=5 \
    -e KEY_THRESHOLD_MINUTES=1440 \
    -e GLOBAL_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_ONLINE_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_UPDATE_HEALTHY_THRESHOLD=100 \
    -e UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH=NO \
    -e DISPLAY_SETTINGS_IN_OUTPUT=NO \
    -e PORT=5000 \
    -e TIMEZONE="Europe/Berlin" \
    -e INCLUDE_OS="" \
    -e EXCLUDE_OS="" \
    -e INCLUDE_IDENTIFIER="" \
    -e EXCLUDE_IDENTIFIER="" \
    -e INCLUDE_TAGS="" \
    -e EXCLUDE_TAGS="" \
    -e INCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e EXCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e INCLUDE_TAG_UPDATE_HEALTHY="" \
    -e EXCLUDE_TAG_UPDATE_HEALTHY="" \
    --name tailscale-healthcheck laitco/tailscale-healthcheck
```

#### Using OAuth
```bash
docker run -d -p 5000:5000 \
    -e TAILNET_DOMAIN="example.com" \
    -e OAUTH_CLIENT_ID="your-oauth-client-id" \
    -e OAUTH_CLIENT_SECRET="your-oauth-client-secret" \
    -e ONLINE_THRESHOLD_MINUTES=5 \
    -e KEY_THRESHOLD_MINUTES=1440 \
    -e GLOBAL_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_ONLINE_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_KEY_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_UPDATE_HEALTHY_THRESHOLD=100 \
    -e UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH=NO \
    -e DISPLAY_SETTINGS_IN_OUTPUT=NO \
    -e PORT=5000 \
    -e TIMEZONE="Europe/Berlin" \
    -e INCLUDE_OS="" \
    -e EXCLUDE_OS="" \
    -e INCLUDE_IDENTIFIER="" \
    -e EXCLUDE_IDENTIFIER="" \
    -e INCLUDE_TAGS="" \
    -e EXCLUDE_TAGS="" \
    -e INCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e EXCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e INCLUDE_TAG_UPDATE_HEALTHY="" \
    -e EXCLUDE_TAG_UPDATE_HEALTHY="" \
    --name tailscale-healthcheck laitco/tailscale-healthcheck
```

### 3. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/
   ```
   This opens the web dashboard with global metrics, search/filter controls, export (CSV/JSON), and device details. The raw JSON API remains available at:
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

#### Using an API Key
```bash
docker run -d -p 5000:5000 \
    -e TAILNET_DOMAIN="example.com" \
    -e AUTH_TOKEN="your-api-key" \
    -e ONLINE_THRESHOLD_MINUTES=5 \
    -e KEY_THRESHOLD_MINUTES=1440 \
    -e GLOBAL_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_ONLINE_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_KEY_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_UPDATE_HEALTHY_THRESHOLD=100 \
    -e UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH=NO \
    -e DISPLAY_SETTINGS_IN_OUTPUT=NO \
    -e PORT=5000 \
    -e TIMEZONE="Europe/Berlin" \
    -e INCLUDE_OS="" \
    -e EXCLUDE_OS="" \
    -e INCLUDE_IDENTIFIER="" \
    -e EXCLUDE_IDENTIFIER="" \
    -e INCLUDE_TAGS="" \
    -e EXCLUDE_TAGS="" \
    -e INCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e EXCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e INCLUDE_TAG_UPDATE_HEALTHY="" \
    -e EXCLUDE_TAG_UPDATE_HEALTHY="" \
    --name tailscale-healthcheck laitco/tailscale-healthcheck:latest
```

#### Using OAuth
```bash
docker run -d -p 5000:5000 \
    -e TAILNET_DOMAIN="example.com" \
    -e OAUTH_CLIENT_ID="your-oauth-client-id" \
    -e OAUTH_CLIENT_SECRET="your-oauth-client-secret" \
    -e ONLINE_THRESHOLD_MINUTES=5 \
    -e KEY_THRESHOLD_MINUTES=1440 \
    -e GLOBAL_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_ONLINE_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_KEY_HEALTHY_THRESHOLD=100 \
    -e GLOBAL_UPDATE_HEALTHY_THRESHOLD=100 \
    -e UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH=NO \
    -e DISPLAY_SETTINGS_IN_OUTPUT=NO \
    -e PORT=5000 \
    -e TIMEZONE="Europe/Berlin" \
    -e INCLUDE_OS="" \
    -e EXCLUDE_OS="" \
    -e INCLUDE_IDENTIFIER="" \
    -e EXCLUDE_IDENTIFIER="" \
    -e INCLUDE_TAGS="" \
    -e EXCLUDE_TAGS="" \
    -e INCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e EXCLUDE_IDENTIFIER_UPDATE_HEALTHY="" \
    -e INCLUDE_TAG_UPDATE_HEALTHY="" \
    -e EXCLUDE_TAG_UPDATE_HEALTHY="" \
    --name tailscale-healthcheck laitco/tailscale-healthcheck:latest
```

### 3. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/health
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

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=laitco/tailscale-healthcheck&type=Date)](https://www.star-history.com/#laitco/tailscale-healthcheck&Date)
