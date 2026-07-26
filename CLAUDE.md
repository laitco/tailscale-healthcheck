# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Flask application, split across `healthcheck.py` plus a handful of focused modules
(`dbstore.py`, `auth.py`, `poller.py`, `admin.py`), that exposes health-check endpoints (JSON) plus a React
dashboard for monitoring device online status, key expiry, and update status across a tailnet. A background
poller refreshes devices/tailnet keys from the Tailscale API into a SQLite database (`DATABASE_PATH`); the
`/health*` JSON API and dashboard read from that snapshot rather than calling Tailscale per request. A
web-based admin UI (`/admin`) provides a first-run setup wizard, login, settings, user management, and an
audit log, all backed by the same database. Designed to run under Gunicorn in Docker, and to be scraped by
monitoring tools like Gatus.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Run for local dev (auto-reload)
FLASK_APP=healthcheck.py flask run --port 5000

# Run like production
gunicorn -w 4 -b 0.0.0.0:5000 -c gunicorn_config.py healthcheck:app

# Lint (see .flake8 for max-line-length=140 and ignored rules)
pip install flake8 && flake8 healthcheck.py dbstore.py auth.py poller.py admin.py

# Tests
pip install pytest && pytest -q
pytest tests/test_dbstore.py -q          # single file
pytest tests/test_dbstore.py::test_name -q  # single test

# Docker
docker build -t tailscale-healthcheck .
docker run -p 5000:5000 -v tailscale-healthcheck-data:/data --env-file .env tailscale-healthcheck
```

The Python backend has no separate build step. The dashboard/admin UI is a Vite/React SPA under `frontend/`,
built into `static/app/` (done automatically in the multi-stage Dockerfile; for local dev run `pnpm build`
inside `frontend/` after editing it, or `pnpm dev` for hot reload against a locally running Flask backend).

## Architecture

The backend is split across a few modules:

- `healthcheck.py` — Flask app setup, `/health*` JSON API, dashboard shell routes, rate limiting, and
  OAuth token machinery.
- `dbstore.py` — SQLite connection/schema management (WAL mode), settings get/set with env-override
  semantics, device/key snapshot read/write with change diffing, audit log read/purge, user CRUD.
- `auth.py` — Flask-Login wiring (`LoginManager`, `User`), backed by `dbstore`'s users table.
- `poller.py` — background thread that refreshes devices/tailnet keys from the Tailscale API into SQLite
  every `POLL_INTERVAL_SECONDS`; elects a single runner across Gunicorn workers via an `fcntl` lock file.
- `admin.py` — the `/admin` Blueprint: setup wizard, login, settings, user management, audit log (both
  HTML shell routes and a `/admin/api/*` JSON API the React admin pages call).

Key pieces, in the order a change usually touches them:

1. **Config via the settings registry** — Every runtime-configurable setting (connection info, health
   thresholds, device/key filters, timezone, HTTP timeout, log level, rate limiting, retry/backoff, poll
   interval, audit retention, debug log capture) lives in `dbstore.SETTINGS_REGISTRY`, keyed by setting name
   to a 5-tuple `(env_var, type, default, sentinel, group)`. Resolution is env-first, DB-fallback:
   `dbstore.get_setting(name)`/`get_setting_typed(name)` return the env var's value if set (and not equal to
   the sentinel placeholder, e.g. `TAILNET_DOMAIN=example.com`), else the last value saved to the database
   (by `sync_env_settings()` at boot, the setup wizard, or `/admin/settings`), else `default`. This is what
   lets the admin UI change settings without a restart (for most of them — see below) and lets removing an
   env var later fall back to the last-known-good DB value instead of reverting to "unconfigured".
   **When adding a new setting**: add one entry to `SETTINGS_REGISTRY` (that's what makes it show up in
   `/admin/settings`, auto-grouped, and auto-synced from its env var) rather than a standalone
   `os.getenv(...)` call, and document it in `.env.example` + README's Configuration table. `PORT` and the
   Gunicorn bind/worker-count flags are the deliberate exception — pure process-bootstrap concerns, not in
   the registry, env-only.
   **Avoid N+1 settings reads in per-device loops**: `dbstore.get_settings_typed(names)` resolves several
   settings in a single DB round trip — call it once per request/poll-cycle (see `HEALTH_SUMMARY_SETTINGS` /
   `DEVICE_FILTER_SETTINGS` / `UPDATE_HEALTHY_FILTER_SETTINGS` / `KEY_FILTER_SETTINGS` in `healthcheck.py`)
   and pass the resulting dict into per-device helpers like `should_include_device(device, filters)` —
   never call `get_setting_typed()` per device.
   **Restart-required settings**: `RATE_LIMIT_*` and `LOG_LEVEL` are wired up once at process/Flask-app
   startup (Flask-Limiter construction, `logging.basicConfig()`), so saving a new value persists it
   immediately but it only takes effect after a restart — see `admin.RESTART_REQUIRED_SETTINGS`, surfaced to
   the UI via each field's `restart_required` flag in the `/admin/api/settings` response.
2. **Auth (Tailscale API)** — Two mutually exclusive modes: static `AUTH_TOKEN` or OAuth (`OAUTH_CLIENT_ID` /
   `OAUTH_CLIENT_SECRET`), both resolved via `dbstore.get_setting()`. OAuth tokens are fetched via
   `fetch_oauth_token()` / `initialize_oauth()` and auto-renewed with a `threading.Timer`.
   `make_authenticated_request()` is the single choke point for all outbound Tailscale API calls (handles
   auth headers, retries, and error translation); `build_auth_header()` picks OAuth vs. static token.
3. **Rate limiting** — Two independent layers: `flask_limiter` (optional dependency, degrades gracefully if
   not installed — see `_HAVE_FLASK_LIMITER`) for per-IP request limits, and a separate file-based limiter
   (`_rl_file_load`/`_rl_file_save`/`_file_rate_limit_check_and_inc`, using `fcntl` locking) enforced in
   `_enforce_file_rate_limits()`. Don't assume only one rate-limiting mechanism is active.
4. **Background polling (not per-request caching)** — `poller.py`'s `run_poll_cycle()` is the only code path
   that calls the Tailscale devices/keys API; it upserts results into `dbstore`'s `devices`/`tailnet_keys`
   tables and writes `audit_log` rows for meaningful field changes (see `DEVICE_AUDIT_FIELDS`/
   `KEY_AUDIT_FIELDS` in `dbstore.py` — noisy fields like `lastSeen` are deliberately excluded, but
   `connected_to_control` transitions ARE audited since a row is only written when the *stored* value
   differs from the latest poll, not on every poll). Each cycle also appends one row to `dbstore`'s
   `metrics_history` table (aggregate counters only, via `record_metrics_snapshot()`, purged after 48h) for
   the dashboard's trend tiles (`GET /admin/api/metrics-history`), and records structured events (fixed
   `poller.EVENT_TYPES`: `poll_skipped`, `poll_started`, `devices_success`, `devices_error`,
   `keys_success`, `keys_error`, `poll_completed`) into the persistent `dbstore.poller_log` table
   (`_record()`/`get_poll_log()`, gated by the `debug_log_enabled` setting, purged per
   `poller_log_retention_days` alongside `audit_log`) surfaced at `GET /admin/api/debug/poller-log` and
   rendered on the `/debug` page, filterable by event type (not log severity). Each cycle also records
   overall pass/fail status via `dbstore.set_poll_status()`/`get_poll_status()` — `poller._is_auth_error()`
   flags 401/403 `HTTPError`s specifically (missing/wrong/revoked credentials) as distinct from other
   failures — surfaced in `/health`'s and `/admin/api/settings`'s `poll_meta`/`_meta` blocks
   (`last_poll_ok`/`last_poll_error`/`last_poll_auth_error`) so the dashboard/settings UI can show a real
   "can't reach Tailscale, check your credentials" banner instead of silently sitting on an empty/stale
   device list. `/health/cache/invalidate` triggers an immediate out-of-band cycle (kept at that URL for
   backward compatibility even though there's no more "cache" to invalidate).
5. **Device/key reads** — `fetch_devices()`/`fetch_tailnet_keys()` in `healthcheck.py` now just return
   `dbstore.get_devices_snapshot()`/`get_keys_snapshot()`. `_get_tailnet_keys_status_safe()` wraps key-status
   computation so a keys problem degrades the dashboard gracefully instead of failing the whole `/health`
   response.
6. **Filtering** — `should_include_device()` and `should_force_update_healthy()` implement the
   include/exclude filtering by OS, identifier, and tags (wildcard patterns via `fnmatch`), separately for
   general health and for update-health overrides. Any new filter dimension should follow this same
   include/exclude + wildcard convention.
7. **Health computation** — `_compute_health_summary()` derives per-device and global health
   (`online_healthy`, `key_healthy`, `update_healthy`, `global_*`) from raw device data plus the configured
   thresholds. `_compute_keys_summary()` does the analogous computation for tailnet API/auth keys. Note:
   `/health/<identifier>`, `/health/unhealthy`, `/health/healthy` duplicate this logic inline rather than
   calling `_compute_health_summary()` — a change here usually needs updating all 4 places.
8. **Routes** — Three families:
   - JSON API under `/health*` (`/health`, `/health/<identifier>`, `/health/healthy`, `/health/unhealthy`,
     `/keys`, `/health/cache/invalidate`) — must remain idempotent, JSON-only, no manual trailing-slash
     redirects (see `app.url_map.strict_slashes = False`). **Only `/health` (and its `/health/` redirect)
     is unauthenticated** — every other route in this family is decorated with `@login_required` (from
     `flask_login`), including `/keys`, `/health/<identifier>`, `/health/healthy`, `/health/unhealthy`, and
     `/health/cache/invalidate`.
   - Dashboard UI (`/`, `/dashboard`, `/devices`, `/tailnet-keys`, `/debug`, `/device/<identifier>`)
     rendered via `templates/` + `static/app/` (a Vite/React SPA) — gated behind setup-complete + login
     (see `_gate_dashboard_ui()`), so a request to any of these redirects to `/admin/setup` or
     `/admin/login` if either condition isn't met. `/debug` is the poller activity log viewer (reads
     `/admin/api/debug/poller-log`), not the old settings-dump page.
   - `/admin/*` (see `admin.py`) — setup wizard, login, settings, users, audit, metrics history, poller log;
     the only part of the app that accepts non-GET methods. Setup/login/logout endpoints must stay reachable
     without a session (that's how login happens); everything else under `/admin` is `@login_required`.
   Error responses are content-negotiated: JSON for `/health*` or `Accept: application/json`, an HTML 404
   page otherwise (`handle_404`).
9. **Read-only enforcement** — `enforce_read_only_methods()` (a `before_request` hook) rejects non-GET
   methods everywhere except paths under `/admin` (protected by login instead); this is a deliberate design
   constraint, not an oversight. `/health` staying unauthenticated and GET-only is the load-bearing
   contract existing monitoring integrations (Gatus, etc.) depend on — don't add auth there. Don't confuse
   this with the rest of the `/health*` family, which DOES require login (see point 8 above).

## Testing conventions

- Tests live in `tests/test_*.py`, run with `pytest`.
- Network calls (`requests.get`/`requests.post`) are mocked with `unittest.mock.patch` — never hit the real
  Tailscale API in tests.
- Time-dependent logic (online/key-expiry thresholds) is tested by patching timezone/time utilities, not by
  sleeping.
- New helpers or `/health*` response changes need dedicated unit coverage in the matching `tests/test_*.py`
  file (or a new one if the concern is distinct).
- Tests that touch `dbstore`/`poller`/`admin` must isolate the SQLite file per test — set `DATABASE_PATH` to
  a `tmp_path`-based path (via `monkeypatch.setenv` or before dynamically loading `healthcheck.py`) and call
  `dbstore.configure(path)` directly when using `dbstore`/`poller` without loading `healthcheck.py`. Setting
  `DATABASE_PATH` only inside the env dict passed to a loader that restores `os.environ` right after
  `exec_module()` doesn't work on its own — `dbstore.configure()` (called by `healthcheck.py` at import
  time) is what pins the path for the rest of that module-load, since `dbstore` itself is cached in
  `sys.modules` across dynamically-reloaded copies of `healthcheck.py`.

## Frontend gotcha: `<main>` must not set `overflow-x` without also affecting `overflow-y`

`frontend/src/components/layout.tsx`'s `<main>` has no `overflow-x-auto` (removed deliberately). Per the CSS
overflow spec, setting `overflow-x` to anything other than `visible` forces the *computed* `overflow-y` to
`auto` too — even if you explicitly write `overflow-y: visible` on the same element, it still computes to
`auto`; there's no way to have one axis scrollable and the other truly `visible` on the same box. That
matters here because `<main>` grows to fit its content (no fixed height), so it never develops its own
scrollbar — but by becoming a non-`visible` overflow ancestor, it silently becomes the reference box for
every `position: sticky` descendant instead of the viewport, and since `<main>` itself never scrolls, those
sticky elements just sit inert instead of sticking. If you need horizontal scroll for wide content (tables,
etc.), add `overflow-x-auto` to that specific element/wrapper (see `device-table.tsx`, `keys-table.tsx`,
`admin-audit.tsx`, or the base `ui/table.tsx`, which already does this) — never back on `<main>`.

## Coding style

- Python 3.12, four-space indentation, `snake_case` functions/variables, `PascalCase` classes,
  lowercase-snake-case module filenames.
- Prefer small, testable pure helper functions (e.g. `should_include_device`) over inline logic in route
  handlers; add a docstring to new pure helpers.
- Keep secrets out of logs — existing logging paths mask sensitive values (tokens, keys); follow that
  pattern for any new logged data.

## Commit & PR conventions

- Short imperative commit subjects (e.g. "Add device filter helper"); reference issues as
  "Resolves #<id>" where applicable.
- PRs should summarize behavior changes, include sample `/health` responses when relevant, and call out any
  new/changed environment variables (update `.env.example` and README alongside code).
