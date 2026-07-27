"""Cross-endpoint consistency for the /health* JSON API family.

/health/healthy, /health/unhealthy and /health/<identifier> used to inline
their own copy of _compute_health_summary()'s per-device logic. The copies
drifted, so all four endpoints could disagree about the same device: the
device include/exclude filters were applied only by /health, the `healthy`
field ignored UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH on three of them, and
/health/healthy's global_* flags were structurally always true. These tests
pin the agreement so the endpoints can't drift apart again.
"""
import importlib.util
import os
import types
from datetime import datetime, timedelta

import pytest
import pytz


def _load_healthcheck(database_path, **env) -> types.ModuleType:
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    assert spec and spec.loader
    old_env = os.environ.copy()
    try:
        os.environ.update({
            "RATE_LIMIT_ENABLED": "NO",
            "TAILNET_DOMAIN": "example.ts.net",
            "AUTH_TOKEN": "test-token",
            "DATABASE_PATH": str(database_path),
            **env,
        })
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    finally:
        os.environ.clear()
        os.environ.update(old_env)


def _device(device_id, hostname, *, os_name="linux", online=True, update_available=False, tags=None):
    """A device that is healthy unless told otherwise. `online=False` pushes
    lastSeen well past any sane ONLINE_THRESHOLD_MINUTES."""
    last_seen = datetime.now(pytz.UTC) - (timedelta(minutes=0) if online else timedelta(days=30))
    return {
        "id": device_id,
        "name": f"{hostname}.example.ts.net",
        "hostname": hostname,
        "os": os_name,
        "clientVersion": "1.98.0",
        "updateAvailable": update_available,
        "connectedToControl": online,
        "lastSeen": last_seen.isoformat().replace("+00:00", "Z"),
        "keyExpiryDisabled": True,
        "expires": None,
        "tags": tags or [],
        "tailnetLockError": "",
    }


@pytest.fixture
def tailnet(tmp_path):
    """One healthy device, one offline (unhealthy) device."""
    m = _load_healthcheck(tmp_path / "healthcheck.db")
    devices = [_device("d1", "alpha"), _device("d2", "bravo", online=False)]
    m.fetch_devices = lambda: devices
    return m


def _json(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    return resp.get_json()


def test_all_four_endpoints_agree_on_healthy_and_metrics(tailnet):
    """The same device must carry the same `healthy` verdict on every route,
    and the tailnet-wide counters must be identical wherever they appear."""
    client = tailnet.app.test_client()

    overview = _json(client, "/health")
    healthy = _json(client, "/health/healthy")
    unhealthy = _json(client, "/health/unhealthy")

    assert [d["id"] for d in healthy["devices"]] == ["d1"]
    assert [d["id"] for d in unhealthy["devices"]] == ["d2"]
    # devices is a partition of /health's list, with nothing invented or lost
    assert len(healthy["devices"]) + len(unhealthy["devices"]) == len(overview["devices"])

    # metrics are tailnet-wide, not scoped to the returned subset
    assert healthy["metrics"] == overview["metrics"]
    assert unhealthy["metrics"] == overview["metrics"]

    # per-device lookups agree with the overview entry, field for field
    for device in overview["devices"]:
        assert _json(client, f"/health/{device['id']}")["device"] == device


def test_healthy_endpoint_reports_global_unhealthy_when_tailnet_is_sick(tmp_path):
    """Regression: counters used to be incremented only for the devices being
    output, so counter_*_false was always 0 on /health/healthy and every
    global_* flag read `true` no matter how many devices were down.

    Thresholds are pinned to 0 here because they default to 100 - the point is
    that the flag can flip at all on this endpoint, not where the line sits.
    """
    m = _load_healthcheck(
        tmp_path / "healthcheck.db",
        GLOBAL_HEALTHY_THRESHOLD="0",
        GLOBAL_ONLINE_HEALTHY_THRESHOLD="0",
    )
    m.fetch_devices = lambda: [_device("d1", "alpha"), _device("d2", "bravo", online=False)]
    body = _json(m.app.test_client(), "/health/healthy")

    assert [d["id"] for d in body["devices"]] == ["d1"]
    assert body["metrics"]["counter_healthy_false"] == 1
    assert body["metrics"]["counter_healthy_online_false"] == 1
    assert body["metrics"]["global_healthy"] is False
    assert body["metrics"]["global_online_healthy"] is False


def test_device_filters_apply_to_every_endpoint(tmp_path):
    """Regression: should_include_device() was called only by /health, so a
    device excluded by EXCLUDE_OS still showed up in /health/unhealthy and
    could fail a monitoring check it was meant to be exempt from."""
    m = _load_healthcheck(tmp_path / "healthcheck.db", EXCLUDE_OS="windows")
    devices = [_device("d1", "alpha"), _device("d2", "bravo", os_name="windows", online=False)]
    m.fetch_devices = lambda: devices
    client = m.app.test_client()

    for path in ("/health", "/health/healthy", "/health/unhealthy"):
        assert "d2" not in [d["id"] for d in _json(client, path)["devices"]], f"{path} leaked a filtered device"

    # An excluded device is not addressable either - same as not existing.
    assert client.get("/health/d2").status_code == 404
    assert client.get("/health/bravo").status_code == 404
    assert client.get("/health/d1").status_code == 200

    # ...and it must not be counted in the aggregate metrics.
    metrics = _json(client, "/health")["metrics"]
    assert metrics["counter_healthy_true"] == 1
    assert metrics["counter_healthy_false"] == 0
    assert metrics["global_healthy"] is True


def test_update_health_is_consistent_when_included_in_health(tmp_path):
    """Regression: the three copied handlers hardcoded `healthy` without the
    update term while their counters honoured it, so /health/unhealthy could
    return a device labelled "healthy": true."""
    m = _load_healthcheck(
        tmp_path / "healthcheck.db",
        UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH="true",
    )
    devices = [_device("d1", "alpha"), _device("d2", "bravo", update_available=True)]
    m.fetch_devices = lambda: devices
    client = m.app.test_client()

    unhealthy = _json(client, "/health/unhealthy")
    assert [d["id"] for d in unhealthy["devices"]] == ["d2"]
    assert all(d["healthy"] is False for d in unhealthy["devices"])
    assert all(d["healthy"] is True for d in _json(client, "/health/healthy")["devices"])
    assert _json(client, "/health/d2")["device"]["healthy"] is False


def test_force_update_healthy_filter_moves_the_update_counters(tmp_path):
    """Regression: counter_update_healthy_* counted the raw updateAvailable
    flag, so should_force_update_healthy() changed each device's
    `update_healthy` field but never reached global_update_healthy or the
    dashboard's "Devices Up to Date" tile."""
    devices = [_device("d1", "alpha", update_available=True, tags=["tag:kiosk"])]

    plain = _load_healthcheck(tmp_path / "plain.db")
    plain.fetch_devices = lambda: devices
    metrics = _json(plain.app.test_client(), "/health")["metrics"]
    assert metrics["counter_update_healthy_false"] == 1
    assert metrics["counter_update_healthy_true"] == 0

    # EXCLUDE_TAG_UPDATE_HEALTHY exempts matching devices from update health.
    # (Its INCLUDE counterpart is the inverse: only matching tags participate,
    # so everything *not* matching is what gets forced healthy.)
    exempt = _load_healthcheck(tmp_path / "exempt.db", EXCLUDE_TAG_UPDATE_HEALTHY="kiosk")
    exempt.fetch_devices = lambda: devices
    body = _json(exempt.app.test_client(), "/health")
    assert body["devices"][0]["update_healthy"] is True
    assert body["metrics"]["counter_update_healthy_false"] == 0
    assert body["metrics"]["counter_update_healthy_true"] == 1
    assert body["metrics"]["global_update_healthy"] is True


def test_identifier_lookup_accepts_every_alias(tailnet):
    """hostname, id, full name and machineName must all resolve to the same
    device - the alias set shared with should_include_device()."""
    client = tailnet.app.test_client()
    for alias in ("d1", "alpha", "alpha.example.ts.net", "ALPHA"):
        assert _json(client, f"/health/{alias}")["device"]["id"] == "d1", alias


def test_identifier_metrics_stay_scoped_to_the_single_device(tailnet):
    """/health/<identifier> reports counters for just that device (1/0) -
    unchanged behaviour, unlike the healthy/unhealthy pair."""
    metrics = _json(tailnet.app.test_client(), "/health/d2")["metrics"]

    assert metrics["counter_healthy_true"] == 0
    assert metrics["counter_healthy_false"] == 1
    assert metrics["counter_healthy_online_false"] == 1
