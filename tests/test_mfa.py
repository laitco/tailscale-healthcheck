import importlib.util
import os
import types

import pyotp
import pytest


def _load_healthcheck(env: dict, database_path) -> types.ModuleType:
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    assert spec and spec.loader
    old_env = os.environ.copy()
    try:
        os.environ.update(env)
        os.environ["DATABASE_PATH"] = str(database_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    finally:
        os.environ.clear()
        os.environ.update(old_env)


@pytest.fixture
def configured(tmp_path):
    m = _load_healthcheck(
        {"RATE_LIMIT_ENABLED": "NO", "TAILNET_DOMAIN": "example.ts.net", "AUTH_TOKEN": "test-token"},
        tmp_path / "healthcheck.db",
    )
    m.dbstore.create_user("admin", "correct-horse-battery-staple")
    return m


def _login(client, username="admin", password="correct-horse-battery-staple"):
    return client.post("/admin/api/login", json={"username": username, "password": password})


def test_password_change_requires_correct_current_password(configured):
    client = configured.app.test_client()
    _login(client)

    bad = client.post(
        "/admin/api/profile/password",
        json={"current_password": "wrong", "new_password": "brand-new-password"},
    )
    assert bad.status_code == 401

    ok = client.post(
        "/admin/api/profile/password",
        json={"current_password": "correct-horse-battery-staple", "new_password": "brand-new-password"},
    )
    assert ok.status_code == 200

    client.post("/admin/api/logout")
    relogin_old = _login(client, password="correct-horse-battery-staple")
    assert relogin_old.status_code == 401
    relogin_new = _login(client, password="brand-new-password")
    assert relogin_new.status_code == 200


def test_mfa_enroll_confirm_and_login_flow(configured):
    client = configured.app.test_client()
    _login(client)

    enroll = client.post("/admin/api/profile/mfa/enroll")
    assert enroll.status_code == 200
    secret = enroll.get_json()["secret"]
    assert "otpauth://totp/" in enroll.get_json()["provisioning_uri"]

    # Wrong code doesn't activate MFA.
    bad_confirm = client.post("/admin/api/profile/mfa/confirm", json={"code": "000000"})
    assert bad_confirm.status_code == 400
    assert configured.dbstore.get_user_mfa_status("admin")["enabled"] is False

    valid_code = pyotp.TOTP(secret).now()
    confirm = client.post("/admin/api/profile/mfa/confirm", json={"code": valid_code})
    assert confirm.status_code == 200
    recovery_codes = confirm.get_json()["recovery_codes"]
    assert len(recovery_codes) == 10
    assert configured.dbstore.get_user_mfa_status("admin")["enabled"] is True

    # Recovery codes are only ever stored hashed, never in plaintext.
    with configured.dbstore.get_connection() as conn:
        rows = conn.execute("SELECT code_hash FROM user_recovery_codes").fetchall()
    stored_hashes = {r["code_hash"] for r in rows}
    assert not (stored_hashes & set(recovery_codes))

    client.post("/admin/api/logout")

    # Password alone is no longer enough to establish a session.
    step1 = _login(client)
    assert step1.status_code == 200
    assert step1.get_json()["mfa_required"] is True
    assert client.get("/dashboard").status_code == 302  # not logged in yet

    bad_mfa = client.post("/admin/api/login/mfa", json={"code": "000000"})
    assert bad_mfa.status_code == 401

    good_mfa = client.post("/admin/api/login/mfa", json={"code": pyotp.TOTP(secret).now()})
    assert good_mfa.status_code == 200
    assert client.get("/dashboard").status_code == 200


def test_mfa_login_with_recovery_code_and_single_use(configured):
    client = configured.app.test_client()
    _login(client)
    secret = client.post("/admin/api/profile/mfa/enroll").get_json()["secret"]
    recovery_codes = client.post(
        "/admin/api/profile/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}
    ).get_json()["recovery_codes"]
    client.post("/admin/api/logout")

    _login(client)
    code = recovery_codes[0]

    first_use = client.post("/admin/api/login/mfa", json={"recovery_code": code})
    assert first_use.status_code == 200
    client.post("/admin/api/logout")

    _login(client)
    second_use = client.post("/admin/api/login/mfa", json={"recovery_code": code})
    assert second_use.status_code == 401  # already consumed


def test_mfa_pending_challenge_expires(configured, monkeypatch):
    # An abandoned/stolen post-password session cookie must not be usable to
    # complete the second factor arbitrarily later - the pending challenge
    # has a deadline, not just "does a pending user id exist in the session".
    import admin as admin_module

    client = configured.app.test_client()
    _login(client)
    secret = client.post("/admin/api/profile/mfa/enroll").get_json()["secret"]
    client.post("/admin/api/profile/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    client.post("/admin/api/logout")

    _login(client)  # password step succeeds, MFA now pending

    # Simulate the challenge deadline already having passed.
    real_time = admin_module.time.time
    monkeypatch.setattr(admin_module.time, "time", lambda: real_time() + admin_module.MFA_CHALLENGE_TTL_SECONDS + 1)

    resp = client.post("/admin/api/login/mfa", json={"code": pyotp.TOTP(secret).now()})
    assert resp.status_code == 400
    assert "pending" in resp.get_json()["error"].lower()


def test_mfa_disable_requires_valid_totp_code(configured):
    client = configured.app.test_client()
    _login(client)
    secret = client.post("/admin/api/profile/mfa/enroll").get_json()["secret"]
    client.post("/admin/api/profile/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})

    bad = client.post("/admin/api/profile/mfa/disable", json={"code": "000000"})
    assert bad.status_code == 400
    assert configured.dbstore.get_user_mfa_status("admin")["enabled"] is True

    ok = client.post("/admin/api/profile/mfa/disable", json={"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    assert configured.dbstore.get_user_mfa_status("admin")["enabled"] is False

    client.post("/admin/api/logout")
    relogin = _login(client)
    assert relogin.status_code == 200
    assert "mfa_required" not in relogin.get_json() or relogin.get_json().get("mfa_required") is None


def test_login_rejects_sql_injection_shaped_input_as_normal_auth_failure(configured):
    """Regression guardrail: parameterized queries mean this is just a wrong
    username/password, never a 500 or an auth bypass."""
    client = configured.app.test_client()
    payload = {"username": "' OR '1'='1", "password": "' OR '1'='1"}
    resp = client.post("/admin/api/login", json=payload)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Invalid username or password"
    # The injection attempt must not have created a session.
    assert client.get("/dashboard").status_code == 302
