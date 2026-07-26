import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import dbstore  # noqa: E402


def _fresh_db(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()


def test_schema_creates_tables(tmp_path):
    _fresh_db(tmp_path)
    with dbstore.get_connection() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "users", "devices", "tailnet_keys", "audit_log"} <= tables


def test_setting_env_overrides_and_persists_after_env_removed(tmp_path, monkeypatch):
    _fresh_db(tmp_path)
    monkeypatch.setenv("TAILNET_DOMAIN", "example.ts.net")
    dbstore.sync_env_settings()
    assert dbstore.get_setting("tailnet_domain") == "example.ts.net"
    meta = dbstore.get_setting_meta("tailnet_domain")
    assert meta == {"value": "example.ts.net", "source": "env"}

    # Env removed: the last-synced DB value should still be effective.
    monkeypatch.delenv("TAILNET_DOMAIN")
    assert dbstore.get_setting("tailnet_domain") == "example.ts.net"
    meta = dbstore.get_setting_meta("tailnet_domain")
    assert meta["source"] == "env"  # source recorded at the time it was synced


def test_setting_sentinel_values_are_not_synced(tmp_path, monkeypatch):
    _fresh_db(tmp_path)
    monkeypatch.setenv("TAILNET_DOMAIN", "example.com")
    monkeypatch.setenv("AUTH_TOKEN", "your-default-token")
    dbstore.sync_env_settings()
    assert dbstore.get_setting("tailnet_domain") is None
    assert dbstore.get_setting("auth_token") is None
    assert not dbstore.is_tailnet_configured()


def test_db_sourced_setting_survives_across_boots(tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_setting("tailnet_domain", "wizard-set.ts.net", source="db")
    assert dbstore.get_setting("tailnet_domain") == "wizard-set.ts.net"
    assert dbstore.is_tailnet_configured()

    # Simulate a fresh process boot against the same DB file, no env set.
    dbstore.sync_env_settings()
    assert dbstore.get_setting("tailnet_domain") == "wizard-set.ts.net"


def _device(device_id, name="dev1.example.com", **overrides):
    base = {
        "id": device_id,
        "name": name,
        "hostname": name.split(".")[0],
        "os": "linux",
        "clientVersion": "1.2.3",
        "updateAvailable": False,
        "connectedToControl": True,
        "lastSeen": "2024-01-01T00:00:00Z",
        "keyExpiryDisabled": False,
        "expires": "2025-01-01T00:00:00Z",
        "tags": ["tag:prod"],
    }
    base.update(overrides)
    return base


def test_device_upsert_creates_and_audits(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1")])
    snapshot = dbstore.get_devices_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0]["id"] == "d1"

    entries = dbstore.list_audit_log(entity_type="device")
    assert len(entries) == 1
    assert entries[0]["action"] == "created"


def test_device_last_seen_change_alone_does_not_audit(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1", lastSeen="2024-01-01T00:00:00Z", connectedToControl=True)])
    dbstore.upsert_devices([_device("d1", lastSeen="2024-01-01T00:05:00Z", connectedToControl=True)])

    entries = dbstore.list_audit_log(entity_type="device")
    # Only the initial "created" row - last_seen changes alone never audit.
    assert len(entries) == 1
    assert entries[0]["action"] == "created"


def test_device_connection_status_transition_is_audited(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1", connectedToControl=True)])
    dbstore.upsert_devices([_device("d1", connectedToControl=False)])

    entries = dbstore.list_audit_log(entity_type="device")
    updated = [e for e in entries if e["action"] == "updated"]
    assert len(updated) == 1
    assert "connected_to_control" in updated[0]["changes"]

    # Polling again with the same (still disconnected) status must not add
    # another row - only the transition itself is audited, not every poll.
    dbstore.upsert_devices([_device("d1", connectedToControl=False)])
    entries_after = dbstore.list_audit_log(entity_type="device")
    assert len(entries_after) == len(entries)


def test_device_name_change_does_audit(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1", name="dev1.example.com")])
    dbstore.upsert_devices([_device("d1", name="dev1-renamed.example.com")])

    entries = dbstore.list_audit_log(entity_type="device")
    updated = [e for e in entries if e["action"] == "updated"]
    assert len(updated) == 1
    assert "name" in updated[0]["changes"]


def test_device_removed_is_audited(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1"), _device("d2", name="dev2.example.com")])
    dbstore.upsert_devices([_device("d1")])  # d2 dropped from the latest poll

    assert [d["id"] for d in dbstore.get_devices_snapshot()] == ["d1"]
    entries = dbstore.list_audit_log(entity_type="device")
    removed = [e for e in entries if e["action"] == "removed"]
    assert len(removed) == 1


def test_audit_purge_by_retention(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1")])
    assert len(dbstore.list_audit_log()) == 1

    # Backdate the audit row past the retention window, then purge.
    with dbstore.get_connection() as conn:
        conn.execute("UPDATE audit_log SET occurred_at = '2000-01-01T00:00:00+00:00'")
    dbstore.purge_audit_log(retention_days=14)
    assert dbstore.list_audit_log() == []


def test_audit_log_filters(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1")])
    dbstore.set_setting("tailnet_domain", "filter-test.ts.net", source="db")

    by_entity_type = dbstore.list_audit_log(entity_type="setting")
    assert all(e["entity_type"] == "setting" for e in by_entity_type)
    assert len(by_entity_type) == 1

    by_entity_id = dbstore.list_audit_log(entity_id="d1")
    assert all(e["entity_id"] == "d1" for e in by_entity_id)
    assert len(by_entity_id) == 1

    by_action = dbstore.list_audit_log(action="created")
    assert all(e["action"] == "created" for e in by_action)
    assert len(by_action) == 2  # device created + setting created

    future_only = dbstore.list_audit_log(start="2999-01-01T00:00:00+00:00")
    assert future_only == []

    past_only = dbstore.list_audit_log(end="2000-01-01T00:00:00+00:00")
    assert past_only == []


def test_key_upsert_and_snapshot_roundtrip(tmp_path):
    _fresh_db(tmp_path)
    key = {
        "id": "k1", "description": "ci key", "keyType": "auth",
        "capabilities": {"devices": {}}, "created": "2024-01-01T00:00:00Z",
        "expires": "2025-01-01T00:00:00Z",
    }
    dbstore.upsert_keys([key], key_type_resolver=lambda k: k["keyType"])
    snapshot = dbstore.get_keys_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0]["id"] == "k1"
    assert snapshot[0]["keyType"] == "auth"

    entries = dbstore.list_audit_log(entity_type="tailnet_key")
    assert len(entries) == 1
    assert entries[0]["action"] == "created"


def test_key_removed_from_api_response_is_deleted_and_audited(tmp_path):
    _fresh_db(tmp_path)
    key1 = {"id": "k1", "description": "key one", "keyType": "auth", "capabilities": {}, "expires": None}
    key2 = {"id": "k2", "description": "key two", "keyType": "api", "capabilities": {}, "expires": None}
    resolver = lambda k: k["keyType"]  # noqa: E731

    dbstore.upsert_keys([key1, key2], key_type_resolver=resolver)
    assert {k["id"] for k in dbstore.get_keys_snapshot()} == {"k1", "k2"}

    dbstore.upsert_keys([key1], key_type_resolver=resolver)  # k2 dropped from the latest poll
    assert {k["id"] for k in dbstore.get_keys_snapshot()} == {"k1"}

    removed = [e for e in dbstore.list_audit_log(entity_type="tailnet_key") if e["action"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["entity_id"] == "k2"


def test_audit_log_entity_name_resolution(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1", name="dev1.example.com")])
    dbstore.upsert_devices([_device("d1", name="dev1-renamed.example.com")])
    dbstore.upsert_devices([])  # d1 dropped -> removed

    entries = dbstore.list_audit_log(entity_type="device")
    by_action = {e["action"]: e for e in entries}
    # "created" happened while the live row still had the original name, but
    # by the time we *read* it back the row had since been renamed then
    # removed - so "created"/"updated" resolve via the live row (when present)
    # or the changes blob; "removed" has no live row, so it must come from
    # the changes blob captured at removal time (the post-rename name).
    assert by_action["removed"]["entity_name"] == "dev1-renamed.example.com"
    assert by_action["updated"]["entity_name"] == "dev1-renamed.example.com"

    ids = dbstore.list_audit_log_entity_ids(entity_type="device")
    assert ids == [{"entity_type": "device", "entity_id": "d1", "name": "dev1-renamed.example.com"}]


def test_audit_log_actor_filter(tmp_path):
    _fresh_db(tmp_path)
    dbstore.upsert_devices([_device("d1")])  # actor=None ("poller")
    dbstore.set_setting("tailnet_domain", "actor-test.ts.net", source="db", actor="alice")

    poller_entries = dbstore.list_audit_log(actor="poller")
    assert len(poller_entries) == 1
    assert poller_entries[0]["entity_type"] == "device"

    alice_entries = dbstore.list_audit_log(actor="alice")
    assert len(alice_entries) == 1
    assert alice_entries[0]["entity_type"] == "setting"

    assert dbstore.list_audit_log_actors() == ["alice", "poller"]
    assert {"entity_type": "device", "entity_id": "d1", "name": "dev1.example.com"} in dbstore.list_audit_log_entity_ids()


def test_user_crud_and_password_verification(tmp_path):
    _fresh_db(tmp_path)
    assert not dbstore.has_any_user()
    dbstore.create_user("alice", "s3cret-password")
    assert dbstore.has_any_user()
    assert dbstore.verify_password("alice", "s3cret-password") is not None
    assert dbstore.verify_password("alice", "wrong-password") is None
    assert dbstore.verify_password("nobody", "whatever") is None

    dbstore.delete_user("alice")
    assert not dbstore.has_any_user()
