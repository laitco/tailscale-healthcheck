import importlib.util
import os
import types

import pytest


def _load_healthcheck(env: dict, database_path) -> types.ModuleType:
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    assert spec and spec.loader
    old_env = os.environ.copy()
    try:
        os.environ.update(env)
        os.environ["DATABASE_PATH"] = str(database_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    finally:
        os.environ.clear()
        os.environ.update(old_env)


@pytest.fixture
def unconfigured(tmp_path):
    m = _load_healthcheck({"RATE_LIMIT_ENABLED": "NO"}, tmp_path / "healthcheck.db")
    return m


@pytest.fixture
def configured(tmp_path):
    m = _load_healthcheck(
        {"RATE_LIMIT_ENABLED": "NO", "TAILNET_DOMAIN": "example.ts.net", "AUTH_TOKEN": "test-token"},
        tmp_path / "healthcheck.db",
    )
    return m


@pytest.fixture
def tailnet_only(tmp_path):
    # Tailnet domain set via env, but no AUTH_TOKEN/OAuth - the scenario
    # that used to let the setup wizard report "complete" without ever
    # asking for credentials (see test_setup_requires_usable_auth_method).
    m = _load_healthcheck({"RATE_LIMIT_ENABLED": "NO", "TAILNET_DOMAIN": "example.ts.net"}, tmp_path / "healthcheck.db")
    return m


def test_setup_redirect_when_tailnet_unconfigured(unconfigured):
    client = unconfigured.app.test_client()
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/setup"


def test_setup_redirect_when_no_users_even_if_tailnet_configured(configured):
    # Tailnet is configured but no users exist yet -> still routed to setup.
    client = configured.app.test_client()
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/setup"


def test_status_endpoint_reports_app_version(unconfigured):
    # /admin/api/status is intentionally unauthenticated (the setup/login
    # pages need it before a session exists), and doubles as the source the
    # sidebar reads the app version from (issue #36).
    client = unconfigured.app.test_client()
    resp = client.get("/admin/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "version" in data
    assert data["version"] and data["version"] != "unknown"


def test_login_redirect_once_setup_is_complete(configured):
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/login"


def test_wizard_completes_connection_and_user_in_one_call(unconfigured, monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"devices": []}

    monkeypatch.setattr(unconfigured.requests, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(unconfigured.poller, "run_poll_cycle", lambda: None)

    client = unconfigured.app.test_client()
    resp = client.post("/admin/api/setup", json={
        "tailnet_domain": "example.ts.net",
        "auth_mode": "token",
        "auth_token": "test-token",
        "username": "admin",
        "password": "correct-horse-battery-staple",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["setup_complete"] is True
    assert unconfigured.dbstore.is_tailnet_configured()
    assert unconfigured.dbstore.has_any_user()
    assert unconfigured.dbstore.get_setting_meta("tailnet_domain")["source"] == "db"


def test_setup_requires_usable_auth_method(tailnet_only, monkeypatch):
    # Tailnet domain is already configured via env, but no auth method is.
    # Setup must still be reported incomplete, and the wizard must still
    # accept/require credentials here rather than skipping straight to just
    # creating a user (which used to silently "complete" setup with no way
    # to ever reach the Tailscale API).
    m = tailnet_only
    assert not m.dbstore.is_auth_configured()

    client = m.app.test_client()
    status = client.get("/admin/api/status").get_json()
    assert status["tailnet_configured"] is True
    assert status["auth_configured"] is False

    # Trying to jump straight to just creating a user, omitting credentials
    # entirely, must be rejected.
    resp = client.post("/admin/api/setup", json={"username": "admin", "password": "correct-horse-battery-staple"})
    assert resp.status_code == 400
    assert not m.dbstore.has_any_user()

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"devices": []}

    monkeypatch.setattr(m.requests, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(m.poller, "run_poll_cycle", lambda: None)

    # Supplying the auth token (tailnet_domain omitted - it's already known)
    # completes the connection step and lets the wizard proceed.
    resp = client.post("/admin/api/setup", json={
        "auth_mode": "token",
        "auth_token": "test-token",
        "username": "admin",
        "password": "correct-horse-battery-staple",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["setup_complete"] is True
    assert m.dbstore.is_auth_configured()
    assert m.dbstore.get_setting("tailnet_domain") == "example.ts.net"


def test_login_logout_flow(configured):
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()

    bad = client.post("/admin/api/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/admin/api/login", json={"username": "admin", "password": "correct-horse-battery-staple"})
    assert ok.status_code == 200

    # Now authenticated: dashboard route should render instead of redirect.
    dash = client.get("/dashboard")
    assert dash.status_code == 200

    logout = client.post("/admin/api/logout")
    assert logout.status_code == 200

    dash_after_logout = client.get("/dashboard")
    assert dash_after_logout.status_code == 302
    assert dash_after_logout.headers["Location"] == "/admin/login"


def test_settings_env_sourced_field_cannot_be_edited(configured):
    # AUTH_TOKEN came from env in the `configured` fixture.
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    client.post("/admin/api/login", json={"username": "admin", "password": "correct-horse-battery-staple"})

    resp = client.post("/admin/api/settings", json={"auth_token": "new-token"})
    assert resp.status_code == 409


def test_users_page_requires_login(configured):
    client = configured.app.test_client()
    resp = client.get("/admin/users")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/admin/login")


def test_admin_exempt_from_read_only_but_health_still_enforced(configured):
    client = configured.app.test_client()
    resp = client.post("/admin/api/login", json={"username": "nope", "password": "nope"})
    assert resp.status_code != 403  # reached the handler, wasn't blocked by the method guard

    resp = client.post("/health")
    assert resp.status_code == 403


def test_health_poll_meta_surfaces_auth_error(configured, monkeypatch):
    monkeypatch.setattr(configured, "fetch_devices", lambda: [])
    configured.dbstore.set_poll_status(ok=False, error="401 Client Error", auth_error=True)
    client = configured.app.test_client()

    resp = client.get("/health")
    assert resp.status_code == 200
    poll_meta = resp.get_json()["poll_meta"]
    assert poll_meta["last_poll_ok"] is False
    assert poll_meta["last_poll_auth_error"] is True
    assert poll_meta["last_poll_error"] == "401 Client Error"


def test_json_api_family_is_public(configured, monkeypatch):
    # The entire JSON API family stays public/unauthenticated by default -
    # that's the monitoring-tool contract (Gatus, etc.) - only the human
    # dashboard and /admin/* (besides login/setup) require a session.
    monkeypatch.setattr(configured, "fetch_devices", lambda: [])
    monkeypatch.setattr(configured, "_get_tailnet_keys_status", lambda: ([], {"tailnet_configured": True}))
    monkeypatch.setattr(configured.poller, "run_poll_cycle", lambda: None)
    client = configured.app.test_client()

    assert client.get("/health").status_code == 200
    assert client.get("/health/").status_code == 301
    assert client.get("/keys").status_code == 200
    assert client.get("/health/some-device").status_code == 404  # no such device, but reachable
    assert client.get("/health/healthy").status_code == 200
    assert client.get("/health/unhealthy").status_code == 200

    resp = client.get("/health/cache/invalidate")
    assert resp.status_code == 200

    # The human dashboard is still gated behind login.
    assert client.get("/dashboard").status_code == 302


def test_admin_api_returns_json_401_when_logged_out(configured):
    # A logged-out (or session-expired) fetch() call to /admin/api/* must
    # get a JSON 401, not Flask-Login's default redirect to the HTML login
    # page - the SPA can't meaningfully handle a 200 HTML response where it
    # expected JSON.
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    resp = client.get("/admin/api/users")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "Unauthorized"}

    # The HTML shell routes still redirect, for normal browser navigation.
    page_resp = client.get("/admin/users")
    assert page_resp.status_code == 302


def test_health_endpoint_token_via_env(tmp_path, monkeypatch):
    m = _load_healthcheck(
        {
            "RATE_LIMIT_ENABLED": "NO",
            "TAILNET_DOMAIN": "example.ts.net",
            "AUTH_TOKEN": "test-token",
            "HEALTH_ENDPOINT_TOKEN": "s3cret-header-token",
        },
        tmp_path / "healthcheck.db",
    )
    monkeypatch.setattr(m, "fetch_devices", lambda: [])
    client = m.app.test_client()

    resp_no_header = client.get("/health")
    assert resp_no_header.status_code == 401
    assert resp_no_header.get_json() == {"error": "Unauthorized"}

    resp_wrong = client.get("/health", headers={"X-Health-Token": "wrong"})
    assert resp_wrong.status_code == 401

    resp_ok = client.get("/health", headers={"X-Health-Token": "s3cret-header-token"})
    assert resp_ok.status_code == 200


def test_generate_token_endpoint_returns_random_unsaved_token(configured):
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    client.post("/admin/api/login", json={"username": "admin", "password": "correct-horse-battery-staple"})

    resp = client.post("/admin/api/settings/generate-token")
    assert resp.status_code == 200
    token = resp.get_json()["token"]
    assert len(token) > 20

    resp2 = client.post("/admin/api/settings/generate-token")
    assert resp2.get_json()["token"] != token

    # Purely a generator - must not have been saved as a setting.
    assert configured.dbstore.get_setting("health_endpoint_token") is None


def test_settings_api_reports_restart_required_and_group(configured):
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    client.post("/admin/api/login", json={"username": "admin", "password": "correct-horse-battery-staple"})

    resp = client.get("/admin/api/settings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rate_limit_enabled"]["restart_required"] is True
    assert data["rate_limit_enabled"]["group"] == "rate_limit"
    assert data["online_threshold_minutes"]["restart_required"] is False
    assert data["online_threshold_minutes"]["type"] == "int"
    assert data["include_key_type"]["group"] == "filters"
    assert "display_settings_in_output" not in data
    assert "_meta" in data


def test_settings_api_updates_non_core_setting(configured):
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    client.post("/admin/api/login", json={"username": "admin", "password": "correct-horse-battery-staple"})

    resp = client.post("/admin/api/settings", json={"online_threshold_minutes": 12})
    assert resp.status_code == 200
    assert resp.get_json()["updated"] == ["online_threshold_minutes"]
    assert configured.dbstore.get_setting_typed("online_threshold_minutes") == 12

    bad = client.post("/admin/api/settings", json={"online_threshold_minutes": "not-a-number"})
    assert bad.status_code == 400


def test_settings_batch_update_is_all_or_nothing(configured):
    # A payload with one valid field and one invalid field must not persist
    # the valid field before failing on the invalid one - the whole request
    # is a single unit from the caller's point of view.
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    client.post("/admin/api/login", json={"username": "admin", "password": "correct-horse-battery-staple"})

    original = configured.dbstore.get_setting_typed("online_threshold_minutes")
    resp = client.post("/admin/api/settings", json={
        "online_threshold_minutes": 42,
        "key_threshold_minutes": "not-a-number",
    })
    assert resp.status_code == 400
    assert configured.dbstore.get_setting_typed("online_threshold_minutes") == original


def test_key_filters_narrow_keys_summary(configured):
    configured.dbstore.set_setting("include_key_type", "auth", source="db")
    keys = [
        {"id": "k1", "description": "auth key", "keyType": "auth", "capabilities": {}, "expires": None},
        {"id": "k2", "description": "api key", "keyType": "api", "capabilities": {}, "expires": None},
    ]
    status, metrics = configured._compute_keys_summary(keys)
    assert [k["id"] for k in status] == ["k1"]
    assert metrics["total_keys"] == 1


def test_health_endpoint_token_via_admin_settings(configured, monkeypatch):
    monkeypatch.setattr(configured, "fetch_devices", lambda: [])
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()
    client.post("/admin/api/login", json={"username": "admin", "password": "correct-horse-battery-staple"})

    # No token configured yet -> /health stays open.
    assert client.get("/health").status_code == 200

    resp = client.post("/admin/api/settings", json={"health_endpoint_token": "db-set-token"})
    assert resp.status_code == 200

    # A logged-in dashboard session bypasses the token check - the token
    # value is a masked secret the frontend never sees, so without this the
    # app's own Overview/Devices pages would break the moment this optional
    # feature is turned on.
    assert client.get("/health").status_code == 200

    # A separate, unauthenticated client is the one the token actually guards.
    anon = configured.app.test_client()
    assert anon.get("/health").status_code == 401
    assert anon.get("/health", headers={"X-Health-Token": "db-set-token"}).status_code == 200
    assert anon.get("/health", headers={"X-Health-Token": "wrong"}).status_code == 401

    # Clearing it back to empty re-opens /health.
    client.post("/admin/api/settings", json={"health_endpoint_token": ""})
    assert anon.get("/health").status_code == 200
