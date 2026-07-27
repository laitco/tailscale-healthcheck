"""Security defaults: response headers, the CSP nonce, session cookie flags,
and the opt-in ProxyFix that makes request.remote_addr trustworthy behind a
reverse proxy (which is what the rate limiters and the failed-login lockout
key off).
"""
import importlib.util
import os
import types

import pytest


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


@pytest.fixture
def configured(tmp_path):
    m = _load_healthcheck(tmp_path / "healthcheck.db")
    m.fetch_devices = lambda: []
    return m


def test_security_headers_present_on_json_and_html(configured):
    client = configured.app.test_client()
    for path in ("/health", "/admin/login"):
        headers = client.get(path).headers
        assert headers["X-Content-Type-Options"] == "nosniff", path
        assert headers["X-Frame-Options"] == "DENY", path
        assert headers["Referrer-Policy"] == "same-origin", path
        assert "Content-Security-Policy" in headers, path


def test_csp_is_nonce_based_and_forbids_framing(configured):
    csp = configured.app.test_client().get("/health").headers["Content-Security-Policy"]

    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    # Scripts must never fall back to 'unsafe-inline' - the one inline script
    # in templates/layout.html is nonce-gated instead.
    script_src = next(part for part in csp.split("; ") if part.startswith("script-src"))
    assert "'unsafe-inline'" not in script_src
    assert "'nonce-" in script_src


def test_csp_nonce_is_unique_per_request_and_matches_the_rendered_script(configured):
    # A user must exist, or /admin/login redirects to the setup wizard and no
    # template (and therefore no nonced script tag) is rendered at all.
    configured.dbstore.create_user("admin", "correct-horse-battery-staple")
    client = configured.app.test_client()

    resp = client.get("/admin/login")
    csp = resp.headers["Content-Security-Policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert nonce, "no nonce in CSP"
    # The inline anti-FOUC script must carry the same nonce, or the page's
    # dark-mode flash-prevention silently stops running under the policy.
    assert f'nonce="{nonce}"' in resp.get_data(as_text=True)

    other = client.get("/admin/login").headers["Content-Security-Policy"]
    assert other != csp, "nonce must be regenerated per request"


def test_session_cookie_defaults_are_conservative(configured):
    # Regression: these were set with app.config.setdefault(), which is a no-op
    # because Flask pre-populates every SESSION_COOKIE_* key - SAMESITE stayed
    # None, so the Lax protection the admin API leans on was never in effect.
    # Secure defaults to off so a plain-HTTP LAN deployment can still log in.
    assert configured.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert configured.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert configured.app.config["SESSION_COOKIE_SECURE"] is False
    assert configured.app.config["PERMANENT_SESSION_LIFETIME"].total_seconds() > 0


def test_session_cookie_secure_opt_in(tmp_path):
    m = _load_healthcheck(tmp_path / "healthcheck.db", SESSION_COOKIE_SECURE="true", SESSION_LIFETIME_MINUTES="60")
    assert m.app.config["SESSION_COOKIE_SECURE"] is True
    assert m.app.config["PERMANENT_SESSION_LIFETIME"].total_seconds() == 3600


def test_proxy_fix_is_off_by_default(configured):
    """Without an explicit trusted_proxy_count, X-Forwarded-For must be ignored
    -   otherwise any client could spoof its own address and evade the per-IP
    rate limit and the login lockout."""
    assert configured.TRUSTED_PROXY_COUNT == 0

    seen = {}
    configured.app.add_url_rule(
        "/__remote_addr", "remote_addr_probe", lambda: (seen.update(addr=configured.request.remote_addr) or "ok")
    )
    configured.app.test_client().get("/__remote_addr", headers={"X-Forwarded-For": "203.0.113.9"})
    assert seen["addr"] != "203.0.113.9"


def test_proxy_fix_honours_forwarded_for_when_enabled(tmp_path):
    m = _load_healthcheck(tmp_path / "healthcheck.db", TRUSTED_PROXY_COUNT="1")
    assert m.TRUSTED_PROXY_COUNT == 1

    seen = {}
    m.app.add_url_rule(
        "/__remote_addr", "remote_addr_probe", lambda: (seen.update(addr=m.request.remote_addr) or "ok")
    )
    m.app.test_client().get("/__remote_addr", headers={"X-Forwarded-For": "203.0.113.9"})
    assert seen["addr"] == "203.0.113.9"


def test_trusted_proxy_count_is_flagged_restart_required(configured):
    import admin

    for name in ("trusted_proxy_count", "session_cookie_secure", "session_lifetime_minutes"):
        assert name in admin.RESTART_REQUIRED_SETTINGS
        assert name in configured.dbstore.SETTINGS_REGISTRY
