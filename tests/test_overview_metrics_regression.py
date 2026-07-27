"""Regression coverage for a real-world bug: a device transitioning from
offline (unhealthy-because-offline) to online (healthy) must not increase
the "issues" (unhealthy) counters that back the dashboard's Overall Health
trend - only the "online" counters should move. See the incident writeup
in the PR/commit history for the production data that surfaced this.
"""
import importlib.util
import os
import types
from datetime import datetime, timedelta, timezone

import pytz


def _load_healthcheck(database_path) -> types.ModuleType:
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
        })
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    finally:
        os.environ.clear()
        os.environ.update(old_env)


def _offline_device(now):
    # Offline: connectedToControl is False and lastSeen is well past
    # ONLINE_THRESHOLD_MINUTES (default 5) - the exact "iPhone was offline"
    # state from the production incident.
    return {
        "id": "d1", "name": "iphone-von-florian.example.ts.net", "hostname": "localhost",
        "os": "iOS", "clientVersion": "1.98.9", "updateAvailable": False,
        "connectedToControl": False,
        "lastSeen": (now - timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
        "keyExpiryDisabled": False,
        "expires": (now + timedelta(days=48)).isoformat().replace("+00:00", "Z"),
        "tags": ["tag:admin-device", "tag:user-device"],
    }


def _online_device(now):
    # Same device, now reconnected - the only thing that changed.
    d = _offline_device(now)
    d["connectedToControl"] = True
    d["lastSeen"] = now.isoformat().replace("+00:00", "Z")
    return d


def test_device_offline_to_online_transition_does_not_increase_issues(tmp_path):
    """Direct unit-level reproduction: _compute_health_summary() on the same
    device just before/after reconnecting must show issues going DOWN (or at
    worst unchanged), never up, and online-healthy going up by exactly one -
    matching the exact production scenario (5 other unrelated devices stay
    fixed throughout, isolating the transitioning device's effect)."""
    m = _load_healthcheck(tmp_path / "healthcheck.db")
    now = datetime.now(pytz.UTC)

    other_devices = [
        {
            "id": f"other{i}", "name": f"other{i}.example.ts.net", "hostname": f"other{i}",
            "os": "linux", "clientVersion": "1.98.0", "updateAvailable": False,
            "connectedToControl": True, "lastSeen": now.isoformat().replace("+00:00", "Z"),
            "keyExpiryDisabled": True, "expires": None, "tags": [],
        }
        for i in range(5)
    ]

    devices_before = other_devices + [_offline_device(now)]
    devices_after = other_devices + [_online_device(now)]

    _, metrics_before = m._compute_health_summary(devices_before)
    _, metrics_after = m._compute_health_summary(devices_after)

    # The reconnect must not create issues: unhealthy count must not rise...
    assert metrics_after["counter_healthy_false"] <= metrics_before["counter_healthy_false"]
    assert metrics_after["counter_healthy_online_false"] <= metrics_before["counter_healthy_online_false"]
    # ...and online/healthy counts must rise by exactly the one device that reconnected.
    assert metrics_after["counter_healthy_true"] == metrics_before["counter_healthy_true"] + 1
    assert metrics_after["counter_healthy_online_true"] == metrics_before["counter_healthy_online_true"] + 1
    # Update-health is untouched by an online/offline transition.
    assert metrics_after["counter_update_healthy_false"] == metrics_before["counter_update_healthy_false"]


def test_device_offline_to_online_transition_via_full_poll_and_metrics_history(tmp_path, monkeypatch):
    """End-to-end: run two real poll cycles (via dbstore.upsert_devices +
    the real _compute_health_summary, exactly as poller.run_poll_cycle()
    does) and assert the recorded metrics_history snapshot shows issues
    going down, not up, across the transition."""
    import dbstore

    m = _load_healthcheck(tmp_path / "healthcheck.db")
    now = datetime.now(pytz.UTC)

    other_devices = [
        {
            "id": f"other{i}", "name": f"other{i}.example.ts.net", "hostname": f"other{i}",
            "os": "linux", "clientVersion": "1.98.0", "updateAvailable": False,
            "connectedToControl": True, "lastSeen": now.isoformat().replace("+00:00", "Z"),
            "keyExpiryDisabled": True, "expires": None, "tags": [],
        }
        for i in range(5)
    ]

    # Cycle 1: device offline.
    dbstore.upsert_devices(other_devices + [_offline_device(now)])
    health_status, metrics = m._compute_health_summary(dbstore.get_devices_snapshot())
    dbstore.record_metrics_snapshot(metrics, {"counter_key_healthy_true": 0, "counter_key_healthy_false": 0})

    # Cycle 2: device reconnects - the audited connected_to_control transition
    # from the bug report happens here via upsert_devices' own diffing.
    dbstore.upsert_devices(other_devices + [_online_device(now)])
    health_status, metrics = m._compute_health_summary(dbstore.get_devices_snapshot())
    dbstore.record_metrics_snapshot(metrics, {"counter_key_healthy_true": 0, "counter_key_healthy_false": 0})

    history = dbstore.get_metrics_history(hours=24)
    assert len(history) == 2
    before, after = history[0], history[1]

    assert after["counter_healthy_false"] <= before["counter_healthy_false"]
    assert after["counter_healthy_true"] == before["counter_healthy_true"] + 1

    # The transition itself is audited (connected_to_control), but that must
    # never be misread as an "issue" - it's a device-history entry, not a
    # counter input in its own right.
    audit_entries = dbstore.list_audit_log(entity_type="device", action="updated")
    assert any("connected_to_control" in e["changes"] for e in audit_entries)
