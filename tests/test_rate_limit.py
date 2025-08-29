import importlib.util
import os
import types
import pytest

try:
    import flask_limiter  # type: ignore
    _HAVE_LIMITER = True
except Exception:  # pragma: no cover
    _HAVE_LIMITER = False


def _load_healthcheck() -> types.ModuleType:
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not _HAVE_LIMITER, reason="Flask-Limiter not installed")
def test_rate_limit_per_ip(monkeypatch):
    # Configure strict, low per-IP limit and disable global
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "YES")
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "2")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL", "")

    module = _load_healthcheck()
    # Avoid external calls during GETs by mocking device fetch
    monkeypatch.setattr(module, "fetch_devices", lambda: [])

    app = module.app
    app.testing = True
    client = app.test_client()

    r1 = client.get("/health")
    assert r1.status_code == 200
    r2 = client.get("/health")
    assert r2.status_code == 200
    r3 = client.get("/health")
    assert r3.status_code == 429
    body = r3.get_json()
    assert body and ("Too Many" in body.get("error", "") or r3.status.startswith("429"))


@pytest.mark.skipif(not _HAVE_LIMITER, reason="Flask-Limiter not installed")
def test_rate_limit_global_shared(monkeypatch):
    # High per-IP limit, low global shared limit
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "YES")
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "100")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL", "3")


def test_rate_limit_file_backend_per_ip(monkeypatch, tmp_path):
    # Enable file-backed limiter, low per-IP limit, no global
    rl_file = tmp_path / "rl.json"
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "YES")
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "2")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL", "0")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URL", f"file://{rl_file}")

    module = _load_healthcheck()
    monkeypatch.setattr(module, "fetch_devices", lambda: [])
    app = module.app
    app.testing = True
    client = app.test_client()

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    r = client.get("/health")
    assert r.status_code == 429
    body = r.get_json()
    assert body and "Too Many" in body.get("error", "")

    # New module instance, same minute; file-backed counts persist
    module = _load_healthcheck()
    monkeypatch.setattr(module, "fetch_devices", lambda: [])
    app = module.app
    app.testing = True
    client = app.test_client()
    r = client.get("/health")
    assert r.status_code == 429
