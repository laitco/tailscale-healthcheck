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
            "updateAvailable": True,
            "lastSeen": (now - timedelta(minutes=120)).isoformat().replace("+00:00", "Z"),
            "keyExpiryDisabled": False,
            "expires": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "tags": ["tag:dev"],
        },
    ]


@pytest.fixture
def module():
    m = _load_healthcheck_with_env({
        "CACHE_ENABLED": "NO",
        "DISPLAY_SETTINGS_IN_OUTPUT": "NO",
        "ONLINE_THRESHOLD_MINUTES": "5",
        "KEY_THRESHOLD_MINUTES": "1440",
        "RATE_LIMIT_ENABLED": "NO",
    })
    # monkeypatch fetch_devices
    m.fetch_devices = lambda: _sample_devices()
    return m


def test_dashboard_renders(module):
    app = module.app
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Tailscale Healthcheck" in body
    assert "dev1" in body


def test_dashboard_settings_render_when_enabled():
    m = _load_healthcheck_with_env({
        "CACHE_ENABLED": "NO",
        "DISPLAY_SETTINGS_IN_OUTPUT": "YES",
        "ONLINE_THRESHOLD_MINUTES": "5",
        "KEY_THRESHOLD_MINUTES": "1440",
        "RATE_LIMIT_ENABLED": "NO",
        "TAILNET_DOMAIN": "example.com",
    })
    m.fetch_devices = lambda: _sample_devices()
    client = m.app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Settings (redacted)" in html
    assert "TAILNET_DOMAIN" in html
    assert "RATE_LIMIT_ENABLED" in html


def test_device_detail_renders(module):
    app = module.app
    client = app.test_client()
    resp = client.get("/device/dev1")
    assert resp.status_code == 200
    assert "dev1" in resp.get_data(as_text=True)


def test_404_json_when_requested(module):
    app = module.app
    client = app.test_client()
    resp = client.get("/missing", headers={"Accept": "application/json"})
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "Not Found", "status": 404}


def test_404_ui_for_html(module):
    app = module.app
    client = app.test_client()
    resp = client.get("/missing")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "404 Not Found" in body
