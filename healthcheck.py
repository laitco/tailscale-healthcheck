import os
import time
import json
import fcntl
import hmac
import requests
import random
from datetime import datetime, timedelta
from flask import Flask, jsonify, redirect, request, render_template, url_for
try:  # Optional dependency; app runs without rate limiting if unavailable
    from flask_limiter import Limiter  # type: ignore
    from flask_limiter.util import get_remote_address  # type: ignore
    _HAVE_FLASK_LIMITER = True
except Exception:  # pragma: no cover - import guard
    Limiter = None  # type: ignore
    _HAVE_FLASK_LIMITER = False
    
    def get_remote_address():  # type: ignore
        return request.remote_addr
import pytz
import logging  # Add logging for debugging
from threading import Timer  # For token renewal
from urllib3.exceptions import ProtocolError  # Add import for better error handling
from http.client import RemoteDisconnected  # Add import for better error handling
import fnmatch  # Add for wildcard pattern matching
from dateutil import parser  # Add this import
from flask_login import current_user, login_required

import dbstore
import poller
import auth
from admin import admin_bp

def get_log_level_from_env(default=logging.INFO):
    """Return a logging level from LOG_LEVEL env var, defaulting to INFO.

    Accepts standard level names like DEBUG, INFO, WARNING, ERROR, CRITICAL.
    Falls back to the provided default if the value is missing or invalid.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO")
    return getattr(logging, str(level_name).upper(), default)

# Configure logging with safe default (INFO) and env override
logging.basicConfig(level=get_log_level_from_env())

app = Flask(__name__)
app.url_map.strict_slashes = False  # Allow trailing slashes to be ignored

# Load configuration from environment variables
dbstore.configure()
dbstore.init_db()
dbstore.sync_env_settings()

app.secret_key = dbstore.get_secret_key()
auth.init_app(app)
app.register_blueprint(admin_bp)

def _is_tailnet_configured() -> bool:
    """Return True if a tailnet domain has been configured (env or DB)."""
    return dbstore.is_tailnet_configured()

PORT = int(os.getenv("PORT", 5000))  # Default to port 5000 - process bootstrap, env-only

# Rate limiting, logging level: read once at startup via dbstore (env-first,
# DB-fallback, so a value saved through the setup wizard/admin UI on a
# previous boot still applies even if the env var is gone) - but these are
# still effectively frozen for the life of the process, since Flask-Limiter
# is wired up once here and logging.basicConfig() already ran above. Changing
# them via /admin/settings persists to the DB but needs a restart to apply;
# admin.py flags this to the UI via RESTART_REQUIRED_SETTINGS.
RATE_LIMIT_ENABLED = dbstore.get_setting_typed("rate_limit_enabled")
RATE_LIMIT_PER_IP = max(0, dbstore.get_setting_typed("rate_limit_per_ip"))
RATE_LIMIT_GLOBAL_INT = max(0, dbstore.get_setting_typed("rate_limit_global"))
RATE_LIMIT_STORAGE_URL = dbstore.get_setting_typed("rate_limit_storage_url") or None
RATE_LIMIT_HEADERS_ENABLED = dbstore.get_setting_typed("rate_limit_headers_enabled")

# Initialize rate limiter (no-op if disabled)
limiter = None
_USE_FILE_RATE_LIMIT = False
_RATE_LIMIT_FILE_PATH = None
if RATE_LIMIT_ENABLED and RATE_LIMIT_STORAGE_URL and RATE_LIMIT_STORAGE_URL.startswith("file://"):
    _USE_FILE_RATE_LIMIT = True
    _RATE_LIMIT_FILE_PATH = RATE_LIMIT_STORAGE_URL[len("file://"):]
elif RATE_LIMIT_ENABLED and _HAVE_FLASK_LIMITER:
    try:
        limiter = Limiter(
            key_func=get_remote_address,
            app=app,
            storage_uri=RATE_LIMIT_STORAGE_URL,  # Memory by default; can use Redis/etc via env
            default_limits=[],
            headers_enabled=RATE_LIMIT_HEADERS_ENABLED,
        )
    except Exception as e:  # pragma: no cover - initialization failure
        logging.error(f"Failed to initialize rate limiter: {e}. Disabling rate limits.")
        limiter = None
        RATE_LIMIT_ENABLED = False
elif RATE_LIMIT_ENABLED and not _HAVE_FLASK_LIMITER:
    logging.warning("RATE_LIMIT_ENABLED=YES but Flask-Limiter is not installed. Rate limiting disabled.")

def _apply_limits(fn):
    """Decorator to apply configured limits to a view function."""
    if not RATE_LIMIT_ENABLED or (limiter is None and not _USE_FILE_RATE_LIMIT):
        return fn
    wrapped = fn
    # If using Flask-Limiter, apply decorator-based limits
    if limiter is not None:
        if RATE_LIMIT_PER_IP > 0:
            wrapped = limiter.limit(f"{RATE_LIMIT_PER_IP} per minute")(wrapped)
        if RATE_LIMIT_GLOBAL_INT > 0:
            wrapped = limiter.shared_limit(f"{RATE_LIMIT_GLOBAL_INT} per minute", scope="global")(wrapped)
        return wrapped
    # File-based limiter uses a before_request hook; no-op here
    return wrapped

# File-based rate limit state helpers (fixed 1-minute windows)
def _rl_file_load():
    if not _RATE_LIMIT_FILE_PATH:
        return None
    try:
        with open(_RATE_LIMIT_FILE_PATH, "r") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                obj = json.load(fh)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return obj
    except FileNotFoundError:
        return None
    except Exception:
        return None

def _rl_file_save(obj):
    if not _RATE_LIMIT_FILE_PATH:
        return
    try:
        directory = os.path.dirname(_RATE_LIMIT_FILE_PATH) or "."
        os.makedirs(directory, exist_ok=True)
        tmp_path = f"{_RATE_LIMIT_FILE_PATH}.tmp"
        with open(tmp_path, "w") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            json.dump(obj, fh)
            fh.flush()
            os.fsync(fh.fileno())
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        os.replace(tmp_path, _RATE_LIMIT_FILE_PATH)
    except Exception:
        pass

def _file_rate_limit_check_and_inc(ip):
    now = int(time.time())
    window_start = now - (now % 60)  # minute window
    state = _rl_file_load() or {}
    if state.get("window_start") != window_start:
        state = {"window_start": window_start, "per_ip": {}, "global": 0}
    # Check per-IP
    if RATE_LIMIT_PER_IP > 0:
        ip_count = int(state["per_ip"].get(ip, 0))
        if ip_count >= RATE_LIMIT_PER_IP:
            _rl_file_save(state)  # persist unchanged state
            return False, f"Per-IP limit {RATE_LIMIT_PER_IP}/min exceeded"
        state["per_ip"][ip] = ip_count + 1
    # Check global
    if RATE_LIMIT_GLOBAL_INT > 0:
        global_count = int(state.get("global", 0))
        if global_count >= RATE_LIMIT_GLOBAL_INT:
            _rl_file_save(state)
            return False, f"Global limit {RATE_LIMIT_GLOBAL_INT}/min exceeded"
        state["global"] = global_count + 1
    _rl_file_save(state)
    return True, None

RETRY_BACKOFF_SETTINGS = (
    "max_retries", "backoff_base_seconds", "backoff_max_seconds", "backoff_jitter_seconds",
)

# HTTP method restrictions (read-only proxy, not user-configurable)
ALLOWED_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}

def get_http_timeout(default: float = 10.0) -> float:
    """Return the effective HTTP timeout (seconds): env `HTTP_TIMEOUT` if set,
    else the last DB-saved value, else `default`. Resolved fresh on each call
    (cheap local SQLite read) so /admin/settings changes apply immediately."""
    try:
        value = float(dbstore.get_setting_typed("http_timeout"))
        return value if value > 0 else float(default)
    except Exception:
        return float(default)

def get_timezone_name() -> str:
    """Return the effective TIMEZONE setting (env-first, DB-fallback)."""
    return dbstore.get_setting_typed("timezone")

def _build_poll_meta() -> dict:
    """Poller freshness + health, for the dashboard to show a real "can't
    reach Tailscale" banner (driven by actual poll outcomes) instead of
    silently sitting on an empty/stale device list with no explanation."""
    status = dbstore.get_poll_status()
    return {
        "last_polled_at": dbstore.get_poll_meta(),
        "poll_interval_seconds": poller.poll_interval_seconds(),
        "last_poll_ok": status.get("ok"),
        "last_poll_error": status.get("error"),
        "last_poll_auth_error": bool(status.get("auth_error")),
    }

# Device filter settings (INCLUDE_OS/EXCLUDE_OS/... ) are resolved dynamically
# via dbstore.get_settings_typed() at the top of each caller (once per
# request, not per device) - see should_include_device()/
# should_force_update_healthy() and their call sites below.

# OAuth client id/secret are resolved via dbstore.get_setting() (env-first,
# DB-fallback) so the admin settings UI can change them without a restart.

# Global variable to store the OAuth access token and timer
ACCESS_TOKEN = None
TOKEN_RENEWAL_TIMER = None

# Global variable to track if it's the initial token fetch
IS_INITIAL_FETCH = True

def fetch_oauth_token():
    """
    Fetches a new OAuth access token using the client ID and client secret.
    """
    global ACCESS_TOKEN, TOKEN_RENEWAL_TIMER, IS_INITIAL_FETCH
    client_id = dbstore.get_setting("oauth_client_id")
    client_secret = dbstore.get_setting("oauth_client_secret")
    try:
        response = requests.post(
            "https://api.tailscale.com/api/v2/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret
            },
            timeout=get_http_timeout()
        )
        response.raise_for_status()
        token_data = response.json()
        ACCESS_TOKEN = token_data["access_token"]
        logging.info("Successfully fetched OAuth access token.")

        # Cancel any existing timer before scheduling a new one
        if TOKEN_RENEWAL_TIMER:
            TOKEN_RENEWAL_TIMER.cancel()

        # Schedule the next token renewal after 50 minutes
        TOKEN_RENEWAL_TIMER = Timer(50 * 60, fetch_oauth_token)
        TOKEN_RENEWAL_TIMER.daemon = True
        TOKEN_RENEWAL_TIMER.start()

        # Log the token renewal time only if it's not the initial fetch
        if not IS_INITIAL_FETCH:
            timezone_name = get_timezone_name()
            try:
                tz = pytz.timezone(timezone_name)
                renewal_time = datetime.now(tz).isoformat()
                logging.info(f"OAuth access token renewed at {renewal_time} ({timezone_name}).")
            except pytz.UnknownTimeZoneError:
                logging.error(f"Unknown timezone: {timezone_name}. Logging renewal time in UTC.")
                logging.info(f"OAuth access token renewed at {datetime.utcnow().isoformat()} UTC.")
        else:
            IS_INITIAL_FETCH = False  # Mark the initial fetch as complete
    except requests.exceptions.Timeout as to_err:
        logging.warning(f"Timeout during token fetch after {get_http_timeout()}s: {to_err}")
        ACCESS_TOKEN = None
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error during token fetch: {http_err}")
        if response.status_code == 401:
            logging.error("Unauthorized error (401). Retrying token fetch...")
            ACCESS_TOKEN = None
        else:
            logging.error(f"Unexpected HTTP error: {response.status_code}")
    except Exception as e:
        logging.error(f"Failed to fetch OAuth access token: {e}")
        ACCESS_TOKEN = None

def initialize_oauth():
    """
    Initializes OAuth token fetching if OAuth is configured.
    This function should only be called once during the master process initialization.
    """
    if dbstore.get_setting("oauth_client_id") and dbstore.get_setting("oauth_client_secret"):
        logging.info("OAuth configuration detected. Fetching initial access token...")
        fetch_oauth_token()

def build_auth_header() -> dict:
    """Return the Authorization header to use for Tailscale API calls."""
    client_id = dbstore.get_setting("oauth_client_id")
    client_secret = dbstore.get_setting("oauth_client_secret")
    if client_id and client_secret and ACCESS_TOKEN:
        return {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    auth_token = dbstore.get_setting("auth_token") or "your-default-token"
    return {"Authorization": f"Bearer {auth_token}"}

# Only initialize OAuth in the Gunicorn master process
if os.getenv("GUNICORN_MASTER_PROCESS", "false").lower() == "true":
    initialize_oauth()

# Log the configured timezone
logging.debug(f"Configured TIMEZONE: {get_timezone_name()}")

@app.before_request
def enforce_read_only_methods():
    """Reject non-read methods with a 403 to enforce read-only proxy.

    Allowed methods are strictly GET, HEAD, and OPTIONS (not configurable),
    except under /admin, which is where the setup wizard, login, settings,
    user management, and audit log intentionally accept POST/DELETE - that
    surface is instead protected by Flask-Login authentication.
    """
    if request.path.startswith("/admin"):
        return None
    method = request.method.upper()
    if method not in ALLOWED_HTTP_METHODS:
        logging.warning(
            "Blocked disallowed method",
            extra={
                "event": "method_blocked",
                "method": method,
                "path": request.path,
                "remote_addr": request.remote_addr,
            },
        )
        return (
            jsonify({
                "error": "Forbidden: method not allowed on read-only proxy",
                "method": method,
                "allowed_methods": sorted(ALLOWED_HTTP_METHODS),
            }),
            403,
        )
    # No return -> continue when allowed

_DASHBOARD_UI_PATHS = {"/", "/dashboard", "/devices", "/tailnet-keys", "/debug"}

@app.before_request
def _gate_dashboard_ui():
    """Require setup completion + login for the human dashboard.

    /health*, /keys, /admin/* and static assets are unaffected - only the
    React dashboard shell routes are gated here.
    """
    path = request.path
    is_dashboard_path = path in _DASHBOARD_UI_PATHS or path.startswith("/device/")
    if not is_dashboard_path:
        return None
    if dbstore.is_tailnet_configured() and dbstore.has_any_user():
        if not current_user.is_authenticated:
            return redirect(url_for("admin.login_page"))
        return None
    return redirect(url_for("admin.setup_page"))

@app.before_request
def _enforce_file_rate_limits():
    if not RATE_LIMIT_ENABLED or not _USE_FILE_RATE_LIMIT:
        return None
    # Apply only to read methods we allow
    if request.method.upper() not in ALLOWED_HTTP_METHODS:
        return None
    ip = request.remote_addr or "unknown"
    allowed, reason = _file_rate_limit_check_and_inc(ip)
    if not allowed:
        logging.warning(
            "Rate limit exceeded (file backend)",
            extra={
                "event": "rate_limit_exceeded",
                "remote_addr": request.remote_addr,
                "path": request.path,
                "detail": reason,
            },
        )
        return jsonify({"error": "Too Many Requests", "details": reason}), 429
    return None

try:
    from flask_limiter.errors import RateLimitExceeded
except Exception:  # pragma: no cover - import guard
    RateLimitExceeded = Exception  # type: ignore

@app.errorhandler(429)
def handle_429(e):  # Flask will pass the exception
    # Flask-Limiter raises RateLimitExceeded; ensure consistent JSON
    msg = "Too Many Requests"
    detail = getattr(e, "description", None) or str(e)
    logging.warning(
        "Rate limit exceeded",
        extra={
            "event": "rate_limit_exceeded",
            "remote_addr": request.remote_addr,
            "path": request.path,
            "detail": detail,
        },
    )
    return jsonify({"error": msg, "details": detail}), 429

@app.errorhandler(404)
def handle_404(e):
    """Return consistent 404s for API and UI.

    - For JSON API (Accept includes application/json or path under /health),
      return a structured JSON error without leaking internals.
    - For UI routes, render a friendly themed 404 page.
    """
    accept = request.headers.get("Accept", "")
    wants_json = "application/json" in accept or request.path.startswith("/health")
    payload = {"error": "Not Found", "status": 404}
    if wants_json:
        return jsonify(payload), 404
    # UI: render a clean 404 page with link to dashboard
    return render_template("404.html", error_title="Not Found", payload=payload), 404

def _upstream_error_payload(e: "requests.exceptions.HTTPError"):
    """Build a JSON error payload/status pair from an upstream Tailscale API error.

    Passes through the real upstream status code (e.g. 403 when the API
    token/OAuth client lacks the required scope or capability, 404, etc.)
    instead of collapsing every upstream failure to a generic 500.
    """
    status = 502
    message = str(e)
    if e.response is not None:
        status = e.response.status_code
        try:
            body = e.response.json()
            if isinstance(body, dict):
                message = body.get("message") or body.get("error") or message
        except Exception:
            pass
    return {"error": message, "upstream_status": status}, status

def make_authenticated_request(url, headers):
    """
    Make an authenticated GET request with bounded, iterative retries.

    - Retries only on transient connection errors (e.g., RemoteDisconnected, ProtocolError).
    - On 401, fetches a new OAuth token and retries once immediately within the same attempt.
    - Uses exponential backoff with jitter between attempts.
    - Honours `HTTP_TIMEOUT` for each request attempt.
    - Bounds attempts by `max_retries` (total attempts, not additional retries).

    Retry/backoff settings are resolved once here (a single DB round trip),
    not per attempt, so admin-edited values apply on the next call without a
    restart.
    """
    retry_cfg = dbstore.get_settings_typed(RETRY_BACKOFF_SETTINGS)
    max_retries = int(retry_cfg["max_retries"])
    backoff_base = retry_cfg["backoff_base_seconds"]
    backoff_max = retry_cfg["backoff_max_seconds"]
    backoff_jitter = retry_cfg["backoff_jitter_seconds"]

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=get_http_timeout())
            if response.status_code == 401:
                logging.error("Unauthorized error (401). Attempting to refresh OAuth token...")
                fetch_oauth_token()
                if ACCESS_TOKEN:
                    headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
                    response = requests.get(url, headers=headers, timeout=get_http_timeout())
            response.raise_for_status()
            return response
        except (RemoteDisconnected, ProtocolError) as e:
            last_err = e
            if attempt >= max_retries:
                break
            # Compute backoff with jitter and sleep
            delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
            jitter = random.uniform(0, backoff_jitter) if backoff_jitter > 0 else 0.0
            sleep_for = max(0.0, delay + jitter)
            logging.error(
                "Connection error during authenticated request. Will retry.",
                extra={
                    "event": "auth_request_retry",
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "error": str(e),
                    "sleep_seconds": round(sleep_for, 3),
                },
            )
            time.sleep(sleep_for)
        except requests.exceptions.Timeout as to_err:
            logging.warning(f"Timeout during external request after {get_http_timeout()}s: {to_err}")
            raise
        except Exception as e:
            logging.error(f"Error during authenticated request: {e}")
            raise

    # Exhausted retries
    logging.error(
        "Max retries exceeded for authenticated request.",
        extra={
            "event": "auth_request_max_retries_exceeded",
            "max_retries": max_retries,
            "error": str(last_err) if last_err else "unknown",
        },
    )
    raise RuntimeError("Max retries exceeded for authenticated request")

def fetch_devices():
    """Return the latest device snapshot persisted by the background poller.

    Data freshness is governed by POLL_INTERVAL_SECONDS (default 60s); the
    Tailscale API itself is only called from poller.py now, not per-request.
    """
    return dbstore.get_devices_snapshot()

def fetch_tailnet_keys():
    """Return the latest tailnet key snapshot persisted by the background poller."""
    return dbstore.get_keys_snapshot()

def _infer_key_type(key: dict) -> str:
    """Infer whether a tailnet key is an "api" or "auth" key.

    Newer Tailscale API responses may include an explicit type field
    (e.g. "keyType"); older/list responses may not, so fall back to
    inspecting `capabilities` (auth keys grant `devices` capabilities).
    """
    explicit = str(key.get("keyType") or key.get("type") or "").strip().lower()
    if explicit:
        return explicit
    capabilities = key.get("capabilities") or {}
    if "devices" in capabilities:
        return "auth"
    return "api"

KEY_FILTER_SETTINGS = (
    "include_key_type", "exclude_key_type", "include_key_description", "exclude_key_description",
)

def should_include_key(key: dict, key_type: str, filters=None) -> bool:
    """Mirror should_include_device(): INCLUDE takes precedence over EXCLUDE,
    globbed (fnmatch) against comma-separated patterns - here against the
    inferred key type (api/auth) and the key's description."""
    if filters is None:
        filters = dbstore.get_settings_typed(KEY_FILTER_SETTINGS)
    include_type, exclude_type = filters["include_key_type"], filters["exclude_key_type"]
    include_desc, exclude_desc = filters["include_key_description"], filters["exclude_key_description"]
    description = key.get("description", "") or ""

    if include_type and include_type.strip():
        patterns = [p.strip() for p in include_type.split(",") if p.strip()]
        if patterns and not any(fnmatch.fnmatch(key_type, pattern) for pattern in patterns):
            return False
    elif exclude_type and exclude_type.strip():
        patterns = [p.strip() for p in exclude_type.split(",") if p.strip()]
        if patterns and any(fnmatch.fnmatch(key_type, pattern) for pattern in patterns):
            return False

    if include_desc and include_desc.strip():
        patterns = [p.strip() for p in include_desc.split(",") if p.strip()]
        if patterns and not any(fnmatch.fnmatch(description, pattern) for pattern in patterns):
            return False
    elif exclude_desc and exclude_desc.strip():
        patterns = [p.strip() for p in exclude_desc.split(",") if p.strip()]
        if patterns and any(fnmatch.fnmatch(description, pattern) for pattern in patterns):
            return False

    return True

def _compute_keys_summary(keys):
    """Compute normalized tailnet key status list and aggregate metrics.

    Only "api" and "auth" key types are included (e.g. oauth-client keys
    are excluded), further narrowed by should_include_key(). A key is
    considered unhealthy once its expiry falls at or below
    KEY_EXPIRY_WARNING_DAYS; keys without an `expires` field are treated as
    never expiring and therefore healthy.
    """
    timezone_name = get_timezone_name()
    key_expiry_warning_days = dbstore.get_setting_typed("key_expiry_warning_days")
    key_filters = dbstore.get_settings_typed(KEY_FILTER_SETTINGS)
    try:
        tz = pytz.timezone(timezone_name)
    except pytz.UnknownTimeZoneError:
        raise ValueError(f"Unknown timezone: {timezone_name}")

    now = datetime.now(tz)
    key_status = []
    counter_healthy_true = 0
    counter_healthy_false = 0

    for key in keys:
        key_type = _infer_key_type(key)
        if key_type not in ("api", "auth"):
            continue
        if not should_include_key(key, key_type, key_filters):
            continue

        expires_raw = key.get("expires")
        key_days_to_expire = None
        expires_iso = None
        if expires_raw:
            expires = parser.isoparse(expires_raw).replace(tzinfo=pytz.UTC).astimezone(tz)
            expires_iso = expires.isoformat()
            key_days_to_expire = (expires - now).days
            key_healthy = key_days_to_expire > key_expiry_warning_days
        else:
            key_healthy = True

        if key_healthy:
            counter_healthy_true += 1
        else:
            counter_healthy_false += 1

        key_status.append({
            "id": key.get("id"),
            "description": key.get("description", ""),
            "keyType": key_type,
            "created": key.get("created"),
            "expires": expires_iso,
            "key_days_to_expire": key_days_to_expire,
            "key_healthy": key_healthy,
        })

    total_keys = counter_healthy_true + counter_healthy_false
    metrics = {
        "total_keys": total_keys,
        "counter_key_healthy_true": counter_healthy_true,
        "counter_key_healthy_false": counter_healthy_false,
        "global_keys_healthy": counter_healthy_false == 0,
        "has_keys": total_keys > 0,
        "key_expiry_warning_days": key_expiry_warning_days,
    }
    return key_status, metrics

def _get_tailnet_keys_status():
    """Fetch and summarize tailnet keys, guarding against an unconfigured tailnet."""
    tailnet_configured = _is_tailnet_configured()
    if tailnet_configured:
        keys = fetch_tailnet_keys()
        key_status, metrics = _compute_keys_summary(keys)
    else:
        key_status, metrics = [], {
            "total_keys": 0,
            "counter_key_healthy_true": 0,
            "counter_key_healthy_false": 0,
            "global_keys_healthy": True,
            "has_keys": False,
            "key_expiry_warning_days": dbstore.get_setting_typed("key_expiry_warning_days"),
        }
    metrics["tailnet_configured"] = tailnet_configured
    return key_status, metrics

def _get_tailnet_keys_status_safe():
    """Like _get_tailnet_keys_status, but never raises.

    Used by the dashboard so a keys-specific problem (most commonly the
    configured credential lacking the Keys scope/capability) degrades
    that section to an "unavailable" state instead of taking down the
    whole device health dashboard.
    """
    try:
        return _get_tailnet_keys_status()
    except requests.exceptions.HTTPError as e:
        logging.warning(f"Tailnet keys unavailable (upstream error): {e}")
        payload, _ = _upstream_error_payload(e)
        error_message = payload["error"]
    except requests.exceptions.Timeout as e:
        logging.warning(f"Tailnet keys unavailable (timeout): {e}")
        error_message = "Request to external API timed out"
    except Exception as e:
        logging.warning(f"Tailnet keys unavailable: {e}")
        error_message = "Unexpected error fetching tailnet keys"

    return [], {
        "total_keys": 0,
        "counter_key_healthy_true": 0,
        "counter_key_healthy_false": 0,
        "global_keys_healthy": True,
        "has_keys": False,
        "key_expiry_warning_days": dbstore.get_setting_typed("key_expiry_warning_days"),
        "tailnet_configured": _is_tailnet_configured(),
        "keys_error": error_message,
    }

HEALTH_SUMMARY_SETTINGS = (
    "timezone", "online_threshold_minutes", "key_threshold_minutes",
    "update_healthy_is_included_in_health",
    "global_healthy_threshold", "global_key_healthy_threshold",
    "global_online_healthy_threshold", "global_update_healthy_threshold",
    "include_os", "exclude_os", "include_identifier", "exclude_identifier",
    "include_tags", "exclude_tags",
    "include_identifier_update_healthy", "exclude_identifier_update_healthy",
    "include_tag_update_healthy", "exclude_tag_update_healthy",
)

def _compute_health_summary(devices):
    """Compute normalized device health list and aggregate metrics.

    Returns (device_list, metrics_dict). Mirrors /health logic for consistency.

    Resolves all needed settings once via dbstore.get_settings_typed() up
    front (a single DB round trip) rather than once per device in the loop
    below.
    """
    cfg = dbstore.get_settings_typed(HEALTH_SUMMARY_SETTINGS)
    try:
        tz = pytz.timezone(cfg["timezone"])
    except pytz.UnknownTimeZoneError:
        raise ValueError(f"Unknown timezone: {cfg['timezone']}")

    device_filters = {name: cfg[name] for name in DEVICE_FILTER_SETTINGS}
    update_healthy_filters = {name: cfg[name] for name in UPDATE_HEALTHY_FILTER_SETTINGS}

    threshold_time = datetime.now(tz) - timedelta(minutes=cfg["online_threshold_minutes"])
    health_status = []
    counter_healthy_true = 0
    counter_healthy_false = 0
    counter_healthy_online_true = 0
    counter_healthy_online_false = 0
    counter_key_healthy_true = 0
    counter_key_healthy_false = 0
    counter_update_healthy_true = 0
    counter_update_healthy_false = 0

    for device in devices:
        if not should_include_device(device, device_filters):
            continue
        last_seen_local = _parse_last_seen_local(device, tz)
        expires = None
        key_healthy = True if device.get("keyExpiryDisabled", False) else True
        key_days_to_expire = None
        if not device.get("keyExpiryDisabled", False) and device.get("expires"):
            expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
            expires = expires.astimezone(tz)
            time_until_expiry = expires - datetime.now(tz)
            key_healthy = time_until_expiry.total_seconds() / 60 > cfg["key_threshold_minutes"]
            key_days_to_expire = time_until_expiry.days

        online_is_healthy = _determine_online_status(device, last_seen_local, threshold_time)
        update_is_healthy = should_force_update_healthy(device, update_healthy_filters) or not device.get("updateAvailable", False)
        key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
        is_healthy = online_is_healthy and key_healthy
        if cfg["update_healthy_is_included_in_health"]:
            is_healthy = is_healthy and update_is_healthy

        if is_healthy:
            counter_healthy_true += 1
        else:
            counter_healthy_false += 1
        if online_is_healthy:
            counter_healthy_online_true += 1
        else:
            counter_healthy_online_false += 1
        if key_healthy:
            counter_key_healthy_true += 1
        else:
            counter_key_healthy_false += 1
        if not device.get("updateAvailable", False):
            counter_update_healthy_true += 1
        else:
            counter_update_healthy_false += 1

        machine_name = device["name"].split('.')[0]
        health_info = {
            "id": device["id"],
            "device": device["name"],
            "machineName": machine_name,
            "hostname": device["hostname"],
            "os": device["os"],
            "clientVersion": device.get("clientVersion", ""),
            "updateAvailable": device.get("updateAvailable", False),
            "update_healthy": update_is_healthy,
            "connectedToControl": device.get("connectedToControl"),
            "lastSeen": last_seen_local.isoformat() if last_seen_local else None,
            "online_healthy": online_is_healthy,
            "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
            "key_healthy": key_healthy,
            "key_days_to_expire": key_days_to_expire,
            "healthy": is_healthy,
            "tags": remove_tag_prefix(device.get("tags", [])),
        }
        if not device.get("keyExpiryDisabled", False):
            health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
        health_status.append(health_info)

    metrics = {
        "counter_healthy_true": counter_healthy_true,
        "counter_healthy_false": counter_healthy_false,
        "counter_healthy_online_true": counter_healthy_online_true,
        "counter_healthy_online_false": counter_healthy_online_false,
        "counter_key_healthy_true": counter_key_healthy_true,
        "counter_key_healthy_false": counter_key_healthy_false,
        "counter_update_healthy_true": counter_update_healthy_true,
        "counter_update_healthy_false": counter_update_healthy_false,
        "global_healthy": counter_healthy_false <= cfg["global_healthy_threshold"],
        "global_key_healthy": counter_key_healthy_false <= cfg["global_key_healthy_threshold"],
        "global_online_healthy": counter_healthy_online_false <= cfg["global_online_healthy_threshold"],
        "global_update_healthy": counter_update_healthy_false <= cfg["global_update_healthy_threshold"],
    }
    return health_status, metrics


# The routes below serve the React (shadcn/ui) dashboard shell only. All
# data fetching, filtering, and error handling happens client-side against
# the JSON API (/health, /keys, /health/<identifier>) below - these routes
# intentionally do not touch the Tailscale API themselves, so a slow/failing
# upstream never prevents the app shell from loading.
@app.route('/', methods=['GET'])
@app.route('/dashboard', methods=['GET'])
@_apply_limits
def ui_dashboard():
    return render_template('dashboard.html')

@app.route('/devices', methods=['GET'])
@_apply_limits
def ui_devices():
    return render_template('devices.html')

@app.route('/tailnet-keys', methods=['GET'])
@_apply_limits
def ui_tailnet_keys():
    return render_template('tailnet_keys.html')

@app.route('/debug', methods=['GET'])
@_apply_limits
def ui_debug():
    return render_template('debug.html')

@app.route('/device/<string:identifier>', methods=['GET'])
@_apply_limits
def ui_device_detail(identifier: str):
    return render_template('device_detail.html')

DEVICE_FILTER_SETTINGS = (
    "include_os", "exclude_os", "include_identifier", "exclude_identifier",
    "include_tags", "exclude_tags",
)
UPDATE_HEALTHY_FILTER_SETTINGS = (
    "include_identifier_update_healthy", "exclude_identifier_update_healthy",
    "include_tag_update_healthy", "exclude_tag_update_healthy",
)

def should_include_device(device, filters=None):
    """
    Check if a device should be included based on filter settings.

    `filters` should be a dict from dbstore.get_settings_typed(DEVICE_FILTER_SETTINGS),
    resolved once by the caller (not per device) and passed in; if omitted it's
    resolved here as a convenience for direct/standalone calls (e.g. tests).
    """
    if filters is None:
        filters = dbstore.get_settings_typed(DEVICE_FILTER_SETTINGS)
    include_tags, exclude_tags = filters["include_tags"], filters["exclude_tags"]
    include_os, exclude_os = filters["include_os"], filters["exclude_os"]
    include_identifier, exclude_identifier = filters["include_identifier"], filters["exclude_identifier"]

    # Get device identifiers
    identifiers = [
        device["hostname"].lower(),
        device["id"].lower(),
        device["name"].lower(),
        device["name"].split('.')[0].lower()  # machineName
    ]

    # Get device tags without 'tag:' prefix
    device_tags = [tag.replace('tag:', '') for tag in device.get("tags", [])]

    # Tag filtering - check if any device tag matches any pattern
    if include_tags and include_tags.strip() != "":
        tag_patterns = [p.strip() for p in include_tags.split(",") if p.strip()]
        if tag_patterns:
            # Device must have at least one tag that matches any pattern
            if not any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags):
                return False
    elif exclude_tags and exclude_tags.strip() != "":
        tag_patterns = [p.strip() for p in exclude_tags.split(",") if p.strip()]
        if tag_patterns:
            # Device must not have any tag that matches any pattern
            if any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags):
                return False

    # OS filtering
    if include_os and include_os.strip() != "":
        os_patterns = [p.strip() for p in include_os.split(",") if p.strip()]
        if not os_patterns:  # Skip if no valid patterns after cleaning
            return True
        if not any(fnmatch.fnmatch(device["os"], pattern) for pattern in os_patterns):
            return False
    elif exclude_os and exclude_os.strip() != "":
        os_patterns = [p.strip() for p in exclude_os.split(",") if p.strip()]
        if not os_patterns:  # Skip if no valid patterns after cleaning
            return True
        if any(fnmatch.fnmatch(device["os"], pattern) for pattern in os_patterns):
            return False

    # Identifier filtering
    if include_identifier and include_identifier.strip() != "":
        identifier_patterns = [p.strip().lower() for p in include_identifier.split(",") if p.strip()]
        if not identifier_patterns:  # Skip if no valid patterns after cleaning
            return True
        if not any(any(fnmatch.fnmatch(identifier, pattern) for pattern in identifier_patterns) for identifier in identifiers):
            return False
    elif exclude_identifier and exclude_identifier.strip() != "":
        identifier_patterns = [p.strip().lower() for p in exclude_identifier.split(",") if p.strip()]
        if not identifier_patterns:  # Skip if no valid patterns after cleaning
            return True
        if any(any(fnmatch.fnmatch(identifier, pattern) for pattern in identifier_patterns) for identifier in identifiers):
            return False

    return True

def should_force_update_healthy(device, filters=None):
    """
    Check if a device should have forced update_healthy status based on identifier and tag filters.

    `filters` should be a dict from dbstore.get_settings_typed(UPDATE_HEALTHY_FILTER_SETTINGS),
    resolved once by the caller (not per device) and passed in; if omitted it's
    resolved here as a convenience for direct/standalone calls (e.g. tests).
    """
    if filters is None:
        filters = dbstore.get_settings_typed(UPDATE_HEALTHY_FILTER_SETTINGS)
    include_identifier_uh = filters["include_identifier_update_healthy"]
    exclude_identifier_uh = filters["exclude_identifier_update_healthy"]
    include_tag_uh = filters["include_tag_update_healthy"]
    exclude_tag_uh = filters["exclude_tag_update_healthy"]

    identifiers = [
        device["hostname"].lower(),
        device["id"].lower(),
        device["name"].lower(),
        device["name"].split('.')[0].lower()  # machineName
    ]

    device_tags = [tag.replace('tag:', '').lower() for tag in device.get("tags", [])]

    # Check EXCLUDE_TAG_UPDATE_HEALTHY
    if exclude_tag_uh:
        tag_patterns = [p.strip().lower() for p in exclude_tag_uh.split(",") if p.strip()]
        if tag_patterns and any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags):
            return True

    # Check INCLUDE_TAG_UPDATE_HEALTHY
    if include_tag_uh:
        tag_patterns = [p.strip().lower() for p in include_tag_uh.split(",") if p.strip()]
        if tag_patterns:
            return not any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags)

    # Check EXCLUDE_IDENTIFIER_UPDATE_HEALTHY
    if exclude_identifier_uh:
        patterns = [p.strip().lower() for p in exclude_identifier_uh.split(",") if p.strip()]
        if patterns and any(any(fnmatch.fnmatch(identifier, pattern) for pattern in patterns) for identifier in identifiers):
            return True

    # Check INCLUDE_IDENTIFIER_UPDATE_HEALTHY
    if include_identifier_uh:
        patterns = [p.strip().lower() for p in include_identifier_uh.split(",") if p.strip()]
        if patterns:
            return not any(any(fnmatch.fnmatch(identifier, pattern) for pattern in patterns) for identifier in identifiers)

    return False

def remove_tag_prefix(tags):
    if not tags:
        return []
    return [tag.replace('tag:', '') for tag in tags]

def _parse_last_seen_local(device, tz):
    """Return the device lastSeen timestamp converted to the provided timezone."""
    last_seen_raw = device.get("lastSeen")
    if not last_seen_raw and device.get("connectedToControl") is True:
        return datetime.now(tz)
    if not last_seen_raw:
        return None
    try:
        parsed = parser.isoparse(last_seen_raw)
    except (ValueError, TypeError) as exc:
        logging.debug(f"Unable to parse lastSeen for {device.get('name', '<unknown>')}: {exc}")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=pytz.UTC)
    else:
        parsed = parsed.astimezone(pytz.UTC)
    return parsed.astimezone(tz)

def _determine_online_status(device, last_seen_local, threshold_time):
    """Compute online health using connectedToControl when available."""
    connected_flag = device.get("connectedToControl")
    if connected_flag is True:
        return True
    if last_seen_local is None:
        return False
    return last_seen_local >= threshold_time

def _health_endpoint_token_ok() -> bool:
    """Check the optional X-Health-Token header against health_endpoint_token.

    /health (and /health/) is the one route that stays unauthenticated by
    default, for existing monitoring integrations (Gatus, etc.). Setting
    HEALTH_ENDPOINT_TOKEN (env or via /admin/settings) locks it behind a
    shared-secret header instead, without requiring a login session.
    """
    configured_token = dbstore.get_setting("health_endpoint_token")
    if not configured_token:
        return True
    provided = request.headers.get("X-Health-Token", "")
    return hmac.compare_digest(provided, configured_token)

@app.route('/health', methods=['GET'])
@_apply_limits
def health_check():
    if not _health_endpoint_token_ok():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        # Fetch devices from the SQLite snapshot maintained by the background poller
        devices = fetch_devices()

        try:
            health_status, metrics = _compute_health_summary(devices)
        except ValueError as exc:
            logging.error(str(exc))
            return jsonify({"error": str(exc)}), 400

        response = {
            "devices": health_status,
            "metrics": metrics,
            "poll_meta": _build_poll_meta(),
        }

        return jsonify(response)

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except requests.exceptions.HTTPError as e:
        logging.error(f"Upstream Tailscale API error in health_check: {e}")
        payload, status = _upstream_error_payload(e)
        return jsonify(payload), status
    except Exception as e:
        logging.error(f"Error in health_check: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/keys', methods=['GET'])
@_apply_limits
@login_required
def keys_status():
    """Return health status for tailnet API/auth keys.

    Only "api" and "auth" key types are reported; a key is unhealthy once
    its expiry is at or below KEY_EXPIRY_WARNING_DAYS. If TAILNET_DOMAIN is
    not configured, or the tailnet has no such keys, this returns an empty
    list with metrics reflecting that state rather than erroring out.
    """
    try:
        try:
            key_status, metrics = _get_tailnet_keys_status()
        except ValueError as exc:
            logging.error(str(exc))
            return jsonify({"error": str(exc)}), 400

        response = {
            "keys": key_status,
            "metrics": metrics,
        }

        if metrics.get("tailnet_configured") and not metrics.get("keys_error"):
            response["poll_meta"] = _build_poll_meta()

        return jsonify(response)

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except requests.exceptions.HTTPError as e:
        logging.error(f"Upstream Tailscale API error in keys_status: {e}")
        payload, status = _upstream_error_payload(e)
        return jsonify(payload), status
    except Exception as e:
        logging.error(f"Error in keys_status: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/', methods=['GET'])
@_apply_limits
def health_check_redirect():
    # Redirect to /health without trailing slash
    return redirect('/health', code=301)

@app.route('/health/<identifier>', methods=['GET'])
@_apply_limits
@login_required
def health_check_by_identifier(identifier):
    try:
        # Fetch devices from the SQLite snapshot maintained by the background poller
        devices = fetch_devices()
        cfg = dbstore.get_settings_typed(HEALTH_SUMMARY_SETTINGS)
        update_healthy_filters = {name: cfg[name] for name in UPDATE_HEALTHY_FILTER_SETTINGS}

        # Get the timezone object
        try:
            tz = pytz.timezone(cfg["timezone"])
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {cfg['timezone']}")
            return jsonify({"error": f"Unknown timezone: {cfg['timezone']}"}), 400

        # Calculate the threshold time (now - online_threshold_minutes) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=cfg["online_threshold_minutes"])
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Convert identifier to lowercase for case-insensitive comparison
        identifier_lower = identifier.lower()

        # Initialize counters
        counter_healthy_true = 0
        counter_healthy_false = 0
        counter_healthy_online_true = 0
        counter_healthy_online_false = 0
        counter_key_healthy_true = 0
        counter_key_healthy_false = 0
        counter_update_healthy_true = 0
        counter_update_healthy_false = 0

        # Find the device with the matching hostname, ID, name, or machineName
        for device in devices:
            machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
            if (
                device["hostname"].lower() == identifier_lower
                or device["id"].lower() == identifier_lower
                or device["name"].lower() == identifier_lower
                or machine_name.lower() == identifier_lower
            ):
                last_seen_local = _parse_last_seen_local(device, tz)
                expires = None
                key_healthy = True if device.get("keyExpiryDisabled", False) else True
                key_days_to_expire = None
                if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                    expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
                    expires = expires.astimezone(tz)
                    time_until_expiry = expires - datetime.now(tz)
                    key_healthy = time_until_expiry.total_seconds() / 60 > cfg["key_threshold_minutes"]
                    key_days_to_expire = time_until_expiry.days

                if last_seen_local:
                    logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
                elif device.get("connectedToControl") is True:
                    logging.debug(f"Device {device['name']} connected to control; lastSeen omitted.")
                else:
                    logging.debug(f"Device {device['name']} last seen timestamp unavailable.")

                online_is_healthy = _determine_online_status(device, last_seen_local, threshold_time)
                update_is_healthy = should_force_update_healthy(device, update_healthy_filters) or not device.get("updateAvailable", False)
                key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
                is_healthy = online_is_healthy and key_healthy
                if cfg["update_healthy_is_included_in_health"]:
                    is_healthy = is_healthy and update_is_healthy

                # Count only this specific device
                counter_healthy_true = 1 if is_healthy else 0
                counter_healthy_false = 0 if is_healthy else 1
                counter_healthy_online_true = 1 if online_is_healthy else 0
                counter_healthy_online_false = 0 if online_is_healthy else 1
                counter_key_healthy_true = 1 if key_healthy else 0
                counter_key_healthy_false = 0 if key_healthy else 1

                # Update update healthy counters
                if not device.get("updateAvailable", False):
                    counter_update_healthy_true += 1
                else:
                    counter_update_healthy_false += 1

                health_info = {
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "os": device["os"],
                    "clientVersion": device.get("clientVersion", ""),
                    "updateAvailable": device.get("updateAvailable", False),
                    "update_healthy": update_is_healthy,
                    "connectedToControl": device.get("connectedToControl"),
                    "lastSeen": last_seen_local.isoformat() if last_seen_local else None,  # Include timezone offset in ISO format
                    "online_healthy": online_is_healthy,
                    "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                    "key_healthy": key_healthy,
                    "key_days_to_expire": key_days_to_expire,
                    "healthy": online_is_healthy and key_healthy,
                    "tags": remove_tag_prefix(device.get("tags", []))
                }
                
                if not device.get("keyExpiryDisabled", False):
                    health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None

                response = {
                    "device": health_info,
                    "metrics": {
                        "counter_healthy_true": counter_healthy_true,
                        "counter_healthy_false": counter_healthy_false,
                        "counter_healthy_online_true": counter_healthy_online_true,
                        "counter_healthy_online_false": counter_healthy_online_false,
                        "counter_key_healthy_true": counter_key_healthy_true,
                        "counter_key_healthy_false": counter_key_healthy_false,
                        "counter_update_healthy_true": counter_update_healthy_true,
                        "counter_update_healthy_false": counter_update_healthy_false,
                        "global_healthy": counter_healthy_false <= cfg["global_healthy_threshold"],
                        "global_key_healthy": counter_key_healthy_false <= cfg["global_key_healthy_threshold"],
                        "global_online_healthy": counter_healthy_online_false <= cfg["global_online_healthy_threshold"],
                        "global_update_healthy": counter_update_healthy_false <= cfg["global_update_healthy_threshold"]
                    }
                }

                return jsonify(response)

        # If no matching hostname, ID, name, or machineName is found
        return jsonify({"error": "Device not found"}), 404

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except requests.exceptions.HTTPError as e:
        logging.error(f"Upstream Tailscale API error in health_check_by_identifier: {e}")
        payload, status = _upstream_error_payload(e)
        return jsonify(payload), status
    except Exception as e:
        logging.error(f"Error in health_check_by_identifier: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/unhealthy', methods=['GET'])
@_apply_limits
@login_required
def health_check_unhealthy():
    try:
        # Fetch devices from the SQLite snapshot maintained by the background poller
        devices = fetch_devices()
        cfg = dbstore.get_settings_typed(HEALTH_SUMMARY_SETTINGS)
        update_healthy_filters = {name: cfg[name] for name in UPDATE_HEALTHY_FILTER_SETTINGS}

        # Get the timezone object
        try:
            tz = pytz.timezone(cfg["timezone"])
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {cfg['timezone']}")
            return jsonify({"error": f"Unknown timezone: {cfg['timezone']}"}), 400

        # Calculate the threshold time (now - online_threshold_minutes) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=cfg["online_threshold_minutes"])
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Initialize counters
        counter_healthy_true = 0
        counter_healthy_false = 0
        counter_healthy_online_true = 0
        counter_healthy_online_false = 0
        counter_key_healthy_true = 0
        counter_key_healthy_false = 0
        counter_update_healthy_true = 0
        counter_update_healthy_false = 0

        # Check health status for each device and filter unhealthy devices
        unhealthy_devices = []
        for device in devices:
            last_seen_local = _parse_last_seen_local(device, tz)  # Convert lastSeen to the specified timezone
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            key_days_to_expire = None
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > cfg["key_threshold_minutes"]
                key_days_to_expire = time_until_expiry.days

            if last_seen_local:
                logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            elif device.get("connectedToControl") is True:
                logging.debug(f"Device {device['name']} connected to control; lastSeen omitted.")
            else:
                logging.debug(f"Device {device['name']} last seen timestamp unavailable.")

            online_is_healthy = _determine_online_status(device, last_seen_local, threshold_time)
            update_is_healthy = should_force_update_healthy(device, update_healthy_filters) or not device.get("updateAvailable", False)
            key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
            is_healthy = online_is_healthy and key_healthy
            if cfg["update_healthy_is_included_in_health"]:
                is_healthy = is_healthy and update_is_healthy

            if not is_healthy:
                # Count only unhealthy devices that will be output
                counter_healthy_false += 1
                if not online_is_healthy:
                    counter_healthy_online_false += 1
                else:
                    counter_healthy_online_true += 1
                if not key_healthy:
                    counter_key_healthy_false += 1
                else:
                    counter_key_healthy_true += 1

                # Update update healthy counters
                if not device.get("updateAvailable", False):
                    counter_update_healthy_true += 1
                else:
                    counter_update_healthy_false += 1

                machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
                health_info = {
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "os": device["os"],
                    "clientVersion": device.get("clientVersion", ""),
                    "updateAvailable": device.get("updateAvailable", False),
                    "update_healthy": update_is_healthy,
                    "connectedToControl": device.get("connectedToControl"),
                    "lastSeen": last_seen_local.isoformat() if last_seen_local else None,  # Include timezone offset in ISO format
                    "online_healthy": online_is_healthy,
                    "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                    "key_healthy": key_healthy,
                    "key_days_to_expire": key_days_to_expire,
                    "healthy": online_is_healthy and key_healthy,
                    "tags": remove_tag_prefix(device.get("tags", []))
                }
                
                if not device.get("keyExpiryDisabled", False):
                    health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
                
                unhealthy_devices.append(health_info)

        response = {
            "devices": unhealthy_devices,
            "metrics": {
                "counter_healthy_true": counter_healthy_true,
                "counter_healthy_false": counter_healthy_false,
                "counter_healthy_online_true": counter_healthy_online_true,
                "counter_healthy_online_false": counter_healthy_online_false,
                "counter_key_healthy_true": counter_key_healthy_true,
                "counter_key_healthy_false": counter_key_healthy_false,
                "counter_update_healthy_true": counter_update_healthy_true,
                "counter_update_healthy_false": counter_update_healthy_false,
                "global_key_healthy": counter_key_healthy_false <= cfg["global_key_healthy_threshold"],
                "global_online_healthy": counter_healthy_online_false <= cfg["global_online_healthy_threshold"],
                "global_healthy": counter_healthy_false <= cfg["global_healthy_threshold"],
                "global_update_healthy": counter_update_healthy_false <= cfg["global_update_healthy_threshold"]
            }
        }

        return jsonify(response)

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except requests.exceptions.HTTPError as e:
        logging.error(f"Upstream Tailscale API error in health_check_unhealthy: {e}")
        payload, status = _upstream_error_payload(e)
        return jsonify(payload), status
    except Exception as e:
        logging.error(f"Error in health_check_unhealthy: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/healthy', methods=['GET'])
@_apply_limits
@login_required
def health_check_healthy():
    try:
        # Fetch devices from the SQLite snapshot maintained by the background poller
        devices = fetch_devices()
        cfg = dbstore.get_settings_typed(HEALTH_SUMMARY_SETTINGS)
        update_healthy_filters = {name: cfg[name] for name in UPDATE_HEALTHY_FILTER_SETTINGS}

        # Get the timezone object
        try:
            tz = pytz.timezone(cfg["timezone"])
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {cfg['timezone']}")
            return jsonify({"error": f"Unknown timezone: {cfg['timezone']}"}), 400

        # Calculate the threshold time (now - online_threshold_minutes) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=cfg["online_threshold_minutes"])
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Initialize counters
        counter_healthy_true = 0
        counter_healthy_false = 0
        counter_healthy_online_true = 0
        counter_healthy_online_false = 0
        counter_key_healthy_true = 0
        counter_key_healthy_false = 0
        counter_update_healthy_true = 0
        counter_update_healthy_false = 0

        # Check health status for each device and filter healthy devices
        healthy_devices = []
        for device in devices:
            last_seen_local = _parse_last_seen_local(device, tz)  # Convert lastSeen to the specified timezone
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            key_days_to_expire = None
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > cfg["key_threshold_minutes"]
                key_days_to_expire = time_until_expiry.days

            if last_seen_local:
                logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            elif device.get("connectedToControl") is True:
                logging.debug(f"Device {device['name']} connected to control; lastSeen omitted.")
            else:
                logging.debug(f"Device {device['name']} last seen timestamp unavailable.")

            online_is_healthy = _determine_online_status(device, last_seen_local, threshold_time)
            update_is_healthy = should_force_update_healthy(device, update_healthy_filters) or not device.get("updateAvailable", False)
            key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
            is_healthy = online_is_healthy and key_healthy
            if cfg["update_healthy_is_included_in_health"]:
                is_healthy = is_healthy and update_is_healthy

            if is_healthy:
                # Count only healthy devices that will be output
                counter_healthy_true += 1
                counter_healthy_online_true += 1
                counter_key_healthy_true += 1

                # Update update healthy counters
                if not device.get("updateAvailable", False):
                    counter_update_healthy_true += 1
                else:
                    counter_update_healthy_false += 1

                machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
                health_info = {
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "os": device["os"],
                    "clientVersion": device.get("clientVersion", ""),
                    "updateAvailable": device.get("updateAvailable", False),
                    "update_healthy": update_is_healthy,
                    "connectedToControl": device.get("connectedToControl"),
                    "lastSeen": last_seen_local.isoformat() if last_seen_local else None,  # Include timezone offset in ISO format
                    "online_healthy": online_is_healthy,
                    "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                    "key_healthy": key_healthy,
                    "key_days_to_expire": key_days_to_expire,
                    "healthy": online_is_healthy and key_healthy,
                    "tags": remove_tag_prefix(device.get("tags", []))
                }
                
                if not device.get("keyExpiryDisabled", False):
                    health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
                
                healthy_devices.append(health_info)

        response = {
            "devices": healthy_devices,
            "metrics": {
                "counter_healthy_true": counter_healthy_true,
                "counter_healthy_false": counter_healthy_false,
                "counter_healthy_online_true": counter_healthy_online_true,
                "counter_healthy_online_false": counter_healthy_online_false,
                "counter_key_healthy_true": counter_key_healthy_true,
                "counter_key_healthy_false": counter_key_healthy_false,
                "counter_update_healthy_true": counter_update_healthy_true,
                "counter_update_healthy_false": counter_update_healthy_false,
                "global_key_healthy": counter_key_healthy_false <= cfg["global_key_healthy_threshold"],
                "global_online_healthy": counter_healthy_online_false <= cfg["global_online_healthy_threshold"],
                "global_healthy": counter_healthy_false <= cfg["global_healthy_threshold"],
                "global_update_healthy": counter_update_healthy_false <= cfg["global_update_healthy_threshold"]
            }
        }

        return jsonify(response)

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except requests.exceptions.HTTPError as e:
        logging.error(f"Upstream Tailscale API error in health_check_healthy: {e}")
        payload, status = _upstream_error_payload(e)
        return jsonify(payload), status
    except Exception as e:
        logging.error(f"Error in health_check_healthy: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/cache/invalidate', methods=['GET'])
@_apply_limits
@login_required
def cache_invalidate():
    """Trigger an immediate out-of-band poll cycle.

    Kept at this URL/method for backward compatibility with existing
    monitoring scripts; the underlying response cache this route used to
    clear no longer exists (device/key data is now polled into SQLite).
    """
    try:
        poller.run_poll_cycle()
        return jsonify({
            "triggered": True,
            "last_polled_at": dbstore.get_poll_meta(),
        })
    except Exception as e:
        logging.error(f"Error triggering poll: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    dbstore.init_db()
    poller.start()
    app.run(host='0.0.0.0', port=PORT)
