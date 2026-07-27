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
    assert {"settings", "users", "devices", "tailnet_keys", "audit_log", "user_recovery_codes"} <= tables


def test_init_db_migrates_pre_mfa_users_table(tmp_path):
    """Simulates an existing production DB created before totp_secret/
    totp_enabled existed - init_db() must ALTER TABLE it in place rather
    than assuming CREATE TABLE IF NOT EXISTS is enough."""
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    with dbstore.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("legacy", "hash", "2024-01-01T00:00:00+00:00"),
        )

    dbstore.init_db()  # must not raise, and must add the missing columns

    with dbstore.get_connection() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    assert {"totp_secret", "totp_enabled"} <= columns
    assert dbstore.get_user_mfa_status("legacy") == {"enabled": False}


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


def test_removed_env_var_unlocks_setting_on_next_sync(tmp_path, monkeypatch):
    _fresh_db(tmp_path)
    monkeypatch.setenv("TAILNET_DOMAIN", "example.ts.net")
    dbstore.sync_env_settings()
    assert dbstore.get_setting_meta("tailnet_domain") == {"value": "example.ts.net", "source": "env"}

    # Env removed and the process restarts (sync_env_settings runs again on boot):
    # the value must be preserved, but source should flip back to 'db' so the
    # admin UI unlocks the field instead of staying permanently env-locked.
    monkeypatch.delenv("TAILNET_DOMAIN")
    dbstore.sync_env_settings()
    meta = dbstore.get_setting_meta("tailnet_domain")
    assert meta == {"value": "example.ts.net", "source": "db"}
    assert dbstore.get_setting("tailnet_domain") == "example.ts.net"


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


def test_secret_setting_changes_are_redacted_in_audit_log(tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_setting("auth_token", "super-secret-value", source="db")
    dbstore.set_setting("oauth_client_secret", "another-secret", source="db")
    dbstore.set_setting("tailnet_domain", "wizard-set.ts.net", source="db")  # non-secret control case

    entries = {e["entity_id"]: e for e in dbstore.list_audit_log(entity_type="setting")}
    assert entries["auth_token"]["changes"]["new"] == "[redacted]"
    assert entries["auth_token"]["changes"]["old"] is None
    assert entries["oauth_client_secret"]["changes"]["new"] == "[redacted]"
    assert entries["tailnet_domain"]["changes"]["new"] == "wizard-set.ts.net"  # not a secret, stays plaintext

    # And the raw audit_log table itself must never contain the plaintext value.
    with dbstore.get_connection() as conn:
        raw = "\n".join(r["changes"] for r in conn.execute("SELECT changes FROM audit_log"))
    assert "super-secret-value" not in raw
    assert "another-secret" not in raw


def test_login_rate_limit_blocks_after_threshold(tmp_path):
    _fresh_db(tmp_path)
    for _ in range(dbstore.LOGIN_RATE_LIMIT_ATTEMPTS):
        assert dbstore.check_login_rate_limit("1.2.3.4") is True
    assert dbstore.check_login_rate_limit("1.2.3.4") is False
    # A different IP has its own independent counter.
    assert dbstore.check_login_rate_limit("5.6.7.8") is True


def test_manual_poll_claim_collapses_concurrent_callers(tmp_path):
    _fresh_db(tmp_path)
    # First caller wins the claim...
    assert dbstore.try_claim_manual_poll(ttl_seconds=10) is True
    # ...every other caller within the TTL window loses it, so N concurrent
    # /health/cache/invalidate requests only ever result in one real poll.
    assert dbstore.try_claim_manual_poll(ttl_seconds=10) is False
    assert dbstore.try_claim_manual_poll(ttl_seconds=10) is False


def test_manual_poll_claim_expires(tmp_path):
    _fresh_db(tmp_path)
    assert dbstore.try_claim_manual_poll(ttl_seconds=-1) is True  # already-expired claim
    # A new claim attempt after the (already-past) TTL must succeed again.
    assert dbstore.try_claim_manual_poll(ttl_seconds=10) is True


def test_manual_poll_claim_release_lets_next_caller_in_immediately(tmp_path):
    _fresh_db(tmp_path)
    assert dbstore.try_claim_manual_poll(ttl_seconds=300) is True
    assert dbstore.try_claim_manual_poll(ttl_seconds=300) is False
    dbstore.release_manual_poll_claim()
    # A normal-completion release must not require waiting out the
    # crash-recovery TTL - the whole point is the next caller isn't blocked
    # for up to 300s just because the previous poll already finished.
    assert dbstore.try_claim_manual_poll(ttl_seconds=300) is True


def test_rate_limit_storage_url_is_a_secret_setting():
    assert "rate_limit_storage_url" in dbstore.SECRET_SETTINGS


def test_recovery_code_cannot_be_consumed_twice_even_racing_the_check(tmp_path):
    # Simulates the race directly at the storage layer: two "concurrent"
    # attempts to claim the same still-unused row must not both succeed.
    _fresh_db(tmp_path)
    dbstore.create_user("racer", "correct-horse-battery-staple")
    from werkzeug.security import generate_password_hash
    with dbstore.get_connection() as conn:
        user_id = conn.execute("SELECT id FROM users WHERE username = 'racer'").fetchone()["id"]
        conn.execute(
            "INSERT INTO user_recovery_codes (user_id, code_hash, created_at) VALUES (?, ?, ?)",
            (user_id, generate_password_hash("abc123"), "2024-01-01T00:00:00+00:00"),
        )
    assert dbstore.verify_recovery_code("racer", "abc123") is True
    assert dbstore.verify_recovery_code("racer", "abc123") is False


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

    # delete_user() refuses to remove the sole remaining user (enforced
    # atomically inside the function itself - see
    # test_delete_user_last_user_guard_is_atomic for why it can't be a
    # separate check-then-delete).
    assert dbstore.delete_user("alice") == "last_user"
    assert dbstore.has_any_user()

    dbstore.create_user("bob", "another-password")
    assert dbstore.delete_user("alice") == "deleted"
    assert dbstore.delete_user("nobody") == "not_found"
    assert dbstore.has_any_user()  # bob remains


def test_delete_user_last_user_guard_is_atomic(tmp_path):
    _fresh_db(tmp_path)
    dbstore.create_user("alice", "s3cret-password")
    dbstore.create_user("bob", "another-password")

    # With exactly 2 users, deleting either one individually must succeed...
    assert dbstore.delete_user("alice") == "deleted"
    # ...but now only 1 remains, so deleting the last one is refused.
    assert dbstore.delete_user("bob") == "last_user"
    assert dbstore.has_any_user()


def test_count_audit_log_matches_list_filters(tmp_path):
    """The pagination total must be computed with exactly the same filters as
    the page itself, or the UI reports a count it can't actually page to."""
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()

    for i in range(7):
        dbstore.set_setting(f"setting_{i}", "x", actor="alice")
    for i in range(3):
        dbstore.set_setting(f"other_{i}", "x", actor="bob")

    assert dbstore.count_audit_log(actor="alice") == 7
    assert dbstore.count_audit_log(actor="bob") == 3
    assert dbstore.count_audit_log() == 10

    # A limited page doesn't change the total it reports alongside itself.
    page = dbstore.list_audit_log(limit=4, actor="alice")
    assert len(page) == 4
    assert dbstore.count_audit_log(actor="alice") == 7

    # Offsetting past the end yields no rows but the same total.
    assert dbstore.list_audit_log(limit=4, offset=100, actor="alice") == []
    assert dbstore.count_audit_log(actor="alice") == 7


def test_set_health_state_bulk_matches_single_writes(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()

    dbstore.set_health_state_bulk("device", {"d1": True, "d2": False, "d3": True})
    assert dbstore.get_health_state("device") == {"d1": True, "d2": False, "d3": True}

    # Upserts, not inserts - re-writing an existing id flips it in place.
    dbstore.set_health_state_bulk("device", {"d1": False, "d4": True})
    assert dbstore.get_health_state("device") == {"d1": False, "d2": False, "d3": True, "d4": True}

    # An empty batch is a no-op, not a wipe.
    dbstore.set_health_state_bulk("device", {})
    assert len(dbstore.get_health_state("device")) == 4


def test_purge_login_rate_limit_drops_only_closed_windows(tmp_path):
    """The table had no purge at all, so it grew one permanent row per source
    IP that ever attempted a login."""
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()

    assert dbstore.check_login_rate_limit("10.0.0.1") is True
    with dbstore.get_connection() as conn:
        conn.execute("INSERT INTO login_rate_limit (ip, window_start, count) VALUES ('10.0.0.2', 0, 5)")

    dbstore.purge_login_rate_limit()

    with dbstore.get_connection() as conn:
        remaining = {r["ip"] for r in conn.execute("SELECT ip FROM login_rate_limit")}
    assert remaining == {"10.0.0.1"}, "current window must survive, ancient one must not"


def test_get_settings_meta_matches_per_setting_lookup(tmp_path, monkeypatch):
    """The batched variant backing the settings page must agree with the
    single-setting one it replaced, including env-vs-db source attribution."""
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()
    dbstore.set_setting("online_threshold_minutes", 42)
    monkeypatch.setenv("TIMEZONE", "Europe/Berlin")

    names = ["online_threshold_minutes", "timezone", "exclude_os"]
    batched = dbstore.get_settings_meta(names)

    for name in names:
        assert batched[name] == dbstore.get_setting_meta(name), name
    assert batched["timezone"]["source"] == "env"
    assert batched["online_threshold_minutes"]["source"] == "db"
    assert batched["exclude_os"]["source"] is None


def _seed_change_rows(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()
    with dbstore.get_connection() as conn:
        rows = [
            # device "updated" shape: {field: {old, new}}
            ("device", "d1", "updated", {"os": {"old": "linux", "new": "windows"}}),
            ("device", "d2", "updated", {"client_version": {"old": "1.0", "new": "1.1"}}),
            # device "created" snapshot shape: {field: value}
            ("device", "d3", "created", {"os": "linux", "hostname": "ReverseProxy"}),
            # setting shape: the field IS the entity_id, top-level keys are meta
            ("setting", "log_level", "updated", {"old": "INFO", "new": "DEBUG", "source": "db"}),
        ]
        for entity_type, entity_id, action, changes in rows:
            dbstore._add_audit(conn, entity_type, entity_id, action, changes)


def test_audit_changed_field_filter(tmp_path):
    """Filtering by changed field must match both the {field: {old,new}} update
    shape and the {field: value} created/removed snapshot shape."""
    _seed_change_rows(tmp_path)

    os_rows = dbstore.list_audit_log(changed_field="os")
    assert {r["entity_id"] for r in os_rows} == {"d1", "d3"}
    assert dbstore.count_audit_log(changed_field="os") == 2

    assert dbstore.count_audit_log(changed_field="client_version") == 1
    assert dbstore.count_audit_log(changed_field="nonexistent_field") == 0

    # A setting row's wrapper keys are not addressable as fields - a setting's
    # field is its entity_id, which the existing entity_id filter covers.
    assert dbstore.count_audit_log(changed_field="source") == 0


def test_audit_changed_field_options_exclude_setting_wrappers(tmp_path):
    _seed_change_rows(tmp_path)

    fields = dbstore.list_audit_log_changed_fields()
    assert fields == ["client_version", "hostname", "os"]
    for meta in ("old", "new", "source"):
        assert meta not in fields

    assert dbstore.list_audit_log_changed_fields("setting") == []
    assert dbstore.list_audit_log_changed_fields("device") == ["client_version", "hostname", "os"]


def test_audit_changes_contains_search(tmp_path):
    """Free-text search covers values, not just field names - that's the point
    of it next to the changed-field select."""
    _seed_change_rows(tmp_path)

    assert {r["entity_id"] for r in dbstore.list_audit_log(changes_contains="windows")} == {"d1"}
    # Case-insensitive, and matches a value buried in a snapshot row.
    assert {r["entity_id"] for r in dbstore.list_audit_log(changes_contains="reverseproxy")} == {"d3"}
    assert dbstore.count_audit_log(changes_contains="DEBUG") == 1
    assert dbstore.count_audit_log(changes_contains="no-such-value") == 0


def test_audit_changes_contains_escapes_like_wildcards(tmp_path):
    """A search for "%" must not silently match every row."""
    _seed_change_rows(tmp_path)
    total = dbstore.count_audit_log()
    assert total == 4

    assert dbstore.count_audit_log(changes_contains="%") == 0
    assert dbstore.count_audit_log(changes_contains="_") < total


def test_audit_change_filters_combine_with_the_others(tmp_path):
    """New filters must AND with the existing ones, and count must agree with
    the page it describes."""
    _seed_change_rows(tmp_path)

    assert dbstore.count_audit_log(changed_field="os", action="created") == 1
    assert dbstore.count_audit_log(changed_field="os", action="updated") == 1
    assert dbstore.count_audit_log(changed_field="os", entity_type="setting") == 0
    assert dbstore.count_audit_log(changed_field="os", changes_contains="windows") == 1

    rows = dbstore.list_audit_log(changed_field="os", changes_contains="linux")
    assert dbstore.count_audit_log(changed_field="os", changes_contains="linux") == len(rows)
