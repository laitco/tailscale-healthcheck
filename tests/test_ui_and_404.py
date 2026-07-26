import os
import importlib.util
import types
from datetime import datetime, timedelta

import pytz
import pytest


def _load_healthcheck_with_env(env: dict) -> types.ModuleType:
    root = os.path.dirname(os.path.dirname(__file__))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    assert spec and spec.loader
    # Isolate env
    old_env = os.environ.copy()
    os.environ.update(env)
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    finally:
        os.environ.clear()
        os.environ.update(old_env)


def _logged_in_client(m):
    """Create a user and return a test client with an authenticated session.

    The dashboard shell routes are now gated behind setup-complete + login.
    """
    m.dbstore.create_user("tester", "correct-horse-battery-staple")
    client = m.app.test_client()
    resp = client.post(
        "/admin/api/login",
        json={"username": "tester", "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    return client


def _sample_devices():
    tz = pytz.UTC
    now = datetime.now(tz)
    return [
        {
            "id": "dev1",
            "name": "dev1.example.com",
            "hostname": "dev1",
            "os": "linux",
            "clientVersion": "1.2.3",
            "connectedToControl": False,
            "updateAvailable": False,
            "lastSeen": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "keyExpiryDisabled": False,
            "expires": (now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            "tags": ["tag:prod"],
        },
        {
            "id": "dev2",
            "name": "dev2.example.com",
            "hostname": "dev2",
            "os": "windows",
            "clientVersion": "1.2.4",
            "connectedToControl": False,
            "updateAvailable": True,
            "lastSeen": (now - timedelta(minutes=120)).isoformat().replace("+00:00", "Z"),
            "keyExpiryDisabled": False,
            "expires": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "tags": ["tag:dev"],
        },
    ]


@pytest.fixture
def module(tmp_path):
    m = _load_healthcheck_with_env({
        "DISPLAY_SETTINGS_IN_OUTPUT": "NO",
        "ONLINE_THRESHOLD_MINUTES": "5",
        "KEY_THRESHOLD_MINUTES": "1440",
        "RATE_LIMIT_ENABLED": "NO",
        "TAILNET_DOMAIN": "example.ts.net",
        "DATABASE_PATH": str(tmp_path / "healthcheck.db"),
    })
    # monkeypatch fetch_devices
    m.fetch_devices = lambda: _sample_devices()
    return m


def test_dashboard_renders(module):
    # The dashboard is a client-rendered React app; the Flask route only
    # serves the mount shell that loads the built bundle.
    client = _logged_in_client(module)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Tailscale Healthcheck" in body
    assert '<div id="root"></div>' in body
    assert "/static/app/app.js" in body


def test_health_response_has_no_settings_block(tmp_path):
    # DISPLAY_SETTINGS_IN_OUTPUT and the settings-dump-in-JSON feature were
    # retired: full settings (including secrets, masked) now live behind
    # login at /admin/api/settings instead of being embedded in the public
    # /health response.
    m = _load_healthcheck_with_env({
        "ONLINE_THRESHOLD_MINUTES": "5",
        "KEY_THRESHOLD_MINUTES": "1440",
        "RATE_LIMIT_ENABLED": "NO",
        "TAILNET_DOMAIN": "example.com",
        "DATABASE_PATH": str(tmp_path / "healthcheck.db"),
    })
    m.fetch_devices = lambda: _sample_devices()
    client = m.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "settings" not in data


def test_device_detail_renders(module):
    # Device data (including whether the identifier even exists) is fetched
    # client-side from /health/<identifier>; the Flask route only serves the
    # shell, unconditionally, so a slow/failing upstream never blocks it.
    client = _logged_in_client(module)
    resp = client.get("/device/dev1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '<div id="root"></div>' in body
    assert "/static/app/app.js" in body


def test_devices_and_tailnet_keys_and_debug_shells_render(module):
    client = _logged_in_client(module)
    for path in ("/devices", "/tailnet-keys", "/debug"):
        resp = client.get(path)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert '<div id="root"></div>' in body
        assert "/static/app/app.js" in body


def test_404_json_when_requested(module):
    app = module.app
    client = app.test_client()
    resp = client.get("/missing", headers={"Accept": "application/json"})
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "Not Found", "status": 404}


def test_404_ui_for_html(module):
    # The 404 message itself is rendered client-side by the React app's
    # not-found route; the Flask route just serves the mount shell with a
    # 404 status and title.
    app = module.app
    client = app.test_client()
    resp = client.get("/missing")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "404" in body
    assert '<div id="root"></div>' in body
