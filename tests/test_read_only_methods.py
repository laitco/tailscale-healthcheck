import importlib.util
import os
import types
import pytest


def _load_healthcheck(database_path) -> types.ModuleType:
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    os.environ["DATABASE_PATH"] = str(database_path)
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(monkeypatch, tmp_path):
    module = _load_healthcheck(tmp_path / "healthcheck.db")
    # Avoid external calls during GETs by mocking device fetch
    monkeypatch.setattr(module, "fetch_devices", lambda: [])
    module.dbstore.create_user("tester", "correct-horse-battery-staple")
    app = module.app
    app.testing = True
    with app.test_client() as c:
        c.post("/admin/api/login", json={"username": "tester", "password": "correct-horse-battery-staple"})
        yield c


def test_block_modifying_methods_are_forbidden(client):
    for method in ["POST", "PUT", "PATCH", "DELETE"]:
        resp = client.open("/health", method=method)
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["method"] == method
        assert "Forbidden" in body["error"]


def test_allow_get_head_options(client):
    # GET is allowed
    r_get = client.get("/health")
    assert r_get.status_code == 200

    # HEAD is allowed
    r_head = client.head("/health")
    assert r_head.status_code == 200

    # OPTIONS is allowed
    r_options = client.open("/health", method="OPTIONS")
    assert r_options.status_code in (200, 204)


def test_cache_invalidate_get_ok_and_post_forbidden(client):
    r_get = client.get("/health/cache/invalidate")
    assert r_get.status_code == 200
    data = r_get.get_json()
    assert "triggered" in data

    r_post = client.post("/health/cache/invalidate")
    assert r_post.status_code == 403


def test_admin_routes_exempt_from_read_only_enforcement(client):
    # /admin/* legitimately needs POST (setup wizard, login, etc.) and must
    # not be rejected by the blanket read-only-method guard.
    resp = client.post("/admin/api/login", json={"username": "x", "password": "y"})
    assert resp.status_code != 403
