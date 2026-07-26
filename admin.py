"""Admin UI: setup wizard, login, settings, user management, audit log.

Two route families under the same /admin prefix:
  - HTML shell routes (render the layout.html shell the React SPA mounts into,
    same convention as the existing dashboard routes in healthcheck.py).
  - /admin/api/* JSON endpoints the SPA calls with same-origin fetch;
    Flask-Login's session cookie carries auth, no token plumbing needed.

This blueprint is exempted from healthcheck.py's global read-only-method
enforcement (see enforce_read_only_methods) since it's the one place in the
app that legitimately needs POST/DELETE.
"""
import logging
import secrets

import requests
from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

import dbstore
import poller

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

MASKED_SETTINGS = {"auth_token", "oauth_client_secret", "health_endpoint_token"}

# Settings that require a process restart to take effect even after being
# saved to the DB, because they're read once at Flask app / logging setup
# time rather than per-request (Flask-Limiter wiring, logging.basicConfig).
RESTART_REQUIRED_SETTINGS = {
    "rate_limit_enabled", "rate_limit_per_ip", "rate_limit_global",
    "rate_limit_storage_url", "rate_limit_headers_enabled", "log_level",
}


def _setting_field(name):
    env_var, type_name, default, sentinel, group = dbstore.SETTINGS_REGISTRY[name]
    meta = dbstore.get_setting_meta(name)
    typed_value = dbstore.get_setting_typed(name)
    secret = name in MASKED_SETTINGS
    display_value = "********" if (secret and meta.get("value")) else typed_value
    return {
        "value": display_value,
        "source": meta.get("source"),
        "configured": meta.get("value") is not None and meta.get("value") != "",
        "type": type_name,
        "default": default,
        "group": group,
        "secret": secret,
        "env_var": env_var,
        "restart_required": name in RESTART_REQUIRED_SETTINGS,
    }


def _setup_incomplete() -> bool:
    return not dbstore.is_tailnet_configured() or not dbstore.has_any_user()


def _validate_tailscale_credentials(tailnet_domain: str, auth_header: dict):
    """Trial call against the Tailscale devices API; raises on failure."""
    url = f"https://api.tailscale.com/api/v2/tailnet/{tailnet_domain}/devices"
    response = requests.get(url, headers=auth_header, timeout=10)
    response.raise_for_status()


# ---------------------------------------------------------------------------
# HTML shell routes
# ---------------------------------------------------------------------------

@admin_bp.route("/", methods=["GET"])
def index():
    if _setup_incomplete():
        return redirect(url_for("admin.setup_page"))
    if not current_user.is_authenticated:
        return redirect(url_for("admin.login_page"))
    return redirect(url_for("admin.settings_page"))


@admin_bp.route("/setup", methods=["GET"])
def setup_page():
    if not _setup_incomplete():
        return redirect(url_for("admin.login_page"))
    return render_template("admin_setup.html")


@admin_bp.route("/login", methods=["GET"])
def login_page():
    if _setup_incomplete():
        return redirect(url_for("admin.setup_page"))
    if current_user.is_authenticated:
        return redirect(url_for("admin.settings_page"))
    return render_template("admin_login.html")


@admin_bp.route("/settings", methods=["GET"])
@login_required
def settings_page():
    return render_template("admin_settings.html")


@admin_bp.route("/users", methods=["GET"])
@login_required
def users_page():
    return render_template("admin_users.html")


@admin_bp.route("/audit", methods=["GET"])
@login_required
def audit_page():
    return render_template("admin_audit.html")


@admin_bp.route("/api-docs", methods=["GET"])
@login_required
def api_docs_page():
    return render_template("admin_api_docs.html")


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@admin_bp.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "tailnet_configured": dbstore.is_tailnet_configured(),
        "has_users": dbstore.has_any_user(),
        "authenticated": current_user.is_authenticated,
    })


@admin_bp.route("/api/setup", methods=["POST"])
def api_setup():
    if not _setup_incomplete():
        return jsonify({"error": "Setup already complete"}), 403

    data = request.get_json(silent=True) or {}
    response = {}

    if not dbstore.is_tailnet_configured():
        tailnet_domain = str(data.get("tailnet_domain", "")).strip()
        auth_mode = str(data.get("auth_mode", "")).strip().lower()
        if not tailnet_domain or tailnet_domain.lower() == "example.com":
            return jsonify({"error": "A valid tailnet domain is required"}), 400

        if auth_mode == "oauth":
            client_id = str(data.get("oauth_client_id", "")).strip()
            client_secret = str(data.get("oauth_client_secret", "")).strip()
            if not client_id or not client_secret:
                return jsonify({"error": "OAuth client id and secret are required"}), 400
            try:
                token_resp = requests.post(
                    "https://api.tailscale.com/api/v2/oauth/token",
                    data={"client_id": client_id, "client_secret": client_secret},
                    timeout=10,
                )
                token_resp.raise_for_status()
                access_token = token_resp.json()["access_token"]
                _validate_tailscale_credentials(tailnet_domain, {"Authorization": f"Bearer {access_token}"})
            except Exception as e:
                logging.warning(f"Setup wizard: OAuth credential validation failed: {e}")
                return jsonify({"error": "Could not authenticate to the Tailscale API with the provided OAuth credentials"}), 400
            dbstore.set_setting("tailnet_domain", tailnet_domain, source="db")
            dbstore.set_setting("oauth_client_id", client_id, source="db")
            dbstore.set_setting("oauth_client_secret", client_secret, source="db")
        elif auth_mode == "token":
            auth_token = str(data.get("auth_token", "")).strip()
            if not auth_token:
                return jsonify({"error": "An API auth token is required"}), 400
            try:
                _validate_tailscale_credentials(tailnet_domain, {"Authorization": f"Bearer {auth_token}"})
            except Exception as e:
                logging.warning(f"Setup wizard: token credential validation failed: {e}")
                return jsonify({"error": "Could not authenticate to the Tailscale API with the provided token"}), 400
            dbstore.set_setting("tailnet_domain", tailnet_domain, source="db")
            dbstore.set_setting("auth_token", auth_token, source="db")
        else:
            return jsonify({"error": "auth_mode must be 'token' or 'oauth'"}), 400

        response["connection_configured"] = True

    api_base_url = data.get("api_base_url")
    if api_base_url is not None and dbstore.get_setting_meta("api_base_url").get("source") != "env":
        dbstore.set_setting("api_base_url", str(api_base_url).strip().rstrip("/"), source="db")

    if not dbstore.has_any_user():
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        if not username or len(password) < 8:
            return jsonify({"error": "A username and a password of at least 8 characters are required"}), 400
        if dbstore.get_user_by_username(username):
            return jsonify({"error": "Username already exists"}), 400
        dbstore.create_user(username, password)
        response["user_created"] = True

    response["setup_complete"] = not _setup_incomplete()
    if response.get("connection_configured"):
        # Kick off an immediate poll so the dashboard has data right away.
        try:
            poller.run_poll_cycle()
        except Exception as e:  # pragma: no cover - best effort
            logging.warning(f"Post-setup poll trigger failed: {e}")
    return jsonify(response)


@admin_bp.route("/api/login", methods=["POST"])
def api_login():
    # Login only needs a user to exist - it shouldn't be blocked just because
    # the tailnet connection itself isn't configured yet (that's editable
    # from /admin/settings once logged in).
    if not dbstore.has_any_user():
        return jsonify({"error": "Setup is not complete"}), 400
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    user_row = dbstore.verify_password(username, password)
    if not user_row:
        return jsonify({"error": "Invalid username or password"}), 401
    from auth import User
    login_user(User.from_row(user_row))
    return jsonify({"ok": True, "username": user_row["username"]})


@admin_bp.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@admin_bp.route("/api/settings", methods=["GET"])
@login_required
def api_get_settings():
    settings = {name: _setting_field(name) for name in dbstore.SETTINGS_REGISTRY}
    poll_status = dbstore.get_poll_status()
    settings["_meta"] = {
        "last_polled_at": dbstore.get_poll_meta(),
        "poll_interval_seconds": poller.poll_interval_seconds(),
        "last_poll_ok": poll_status.get("ok"),
        "last_poll_error": poll_status.get("error"),
        "last_poll_auth_error": bool(poll_status.get("auth_error")),
    }
    return jsonify(settings)


@admin_bp.route("/api/settings", methods=["POST"])
@login_required
def api_update_settings():
    data = request.get_json(silent=True) or {}
    updated = []
    for name, raw_value in data.items():
        if name not in dbstore.SETTINGS_REGISTRY:
            return jsonify({"error": f"Unknown setting: {name}"}), 400
        meta = dbstore.get_setting_meta(name)
        if meta.get("source") == "env":
            return jsonify({"error": f"{name} is set via an environment variable and cannot be changed here"}), 409
        try:
            encoded = dbstore.validate_setting_value(name, raw_value)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        dbstore.set_setting(name, encoded, source="db", actor=current_user.username)
        updated.append(name)

    restarts_needed = sorted(set(updated) & RESTART_REQUIRED_SETTINGS)
    return jsonify({"ok": True, "updated": updated, "restart_required_for": restarts_needed})


@admin_bp.route("/api/settings/generate-token", methods=["POST"])
@login_required
def api_generate_token():
    """Generate a random token for use as a setting value (e.g. health_endpoint_token).

    Purely a convenience generator - does NOT save anything. The caller
    fills the returned value into a form field and it only takes effect
    once they POST it to /admin/api/settings themselves.
    """
    return jsonify({"token": secrets.token_urlsafe(32)})


@admin_bp.route("/api/poll-now", methods=["POST"])
@login_required
def api_poll_now():
    try:
        poller.run_poll_cycle()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "last_polled_at": dbstore.get_poll_meta()})


@admin_bp.route("/api/users", methods=["GET"])
@login_required
def api_list_users():
    return jsonify({"users": dbstore.list_users()})


@admin_bp.route("/api/users", methods=["POST"])
@login_required
def api_create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or len(password) < 8:
        return jsonify({"error": "A username and a password of at least 8 characters are required"}), 400
    if dbstore.get_user_by_username(username):
        return jsonify({"error": "Username already exists"}), 400
    dbstore.create_user(username, password, actor=current_user.username)
    return jsonify({"ok": True})


@admin_bp.route("/api/users/<string:username>", methods=["DELETE"])
@login_required
def api_delete_user(username):
    if len(dbstore.list_users()) <= 1:
        return jsonify({"error": "Cannot delete the last remaining user"}), 400
    if not dbstore.get_user_by_username(username):
        return jsonify({"error": "User not found"}), 404
    dbstore.delete_user(username, actor=current_user.username)
    return jsonify({"ok": True})


@admin_bp.route("/api/audit", methods=["GET"])
@login_required
def api_audit_log():
    try:
        limit = max(1, min(500, int(request.args.get("limit", 100))))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "limit/offset must be integers"}), 400
    entries = dbstore.list_audit_log(
        limit=limit,
        offset=offset,
        entity_type=request.args.get("entity_type") or None,
        entity_id=request.args.get("entity_id") or None,
        action=request.args.get("action") or None,
        actor=request.args.get("actor") or None,
        start=request.args.get("start") or None,
        end=request.args.get("end") or None,
    )
    return jsonify({"entries": entries})


@admin_bp.route("/api/audit/filters", methods=["GET"])
@login_required
def api_audit_filters():
    """Distinct values to populate the audit log filter UI (actors, entity ids)."""
    entity_type = request.args.get("entity_type") or None
    return jsonify({
        "actors": dbstore.list_audit_log_actors(),
        "entity_ids": dbstore.list_audit_log_entity_ids(entity_type),
        "entity_types": ["device", "tailnet_key", "setting", "user"],
        "actions": ["created", "updated", "removed"],
    })


@admin_bp.route("/api/metrics-history", methods=["GET"])
@login_required
def api_metrics_history():
    try:
        hours = max(1, min(168, int(request.args.get("hours", 24))))
    except ValueError:
        return jsonify({"error": "hours must be an integer"}), 400
    return jsonify({"entries": dbstore.get_metrics_history(hours=hours)})


@admin_bp.route("/api/debug/poller-log", methods=["GET"])
@login_required
def api_poller_log():
    event_type = request.args.get("event_type") or None
    try:
        limit = max(1, min(500, int(request.args.get("limit", 200))))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    entries = poller.get_poll_log(event_type=event_type, limit=limit)
    return jsonify({
        "entries": entries,
        "event_types": poller.get_poll_log_event_types(),
        "enabled": dbstore.get_setting_typed("debug_log_enabled"),
        "last_polled_at": dbstore.get_poll_meta(),
        "poll_interval_seconds": poller.poll_interval_seconds(),
    })
