import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import dbstore  # noqa: E402
import poller  # noqa: E402


def _fresh_db(tmp_path, monkeypatch, tailnet="example.ts.net"):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()
    monkeypatch.setenv("TAILNET_DOMAIN", tailnet)
    monkeypatch.setenv("AUTH_TOKEN", "test-token")
    dbstore.sync_env_settings()


def _fake_healthcheck_module(devices, keys):
    fake = types.ModuleType("healthcheck")
    fake.build_auth_header = lambda: {"Authorization": "Bearer test-token"}

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_make_authenticated_request(url, headers):
        if "/keys" in url:
            return FakeResponse({"keys": keys})
        return FakeResponse({"devices": devices})

    fake.make_authenticated_request = fake_make_authenticated_request
    fake._infer_key_type = lambda key: key.get("keyType", "auth")

    # Minimal stand-ins for the real health/keys summary computation - just
    # enough for poller.run_poll_cycle()'s metrics_history recording step to
    # produce a predictable counter (len of whatever's in the DB snapshot at
    # call time), without pulling in the real healthcheck.py's full settings
    # resolution / Flask app bootstrap into this test.
    def fake_compute_health_summary(devices):
        n = len(devices)
        return devices, {
            "counter_healthy_true": n, "counter_healthy_false": 0,
            "counter_healthy_online_true": n, "counter_healthy_online_false": 0,
            "counter_key_healthy_true": n, "counter_key_healthy_false": 0,
            "counter_update_healthy_true": n, "counter_update_healthy_false": 0,
        }

    def fake_compute_keys_summary(keys):
        n = len(keys)
        return keys, {"counter_key_healthy_true": n, "counter_key_healthy_false": 0}

    fake._compute_health_summary = fake_compute_health_summary
    fake._compute_keys_summary = fake_compute_keys_summary
    return fake


def test_poller_lock_election_is_exclusive(tmp_path, monkeypatch):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    poller._have_lock = False
    poller._lock_fh = None
    assert poller._acquire_poller_lock() is True

    # A second, independent attempt (simulating another worker process) must
    # fail to acquire the same lock file while the first is held open.
    import fcntl
    with open(poller._lock_path(), "w") as fh2:
        try:
            fcntl.flock(fh2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired_again = True
        except (BlockingIOError, OSError):
            acquired_again = False
    assert acquired_again is False


def test_poll_cycle_skips_when_tailnet_unconfigured(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()
    sys.modules.pop("healthcheck", None)
    poller.run_poll_cycle()  # should not raise, no tailnet configured
    assert dbstore.get_poll_meta() is None


def test_poll_cycle_skips_when_auth_unconfigured(tmp_path, monkeypatch):
    # Tailnet domain set, but no AUTH_TOKEN/OAuth - a fresh/unconfigured
    # instance (or one where auth was removed) must not hit the Tailscale
    # API at all, not even with the placeholder token, every poll cycle.
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()
    monkeypatch.setenv("TAILNET_DOMAIN", "example.ts.net")
    dbstore.sync_env_settings()
    assert dbstore.is_tailnet_configured()
    assert not dbstore.is_auth_configured()

    calls = {"count": 0}
    fake = _fake_healthcheck_module([], [])

    def tracked_request(*a, **k):
        calls["count"] += 1
        return fake.make_authenticated_request(*a, **k)

    fake.make_authenticated_request = tracked_request
    sys.modules["healthcheck"] = fake
    try:
        poller.run_poll_cycle()
    finally:
        sys.modules.pop("healthcheck", None)

    assert calls["count"] == 0
    assert dbstore.get_poll_meta() is None
    events = {e["event_type"] for e in dbstore.list_poller_log()}
    assert "poll_skipped" in events
    assert "poll_started" not in events


def test_is_auth_error_detects_401_403_only():
    resp_401 = types.SimpleNamespace(status_code=401)
    resp_500 = types.SimpleNamespace(status_code=500)
    import requests
    err_401 = requests.exceptions.HTTPError("401")
    err_401.response = resp_401
    err_500 = requests.exceptions.HTTPError("500")
    err_500.response = resp_500

    assert poller._is_auth_error(err_401) is True
    assert poller._is_auth_error(err_500) is False
    assert poller._is_auth_error(RuntimeError("boom")) is False


def test_poll_cycle_records_auth_error_status(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    import requests

    def raise_401(url, headers):
        resp = types.SimpleNamespace(status_code=401)
        err = requests.exceptions.HTTPError("401 Client Error")
        err.response = resp
        raise err

    fake = _fake_healthcheck_module([], [])
    fake.make_authenticated_request = raise_401
    sys.modules["healthcheck"] = fake
    try:
        poller.run_poll_cycle()
    finally:
        sys.modules.pop("healthcheck", None)

    status = dbstore.get_poll_status()
    assert status["ok"] is False
    assert status["auth_error"] is True
    assert "401" in status["error"]

    error_entries = [e for e in dbstore.list_poller_log() if e["event_type"] == "devices_error"]
    assert len(error_entries) == 1
    assert error_entries[0]["detail"]["auth_error"] is True


def test_poll_cycle_populates_and_audits_changes(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)

    device_v1 = {
        "id": "d1", "name": "dev1.example.com", "hostname": "dev1", "os": "linux",
        "clientVersion": "1.0", "updateAvailable": False, "connectedToControl": True,
        "lastSeen": "2024-01-01T00:00:00Z", "keyExpiryDisabled": True, "expires": None,
        "tags": ["tag:prod"],
    }
    key_v1 = {"id": "k1", "description": "ci key", "keyType": "auth", "capabilities": {}, "created": "2024-01-01T00:00:00Z", "expires": "2025-01-01T00:00:00Z"}

    sys.modules["healthcheck"] = _fake_healthcheck_module([device_v1], [key_v1])
    try:
        poller.run_poll_cycle()
    finally:
        sys.modules.pop("healthcheck", None)

    assert len(dbstore.get_devices_snapshot()) == 1
    assert len(dbstore.get_keys_snapshot()) == 1
    assert dbstore.get_poll_meta() is not None

    device_v2 = dict(device_v1, name="dev1-renamed.example.com")
    sys.modules["healthcheck"] = _fake_healthcheck_module([device_v2], [key_v1])
    try:
        poller.run_poll_cycle()
    finally:
        sys.modules.pop("healthcheck", None)

    entries = dbstore.list_audit_log(entity_type="device")
    updated = [e for e in entries if e["action"] == "updated"]
    assert len(updated) == 1
    assert "name" in updated[0]["changes"]


def test_poll_cycle_removes_device_and_key_dropped_from_api_response(tmp_path, monkeypatch):
    """End-to-end (not just dbstore.upsert_*) check that a device/key no longer
    returned by the Tailscale API gets deleted from the DB, not left stale,
    with an audit 'removed' row - and that a metrics_history snapshot taken
    while it still existed is NOT retroactively rewritten."""
    _fresh_db(tmp_path, monkeypatch)

    device = {
        "id": "d1", "name": "dev1.example.com", "hostname": "dev1", "os": "linux",
        "clientVersion": "1.0", "updateAvailable": False, "connectedToControl": True,
        "lastSeen": "2024-01-01T00:00:00Z", "keyExpiryDisabled": True, "expires": None,
        "tags": ["tag:prod"],
    }
    key = {
        "id": "k1", "description": "ci key", "keyType": "auth", "capabilities": {},
        "created": "2024-01-01T00:00:00Z", "expires": "2025-01-01T00:00:00Z",
    }

    sys.modules["healthcheck"] = _fake_healthcheck_module([device], [key])
    try:
        poller.run_poll_cycle()
    finally:
        sys.modules.pop("healthcheck", None)

    assert len(dbstore.get_devices_snapshot()) == 1
    assert len(dbstore.get_keys_snapshot()) == 1
    first_cycle_history = dbstore.get_metrics_history(hours=24)
    assert len(first_cycle_history) == 1
    assert first_cycle_history[0]["counter_healthy_true"] == 1  # the one device, counted while present

    # Second cycle: the API no longer returns the device or the key at all.
    sys.modules["healthcheck"] = _fake_healthcheck_module([], [])
    try:
        poller.run_poll_cycle()
    finally:
        sys.modules.pop("healthcheck", None)

    assert dbstore.get_devices_snapshot() == []
    assert dbstore.get_keys_snapshot() == []

    device_removed = [e for e in dbstore.list_audit_log(entity_type="device") if e["action"] == "removed"]
    assert len(device_removed) == 1
    assert device_removed[0]["entity_id"] == "d1"

    key_removed = [e for e in dbstore.list_audit_log(entity_type="tailnet_key") if e["action"] == "removed"]
    assert len(key_removed) == 1
    assert key_removed[0]["entity_id"] == "k1"

    # The historical snapshot from while the device existed must be untouched...
    history = dbstore.get_metrics_history(hours=24)
    assert len(history) == 2
    assert history[0]["counter_healthy_true"] == 1
    # ...but the new snapshot (taken after removal) must not keep counting it.
    assert history[1]["counter_healthy_true"] == 0
