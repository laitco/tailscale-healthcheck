"""Coverage for gunicorn_config.py's master-process hooks.

The OAuth pre-warm in on_starting() used to gate on os.getenv("OAUTH_CLIENT_ID"),
which is empty on any install configured through the setup wizard (credentials
live in SQLite, not the environment). That made the hook report "using
AUTH_TOKEN" and skip the pre-warm on most real OAuth deployments - see
CLAUDE.md's settings-registry rule: resolve settings via dbstore, never a bare
os.getenv.
"""
import importlib.util
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import dbstore  # noqa: E402


def _load_gunicorn_config(database_path, **env) -> types.ModuleType:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    module_path = os.path.join(root, "gunicorn_config.py")
    spec = importlib.util.spec_from_file_location("gunicorn_config_undertest", module_path)
    assert spec and spec.loader
    old_env = os.environ.copy()
    try:
        os.environ.update({
            "RATE_LIMIT_ENABLED": "NO",
            "DATABASE_PATH": str(database_path),
            **env,
        })
        # gunicorn_config imports healthcheck at module load, which pins the DB
        # path via dbstore.configure(); dbstore is cached in sys.modules across
        # dynamically-loaded copies, so re-pin it explicitly first.
        dbstore.configure(str(database_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    finally:
        os.environ.clear()
        os.environ.update(old_env)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "healthcheck.db"
    dbstore.configure(str(path))
    dbstore.init_db()
    return path


def test_oauth_prewarm_fires_for_db_backed_credentials(db, caplog):
    """The regression: OAuth configured via the wizard (DB only, no env vars)
    must still pre-warm the token in the master process."""
    dbstore.set_setting("oauth_client_id", "client-id-from-wizard")
    dbstore.set_setting("oauth_client_secret", "client-secret-from-wizard")

    module = _load_gunicorn_config(db)
    calls = []
    module.initialize_oauth = lambda: calls.append(True)

    with caplog.at_level("INFO"):
        module.on_starting(server=None)

    assert calls == [True], "OAuth pre-warm did not run for DB-backed credentials"
    assert "Initializing OAuth" in caplog.text
    assert "AUTH_TOKEN" not in caplog.text


def test_oauth_prewarm_fires_for_env_credentials(db, caplog, monkeypatch):
    """Env-provided credentials must keep working - env still wins.

    monkeypatch (not the loader's env dict) sets these, because they have to
    still be set when on_starting runs: a real Gunicorn master keeps its
    environment for the whole process lifetime, whereas the loader restores
    os.environ as soon as the module finishes importing.
    """
    module = _load_gunicorn_config(db)
    monkeypatch.setenv("OAUTH_CLIENT_ID", "env-id")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "env-secret")
    calls = []
    module.initialize_oauth = lambda: calls.append(True)

    with caplog.at_level("INFO"):
        module.on_starting(server=None)

    assert calls == [True]
    assert "Initializing OAuth" in caplog.text


def test_static_token_is_reported_accurately(db, caplog):
    dbstore.set_setting("auth_token", "tskey-api-from-wizard")

    module = _load_gunicorn_config(db)
    calls = []
    module.initialize_oauth = lambda: calls.append(True)

    with caplog.at_level("INFO"):
        module.on_starting(server=None)

    assert calls == [], "must not pre-warm OAuth when only a static token is configured"
    assert "static API token" in caplog.text


def test_unconfigured_instance_points_at_the_setup_wizard(db, caplog):
    """A fresh install has neither credential - saying "using AUTH_TOKEN" there
    was misleading too."""
    module = _load_gunicorn_config(db)
    calls = []
    module.initialize_oauth = lambda: calls.append(True)

    with caplog.at_level("INFO"):
        module.on_starting(server=None)

    assert calls == []
    assert "/admin/setup" in caplog.text


def test_post_fork_starts_the_poller(db):
    """Each worker calls poller.start(); the fcntl election decides which one
    actually polls, so this must stay in post_fork rather than moving into the
    preloaded master."""
    module = _load_gunicorn_config(db)
    started = []
    module.poller.start = lambda: started.append(True)

    module.post_fork(server=None, worker=types.SimpleNamespace(pid=123))

    assert started == [True]
