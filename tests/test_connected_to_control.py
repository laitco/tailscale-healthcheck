import importlib.util
import os
import types
from datetime import datetime, timedelta

from dateutil import parser as date_parser
import pytz

def _load_healthcheck_with_env(env: dict, database_path=None) -> types.ModuleType:
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    old_env = os.environ.copy()
    try:
        os.environ.update({k: str(v) for k, v in env.items()})
        if database_path is not None:
            os.environ["DATABASE_PATH"] = str(database_path)
        spec.loader.exec_module(module)
    finally:
        os.environ.clear()
        os.environ.update(old_env)
    return module


def _connected_device():
    return {
        "id": "device-connected",
        "name": "connected.example.com",
        "hostname": "connected",
        "os": "linux",
        "clientVersion": "1.2.3",
        "connectedToControl": True,
        "updateAvailable": False,
        "keyExpiryDisabled": True,
        "tags": ["tag:prod"],
    }


def test_health_endpoint_handles_connected_without_last_seen(monkeypatch, tmp_path):
    module = _load_healthcheck_with_env({
        "CACHE_ENABLED": "NO",
        "RATE_LIMIT_ENABLED": "NO",
        "ONLINE_THRESHOLD_MINUTES": "5",
        "KEY_THRESHOLD_MINUTES": "1440",
    }, database_path=tmp_path / "healthcheck.db")
    monkeypatch.setattr(module, "fetch_devices", lambda: [_connected_device()])
    client = module.app.test_client()

    before = datetime.now(pytz.UTC)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    device = body["devices"][0]

    assert device["connectedToControl"] is True
    assert device["lastSeen"] is not None
    seen_at = date_parser.isoparse(device["lastSeen"])
    seen_at_utc = seen_at.astimezone(pytz.UTC)
    assert abs((seen_at_utc - before).total_seconds()) <= 5
    assert device["online_healthy"] is True
    assert body["metrics"]["counter_healthy_online_true"] == 1
    assert body["metrics"]["counter_healthy_true"] == 1


def test_device_lookup_returns_connected_flag(monkeypatch, tmp_path):
    module = _load_healthcheck_with_env({
        "CACHE_ENABLED": "NO",
        "RATE_LIMIT_ENABLED": "NO",
    }, database_path=tmp_path / "healthcheck.db")
    device_payload = _connected_device()
    monkeypatch.setattr(module, "fetch_devices", lambda: [device_payload])
    module.dbstore.create_user("tester", "correct-horse-battery-staple")
    client = module.app.test_client()
    client.post(
        "/admin/api/login",
        json={"username": "tester", "password": "correct-horse-battery-staple"},
    )

    before = datetime.now(pytz.UTC)
    resp = client.get("/health/connected")
    assert resp.status_code == 200
    body = resp.get_json()
    returned = body["device"]

    assert returned["connectedToControl"] is True
    assert returned["lastSeen"] is not None
    seen_at = date_parser.isoparse(returned["lastSeen"])
    seen_at_utc = seen_at.astimezone(pytz.UTC)
    assert abs((seen_at_utc - before).total_seconds()) <= 5
    assert returned["online_healthy"] is True
