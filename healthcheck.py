import os
import time
import json
import fcntl
import requests
import random
from datetime import datetime, timedelta
from flask import Flask, jsonify, redirect, request, render_template
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
TAILNET_DOMAIN = os.getenv("TAILNET_DOMAIN", "example.com")  # Default to "example.com"
TAILSCALE_API_URL = f"https://api.tailscale.com/api/v2/tailnet/{TAILNET_DOMAIN}/devices"
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your-default-token")
ONLINE_THRESHOLD_MINUTES = int(os.getenv("ONLINE_THRESHOLD_MINUTES", 5))  # Default to 5 minutes
KEY_THRESHOLD_MINUTES = int(os.getenv("KEY_THRESHOLD_MINUTES", 1440))  # Default to 1440 minutes
GLOBAL_HEALTHY_THRESHOLD = int(os.getenv("GLOBAL_HEALTHY_THRESHOLD", 100))
GLOBAL_ONLINE_HEALTHY_THRESHOLD = int(os.getenv("GLOBAL_ONLINE_HEALTHY_THRESHOLD", 100))
GLOBAL_KEY_HEALTHY_THRESHOLD = int(os.getenv("GLOBAL_KEY_HEALTHY_THRESHOLD", 100))
GLOBAL_UPDATE_HEALTHY_THRESHOLD = int(os.getenv("GLOBAL_UPDATE_HEALTHY_THRESHOLD", 100))
UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH = os.getenv("UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH", "NO").upper() == "YES"
DISPLAY_SETTINGS_IN_OUTPUT = os.getenv("DISPLAY_SETTINGS_IN_OUTPUT", "NO").upper() == "YES"

PORT = int(os.getenv("PORT", 5000))  # Default to port 5000
TIMEZONE = os.getenv("TIMEZONE", "UTC")  # Default to UTC
HTTP_TIMEOUT = os.getenv("HTTP_TIMEOUT", "10").strip()

# Rate limiting configuration
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "YES").strip().upper() == "YES"
# Integer only, interpreted as per-minute. 0 disables.
try:
    RATE_LIMIT_PER_IP = int(os.getenv("RATE_LIMIT_PER_IP", "100").strip() or "100")
    if RATE_LIMIT_PER_IP < 0:
        RATE_LIMIT_PER_IP = 0
except Exception:
    RATE_LIMIT_PER_IP = 100
_rl_global_int = os.getenv("RATE_LIMIT_GLOBAL", "").strip()
try:
    RATE_LIMIT_GLOBAL_INT = int(_rl_global_int) if _rl_global_int != "" else 0
    if RATE_LIMIT_GLOBAL_INT < 0:
        RATE_LIMIT_GLOBAL_INT = 0
except Exception:
    RATE_LIMIT_GLOBAL_INT = 0
RATE_LIMIT_STORAGE_URL = os.getenv(
    "RATE_LIMIT_STORAGE_URL",
    "file:///tmp/tailscale-healthcheck-ratelimit.json",
).strip() or None
RATE_LIMIT_HEADERS_ENABLED = os.getenv("RATE_LIMIT_HEADERS_ENABLED", "YES").strip().upper() == "YES"

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

# Retry/backoff configuration
def _get_int_env(name: str, default: int) -> int:
    try:
        raw = os.getenv(name, str(default)).strip()
        val = int(raw) if raw != "" else int(default)
        return val if val >= 0 else int(default)
    except Exception:
        return int(default)

def _get_float_env(name: str, default: float) -> float:
    try:
        raw = os.getenv(name, str(default)).strip()
        val = float(raw) if raw != "" else float(default)
        return val if val >= 0 else float(default)
    except Exception:
        return float(default)

MAX_RETRIES = _get_int_env("MAX_RETRIES", 3)
BACKOFF_BASE_SECONDS = _get_float_env("BACKOFF_BASE_SECONDS", 0.5)
BACKOFF_MAX_SECONDS = _get_float_env("BACKOFF_MAX_SECONDS", 8.0)
BACKOFF_JITTER_SECONDS = _get_float_env("BACKOFF_JITTER_SECONDS", 0.1)

# HTTP method restrictions (read-only proxy, not user-configurable)
ALLOWED_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}

# Caching configuration
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "YES").upper() == "YES"
try:
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60").strip() or 60)
except Exception:
    CACHE_TTL_SECONDS = 60
CACHE_BACKEND = os.getenv("CACHE_BACKEND", "FILE").strip().upper()  # MEMORY, FILE, or REDIS
CACHE_PREFIX = os.getenv("CACHE_PREFIX", "ts_hc").strip() or "ts_hc"
REDIS_URL = os.getenv("REDIS_URL", os.getenv("CACHE_REDIS_URL", "")).strip()
CACHE_FILE_PATH = os.getenv("CACHE_FILE_PATH", "/tmp/tailscale-healthcheck-cache.json").strip()

_redis_client = None
if CACHE_BACKEND == "REDIS" and REDIS_URL:
    try:
        import redis  # type: ignore

        _redis_client = redis.from_url(REDIS_URL)
    except Exception as e:  # pragma: no cover - optional dependency
        logging.warning(f"Redis cache requested but unavailable: {e}. Falling back to MEMORY.")
        _redis_client = None
        CACHE_BACKEND = "MEMORY"

# Simple in-memory cache for Tailscale API responses (per-process)
_cache = {}

def _cache_get(key: str):
    """Return cached value if present and not expired; else None."""
    if not CACHE_ENABLED:
        return None
    if CACHE_BACKEND == "FILE":
        try:
            with open(CACHE_FILE_PATH, "r") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
                try:
                    obj = json.load(fh)
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            expires_at = obj.get("expires_at", 0)
            if expires_at > time.time():
                return obj.get("data")
            # expired -> clear file (best-effort)
            try:
                os.remove(CACHE_FILE_PATH)
            except Exception:
                pass
            return None
        except FileNotFoundError:
            return None
        except Exception as e:  # pragma: no cover - runtime-only
            logging.warning(f"File cache read failed: {e}. Treating as miss.")
            return None
    elif CACHE_BACKEND == "REDIS" and _redis_client is not None:
        try:
            raw = _redis_client.get(f"{CACHE_PREFIX}:{key}")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:  # pragma: no cover - runtime-only
            logging.warning(f"Redis get failed: {e}. Treating as miss.")
            return None
    else:
        entry = _cache.get(key)
        now = time.time()
        if entry and entry.get("expires_at", 0) > now:
            return entry.get("data")
        # Expired or missing
        if key in _cache:
            _cache.pop(key, None)
        return None

def _cache_set(key: str, data):
    """Store value in cache with TTL, if caching enabled and TTL > 0."""
    if not CACHE_ENABLED or CACHE_TTL_SECONDS <= 0:
        return
    if CACHE_BACKEND == "FILE":
        # Write atomically via temp file + rename
        try:
            directory = os.path.dirname(CACHE_FILE_PATH) or "."
            os.makedirs(directory, exist_ok=True)
            tmp_path = f"{CACHE_FILE_PATH}.tmp"
            obj = {"data": data, "expires_at": time.time() + CACHE_TTL_SECONDS}
            with open(tmp_path, "w") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                json.dump(obj, fh)
                fh.flush()
                os.fsync(fh.fileno())
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            os.replace(tmp_path, CACHE_FILE_PATH)
            return
        except Exception as e:  # pragma: no cover - runtime-only
            logging.warning(f"File cache write failed: {e}. Falling back to MEMORY for this write.")
    elif CACHE_BACKEND == "REDIS" and _redis_client is not None:
        try:
            _redis_client.setex(
                name=f"{CACHE_PREFIX}:{key}",
                time=CACHE_TTL_SECONDS,
                value=json.dumps(data),
            )
            return
        except Exception as e:  # pragma: no cover - runtime-only
            logging.warning(f"Redis set failed: {e}. Falling back to MEMORY for this write.")
    _cache[key] = {
        "data": data,
        "expires_at": time.time() + CACHE_TTL_SECONDS,
    }

def _cache_clear():
    """Clear in-memory cache."""
    if CACHE_BACKEND == "FILE":
        try:
            os.remove(CACHE_FILE_PATH)
        except FileNotFoundError:
            pass
        except Exception as e:  # pragma: no cover - runtime-only
            logging.warning(f"File cache clear failed: {e}")
    elif CACHE_BACKEND == "REDIS" and _redis_client is not None:
        try:
            # We only use a small, known key set; delete directly
            _redis_client.delete(f"{CACHE_PREFIX}:devices")
        except Exception as e:  # pragma: no cover - runtime-only
            logging.warning(f"Redis clear failed: {e}. Falling back to MEMORY clear.")
    _cache.clear()

def _cache_backend_name():
    if not CACHE_ENABLED:
        return "disabled"
    if CACHE_BACKEND == "FILE":
        return "file"
    if CACHE_BACKEND == "REDIS" and _redis_client is not None:
        return "redis"
    return "memory"

def _get_devices_cache_meta():
    """Return a small metadata dict about the devices cache state.

    Fields: {"hit": bool, "backend": str, "expires_at": iso-or-None, "ttl_seconds": int|None}
    """
    meta = {"hit": False, "backend": _cache_backend_name(), "expires_at": None, "ttl_seconds": None, "loaded_at_iso": None}
    if not CACHE_ENABLED:
        return meta
    key = "devices"
    if CACHE_BACKEND == "FILE":
        try:
            with open(CACHE_FILE_PATH, "r") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
                try:
                    obj = json.load(fh)
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            expires_at = float(obj.get("expires_at", 0))
            if expires_at > time.time():
                meta["hit"] = True
                meta["expires_at"] = datetime.fromtimestamp(expires_at, tz=pytz.UTC).isoformat()
                meta["ttl_seconds"] = int(expires_at - time.time())
                try:
                    loaded_at_ts = float(expires_at) - float(CACHE_TTL_SECONDS)
                    meta["loaded_at_iso"] = datetime.fromtimestamp(loaded_at_ts, tz=pytz.UTC).isoformat()
                except Exception:
                    pass
            return meta
        except Exception:
            return meta
    elif CACHE_BACKEND == "REDIS" and _redis_client is not None:
        try:
            name = f"{CACHE_PREFIX}:{key}"
            raw = _redis_client.get(name)
            if raw is not None:
                meta["hit"] = True
                try:
                    ttl = _redis_client.ttl(name)
                    if isinstance(ttl, int) and ttl >= 0:
                        meta["ttl_seconds"] = ttl
                        # Estimate when it was loaded based on TTL remaining
                        try:
                            loaded_at_ts = time.time() - (CACHE_TTL_SECONDS - ttl)
                            meta["loaded_at_iso"] = datetime.fromtimestamp(loaded_at_ts, tz=pytz.UTC).isoformat()
                        except Exception:
                            pass
                except Exception:
                    pass
            return meta
        except Exception:
            return meta
    else:  # MEMORY
        entry = _cache.get(key)
        if entry and entry.get("expires_at", 0) > time.time():
            meta["hit"] = True
            expires_at = float(entry.get("expires_at", 0))
            meta["expires_at"] = datetime.fromtimestamp(expires_at, tz=pytz.UTC).isoformat()
            meta["ttl_seconds"] = int(expires_at - time.time())
            try:
                loaded_at_ts = float(expires_at) - float(CACHE_TTL_SECONDS)
                meta["loaded_at_iso"] = datetime.fromtimestamp(loaded_at_ts, tz=pytz.UTC).isoformat()
            except Exception:
                pass
        return meta

def get_http_timeout(default: float = 10.0) -> float:
    """Return HTTP timeout (seconds) from `HTTP_TIMEOUT` env var.

    Falls back to `default` if unset/invalid. Ensures a positive float.
    """
    try:
        value = float(HTTP_TIMEOUT) if HTTP_TIMEOUT != "" else float(default)
        return value if value > 0 else float(default)
    except Exception:
        return float(default)

# Filter configurations
INCLUDE_OS = os.getenv("INCLUDE_OS", "").strip()
EXCLUDE_OS = os.getenv("EXCLUDE_OS", "").strip()
INCLUDE_IDENTIFIER = os.getenv("INCLUDE_IDENTIFIER", "").strip()
EXCLUDE_IDENTIFIER = os.getenv("EXCLUDE_IDENTIFIER", "").strip()
INCLUDE_TAGS = os.getenv("INCLUDE_TAGS", "").strip()
EXCLUDE_TAGS = os.getenv("EXCLUDE_TAGS", "").strip()
INCLUDE_IDENTIFIER_UPDATE_HEALTHY = os.getenv("INCLUDE_IDENTIFIER_UPDATE_HEALTHY", "").strip()
EXCLUDE_IDENTIFIER_UPDATE_HEALTHY = os.getenv("EXCLUDE_IDENTIFIER_UPDATE_HEALTHY", "").strip()
INCLUDE_TAG_UPDATE_HEALTHY = os.getenv("INCLUDE_TAG_UPDATE_HEALTHY", "").strip()
EXCLUDE_TAG_UPDATE_HEALTHY = os.getenv("EXCLUDE_TAG_UPDATE_HEALTHY", "").strip()

# Load OAuth configuration from environment variables
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")

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
    try:
        response = requests.post(
            "https://api.tailscale.com/api/v2/oauth/token",
            data={
                "client_id": OAUTH_CLIENT_ID,
                "client_secret": OAUTH_CLIENT_SECRET
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
        TOKEN_RENEWAL_TIMER.start()

        # Log the token renewal time only if it's not the initial fetch
        if not IS_INITIAL_FETCH:
            try:
                tz = pytz.timezone(TIMEZONE)
                renewal_time = datetime.now(tz).isoformat()
                logging.info(f"OAuth access token renewed at {renewal_time} ({TIMEZONE}).")
            except pytz.UnknownTimeZoneError:
                logging.error(f"Unknown timezone: {TIMEZONE}. Logging renewal time in UTC.")
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
    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET:
        logging.info("OAuth configuration detected. Fetching initial access token...")
        fetch_oauth_token()

# Only initialize OAuth in the Gunicorn master process
if os.getenv("GUNICORN_MASTER_PROCESS", "false").lower() == "true":
    initialize_oauth()

# Log the configured timezone
logging.debug(f"Configured TIMEZONE: {TIMEZONE}")

@app.before_request
def enforce_read_only_methods():
    """Reject non-read methods with a 403 to enforce read-only proxy.

    Allowed methods are strictly GET, HEAD, and OPTIONS (not configurable).
    """
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

def make_authenticated_request(url, headers):
    """
    Make an authenticated GET request with bounded, iterative retries.

    - Retries only on transient connection errors (e.g., RemoteDisconnected, ProtocolError).
    - On 401, fetches a new OAuth token and retries once immediately within the same attempt.
    - Uses exponential backoff with jitter between attempts.
    - Honours `HTTP_TIMEOUT` for each request attempt.
    - Bounds attempts by `MAX_RETRIES` (total attempts, not additional retries).
    """
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
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
            if attempt >= MAX_RETRIES:
                break
            # Compute backoff with jitter and sleep
            delay = min(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), BACKOFF_MAX_SECONDS)
            jitter = random.uniform(0, BACKOFF_JITTER_SECONDS) if BACKOFF_JITTER_SECONDS > 0 else 0.0
            sleep_for = max(0.0, delay + jitter)
            logging.error(
                "Connection error during authenticated request. Will retry.",
                extra={
                    "event": "auth_request_retry",
                    "attempt": attempt,
                    "max_retries": MAX_RETRIES,
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
            "max_retries": MAX_RETRIES,
            "error": str(last_err) if last_err else "unknown",
        },
    )
    raise RuntimeError("Max retries exceeded for authenticated request")

def fetch_devices():
    """Fetch devices from Tailscale API with optional caching.

    Returns a list/dict payload from the Tailscale API `devices` endpoint.
    Caches the full HTTP JSON response body under key "devices".
    """
    # Try cache first
    cached = _cache_get("devices")
    if cached is not None:
        return cached.get("devices", [])

    # Determine the authorization method
    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and ACCESS_TOKEN:
        auth_header = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    else:
        auth_header = {"Authorization": f"Bearer {AUTH_TOKEN}"}

    response = make_authenticated_request(TAILSCALE_API_URL, auth_header)
    payload = response.json()
    _cache_set("devices", payload)
    return payload.get("devices", [])

def _compute_health_summary(devices):
    """Compute normalized device health list and aggregate metrics.

    Returns (device_list, metrics_dict). Mirrors /health logic for consistency.
    """
    try:
        tz = pytz.timezone(TIMEZONE)
    except pytz.UnknownTimeZoneError:
        raise ValueError(f"Unknown timezone: {TIMEZONE}")

    threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
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
        if not should_include_device(device):
            continue
        last_seen = parser.isoparse(device["lastSeen"]).replace(tzinfo=pytz.UTC)
        last_seen_local = last_seen.astimezone(tz)
        expires = None
        key_healthy = True if device.get("keyExpiryDisabled", False) else True
        key_days_to_expire = None
        if not device.get("keyExpiryDisabled", False) and device.get("expires"):
            expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
            expires = expires.astimezone(tz)
            time_until_expiry = expires - datetime.now(tz)
            key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES
            key_days_to_expire = time_until_expiry.days

        online_is_healthy = last_seen_local >= threshold_time
        update_is_healthy = should_force_update_healthy(device) or not device.get("updateAvailable", False)
        key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
        is_healthy = online_is_healthy and key_healthy
        if UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH:
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
            "lastSeen": last_seen_local.isoformat(),
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
        "global_healthy": counter_healthy_false <= GLOBAL_HEALTHY_THRESHOLD,
        "global_key_healthy": counter_key_healthy_false <= GLOBAL_KEY_HEALTHY_THRESHOLD,
        "global_online_healthy": counter_healthy_online_false <= GLOBAL_ONLINE_HEALTHY_THRESHOLD,
        "global_update_healthy": counter_update_healthy_false <= GLOBAL_UPDATE_HEALTHY_THRESHOLD,
    }
    return health_status, metrics

def _find_device_by_identifier(identifier: str, devices):
    ident = identifier.strip().lower()
    for device in devices:
        names = [
            device.get("id", "").lower(),
            device.get("hostname", "").lower(),
            device.get("name", "").lower(),
            device.get("name", "").split('.')[0].lower() if device.get("name") else "",
        ]
        if ident in names:
            return device
    return None

def _build_settings_dict():
    """Build a redacted settings dictionary for optional UI display."""
    # Determine rate-limit backend descriptor
    if not RATE_LIMIT_ENABLED:
        rl_backend = "disabled"
    elif _USE_FILE_RATE_LIMIT:
        rl_backend = "file"
    elif limiter is not None:
        rl_backend = "flask-limiter"
    else:
        rl_backend = "unknown"

    # Mask potentially sensitive URLs
    masked_rate_limit_storage = "********" if RATE_LIMIT_STORAGE_URL else ""
    masked_redis_url = "********" if REDIS_URL else ""

    return {
        "TAILNET_DOMAIN": TAILNET_DOMAIN,
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        "OAUTH_CLIENT_ID": OAUTH_CLIENT_ID if OAUTH_CLIENT_ID else "not configured",
        "OAUTH_CLIENT_SECRET": "********" if OAUTH_CLIENT_SECRET else "not configured",
        "AUTH_TOKEN": "********" if AUTH_TOKEN and AUTH_TOKEN != "your-default-token" else "not configured",
        "HTTP_TIMEOUT": get_http_timeout(),
        "ONLINE_THRESHOLD_MINUTES": ONLINE_THRESHOLD_MINUTES,
        "KEY_THRESHOLD_MINUTES": KEY_THRESHOLD_MINUTES,
        "GLOBAL_HEALTHY_THRESHOLD": GLOBAL_HEALTHY_THRESHOLD,
        "GLOBAL_ONLINE_HEALTHY_THRESHOLD": GLOBAL_ONLINE_HEALTHY_THRESHOLD,
        "GLOBAL_KEY_HEALTHY_THRESHOLD": GLOBAL_KEY_HEALTHY_THRESHOLD,
        "GLOBAL_UPDATE_HEALTHY_THRESHOLD": GLOBAL_UPDATE_HEALTHY_THRESHOLD,
        "UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH": UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH,
        "DISPLAY_SETTINGS_IN_OUTPUT": DISPLAY_SETTINGS_IN_OUTPUT,
        "TIMEZONE": TIMEZONE,
        "INCLUDE_OS": INCLUDE_OS if INCLUDE_OS else "",
        "EXCLUDE_OS": EXCLUDE_OS if EXCLUDE_OS else "",
        "INCLUDE_IDENTIFIER": INCLUDE_IDENTIFIER if INCLUDE_IDENTIFIER else "",
        "EXCLUDE_IDENTIFIER": EXCLUDE_IDENTIFIER if EXCLUDE_IDENTIFIER else "",
        "INCLUDE_TAGS": INCLUDE_TAGS if INCLUDE_TAGS else "",
        "EXCLUDE_TAGS": EXCLUDE_TAGS if EXCLUDE_TAGS else "",
        "INCLUDE_IDENTIFIER_UPDATE_HEALTHY": INCLUDE_IDENTIFIER_UPDATE_HEALTHY if INCLUDE_IDENTIFIER_UPDATE_HEALTHY else "",
        "EXCLUDE_IDENTIFIER_UPDATE_HEALTHY": EXCLUDE_IDENTIFIER_UPDATE_HEALTHY if EXCLUDE_IDENTIFIER_UPDATE_HEALTHY else "",
        "INCLUDE_TAG_UPDATE_HEALTHY": INCLUDE_TAG_UPDATE_HEALTHY if INCLUDE_TAG_UPDATE_HEALTHY else "",
        "EXCLUDE_TAG_UPDATE_HEALTHY": EXCLUDE_TAG_UPDATE_HEALTHY if EXCLUDE_TAG_UPDATE_HEALTHY else "",
        "CACHE_ENABLED": CACHE_ENABLED,
        "CACHE_TTL_SECONDS": CACHE_TTL_SECONDS,
        "CACHE_BACKEND": CACHE_BACKEND,
        "CACHE_PREFIX": CACHE_PREFIX,
        "CACHE_FILE_PATH": CACHE_FILE_PATH,
        "REDIS_URL": masked_redis_url,
        "RATE_LIMIT_ENABLED": RATE_LIMIT_ENABLED,
        "RATE_LIMIT_PER_IP": RATE_LIMIT_PER_IP,
        "RATE_LIMIT_GLOBAL": RATE_LIMIT_GLOBAL_INT,
        "RATE_LIMIT_STORAGE_URL": masked_rate_limit_storage,
        "RATE_LIMIT_HEADERS_ENABLED": RATE_LIMIT_HEADERS_ENABLED,
        "RATE_LIMIT_BACKEND": rl_backend,
    }

@app.route('/', methods=['GET'])
@app.route('/dashboard', methods=['GET'])
@_apply_limits
def ui_dashboard():
    """Render the web dashboard with summary metrics and device list.

    Server-renders data and includes a small JS to enable client-side
    search/filtering and export to CSV/JSON.
    """
    try:
        # Fetch devices first so cache is populated for meta display
        devices = fetch_devices()
        health_list, metrics = _compute_health_summary(devices)
        cache_meta = _get_devices_cache_meta()
        settings = _build_settings_dict()
        # Load time in configured timezone
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            tz = pytz.UTC
        loaded_at = datetime.now(tz)
        loaded_at_human = loaded_at.strftime('%Y-%m-%d %H:%M:%S %Z')
        loaded_at_iso = cache_meta.get("loaded_at_iso") or loaded_at.isoformat()
        # Unique OS and tag options for filters
        os_values = sorted({d.get("os", "") for d in health_list if d.get("os")})
        tag_values = sorted({tag for d in health_list for tag in (d.get("tags") or [])})
        return render_template(
            'dashboard.html',
            devices=health_list,
            metrics=metrics,
            os_values=os_values,
            tag_values=tag_values,
            show_settings=DISPLAY_SETTINGS_IN_OUTPUT,
            settings=settings if DISPLAY_SETTINGS_IN_OUTPUT else None,
            cache_meta=cache_meta,
            loaded_at=loaded_at_iso,
            loaded_at_human=loaded_at_human,
        )
    except ValueError as ve:
        return render_template('error.html', message=str(ve)), 400
    except requests.exceptions.Timeout as e:
        logging.warning(f"Timeout rendering dashboard: {e}")
        return render_template('error.html', message="Request to external API timed out"), 504
    except Exception as e:
        logging.error(f"Error rendering dashboard: {e}")
        return render_template('error.html', message="Unexpected server error"), 500

@app.route('/device/<string:identifier>', methods=['GET'])
@_apply_limits
def ui_device_detail(identifier: str):
    """Render a device detail page with safe fields only."""
    try:
        devices = fetch_devices()
        device = _find_device_by_identifier(identifier, devices)
        if not device:
            # Use UI 404 for unknown device
            return render_template("404.html", error_title="Device Not Found", payload={"error": "Not Found", "status": 404}), 404

        # Reuse summary computation for a single device
        summary_list, _ = _compute_health_summary([device])
        detail = summary_list[0] if summary_list else None
        if not detail:
            return render_template("404.html", error_title="Device Not Found", payload={"error": "Not Found", "status": 404}), 404

        # Render detail view; do not expose sensitive API data
        return render_template('device_detail.html', device=detail)
    except ValueError as ve:
        return render_template('error.html', message=str(ve)), 400
    except requests.exceptions.Timeout as e:
        logging.warning(f"Timeout rendering device detail: {e}")
        return render_template('error.html', message="Request to external API timed out"), 504
    except Exception as e:
        logging.error(f"Error rendering device detail: {e}")
        return render_template('error.html', message="Unexpected server error"), 500

def should_include_device(device):
    """
    Check if a device should be included based on filter settings
    """
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
    if INCLUDE_TAGS and INCLUDE_TAGS.strip() != "":
        tag_patterns = [p.strip() for p in INCLUDE_TAGS.split(",") if p.strip()]
        if tag_patterns:
            # Device must have at least one tag that matches any pattern
            if not any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags):
                return False
    elif EXCLUDE_TAGS and EXCLUDE_TAGS.strip() != "":
        tag_patterns = [p.strip() for p in EXCLUDE_TAGS.split(",") if p.strip()]
        if tag_patterns:
            # Device must not have any tag that matches any pattern
            if any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags):
                return False

    # OS filtering
    if INCLUDE_OS and INCLUDE_OS.strip() != "":
        os_patterns = [p.strip() for p in INCLUDE_OS.split(",") if p.strip()]
        if not os_patterns:  # Skip if no valid patterns after cleaning
            return True
        if not any(fnmatch.fnmatch(device["os"], pattern) for pattern in os_patterns):
            return False
    elif EXCLUDE_OS and EXCLUDE_OS.strip() != "":
        os_patterns = [p.strip() for p in EXCLUDE_OS.split(",") if p.strip()]
        if not os_patterns:  # Skip if no valid patterns after cleaning
            return True
        if any(fnmatch.fnmatch(device["os"], pattern) for pattern in os_patterns):
            return False

    # Identifier filtering
    if INCLUDE_IDENTIFIER and INCLUDE_IDENTIFIER.strip() != "":
        identifier_patterns = [p.strip().lower() for p in INCLUDE_IDENTIFIER.split(",") if p.strip()]
        if not identifier_patterns:  # Skip if no valid patterns after cleaning
            return True
        if not any(any(fnmatch.fnmatch(identifier, pattern) for pattern in identifier_patterns) for identifier in identifiers):
            return False
    elif EXCLUDE_IDENTIFIER and EXCLUDE_IDENTIFIER.strip() != "":
        identifier_patterns = [p.strip().lower() for p in EXCLUDE_IDENTIFIER.split(",") if p.strip()]
        if not identifier_patterns:  # Skip if no valid patterns after cleaning
            return True
        if any(any(fnmatch.fnmatch(identifier, pattern) for pattern in identifier_patterns) for identifier in identifiers):
            return False

    return True

def should_force_update_healthy(device):
    """
    Check if a device should have forced update_healthy status based on identifier and tag filters
    """
    identifiers = [
        device["hostname"].lower(),
        device["id"].lower(),
        device["name"].lower(),
        device["name"].split('.')[0].lower()  # machineName
    ]
    
    device_tags = [tag.replace('tag:', '').lower() for tag in device.get("tags", [])]
    
    # Check EXCLUDE_TAG_UPDATE_HEALTHY
    if EXCLUDE_TAG_UPDATE_HEALTHY:
        tag_patterns = [p.strip().lower() for p in EXCLUDE_TAG_UPDATE_HEALTHY.split(",") if p.strip()]
        if tag_patterns and any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags):
            return True
            
    # Check INCLUDE_TAG_UPDATE_HEALTHY
    if INCLUDE_TAG_UPDATE_HEALTHY:
        tag_patterns = [p.strip().lower() for p in INCLUDE_TAG_UPDATE_HEALTHY.split(",") if p.strip()]
        if tag_patterns:
            return not any(any(fnmatch.fnmatch(tag, pattern) for pattern in tag_patterns) for tag in device_tags)
    
    # Check EXCLUDE_IDENTIFIER_UPDATE_HEALTHY
    if EXCLUDE_IDENTIFIER_UPDATE_HEALTHY:
        patterns = [p.strip().lower() for p in EXCLUDE_IDENTIFIER_UPDATE_HEALTHY.split(",") if p.strip()]
        if patterns and any(any(fnmatch.fnmatch(identifier, pattern) for pattern in patterns) for identifier in identifiers):
            return True
            
    # Check INCLUDE_IDENTIFIER_UPDATE_HEALTHY
    if INCLUDE_IDENTIFIER_UPDATE_HEALTHY:
        patterns = [p.strip().lower() for p in INCLUDE_IDENTIFIER_UPDATE_HEALTHY.split(",") if p.strip()]
        if patterns:
            return not any(any(fnmatch.fnmatch(identifier, pattern) for pattern in patterns) for identifier in identifiers)
            
    return False

def remove_tag_prefix(tags):
    if not tags:
        return []
    return [tag.replace('tag:', '') for tag in tags]

@app.route('/health', methods=['GET'])
@_apply_limits
def health_check():
    try:
        # Fetch devices (uses cache if enabled)
        devices = fetch_devices()

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Check health status for each device
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
            # Apply filters
            if not should_include_device(device):
                continue

            last_seen = parser.isoparse(device["lastSeen"]).replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            key_days_to_expire = None
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES
                key_days_to_expire = time_until_expiry.days

            online_is_healthy = last_seen_local >= threshold_time
            update_is_healthy = should_force_update_healthy(device) or not device.get("updateAvailable", False)
            key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
            is_healthy = online_is_healthy and key_healthy
            if UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH:
                is_healthy = is_healthy and update_is_healthy

            # Update counters
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

            # Update update healthy counters
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
                "update_healthy": should_force_update_healthy(device) or not device.get("updateAvailable", False),
                "lastSeen": last_seen_local.isoformat(),
                "online_healthy": online_is_healthy,
                "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                "key_healthy": key_healthy,
                "key_days_to_expire": key_days_to_expire,
                "healthy": is_healthy,
                "tags": remove_tag_prefix(device.get("tags", []))
            }
            
            if not device.get("keyExpiryDisabled", False):
                health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
            
            health_status.append(health_info)

        # Add counters and global health metrics to response
        settings = _build_settings_dict()

        response = {
            "devices": health_status,
            "metrics": {
                "counter_healthy_true": counter_healthy_true,
                "counter_healthy_false": counter_healthy_false,
                "counter_healthy_online_true": counter_healthy_online_true,
                "counter_healthy_online_false": counter_healthy_online_false,
                "counter_key_healthy_true": counter_key_healthy_true,
                "counter_key_healthy_false": counter_key_healthy_false,
                "counter_update_healthy_true": counter_update_healthy_true,
                "counter_update_healthy_false": counter_update_healthy_false,
                "global_healthy": counter_healthy_false <= GLOBAL_HEALTHY_THRESHOLD,
                "global_key_healthy": counter_key_healthy_false <= GLOBAL_KEY_HEALTHY_THRESHOLD,
                "global_online_healthy": counter_healthy_online_false <= GLOBAL_ONLINE_HEALTHY_THRESHOLD,
                "global_update_healthy": counter_update_healthy_false <= GLOBAL_UPDATE_HEALTHY_THRESHOLD
            }
        }
        
        if DISPLAY_SETTINGS_IN_OUTPUT:
            response["settings"] = settings

        return jsonify(response)

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except Exception as e:
        logging.error(f"Error in health_check: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/', methods=['GET'])
@_apply_limits
def health_check_redirect():
    # Redirect to /health without trailing slash
    return redirect('/health', code=301)

@app.route('/health/<identifier>', methods=['GET'])
@_apply_limits
def health_check_by_identifier(identifier):
    try:
        # Fetch devices (uses cache if enabled)
        devices = fetch_devices()

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
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
                last_seen = parser.isoparse(device["lastSeen"]).replace(tzinfo=pytz.UTC)
                last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
                expires = None
                key_healthy = True if device.get("keyExpiryDisabled", False) else True
                key_days_to_expire = None
                if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                    expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
                    expires = expires.astimezone(tz)
                    time_until_expiry = expires - datetime.now(tz)
                    key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES
                    key_days_to_expire = time_until_expiry.days

                logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
                online_is_healthy = last_seen_local >= threshold_time
                update_is_healthy = should_force_update_healthy(device) or not device.get("updateAvailable", False)
                key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
                is_healthy = online_is_healthy and key_healthy
                if UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH:
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
                    "update_healthy": should_force_update_healthy(device) or not device.get("updateAvailable", False),
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                    "online_healthy": online_is_healthy,
                    "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                    "key_healthy": key_healthy,
                    "key_days_to_expire": key_days_to_expire,
                    "healthy": online_is_healthy and key_healthy,
                    "tags": remove_tag_prefix(device.get("tags", []))
                }
                
                if not device.get("keyExpiryDisabled", False):
                    health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
                
                settings = _build_settings_dict()

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
                        "global_healthy": counter_healthy_false <= GLOBAL_HEALTHY_THRESHOLD,
                        "global_key_healthy": counter_key_healthy_false <= GLOBAL_KEY_HEALTHY_THRESHOLD,
                        "global_online_healthy": counter_healthy_online_false <= GLOBAL_ONLINE_HEALTHY_THRESHOLD,
                        "global_update_healthy": counter_update_healthy_false <= GLOBAL_UPDATE_HEALTHY_THRESHOLD
                    }
                }
                
                if DISPLAY_SETTINGS_IN_OUTPUT:
                    response["settings"] = settings
                
                return jsonify(response)

        # If no matching hostname, ID, name, or machineName is found
        return jsonify({"error": "Device not found"}), 404

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except Exception as e:
        logging.error(f"Error in health_check_by_identifier: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/unhealthy', methods=['GET'])
@_apply_limits
def health_check_unhealthy():
    try:
        # Fetch devices (uses cache if enabled)
        devices = fetch_devices()

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
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
            last_seen = parser.isoparse(device["lastSeen"]).replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            key_days_to_expire = None
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES
                key_days_to_expire = time_until_expiry.days

            logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            online_is_healthy = last_seen_local >= threshold_time
            update_is_healthy = should_force_update_healthy(device) or not device.get("updateAvailable", False)
            key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
            is_healthy = online_is_healthy and key_healthy
            if UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH:
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
                    "update_healthy": should_force_update_healthy(device) or not device.get("updateAvailable", False),
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
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

        settings = _build_settings_dict()

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
                "global_key_healthy": counter_key_healthy_false <= GLOBAL_KEY_HEALTHY_THRESHOLD,
                "global_online_healthy": counter_healthy_online_false <= GLOBAL_ONLINE_HEALTHY_THRESHOLD,
                "global_healthy": counter_healthy_false <= GLOBAL_HEALTHY_THRESHOLD,
                "global_update_healthy": counter_update_healthy_false <= GLOBAL_UPDATE_HEALTHY_THRESHOLD
            }
        }
        
        if DISPLAY_SETTINGS_IN_OUTPUT:
            response["settings"] = settings

        return jsonify(response)

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except Exception as e:
        logging.error(f"Error in health_check_unhealthy: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/healthy', methods=['GET'])
@_apply_limits
def health_check_healthy():
    try:
        # Fetch devices (uses cache if enabled)
        devices = fetch_devices()

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
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
            last_seen = parser.isoparse(device["lastSeen"]).replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            key_days_to_expire = None
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = parser.isoparse(device["expires"]).replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES
                key_days_to_expire = time_until_expiry.days

            logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            online_is_healthy = last_seen_local >= threshold_time
            update_is_healthy = should_force_update_healthy(device) or not device.get("updateAvailable", False)
            key_healthy = True if device.get("keyExpiryDisabled", False) else key_healthy
            is_healthy = online_is_healthy and key_healthy
            if UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH:
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
                    "update_healthy": should_force_update_healthy(device) or not device.get("updateAvailable", False),
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
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

        settings = _build_settings_dict()

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
                "global_key_healthy": counter_key_healthy_false <= GLOBAL_KEY_HEALTHY_THRESHOLD,
                "global_online_healthy": counter_healthy_online_false <= GLOBAL_ONLINE_HEALTHY_THRESHOLD,
                "global_healthy": counter_healthy_false <= GLOBAL_HEALTHY_THRESHOLD,
                "global_update_healthy": counter_update_healthy_false <= GLOBAL_UPDATE_HEALTHY_THRESHOLD
            }
        }
        
        if DISPLAY_SETTINGS_IN_OUTPUT:
            response["settings"] = settings

        return jsonify(response)

    except requests.exceptions.Timeout as e:
        logging.error(f"External API request timed out: {e}")
        return jsonify({"error": "Request to external API timed out"}), 504
    except Exception as e:
        logging.error(f"Error in health_check_healthy: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/cache/invalidate', methods=['GET'])
@_apply_limits
def cache_invalidate():
    """Invalidate the in-memory cache.

    Safe, no-op if caching is disabled or cache is already empty.
    """
    try:
        _cache_clear()
        return jsonify({
            "cache_enabled": CACHE_ENABLED,
            "message": "cache cleared"
        })
    except Exception as e:
        logging.error(f"Error clearing cache: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
