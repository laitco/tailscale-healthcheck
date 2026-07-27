from unittest.mock import Mock, patch

import notifier


def _cfg(**overrides):
    base = {
        "apprise_api_url": "http://apprise.example.com",
        "apprise_notification_urls": "tgram://bottoken/ChatID",
        "apprise_bearer_token": "",
        "notification_events": "device_unhealthy,device_healthy_again",
        "notify_include_tags": "",
        "notify_exclude_tags": "",
    }
    base.update(overrides)
    return base


def test_get_enabled_events_parses_and_filters_unknown():
    assert notifier.get_enabled_events("device_unhealthy, bogus_event, global_unhealthy") == {
        "device_unhealthy", "global_unhealthy",
    }
    assert notifier.get_enabled_events("") == set()
    assert notifier.get_enabled_events(None) == set()


def test_is_configured_requires_both_url_and_urls():
    assert notifier.is_configured(_cfg()) is True
    assert notifier.is_configured(_cfg(apprise_api_url="")) is False
    assert notifier.is_configured(_cfg(apprise_notification_urls="")) is False
    # Bearer token is optional - not configured means url + notification urls only.
    assert notifier.is_configured(_cfg(apprise_bearer_token="")) is True


def test_tag_matches_include_takes_precedence_over_exclude():
    tags = ["tag:prod", "tag:web"]
    # Include patterns win even if a tag would also match exclude.
    assert notifier.tag_matches(tags, "prod", "prod") is True
    assert notifier.tag_matches(tags, "staging", "") is False


def test_tag_matches_exclude_only():
    tags = ["tag:prod"]
    assert notifier.tag_matches(tags, "", "prod") is False
    assert notifier.tag_matches(tags, "", "staging") is True


def test_tag_matches_no_filters_matches_everything():
    assert notifier.tag_matches(["tag:anything"], "", "") is True
    assert notifier.tag_matches([], "", "") is True


def test_is_lock_signer():
    assert notifier.is_lock_signer(["tag:lock-signer"], "lock-signer") is True
    assert notifier.is_lock_signer(["tag:lock-signer"], "") is False
    assert notifier.is_lock_signer(["tag:user-device"], "lock-signer*") is False
    assert notifier.is_lock_signer(["tag:lock-signer-primary"], "lock-signer*") is True


def test_notify_skips_when_not_configured():
    sent, reason = notifier.notify("device_unhealthy", "t", "b", _cfg(apprise_api_url=""))
    assert sent is False
    assert reason == "not_configured"


def test_notify_skips_when_event_not_enabled():
    cfg = _cfg(notification_events="global_unhealthy")
    sent, reason = notifier.notify("device_unhealthy", "t", "b", cfg)
    assert sent is False
    assert reason == "event_not_enabled"


def test_notify_skips_when_tag_filtered():
    cfg = _cfg(notify_include_tags="prod")
    sent, reason = notifier.notify("device_unhealthy", "t", "b", cfg, device_tags=["tag:staging"])
    assert sent is False
    assert reason == "tag_filtered"


@patch("notifier.requests.post")
def test_notify_sends_to_stateless_apprise_endpoint(mock_post):
    mock_post.return_value = Mock(status_code=200, raise_for_status=lambda: None)
    cfg = _cfg()
    sent, reason = notifier.notify("device_unhealthy", "Title", "Body", cfg, device_tags=["tag:prod"])
    assert sent is True
    assert reason is None
    mock_post.assert_called_once_with(
        "http://apprise.example.com/notify",
        json={"urls": "tgram://bottoken/ChatID", "title": "Title", "body": "Body"},
        headers={},
        timeout=10,
    )


@patch("notifier.requests.post")
def test_notify_sends_bearer_token_header_when_set(mock_post):
    mock_post.return_value = Mock(status_code=200, raise_for_status=lambda: None)
    cfg = _cfg(apprise_bearer_token="s3cret")
    notifier.notify("device_unhealthy", "Title", "Body", cfg, device_tags=["tag:prod"])
    assert mock_post.call_args.kwargs["headers"] == {"Authorization": "Bearer s3cret"}


@patch("notifier.requests.post")
def test_notify_returns_error_on_failure_without_raising(mock_post):
    mock_post.side_effect = Exception("connection refused")
    sent, reason = notifier.notify("device_unhealthy", "t", "b", _cfg())
    assert sent is False
    assert reason == "connection refused"


@patch("notifier.requests.post")
def test_test_notification_bypasses_event_and_tag_gating(mock_post):
    mock_post.return_value = Mock(status_code=200, raise_for_status=lambda: None)
    cfg = _cfg(notification_events="")  # nothing enabled
    ok, error = notifier.test(cfg)
    assert ok is True
    assert error is None
    mock_post.assert_called_once()


def test_test_notification_requires_configuration():
    ok, error = notifier.test(_cfg(apprise_api_url=""))
    assert ok is False
    assert error == "not_configured"
