"""SQLite-backed persistence: settings, users, device/key snapshots, and audit log.

Envs always take precedence over DB-stored settings; when an env var is present
it is synced into the DB (source='env') on process startup so that removing the
env later leaves the last-known-good value intact (source stays 'env' until a
human explicitly changes it via the admin UI, which writes source='db').
"""
import os
import json
import secrets
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash, check_password_hash

# Every runtime-configurable app setting, keyed by DB setting name. Each spec
# is (env_var, type, default, sentinel, group):
#   - env_var: the environment variable that overrides the DB value when set
#   - type: "str" | "int" | "float" | "bool" - used by get_setting_typed()/
#     get_settings_typed() to cast the stored string; DB storage is always
#     TEXT (bools stored as "YES"/"NO", matching the existing env convention)
#   - default: fallback when neither env nor DB has a value
#   - sentinel: a placeholder value (case-insensitive) that counts as "not
#     set" even though the env var itself is present (e.g. TAILNET_DOMAIN's
#     packaged default of "example.com") - None means no sentinel
#   - group: UI grouping hint for /admin/settings
#
# PORT and Gunicorn bind/worker-count flags are deliberately NOT here - those
# are process-bootstrap concerns (need a restart to matter no matter what),
# not runtime app behavior.
SETTINGS_REGISTRY = {
    # Connection
    "tailnet_domain": ("TAILNET_DOMAIN", "str", None, "example.com", "connection"),
    "auth_token": ("AUTH_TOKEN", "str", None, "your-default-token", "connection"),
    "oauth_client_id": ("OAUTH_CLIENT_ID", "str", None, None, "connection"),
    "oauth_client_secret": ("OAUTH_CLIENT_SECRET", "str", None, None, "connection"),
    # Opt-in header token guarding the public /health endpoint. Empty/unset
    # (the default) leaves /health fully open, matching existing behavior.
    "health_endpoint_token": ("HEALTH_ENDPOINT_TOKEN", "str", None, None, "connection"),
    # Public base URL for this instance (e.g. behind a reverse proxy with a
    # different external hostname). Used by the API docs page for example
    # curl commands and "Try it" calls. Blank means "use relative URLs /
    # derive from the current request", handled at the point of use.
    "api_base_url": ("API_BASE_URL", "str", "", None, "connection"),

    # Health thresholds
    "online_threshold_minutes": ("ONLINE_THRESHOLD_MINUTES", "int", 5, None, "thresholds"),
    "key_threshold_minutes": ("KEY_THRESHOLD_MINUTES", "int", 1440, None, "thresholds"),
    "key_expiry_warning_days": ("KEY_EXPIRY_WARNING_DAYS", "int", 30, None, "thresholds"),
    "global_healthy_threshold": ("GLOBAL_HEALTHY_THRESHOLD", "int", 100, None, "thresholds"),
    "global_online_healthy_threshold": ("GLOBAL_ONLINE_HEALTHY_THRESHOLD", "int", 100, None, "thresholds"),
    "global_key_healthy_threshold": ("GLOBAL_KEY_HEALTHY_THRESHOLD", "int", 100, None, "thresholds"),
    "global_update_healthy_threshold": ("GLOBAL_UPDATE_HEALTHY_THRESHOLD", "int", 100, None, "thresholds"),
    "update_healthy_is_included_in_health": ("UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH", "bool", False, None, "thresholds"),

    # Device filters (comma-separated, wildcards allowed)
    "include_os": ("INCLUDE_OS", "str", "", None, "filters"),
    "exclude_os": ("EXCLUDE_OS", "str", "", None, "filters"),
    "include_identifier": ("INCLUDE_IDENTIFIER", "str", "", None, "filters"),
    "exclude_identifier": ("EXCLUDE_IDENTIFIER", "str", "", None, "filters"),
    "include_tags": ("INCLUDE_TAGS", "str", "", None, "filters"),
    "exclude_tags": ("EXCLUDE_TAGS", "str", "", None, "filters"),
    "include_identifier_update_healthy": ("INCLUDE_IDENTIFIER_UPDATE_HEALTHY", "str", "", None, "filters"),
    "exclude_identifier_update_healthy": ("EXCLUDE_IDENTIFIER_UPDATE_HEALTHY", "str", "", None, "filters"),
    "include_tag_update_healthy": ("INCLUDE_TAG_UPDATE_HEALTHY", "str", "", None, "filters"),
    "exclude_tag_update_healthy": ("EXCLUDE_TAG_UPDATE_HEALTHY", "str", "", None, "filters"),

    # Tailnet key filters (mirror the device filters above, applied in
    # should_include_key() against the inferred key type and description).
    "include_key_type": ("INCLUDE_KEY_TYPE", "str", "", None, "filters"),
    "exclude_key_type": ("EXCLUDE_KEY_TYPE", "str", "", None, "filters"),
    "include_key_description": ("INCLUDE_KEY_DESCRIPTION", "str", "", None, "filters"),
    "exclude_key_description": ("EXCLUDE_KEY_DESCRIPTION", "str", "", None, "filters"),

    # General
    "timezone": ("TIMEZONE", "str", "UTC", None, "general"),
    "http_timeout": ("HTTP_TIMEOUT", "float", 10.0, None, "general"),
    # Takes effect on next process restart only (logging.basicConfig runs once at import).
    "log_level": ("LOG_LEVEL", "str", "INFO", None, "logging"),
    # Whether the background poller records into its in-memory ring buffer
    # (surfaced by the /debug page via /admin/api/debug/poller-log). Disabling
    # this only stops ring-buffer capture; poll cycles still emit to the
    # standard `logging` module either way.
    "debug_log_enabled": ("DEBUG_LOG_ENABLED", "bool", True, None, "logging"),

    # Rate limiting - takes effect on next process restart only (Flask-Limiter
    # and the @_apply_limits decorators are wired up once at route-definition
    # time, not per-request).
    "rate_limit_enabled": ("RATE_LIMIT_ENABLED", "bool", True, None, "rate_limit"),
    "rate_limit_per_ip": ("RATE_LIMIT_PER_IP", "int", 100, None, "rate_limit"),
    "rate_limit_global": ("RATE_LIMIT_GLOBAL", "int", 0, None, "rate_limit"),
    "rate_limit_storage_url": ("RATE_LIMIT_STORAGE_URL", "str", "file:///tmp/tailscale-healthcheck-ratelimit.json", None, "rate_limit"),
    "rate_limit_headers_enabled": ("RATE_LIMIT_HEADERS_ENABLED", "bool", True, None, "rate_limit"),

    # Retry/backoff for outbound Tailscale API calls (read dynamically per call)
    "max_retries": ("MAX_RETRIES", "int", 3, None, "retry"),
    "backoff_base_seconds": ("BACKOFF_BASE_SECONDS", "float", 0.5, None, "retry"),
    "backoff_max_seconds": ("BACKOFF_MAX_SECONDS", "float", 8.0, None, "retry"),
    "backoff_jitter_seconds": ("BACKOFF_JITTER_SECONDS", "float", 0.1, None, "retry"),

    # Poller / audit
    "poll_interval_seconds": ("POLL_INTERVAL_SECONDS", "int", 60, None, "poll"),
    "audit_retention_days": ("AUDIT_RETENTION_DAYS", "int", 14, None, "poll"),
    # Separate (shorter default) retention for the operational poller_log
    # table shown on /debug - this is high-volume, low-stakes activity log,
    # not the compliance-flavored audit_log, so it gets its own knob.
    "poller_log_retention_days": ("POLLER_LOG_RETENTION_DAYS", "int", 7, None, "poll"),
}

# Device/key fields that trigger an audit_log row when changed. `last_seen`
# is excluded - it genuinely changes on every poll for an online device and
# carries no signal. `connected_to_control` IS included: we only write a row
# when the *stored* value differs from the latest poll (not on every poll),
# so a device transitioning online<->offline produces exactly one audit row
# per transition, not one per poll - the noise concern that excluded it from
# the original design doesn't apply here.
DEVICE_AUDIT_FIELDS = (
    "name", "hostname", "os", "tags", "client_version",
    "update_available", "key_expiry_disabled", "expires", "connected_to_control",
)
KEY_AUDIT_FIELDS = ("description", "key_type", "capabilities", "expires")

_DEFAULT_DB_PATH = "/data/healthcheck.db"

# Explicit override captured by configure() (see below). None means "resolve
# from the environment on every call" - the override exists because this
# module is cached in sys.modules across dynamically-reloaded copies of
# healthcheck.py in tests, so DATABASE_PATH can't just be a frozen constant
# computed once at first import, but pure "read os.environ on every call"
# also breaks for test helpers that only set DATABASE_PATH for the duration
# of exec_module() and restore the environment immediately after. configure()
# (called by healthcheck.py at import time) pins the value seen at that
# moment for the rest of this process/module-load.
_database_path_override = None


def _compute_database_path() -> str:
    path = os.getenv("DATABASE_PATH", "").strip()
    if not path:
        # Fall back to a local path when /data isn't writable (local dev/tests).
        if os.path.isdir("/data") and os.access("/data", os.W_OK):
            path = _DEFAULT_DB_PATH
        else:
            path = os.path.join(tempfile.gettempdir(), "tailscale-healthcheck", "healthcheck.db")
    return path


def configure(path: str = None):
    """Pin the database path for the remainder of this process (or module-load).

    Call once, early - healthcheck.py does this right before init_db(). Safe
    to call again (e.g. once per dynamically-reloaded test module) to repoint
    at a different file.
    """
    global _database_path_override
    resolved = path or _compute_database_path()
    directory = os.path.dirname(resolved) or "."
    os.makedirs(directory, exist_ok=True)
    _database_path_override = resolved
    return resolved


def _current_database_path() -> str:
    if _database_path_override is not None:
        return _database_path_override
    resolved = _compute_database_path()
    directory = os.path.dirname(resolved) or "."
    os.makedirs(directory, exist_ok=True)
    return resolved


def __getattr__(name):
    # PEP 562: resolve DATABASE_PATH via the same logic get_connection() uses.
    if name == "DATABASE_PATH":
        return _current_database_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    conn = sqlite3.connect(_current_database_path(), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create schema if it doesn't already exist. Safe to call repeatedly."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                name TEXT PRIMARY KEY,
                value TEXT,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                name TEXT,
                hostname TEXT,
                os TEXT,
                client_version TEXT,
                update_available INTEGER,
                connected_to_control INTEGER,
                last_seen TEXT,
                key_expiry_disabled INTEGER,
                expires TEXT,
                tags TEXT,
                raw_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_polled_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tailnet_keys (
                key_id TEXT PRIMARY KEY,
                description TEXT,
                key_type TEXT,
                capabilities TEXT,
                created TEXT,
                expires TEXT,
                raw_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_polled_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                changes TEXT NOT NULL,
                actor TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_occurred_at ON audit_log(occurred_at);

            CREATE TABLE IF NOT EXISTS metrics_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                counter_healthy_true INTEGER,
                counter_healthy_false INTEGER,
                counter_healthy_online_true INTEGER,
                counter_healthy_online_false INTEGER,
                counter_key_healthy_true INTEGER,
                counter_key_healthy_false INTEGER,
                counter_update_healthy_true INTEGER,
                counter_update_healthy_false INTEGER,
                keys_counter_healthy_true INTEGER,
                keys_counter_healthy_false INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_history_occurred_at ON metrics_history(occurred_at);

            CREATE TABLE IF NOT EXISTS poller_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_poller_log_occurred_at ON poller_log(occurred_at);
            CREATE INDEX IF NOT EXISTS idx_poller_log_event_type ON poller_log(event_type);
            """
        )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _add_audit(conn, entity_type, entity_id, action, changes, actor=None):
    conn.execute(
        "INSERT INTO audit_log (occurred_at, entity_type, entity_id, action, changes, actor) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_now_iso(), entity_type, entity_id, action, json.dumps(changes), actor),
    )


def _db_get_setting_row(conn, name):
    row = conn.execute("SELECT * FROM settings WHERE name = ?", (name,)).fetchone()
    return row


def set_setting(name: str, value, source: str = "db", actor: str = None):
    """Upsert a setting, writing an audit row only when the value actually changes."""
    with get_connection() as conn:
        existing = _db_get_setting_row(conn, name)
        old_value = existing["value"] if existing else None
        if existing is None or old_value != value:
            conn.execute(
                "INSERT INTO settings (name, value, source, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value, source=excluded.source, "
                "updated_at=excluded.updated_at",
                (name, value, source, _now_iso()),
            )
            _add_audit(
                conn, "setting", name,
                "created" if existing is None else "updated",
                {"old": old_value, "new": value, "source": source},
                actor=actor,
            )
        else:
            # Value unchanged; still refresh source/updated_at silently (no audit noise).
            conn.execute(
                "UPDATE settings SET source = ?, updated_at = ? WHERE name = ?",
                (source, _now_iso(), name),
            )


def _env_override_value(name: str):
    """Return the raw string env override for `name`, or None if not applicable.

    "Not applicable" covers: unset, blank, or equal to the registered sentinel.
    """
    spec = SETTINGS_REGISTRY.get(name)
    if not spec:
        return None
    env_var, _type_name, _default, sentinel, _group = spec
    raw = os.getenv(env_var)
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if sentinel is not None and value.lower() == sentinel.lower():
        return None
    return value


def sync_env_settings():
    """Sync every env-backed setting into the DB. Call once per process at startup.

    This is what makes "delete the env var later, keep the last value" and
    "seed the DB from existing envs on first boot after upgrading" work for
    every setting in SETTINGS_REGISTRY, not just the original connection
    ones - it's one generic loop over the registry, not a per-setting rule.

    If an env var that was previously set is later removed, the DB row must
    stop being locked as source='env' - the last known value is kept, but
    source flips back to 'db' so the admin UI unlocks the field again.
    """
    init_db()
    for name in SETTINGS_REGISTRY:
        value = _env_override_value(name)
        if value is not None:
            set_setting(name, value, source="env")
        else:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT source FROM settings WHERE name = ?", (name,)
                ).fetchone()
            if row is not None and row["source"] == "env":
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE settings SET source = 'db', updated_at = ? WHERE name = ?",
                        (_now_iso(), name),
                    )
                    conn.commit()


def get_setting(name: str):
    """Return the effective raw (string) value for a setting: env var if
    set/non-sentinel, else the last DB value, else None."""
    env_value = _env_override_value(name)
    if env_value is not None:
        return env_value
    with get_connection() as conn:
        row = _db_get_setting_row(conn, name)
        return row["value"] if row else None


def _cast(raw: str, type_name: str, default):
    if raw is None:
        return default
    try:
        if type_name == "int":
            return int(raw)
        if type_name == "float":
            return float(raw)
        if type_name == "bool":
            return str(raw).strip().upper() in ("YES", "TRUE", "1", "ON")
        return raw
    except (TypeError, ValueError):
        return default


def encode_setting_value(name: str, value) -> str:
    """Encode a typed value the way it's stored (bools as YES/NO, matching the
    existing env-var convention elsewhere in this project)."""
    _env_var, type_name, _default, _sentinel, _group = SETTINGS_REGISTRY[name]
    if type_name == "bool":
        if isinstance(value, str):
            return "YES" if value.strip().upper() in ("YES", "TRUE", "1", "ON") else "NO"
        return "YES" if value else "NO"
    return str(value)


def validate_setting_value(name: str, raw: str):
    """Cast+validate a raw string against `name`'s registered type.

    Raises ValueError with a human-readable message on failure; returns the
    encoded (storage-ready) string on success.
    """
    _env_var, type_name, default, _sentinel, _group = SETTINGS_REGISTRY[name]
    if type_name in ("int", "float"):
        caster = int if type_name == "int" else float
        try:
            caster(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a valid {type_name}")
    return encode_setting_value(name, raw)


def get_setting_typed(name: str):
    """Return the effective value for `name`, cast to its registered type."""
    _env_var, type_name, default, _sentinel, _group = SETTINGS_REGISTRY[name]
    return _cast(get_setting(name), type_name, default)


def get_settings_typed(names) -> dict:
    """Resolve multiple settings in a single DB round trip.

    Use this instead of calling get_setting_typed() once per item in a loop
    (e.g. once per device) - call it once per request/computation up front,
    then pass the resulting dict down into the per-item logic.
    """
    result = {}
    need_db = []
    for name in names:
        env_value = _env_override_value(name)
        if env_value is not None:
            _env_var, type_name, default, _sentinel, _group = SETTINGS_REGISTRY[name]
            result[name] = _cast(env_value, type_name, default)
        else:
            need_db.append(name)
    if need_db:
        placeholders = ",".join("?" for _ in need_db)
        with get_connection() as conn:
            rows = {
                r["name"]: r["value"]
                for r in conn.execute(f"SELECT name, value FROM settings WHERE name IN ({placeholders})", need_db)
            }
        for name in need_db:
            _env_var, type_name, default, _sentinel, _group = SETTINGS_REGISTRY[name]
            result[name] = _cast(rows.get(name), type_name, default)
    return result


def get_setting_meta(name: str):
    """Return {"value": ..., "source": "env"|"db"|None} for display in the settings UI."""
    env_value = _env_override_value(name)
    if env_value is not None:
        return {"value": env_value, "source": "env"}
    with get_connection() as conn:
        row = _db_get_setting_row(conn, name)
        if row:
            return {"value": row["value"], "source": row["source"]}
        return {"value": None, "source": None}


def is_tailnet_configured() -> bool:
    value = get_setting("tailnet_domain")
    return bool(value) and value.strip().lower() != "example.com"


def get_secret_key() -> str:
    env_value = os.getenv("SECRET_KEY", "").strip()
    if env_value:
        return env_value
    with get_connection() as conn:
        row = _db_get_setting_row(conn, "secret_key")
        if row and row["value"]:
            return row["value"]
    generated = secrets.token_hex(32)
    set_setting("secret_key", generated, source="db")
    return generated


def get_audit_retention_days() -> int:
    return max(1, get_setting_typed("audit_retention_days"))


def set_audit_retention_days(days: int, actor: str = None):
    set_setting("audit_retention_days", str(int(days)), source="db", actor=actor)


def set_poll_meta(last_polled_at: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (name, value, source, updated_at) VALUES ('last_polled_at', ?, 'db', ?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (last_polled_at, _now_iso()),
        )


def get_poll_meta():
    with get_connection() as conn:
        row = _db_get_setting_row(conn, "last_polled_at")
        return row["value"] if row else None


def set_poll_status(ok: bool, error: str = None, auth_error: bool = False):
    """Record the outcome of the most recent poll cycle (devices+keys fetch),
    so the frontend can show a real "can't reach Tailscale" banner instead of
    silently sitting on an empty/stale device list forever."""
    payload = json.dumps({"ok": ok, "error": error, "auth_error": auth_error})
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (name, value, source, updated_at) VALUES ('last_poll_status', ?, 'db', ?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (payload, _now_iso()),
        )


def get_poll_status():
    with get_connection() as conn:
        row = _db_get_setting_row(conn, "last_poll_status")
    if not row or not row["value"]:
        return {"ok": None, "error": None, "auth_error": False}
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return {"ok": None, "error": None, "auth_error": False}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def has_any_user() -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return row["c"] > 0


def create_user(username: str, password: str, actor: str = None):
    password_hash = generate_password_hash(password)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, _now_iso()),
        )
        _add_audit(conn, "user", username, "created", {"username": username}, actor=actor)


def delete_user(username: str, actor: str = None):
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        _add_audit(conn, "user", username, "removed", {"username": username}, actor=actor)


def get_user_by_username(username: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def list_users():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, created_at, last_login_at FROM users ORDER BY username"
        ).fetchall()
        return [dict(r) for r in rows]


def verify_password(username: str, password: str):
    user = get_user_by_username(username)
    if not user:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    with get_connection() as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now_iso(), user["id"]))
    return user


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def _device_row_to_api_dict(row) -> dict:
    tags = json.loads(row["tags"]) if row["tags"] else []
    return {
        "id": row["device_id"],
        "name": row["name"],
        "hostname": row["hostname"],
        "os": row["os"],
        "clientVersion": row["client_version"] or "",
        "updateAvailable": bool(row["update_available"]),
        "connectedToControl": bool(row["connected_to_control"]) if row["connected_to_control"] is not None else None,
        "lastSeen": row["last_seen"],
        "keyExpiryDisabled": bool(row["key_expiry_disabled"]),
        "expires": row["expires"],
        "tags": tags,
    }


def get_devices_snapshot() -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY name").fetchall()
        return [_device_row_to_api_dict(r) for r in rows]


def _device_diff_fields(device: dict) -> dict:
    return {
        "name": device.get("name"),
        "hostname": device.get("hostname"),
        "os": device.get("os"),
        "tags": device.get("tags") or [],
        "client_version": device.get("clientVersion", ""),
        "update_available": bool(device.get("updateAvailable", False)),
        "key_expiry_disabled": bool(device.get("keyExpiryDisabled", False)),
        "expires": device.get("expires"),
        "connected_to_control": _bool_or_none(device.get("connectedToControl")),
    }


def upsert_devices(devices: list):
    """Upsert the latest device snapshot, diffing against curated fields for audit."""
    now = _now_iso()
    seen_ids = set()
    with get_connection() as conn:
        existing_rows = {r["device_id"]: r for r in conn.execute("SELECT * FROM devices").fetchall()}

        for device in devices:
            device_id = device.get("id")
            if not device_id:
                continue
            seen_ids.add(device_id)
            fields = _device_diff_fields(device)
            existing = existing_rows.get(device_id)

            if existing is None:
                conn.execute(
                    "INSERT INTO devices (device_id, name, hostname, os, client_version, "
                    "update_available, connected_to_control, last_seen, key_expiry_disabled, "
                    "expires, tags, raw_json, first_seen_at, last_polled_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        device_id, fields["name"], fields["hostname"], fields["os"],
                        fields["client_version"], int(fields["update_available"]),
                        fields["connected_to_control"],
                        device.get("lastSeen"), int(fields["key_expiry_disabled"]),
                        fields["expires"], json.dumps(fields["tags"]),
                        json.dumps(device), now, now,
                    ),
                )
                _add_audit(conn, "device", device_id, "created", fields)
            else:
                changes = {}
                for field in DEVICE_AUDIT_FIELDS:
                    old_val = _existing_device_field(existing, field)
                    new_val = fields[field]
                    if old_val != new_val:
                        changes[field] = {"old": old_val, "new": new_val}
                conn.execute(
                    "UPDATE devices SET name=?, hostname=?, os=?, client_version=?, "
                    "update_available=?, connected_to_control=?, last_seen=?, "
                    "key_expiry_disabled=?, expires=?, tags=?, raw_json=?, last_polled_at=? "
                    "WHERE device_id=?",
                    (
                        fields["name"], fields["hostname"], fields["os"], fields["client_version"],
                        int(fields["update_available"]), fields["connected_to_control"],
                        device.get("lastSeen"), int(fields["key_expiry_disabled"]), fields["expires"],
                        json.dumps(fields["tags"]), json.dumps(device), now, device_id,
                    ),
                )
                if changes:
                    _add_audit(conn, "device", device_id, "updated", changes)

        removed_ids = set(existing_rows.keys()) - seen_ids
        for device_id in removed_ids:
            conn.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
            _add_audit(conn, "device", device_id, "removed", {"name": existing_rows[device_id]["name"]})


def _existing_device_field(row, field):
    if field == "tags":
        return json.loads(row["tags"]) if row["tags"] else []
    if field in ("update_available", "key_expiry_disabled"):
        return bool(row[field])
    if field == "connected_to_control":
        return row[field]  # already None/0/1, matches fields["connected_to_control"]
    return row[field]


def _bool_or_none(value):
    return None if value is None else int(bool(value))


# ---------------------------------------------------------------------------
# Tailnet keys
# ---------------------------------------------------------------------------

def _key_row_to_api_dict(row) -> dict:
    return {
        "id": row["key_id"],
        "description": row["description"] or "",
        "keyType": row["key_type"],
        "capabilities": json.loads(row["capabilities"]) if row["capabilities"] else {},
        "created": row["created"],
        "expires": row["expires"],
    }


def get_keys_snapshot() -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM tailnet_keys ORDER BY description").fetchall()
        return [_key_row_to_api_dict(r) for r in rows]


def _key_diff_fields(key: dict, key_type: str) -> dict:
    return {
        "description": key.get("description", ""),
        "key_type": key_type,
        "capabilities": key.get("capabilities") or {},
        "expires": key.get("expires"),
    }


def upsert_keys(keys: list, key_type_resolver):
    """Upsert the latest tailnet key snapshot. `key_type_resolver(key) -> str`."""
    now = _now_iso()
    seen_ids = set()
    with get_connection() as conn:
        existing_rows = {r["key_id"]: r for r in conn.execute("SELECT * FROM tailnet_keys").fetchall()}

        for key in keys:
            key_id = key.get("id")
            if not key_id:
                continue
            key_type = key_type_resolver(key)
            if key_type not in ("api", "auth"):
                continue
            seen_ids.add(key_id)
            fields = _key_diff_fields(key, key_type)
            existing = existing_rows.get(key_id)

            if existing is None:
                conn.execute(
                    "INSERT INTO tailnet_keys (key_id, description, key_type, capabilities, "
                    "created, expires, raw_json, first_seen_at, last_polled_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key_id, fields["description"], fields["key_type"],
                        json.dumps(fields["capabilities"]), key.get("created"),
                        fields["expires"], json.dumps(key), now, now,
                    ),
                )
                _add_audit(conn, "tailnet_key", key_id, "created", fields)
            else:
                changes = {}
                for field in KEY_AUDIT_FIELDS:
                    old_val = _existing_key_field(existing, field)
                    new_val = fields[field]
                    if old_val != new_val:
                        changes[field] = {"old": old_val, "new": new_val}
                conn.execute(
                    "UPDATE tailnet_keys SET description=?, key_type=?, capabilities=?, "
                    "created=?, expires=?, raw_json=?, last_polled_at=? WHERE key_id=?",
                    (
                        fields["description"], fields["key_type"], json.dumps(fields["capabilities"]),
                        key.get("created"), fields["expires"], json.dumps(key), now, key_id,
                    ),
                )
                if changes:
                    _add_audit(conn, "tailnet_key", key_id, "updated", changes)

        removed_ids = set(existing_rows.keys()) - seen_ids
        for key_id in removed_ids:
            conn.execute("DELETE FROM tailnet_keys WHERE key_id = ?", (key_id,))
            _add_audit(conn, "tailnet_key", key_id, "removed", {"description": existing_rows[key_id]["description"]})


def _existing_key_field(row, field):
    if field == "capabilities":
        return json.loads(row["capabilities"]) if row["capabilities"] else {}
    return row[field]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def list_audit_log(
    limit: int = 100,
    offset: int = 0,
    entity_type: str = None,
    entity_id: str = None,
    action: str = None,
    actor: str = None,
    start: str = None,
    end: str = None,
):
    """List audit_log rows, most recent first, filters combined with AND.

    `start`/`end` are ISO8601 timestamps (inclusive) filtering occurred_at.
    `actor` matches the exact username, except the special value "poller"
    which matches automatic (actor IS NULL) changes - the poller doesn't
    write an actor of its own, so this is the only way to filter to/from it.
    """
    query = "SELECT * FROM audit_log"
    clauses = []
    params = []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id = ?")
        params.append(entity_id)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if actor:
        if actor == "poller":
            clauses.append("actor IS NULL")
        else:
            clauses.append("actor = ?")
            params.append(actor)
    if start:
        clauses.append("occurred_at >= ?")
        params.append(start)
    if end:
        clauses.append("occurred_at <= ?")
        params.append(end)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            entry = dict(r)
            try:
                entry["changes"] = json.loads(entry["changes"])
            except (TypeError, ValueError):
                pass
            entry["entity_name"] = _resolve_entity_name(conn, entry["entity_type"], entry["entity_id"], entry["changes"])
            result.append(entry)
        return result


def _resolve_entity_name(conn, entity_type: str, entity_id: str, changes):
    """Human-readable label for an audit_log row's entity.

    Prefers the *current* devices/tailnet_keys row (covers "updated" rows,
    where the entity still exists); falls back to whatever name/description
    was captured in `changes` at the time (covers "removed" rows, where the
    live row is gone - upsert_devices()/upsert_keys() always include the name
    in a removal's changes blob for exactly this reason). Falls back to the
    raw id if neither is available (e.g. a device that was both created and
    removed with the name lookup failing for some other reason).
    """
    if entity_type == "device":
        row = conn.execute("SELECT name FROM devices WHERE device_id = ?", (entity_id,)).fetchone()
        if row and row["name"]:
            return row["name"]
        return _name_from_changes(changes, "name") or entity_id
    if entity_type == "tailnet_key":
        row = conn.execute("SELECT description FROM tailnet_keys WHERE key_id = ?", (entity_id,)).fetchone()
        if row and row["description"]:
            return row["description"]
        return _name_from_changes(changes, "description") or entity_id
    # "setting" (entity_id is the setting name) and "user" (entity_id is the
    # username) are already human-readable as-is.
    return entity_id


def _name_from_changes(changes, field: str):
    if not isinstance(changes, dict):
        return None
    value = changes.get(field)
    if isinstance(value, dict):
        return value.get("new") or value.get("old")
    if isinstance(value, str):
        return value
    return None


def list_audit_log_actors():
    """Distinct actors seen in audit_log, for the audit filter UI. "poller"
    stands in for automatic (actor IS NULL) changes."""
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT actor FROM audit_log WHERE actor IS NOT NULL ORDER BY actor").fetchall()
        actors = [r["actor"] for r in rows]
        has_poller = conn.execute("SELECT 1 FROM audit_log WHERE actor IS NULL LIMIT 1").fetchone() is not None
    if has_poller:
        actors.append("poller")
    return actors


def list_audit_log_entity_ids(entity_type: str = None):
    """Distinct (entity_type, entity_id) pairs seen in audit_log, each with a
    human-readable `name` (see _resolve_entity_name), optionally scoped to
    one entity_type. Used to populate the audit filter UI's entity_id select
    with readable labels instead of raw device/key ids."""
    query = "SELECT DISTINCT entity_type, entity_id FROM audit_log"
    params = []
    if entity_type:
        query += " WHERE entity_type = ?"
        params.append(entity_type)
    query += " ORDER BY entity_type, entity_id"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            # Use the most recent audit changes blob for this entity as the
            # name-resolution fallback (covers removed entities).
            latest = conn.execute(
                "SELECT changes FROM audit_log WHERE entity_type = ? AND entity_id = ? "
                "ORDER BY occurred_at DESC, id DESC LIMIT 1",
                (r["entity_type"], r["entity_id"]),
            ).fetchone()
            changes = None
            if latest and latest["changes"]:
                try:
                    changes = json.loads(latest["changes"])
                except (TypeError, ValueError):
                    changes = None
            name = _resolve_entity_name(conn, r["entity_type"], r["entity_id"], changes)
            result.append({"entity_type": r["entity_type"], "entity_id": r["entity_id"], "name": name})
        return result


def purge_audit_log(retention_days: int = None):
    if retention_days is None:
        retention_days = get_audit_retention_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with get_connection() as conn:
        conn.execute("DELETE FROM audit_log WHERE occurred_at < ?", (cutoff,))


# ---------------------------------------------------------------------------
# Metrics history (lightweight aggregate snapshots for dashboard trend tiles)
# ---------------------------------------------------------------------------

METRICS_HISTORY_RETENTION_HOURS = 48  # keep a bit more than the 24h the UI shows

METRICS_HISTORY_COLUMNS = (
    "counter_healthy_true", "counter_healthy_false",
    "counter_healthy_online_true", "counter_healthy_online_false",
    "counter_key_healthy_true", "counter_key_healthy_false",
    "counter_update_healthy_true", "counter_update_healthy_false",
    "keys_counter_healthy_true", "keys_counter_healthy_false",
)


def record_metrics_snapshot(health_metrics: dict, keys_metrics: dict):
    """Append one aggregate counters row, taken once per poll cycle.

    Deliberately just the small set of counters _compute_health_summary()/
    _compute_keys_summary() already produce - not a per-device snapshot -
    so this table stays cheap to grow and query.
    """
    values = {
        "counter_healthy_true": health_metrics.get("counter_healthy_true", 0),
        "counter_healthy_false": health_metrics.get("counter_healthy_false", 0),
        "counter_healthy_online_true": health_metrics.get("counter_healthy_online_true", 0),
        "counter_healthy_online_false": health_metrics.get("counter_healthy_online_false", 0),
        "counter_key_healthy_true": health_metrics.get("counter_key_healthy_true", 0),
        "counter_key_healthy_false": health_metrics.get("counter_key_healthy_false", 0),
        "counter_update_healthy_true": health_metrics.get("counter_update_healthy_true", 0),
        "counter_update_healthy_false": health_metrics.get("counter_update_healthy_false", 0),
        "keys_counter_healthy_true": keys_metrics.get("counter_key_healthy_true", 0),
        "keys_counter_healthy_false": keys_metrics.get("counter_key_healthy_false", 0),
    }
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO metrics_history (occurred_at, " + ", ".join(METRICS_HISTORY_COLUMNS) + ") "
            "VALUES (?, " + ", ".join("?" for _ in METRICS_HISTORY_COLUMNS) + ")",
            (_now_iso(), *[values[c] for c in METRICS_HISTORY_COLUMNS]),
        )


def get_metrics_history(hours: int = 24):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM metrics_history WHERE occurred_at >= ? ORDER BY occurred_at ASC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def purge_metrics_history(retention_hours: int = METRICS_HISTORY_RETENTION_HOURS):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).isoformat()
    with get_connection() as conn:
        conn.execute("DELETE FROM metrics_history WHERE occurred_at < ?", (cutoff,))


# ---------------------------------------------------------------------------
# Poller activity log (operational log for the /debug page)
# ---------------------------------------------------------------------------

def record_poller_log(event_type: str, message: str, detail: dict = None):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO poller_log (occurred_at, event_type, message, detail) VALUES (?, ?, ?, ?)",
            (_now_iso(), event_type, message, json.dumps(detail) if detail is not None else None),
        )


def list_poller_log(event_type: str = None, limit: int = 200):
    query = "SELECT * FROM poller_log"
    params = []
    if event_type:
        query += " WHERE event_type = ?"
        params.append(event_type)
    query += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            entry = dict(r)
            if entry["detail"]:
                try:
                    entry["detail"] = json.loads(entry["detail"])
                except (TypeError, ValueError):
                    pass
            result.append(entry)
        return result


def list_poller_log_event_types():
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT event_type FROM poller_log ORDER BY event_type").fetchall()
        return [r["event_type"] for r in rows]


def get_poller_log_retention_days() -> int:
    return max(1, get_setting_typed("poller_log_retention_days"))


def purge_poller_log(retention_days: int = None):
    if retention_days is None:
        retention_days = get_poller_log_retention_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with get_connection() as conn:
        conn.execute("DELETE FROM poller_log WHERE occurred_at < ?", (cutoff,))
