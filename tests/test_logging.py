import importlib
import importlib.util
import os
import logging


def _load_healthcheck():
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, os.pardir))
    module_path = os.path.join(root, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_get_log_level_default(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    # Import lazily to ensure env is applied
    module = _load_healthcheck()
    assert module.get_log_level_from_env() == logging.INFO


def test_get_log_level_debug(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    module = _load_healthcheck()
    assert module.get_log_level_from_env() == logging.DEBUG


def test_get_log_level_invalid(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "NOPE")
    module = _load_healthcheck()
    assert module.get_log_level_from_env() == logging.INFO
