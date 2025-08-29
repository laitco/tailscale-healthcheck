import importlib.util
import os
import types
import requests


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


def test_make_authenticated_request_uses_timeout(monkeypatch):
    module = _load_healthcheck_with_env({"HTTP_TIMEOUT": "3"})

    calls = {}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    def fake_get(url, headers=None, timeout=None):
        calls["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(module.requests, "get", fake_get)

    resp = module.make_authenticated_request("https://example.invalid", {"Authorization": "Bearer x"})
    assert isinstance(resp, DummyResponse)
    assert calls.get("timeout") == module.get_http_timeout()


def test_fetch_oauth_token_uses_timeout(monkeypatch):
    module = _load_healthcheck_with_env({
        "HTTP_TIMEOUT": "7",
        "OAUTH_CLIENT_ID": "abc",
        "OAUTH_CLIENT_SECRET": "def",
    })

    calls = {}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "token123"}

    def fake_post(url, data=None, timeout=None):
        calls["timeout"] = timeout
        return DummyResponse()

    class NoopTimer:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            return None

        def cancel(self):
            return None

    monkeypatch.setattr(module, "Timer", NoopTimer)
    monkeypatch.setattr(module.requests, "post", fake_post)

    module.fetch_oauth_token()
    assert calls.get("timeout") == module.get_http_timeout()
    assert module.ACCESS_TOKEN == "token123"


def test_health_endpoint_times_out_gracefully(monkeypatch):
    module = _load_healthcheck_with_env({"HTTP_TIMEOUT": "1"})

    def raise_timeout(*_a, **_kw):
        raise requests.exceptions.Timeout("simulated timeout")

    # Make the underlying HTTP call time out
    monkeypatch.setattr(module.requests, "get", raise_timeout)

    client = module.app.test_client()
    res = client.get("/health")
    assert res.status_code == 504
    data = res.get_json()
    assert "timed out" in data.get("error", "").lower()

