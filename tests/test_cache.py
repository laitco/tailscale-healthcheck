import importlib.util
import os
import types


def _load_healthcheck_with_env(env: dict) -> types.ModuleType:
    # Apply env and load a fresh module instance
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _dummy_devices_payload():
    return {
        "devices": [
            {
                "id": "id-1",
                "name": "host1.example",
                "hostname": "host1",
                "os": "linux",
                "lastSeen": "2099-01-01T00:00:00Z",
                "tags": ["tag:user"],
                "updateAvailable": False,
                "keyExpiryDisabled": True,
            }
        ]
    }


def test_cache_disabled_calls_api_each_time(monkeypatch):
    module = _load_healthcheck_with_env({
        "CACHE_ENABLED": "NO",
        "CACHE_BACKEND": "MEMORY",
    })

    calls = {"count": 0}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _dummy_devices_payload()

    def fake_get(url, headers=None, timeout=None):
        calls["count"] += 1
        return DummyResponse()

    monkeypatch.setattr(module.requests, "get", fake_get)

    client = module.app.test_client()
    res1 = client.get("/health")
    res2 = client.get("/health")
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert calls["count"] == 2


def test_cache_enabled_hits_once_within_ttl(monkeypatch):
    module = _load_healthcheck_with_env({
        "CACHE_ENABLED": "YES",
        "CACHE_TTL_SECONDS": "60",
        "CACHE_BACKEND": "MEMORY",
    })

    calls = {"count": 0}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _dummy_devices_payload()

    def fake_get(url, headers=None, timeout=None):
        calls["count"] += 1
        return DummyResponse()

    monkeypatch.setattr(module.requests, "get", fake_get)

    client = module.app.test_client()
    res1 = client.get("/health")
    res2 = client.get("/health")
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert calls["count"] == 1


def test_cache_expires_then_refreshes(monkeypatch):
    module = _load_healthcheck_with_env({
        "CACHE_ENABLED": "YES",
        "CACHE_TTL_SECONDS": "5",
        "CACHE_BACKEND": "MEMORY",
    })

    # Control time progression
    now = {"t": 1000.0}

    def fake_time():
        return now["t"]

    monkeypatch.setattr(module.time, "time", fake_time)

    calls = {"count": 0}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _dummy_devices_payload()

    def fake_get(url, headers=None, timeout=None):
        calls["count"] += 1
        return DummyResponse()

    monkeypatch.setattr(module.requests, "get", fake_get)

    client = module.app.test_client()
    # First call populates cache at t=1000
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert calls["count"] == 1

    # Within TTL (t=1003), cache hit
    now["t"] = 1003.0
    res2 = client.get("/health")
    assert res2.status_code == 200
    assert calls["count"] == 1

    # After TTL (t=1006), cache miss -> refresh
    now["t"] = 1006.0
    res3 = client.get("/health")
    assert res3.status_code == 200
    assert calls["count"] == 2


def test_cache_invalidate_endpoint(monkeypatch):
    module = _load_healthcheck_with_env({
        "CACHE_ENABLED": "YES",
        "CACHE_TTL_SECONDS": "60",
        "CACHE_BACKEND": "MEMORY",
    })

    calls = {"count": 0}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _dummy_devices_payload()

    def fake_get(url, headers=None, timeout=None):
        calls["count"] += 1
        return DummyResponse()

    monkeypatch.setattr(module.requests, "get", fake_get)

    client = module.app.test_client()
    # Populate cache
    r1 = client.get("/health")
    r2 = client.get("/health")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert calls["count"] == 1

    # Invalidate cache (read-only safe via GET)
    inv = client.get("/health/cache/invalidate")
    assert inv.status_code == 200
    data = inv.get_json()
    assert "message" in data

    # Next request should hit API again
    r3 = client.get("/health")
    assert r3.status_code == 200
    assert calls["count"] == 2


def test_file_cache_backend_shares_via_file(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"

    # First module instance
    module1 = _load_healthcheck_with_env({
        "CACHE_ENABLED": "YES",
        "CACHE_TTL_SECONDS": "60",
        "CACHE_BACKEND": "FILE",
        "CACHE_FILE_PATH": str(cache_path),
    })

    calls = {"count": 0}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _dummy_devices_payload()

    def fake_get(url, headers=None, timeout=None):
        calls["count"] += 1
        return DummyResponse()

    # Patch requests.get in both modules to the same stub
    monkeypatch.setattr(module1.requests, "get", fake_get)

    client1 = module1.app.test_client()
    r1 = client1.get("/health")  # triggers write to file cache
    assert r1.status_code == 200
    assert calls["count"] == 1

    # Second module instance simulates another worker process reading the same file cache
    module2 = _load_healthcheck_with_env({
        "CACHE_ENABLED": "YES",
        "CACHE_TTL_SECONDS": "60",
        "CACHE_BACKEND": "FILE",
        "CACHE_FILE_PATH": str(cache_path),
    })

    monkeypatch.setattr(module2.requests, "get", fake_get)
    client2 = module2.app.test_client()
    r2 = client2.get("/health")  # should be served from file cache
    assert r2.status_code == 200
    assert calls["count"] == 1
