"""Coverage for Tailnet Lock support: the tailnetLockError device field must
flow through storage, /health's device dicts, and the healthy/unhealthy
computation - gated behind the tailnet_lock_enabled opt-in (default off), so
installs that don't use Tailnet Lock see zero behavior change even if the
Tailscale API ever populated the field."""
import importlib.util
import os
import types
from datetime import datetime

import pytz

import dbstore


def _load_healthcheck(database_path, tailnet_lock_enabled=False) -> types.ModuleType:
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
            "TAILNET_LOCK_ENABLED": "YES" if tailnet_lock_enabled else "NO",
        })
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    finally:
        os.environ.clear()
        os.environ.update(old_env)


def _device(now, tailnet_lock_error=""):
    return {
        "id": "d1", "name": "signer.example.ts.net", "hostname": "signer",
        "os": "linux", "clientVersion": "1.98.0", "updateAvailable": False,
        "connectedToControl": True,
        "lastSeen": now.isoformat().replace("+00:00", "Z"),
        "keyExpiryDisabled": True, "expires": None, "tags": [],
        "tailnetLockError": tailnet_lock_error,
    }


def test_lock_disabled_by_default_ignores_tailnet_lock_error(tmp_path):
    """The default-off switch must win even if the Tailscale API somehow
    returns a populated tailnetLockError - an admin has to explicitly opt in
    before it can affect health."""
    m = _load_healthcheck(tmp_path / "healthcheck.db", tailnet_lock_enabled=False)
    now = datetime.now(pytz.UTC)

    devices = [_device(now, tailnet_lock_error="node key signature missing")]
    health_status, metrics = m._compute_health_summary(devices)

    assert health_status[0]["tailnetLockError"] == "node key signature missing"
    assert health_status[0]["lock_healthy"] is True
    assert health_status[0]["healthy"] is True
    assert health_status[0]["tailnetLockEnabled"] is False
    assert metrics["counter_lock_healthy_true"] == 1
    assert metrics["counter_lock_healthy_false"] == 0
    assert metrics["global_lock_healthy"] is True


def test_tailnet_lock_enabled_flag_is_carried_on_each_device(tmp_path):
    """The frontend uses this per-device flag (not a separate settings fetch)
    to decide whether to show the Lock column/field at all."""
    m = _load_healthcheck(tmp_path / "healthcheck.db", tailnet_lock_enabled=True)
    now = datetime.now(pytz.UTC)

    devices = [_device(now, tailnet_lock_error="")]
    health_status, _ = m._compute_health_summary(devices)

    assert health_status[0]["tailnetLockEnabled"] is True


def test_device_needing_signature_is_unhealthy_when_enabled(tmp_path):
    m = _load_healthcheck(tmp_path / "healthcheck.db", tailnet_lock_enabled=True)
    now = datetime.now(pytz.UTC)

    devices = [_device(now, tailnet_lock_error="node key signature missing")]
    health_status, metrics = m._compute_health_summary(devices)

    assert health_status[0]["tailnetLockError"] == "node key signature missing"
    assert health_status[0]["lock_healthy"] is False
    assert health_status[0]["healthy"] is False
    assert metrics["counter_lock_healthy_true"] == 0
    assert metrics["counter_lock_healthy_false"] == 1


def test_device_signed_is_lock_healthy_when_enabled(tmp_path):
    m = _load_healthcheck(tmp_path / "healthcheck.db", tailnet_lock_enabled=True)
    now = datetime.now(pytz.UTC)

    devices = [_device(now, tailnet_lock_error="")]
    health_status, metrics = m._compute_health_summary(devices)

    assert health_status[0]["tailnetLockError"] == ""
    assert health_status[0]["lock_healthy"] is True
    assert health_status[0]["healthy"] is True
    assert metrics["counter_lock_healthy_true"] == 1
    assert metrics["counter_lock_healthy_false"] == 0
    assert metrics["global_lock_healthy"] is True


def test_lock_status_is_inert_when_tailnet_lock_not_used_even_if_enabled(tmp_path):
    """Even with the switch on, a tailnet that doesn't actually use Tailnet
    Lock reports an empty tailnetLockError for every device (per the API
    contract), so lock health stays a no-op."""
    m = _load_healthcheck(tmp_path / "healthcheck.db", tailnet_lock_enabled=True)
    now = datetime.now(pytz.UTC)

    devices = [_device(now, tailnet_lock_error="") for _ in range(5)]
    _, metrics = m._compute_health_summary(devices)

    assert metrics["counter_lock_healthy_false"] == 0
    assert metrics["global_lock_healthy"] is True


def test_tailnet_lock_error_round_trips_through_dbstore(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()

    device = {
        "id": "d1", "name": "signer.example.ts.net", "hostname": "signer",
        "os": "linux", "clientVersion": "1.98.0", "updateAvailable": False,
        "connectedToControl": True, "lastSeen": None,
        "keyExpiryDisabled": True, "expires": None, "tags": [],
        "tailnetLockError": "node key signature missing",
    }
    dbstore.upsert_devices([device])
    snapshot = dbstore.get_devices_snapshot()
    assert snapshot[0]["tailnetLockError"] == "node key signature missing"

    # Device gets signed - tailnetLockError clears. This must produce an
    # audit_log "updated" entry so an admin can see when/who resolved it.
    device["tailnetLockError"] = ""
    dbstore.upsert_devices([device])
    snapshot = dbstore.get_devices_snapshot()
    assert snapshot[0]["tailnetLockError"] == ""

    entries = dbstore.list_audit_log(entity_type="device", entity_id="d1")
    updated = [e for e in entries if e["action"] == "updated"]
    assert len(updated) == 1
    assert updated[0]["changes"]["tailnet_lock_error"] == {
        "old": "node key signature missing", "new": "",
    }


def test_tailnet_lock_enabled_default_is_off(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()
    assert dbstore.get_setting_typed("tailnet_lock_enabled") is False
