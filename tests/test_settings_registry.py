import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import dbstore  # noqa: E402


def _fresh_db(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()


def test_registry_covers_expected_settings():
    expected = {
        "tailnet_domain", "auth_token", "oauth_client_id", "oauth_client_secret",
        "health_endpoint_token", "api_base_url",
        "online_threshold_minutes", "key_threshold_minutes", "key_expiry_warning_days",
        "global_healthy_threshold", "global_online_healthy_threshold",
        "global_key_healthy_threshold", "global_update_healthy_threshold",
        "update_healthy_is_included_in_health",
        "include_os", "exclude_os", "include_identifier", "exclude_identifier",
        "include_tags", "exclude_tags",
        "include_identifier_update_healthy", "exclude_identifier_update_healthy",
        "include_tag_update_healthy", "exclude_tag_update_healthy",
        "include_key_type", "exclude_key_type", "include_key_description", "exclude_key_description",
        "timezone", "http_timeout", "log_level", "debug_log_enabled",
        "rate_limit_enabled", "rate_limit_per_ip", "rate_limit_global",
        "rate_limit_storage_url", "rate_limit_headers_enabled",
        "max_retries", "backoff_base_seconds", "backoff_max_seconds", "backoff_jitter_seconds",
        "poll_interval_seconds", "audit_retention_days",
    }
    assert expected <= set(dbstore.SETTINGS_REGISTRY.keys())
    assert "display_settings_in_output" not in dbstore.SETTINGS_REGISTRY


def test_non_core_setting_env_override_persists_after_removal(tmp_path, monkeypatch):
    _fresh_db(tmp_path)
    monkeypatch.setenv("ONLINE_THRESHOLD_MINUTES", "42")
    dbstore.sync_env_settings()
    assert dbstore.get_setting_typed("online_threshold_minutes") == 42

    monkeypatch.delenv("ONLINE_THRESHOLD_MINUTES")
    assert dbstore.get_setting_typed("online_threshold_minutes") == 42


def test_get_setting_typed_casts_int_float_bool(tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_setting("online_threshold_minutes", "7", source="db")
    dbstore.set_setting("http_timeout", "12.5", source="db")
    dbstore.set_setting("rate_limit_enabled", "NO", source="db")

    assert dbstore.get_setting_typed("online_threshold_minutes") == 7
    assert isinstance(dbstore.get_setting_typed("online_threshold_minutes"), int)
    assert dbstore.get_setting_typed("http_timeout") == 12.5
    assert dbstore.get_setting_typed("rate_limit_enabled") is False


def test_get_setting_typed_falls_back_to_default_when_unset(tmp_path):
    _fresh_db(tmp_path)
    assert dbstore.get_setting_typed("online_threshold_minutes") == 5
    assert dbstore.get_setting_typed("rate_limit_enabled") is True
    assert dbstore.get_setting_typed("include_os") == ""


def test_get_settings_typed_bundles_env_and_db_sources(tmp_path, monkeypatch):
    _fresh_db(tmp_path)
    monkeypatch.setenv("ONLINE_THRESHOLD_MINUTES", "9")
    dbstore.set_setting("key_threshold_minutes", "999", source="db")

    bundle = dbstore.get_settings_typed(["online_threshold_minutes", "key_threshold_minutes", "timezone"])
    assert bundle == {"online_threshold_minutes": 9, "key_threshold_minutes": 999, "timezone": "UTC"}


def test_validate_setting_value_rejects_bad_numbers(tmp_path):
    _fresh_db(tmp_path)
    with pytest.raises(ValueError):
        dbstore.validate_setting_value("online_threshold_minutes", "not-a-number")

    encoded = dbstore.validate_setting_value("online_threshold_minutes", "15")
    assert encoded == "15"


def test_validate_setting_value_encodes_bool():
    assert dbstore.validate_setting_value("rate_limit_enabled", True) == "YES"
    assert dbstore.validate_setting_value("rate_limit_enabled", False) == "NO"
    assert dbstore.validate_setting_value("rate_limit_enabled", "NO") == "NO"


def test_debug_log_enabled_gates_poller_log_persistence(tmp_path):
    import poller

    _fresh_db(tmp_path)
    dbstore.set_setting("debug_log_enabled", "NO", source="db")
    poller._record("poll_started", "should not be captured")
    assert poller.get_poll_log() == []

    dbstore.set_setting("debug_log_enabled", "YES", source="db")
    poller._record("poll_started", "should be captured")
    assert len(poller.get_poll_log()) == 1


def test_poller_log_filters_by_event_type_and_purges(tmp_path):
    import poller

    _fresh_db(tmp_path)
    poller._record("poll_started", "start", {"a": 1})
    poller._record("devices_error", "boom", {"error": "timeout"})

    all_entries = poller.get_poll_log()
    assert len(all_entries) == 2
    assert all_entries[0]["event_type"] == "devices_error"  # newest first
    assert all_entries[0]["detail"] == {"error": "timeout"}

    only_errors = poller.get_poll_log(event_type="devices_error")
    assert len(only_errors) == 1
    assert only_errors[0]["message"] == "boom"

    assert "poll_started" in poller.get_poll_log_event_types()

    with dbstore.get_connection() as conn:
        conn.execute("UPDATE poller_log SET occurred_at = '2000-01-01T00:00:00+00:00'")
    dbstore.purge_poller_log(retention_days=7)
    assert poller.get_poll_log() == []


def test_metrics_history_record_and_purge(tmp_path):
    _fresh_db(tmp_path)
    health_metrics = {
        "counter_healthy_true": 5, "counter_healthy_false": 1,
        "counter_healthy_online_true": 6, "counter_healthy_online_false": 0,
        "counter_key_healthy_true": 5, "counter_key_healthy_false": 1,
        "counter_update_healthy_true": 4, "counter_update_healthy_false": 2,
    }
    keys_metrics = {"counter_key_healthy_true": 3, "counter_key_healthy_false": 0}

    dbstore.record_metrics_snapshot(health_metrics, keys_metrics)
    history = dbstore.get_metrics_history(hours=24)
    assert len(history) == 1
    assert history[0]["counter_healthy_true"] == 5
    assert history[0]["keys_counter_healthy_true"] == 3

    with dbstore.get_connection() as conn:
        conn.execute("UPDATE metrics_history SET occurred_at = '2000-01-01T00:00:00+00:00'")
    dbstore.purge_metrics_history(retention_hours=48)
    assert dbstore.get_metrics_history(hours=24 * 365) == []


def test_every_registry_setting_is_rendered_by_the_settings_ui():
    """The admin settings page renders from a hardcoded FIELDS_BY_GROUP list in
    frontend/src/pages/admin-settings.tsx, not from the registry - so adding a
    setting to SETTINGS_REGISTRY without adding it there leaves it invisible
    and un-editable in the UI, with no error anywhere to say so.

    Guards the group list too: a setting in a group missing from GROUP_ORDER is
    equally invisible, since that array is what the page iterates.
    """
    import re

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    page = open(os.path.join(root, "frontend/src/pages/admin-settings.tsx"), encoding="utf-8").read()

    rendered = set(re.findall(r"\{\s*name:\s*'([a-z0-9_]+)'", page))
    group_order = set(re.findall(r"'([a-z_]+)'", page.split("] as const", 1)[0]))

    missing = sorted(set(dbstore.SETTINGS_REGISTRY) - rendered)
    assert not missing, f"settings missing from the admin UI's FIELDS_BY_GROUP: {missing}"

    groups = {meta[4] for meta in dbstore.SETTINGS_REGISTRY.values()}
    missing_groups = sorted(groups - group_order)
    assert not missing_groups, f"groups missing from the admin UI's GROUP_ORDER: {missing_groups}"
