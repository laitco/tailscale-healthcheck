"""Coverage for poller.py's health-transition -> notifier.notify() wiring.
Exercises the _process_*_notifications() helpers directly against a real
dbstore (so entity_health_state persistence is real), with notifier.notify
mocked out - never hits a real Apprise instance."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import dbstore  # noqa: E402
import poller  # noqa: E402

CFG = {
    "apprise_api_url": "http://apprise.example.com",
    "apprise_config_key": "key",
    "notification_events": ",".join([
        "device_unhealthy", "device_healthy_again", "device_needs_signing", "device_signed",
        "key_expiring", "global_unhealthy", "global_healthy_restored",
    ]),
    "notify_include_tags": "",
    "notify_exclude_tags": "",
    "tailnet_lock_enabled": True,
}


def _fresh_db(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()


def _device(device_id="d1", healthy=True, tailnet_lock_error="", tags=None):
    return {
        "id": device_id, "machineName": "mydevice", "device": "mydevice.example.ts.net",
        "healthy": healthy, "tailnetLockError": tailnet_lock_error, "tags": tags or [],
    }


@patch("poller.notifier.notify", return_value=(True, None))
def test_device_first_seen_never_notifies(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    poller._process_device_notifications(CFG, [_device(healthy=False)])
    mock_notify.assert_not_called()
    assert dbstore.get_health_state("device") == {"d1": False}


@patch("poller.notifier.notify", return_value=(True, None))
def test_device_transition_to_unhealthy_notifies(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "d1", True)
    poller._process_device_notifications(CFG, [_device(healthy=False)])
    assert mock_notify.call_count == 1
    assert mock_notify.call_args[0][0] == "device_unhealthy"
    assert dbstore.get_health_state("device") == {"d1": False}


@patch("poller.notifier.notify", return_value=(True, None))
def test_device_transition_to_healthy_notifies(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "d1", False)
    poller._process_device_notifications(CFG, [_device(healthy=True)])
    assert mock_notify.call_args[0][0] == "device_healthy_again"


@patch("poller.notifier.notify", return_value=(True, None))
def test_device_no_transition_does_not_notify(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "d1", True)
    poller._process_device_notifications(CFG, [_device(healthy=True)])
    mock_notify.assert_not_called()


@patch("poller.notifier.notify", return_value=(True, None))
def test_device_removed_prunes_state(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "gone", True)
    poller._process_device_notifications(CFG, [_device(healthy=True)])
    assert dbstore.get_health_state("device") == {"d1": True}


@patch("poller.notifier.notify", return_value=(True, None))
def test_lock_notifications_skipped_when_tailnet_lock_disabled(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device_lock", "d1", True)
    cfg = dict(CFG, tailnet_lock_enabled=False)
    poller._process_lock_notifications(cfg, [_device(tailnet_lock_error="needs signature")])
    mock_notify.assert_not_called()


@patch("poller.notifier.notify", return_value=(True, None))
def test_lock_notification_on_needs_signing_transition(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device_lock", "d1", True)
    poller._process_lock_notifications(CFG, [_device(tailnet_lock_error="needs signature")])
    assert mock_notify.call_args[0][0] == "device_needs_signing"
    assert dbstore.get_health_state("device_lock") == {"d1": False}


@patch("poller.notifier.notify", return_value=(True, None))
def test_lock_notification_on_signed_transition(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device_lock", "d1", False)
    poller._process_lock_notifications(CFG, [_device(tailnet_lock_error="")])
    assert mock_notify.call_args[0][0] == "device_signed"


@patch("poller.notifier.notify", return_value=(True, None))
def test_key_expiring_fires_only_on_healthy_to_unhealthy_transition(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("key", "k1", True)
    poller._process_key_notifications(CFG, [{"id": "k1", "key_healthy": False, "description": "prod key", "key_days_to_expire": 3}])
    assert mock_notify.call_args[0][0] == "key_expiring"


@patch("poller.notifier.notify", return_value=(True, None))
def test_key_no_healthy_again_event_exists(mock_notify, tmp_path):
    """There's deliberately no 'key healthy again' notification event -
    a key transitioning back to healthy must stay silent."""
    _fresh_db(tmp_path)
    dbstore.set_health_state("key", "k1", False)
    poller._process_key_notifications(CFG, [{"id": "k1", "key_healthy": True, "description": "prod key"}])
    mock_notify.assert_not_called()


@patch("poller.notifier.notify", return_value=(True, None))
def test_global_health_transition_notifies(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("global", "tailnet", True)
    poller._process_global_notifications(CFG, {"global_healthy": False, "counter_healthy_false": 2})
    assert mock_notify.call_args[0][0] == "global_unhealthy"


@patch("poller.notifier.notify", return_value=(True, None))
def test_global_health_no_transition_is_silent(mock_notify, tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("global", "tailnet", True)
    poller._process_global_notifications(CFG, {"global_healthy": True, "counter_healthy_false": 0})
    mock_notify.assert_not_called()


def test_record_notification_logs_only_real_failures(tmp_path):
    """Skips (not configured / event not enabled / tag filtered) shouldn't
    spam the poller_log as failures - only unexpected send errors should."""
    _fresh_db(tmp_path)
    poller._record_notification("device_unhealthy", "d1", False, "tag_filtered")
    poller._record_notification("device_unhealthy", "d1", False, "connection refused")
    poller._record_notification("device_unhealthy", "d1", True, None)

    entries = dbstore.list_poller_log()
    event_types = [e["event_type"] for e in entries]
    assert event_types.count("notification_failed") == 1
    assert event_types.count("notification_sent") == 1
