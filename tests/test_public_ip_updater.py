import os
import stat
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import dbstore  # noqa: E402
import public_ip_updater as updater  # noqa: E402


POLICY = '''{
  // formatting and comments must survive
  "postures": {
    "posture:Home": ["ip:publicAddress == '8.8.4.4'",],
    "posture:Office": ["ip:publicAddress != '1.0.0.1'"],
  },
  "acls": [],
}
'''


@pytest.fixture
def fresh_db(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()
    return tmp_path


def test_update_rules_changes_only_mapped_ip_tokens():
    old, changed = updater.update_rules(POLICY, {
        "posture:Home": "9.9.9.9",
        "posture:Office": "1.1.1.1",
    })
    assert old == {"posture:Home": "8.8.4.4", "posture:Office": "1.0.0.1"}
    assert changed == POLICY.replace("8.8.4.4", "9.9.9.9").replace("1.0.0.1", "1.1.1.1")


def test_update_rules_rejects_missing_or_multi_condition_posture():
    with pytest.raises(updater.UpdateError, match="must exist exactly once"):
        updater.update_rules(POLICY, {"posture:Missing": "8.8.8.8"})
    multi = POLICY.replace(
        '"posture:Home": ["ip:publicAddress == \'8.8.4.4\'",]',
        '"posture:Home": ["ip:publicAddress == \'8.8.4.4\'", "node:os == \'linux\'"],',
    )
    with pytest.raises(updater.UpdateError, match="exactly one string rule"):
        updater.update_rules(multi, {"posture:Home": "8.8.8.8"})


def test_resolver_selects_first_sorted_public_ipv4(monkeypatch):
    answers = [
        (None, None, None, None, ("9.9.9.9", 0)),
        (None, None, None, None, ("192.168.1.2", 0)),
        (None, None, None, None, ("1.1.1.1", 0)),
    ]
    monkeypatch.setattr(updater.socket, "getaddrinfo", lambda *args: answers)
    assert updater.resolve_public_ipv4("home.example.net") == "1.1.1.1"


def test_mapping_crud_and_duplicate_posture(fresh_db):
    first = dbstore.create_public_ip_mapping("home.example.net", "posture:Home", actor="alice")
    assert first["enabled"] is True
    assert first["status"] == "pending"
    with pytest.raises(Exception):
        dbstore.create_public_ip_mapping("other.example.net", "posture:Home")
    updated = dbstore.update_public_ip_mapping(
        first["id"], "new.example.net", "posture:New", False, actor="alice"
    )
    assert updated["hostname"] == "new.example.net"
    assert updated["enabled"] is False
    assert dbstore.delete_public_ip_mapping(first["id"], actor="alice") is True


def test_sync_updates_multiple_rules_with_one_backup_and_post(fresh_db, monkeypatch):
    home = dbstore.create_public_ip_mapping("home.example.net", "posture:Home")
    office = dbstore.create_public_ip_mapping("office.example.net", "posture:Office")
    addresses = {"home.example.net": "9.9.9.9", "office.example.net": "1.1.1.1"}
    monkeypatch.setattr(updater, "resolve_public_ipv4", lambda host: addresses[host])

    class Response:
        content = POLICY.encode()
        headers = {"ETag": '"policy-v1"'}

    calls = []

    def request(method, url, auth, timeout, body=None, content_type=None, etag=None):
        calls.append((method, url, body, etag))
        return Response()

    monkeypatch.setattr(updater, "_api_request", request)
    result = updater.sync([home, office], "example.ts.net", {"Authorization": "Bearer x"}, 5)
    assert result["ok"] is True
    assert result["changed"] == 2
    assert [call[0] for call in calls] == ["GET", "POST", "POST"]
    assert calls[1][1].endswith("/validate")
    assert calls[2][3] == '"policy-v1"'
    assert b"9.9.9.9" in calls[2][2] and b"1.1.1.1" in calls[2][2]
    backup = Path(fresh_db, "public-ip-policy-backups", result["backup"])
    assert backup.read_bytes() == POLICY.encode()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    audit_rows = dbstore.list_audit_log(entity_type="public_ip_mapping", action="updated")
    assert len(audit_rows) == 2
    assert all(row["actor"] is None for row in audit_rows)


def test_sync_aborts_entire_batch_on_one_dns_failure(fresh_db, monkeypatch):
    home = dbstore.create_public_ip_mapping("home.example.net", "posture:Home")
    office = dbstore.create_public_ip_mapping("bad.example.net", "posture:Office")

    def resolve(host):
        if host.startswith("bad"):
            raise updater.UpdateError("DNS failed")
        return "8.8.8.8"

    monkeypatch.setattr(updater, "resolve_public_ipv4", resolve)
    request = Mock()
    monkeypatch.setattr(updater, "_api_request", request)
    result = updater.sync([home, office], "example.ts.net", {}, 5)
    assert result["ok"] is False
    request.assert_not_called()
    assert all(item["status"] == "error" for item in dbstore.list_public_ip_mappings())
